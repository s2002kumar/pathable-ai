"""The ``pathable`` command line.

Operational tasks that are not HTTP requests: seeding regions, building a
candidate network, enriching and sealing it, judging it against the live one,
activating it, rolling back, and inspecting what is live and why. Argparse rather
than a CLI framework — the surface is small, and a dependency that only saves a
few lines of argument wiring is not worth carrying.

The lifecycle, as commands::

    pathable ingest pbf --region waterloo --file ...     # a draft candidate
    pathable elevation apply --region waterloo           # enrich the candidate
    pathable datasets seal <candidate>                   # validate, hash, freeze
    pathable datasets evaluate <candidate>               # route regression vs live
    pathable datasets accept <run> --reason "..."        # only if routes changed
    pathable datasets activate <candidate>               # the short switch
    pathable datasets rollback --region waterloo --reason "..."
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
import time
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from pathable_api import __version__
from pathable_api.core.config import ConfigurationError, get_settings
from pathable_api.core.event_loop import selector_loop_factory
from pathable_api.core.logging import configure_logging, get_logger
from pathable_api.db.session import Database, build_database
from pathable_api.geo.coverage import build_coverage_report, render
from pathable_api.geo.datasets import (
    DatasetLifecycleError,
    DatasetValidationError,
    IngestionResult,
    get_active_dataset,
    ingest_network,
    require_region,
)
from pathable_api.geo.elevation import build_provider
from pathable_api.geo.elevation_apply import summarise
from pathable_api.geo.enums import SourceType
from pathable_api.geo.fixtures import load_synthetic_dataset
from pathable_api.geo.lifecycle import (
    SealRefusedError,
    enrich_with_elevation,
    record_content_checksum,
    resolve_candidate,
    seal_candidate,
    verify_content_checksum,
)
from pathable_api.geo.models import (
    DatasetVersion,
    PilotRegion,
    RouteRegressionAcceptance,
    RouteRegressionRun,
)
from pathable_api.geo.osm import OverpassUnreachableError, import_walk_network
from pathable_api.geo.overture.catalog import (
    LATEST,
    ReleaseError,
    http_json_fetcher,
    resolve_release,
)
from pathable_api.geo.overture.contract import IncompatibleSchemaError
from pathable_api.geo.overture.evidence import write_json
from pathable_api.geo.overture.extract import (
    EXTRACT_MANIFEST,
    ExtractionError,
    ExtractionPlan,
    run_extraction,
)
from pathable_api.geo.overture.identity import parse_pathable_osm_id
from pathable_api.geo.overture.linkage import (
    ExtractMismatchError,
    build_report,
    load_overture_side,
)
from pathable_api.geo.overture.osm_versions import VersionEvidenceError, read_versions
from pathable_api.geo.overture.pathable import PathAbleSideError, load_identities
from pathable_api.geo.pbf import import_from_pbf
from pathable_api.geo.regions import PILOT_REGIONS, region_definition, seed_pilot_regions
from pathable_api.routing.ablation import run_ablation, summarise_ablation
from pathable_api.routing.activation import (
    IDENTICAL,
    accept_regression,
    activate_candidate,
    activation_history,
    evaluate_candidate,
    rollback,
    rollback_target,
    verify_rollback_target,
)
from pathable_api.routing.benchmark import build_measurement_grid, measure
from pathable_api.routing.evaluation import as_records, compare_algorithms, evaluate
from pathable_api.routing.graph import GraphRepository, NoActiveDatasetError, graph_from_payload
from pathable_api.routing.load_benchmark import (
    describe_environment,
    machine_memory,
    process_memory,
    run_load_benchmark,
)
from pathable_api.routing.load_benchmark import render as render_load_benchmark
from pathable_api.routing.profiles import get_profile
from pathable_api.routing.waterloo_cases import WATERLOO_CASES

logger = get_logger(__name__)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_MISCONFIGURED = 2
#: A route regression that found differences, or had nothing to compare with:
#: not a failure, but not something to activate without a person deciding.
EXIT_REVIEW_REQUIRED = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pathable",
        description="PathAble operational commands.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    regions = subcommands.add_parser("regions", help="Manage pilot regions.")
    region_actions = regions.add_subparsers(dest="region_command", required=True)
    region_actions.add_parser("seed", help="Create or refresh the configured pilot regions.")
    region_actions.add_parser("list", help="List regions in the database.")

    ingest = subcommands.add_parser("ingest", help="Build a new network dataset.")
    sources = ingest.add_subparsers(dest="source", required=True)

    osm = sources.add_parser("osm", help="Import a real network from OpenStreetMap.")
    osm.add_argument(
        "--region",
        required=True,
        choices=[definition.slug for definition in PILOT_REGIONS],
        help="Pilot region to import.",
    )
    osm.add_argument(
        "--no-elevation-required",
        action="store_true",
        help="Record that this candidate may be sealed without elevation (default: required).",
    )
    osm.add_argument(
        "--no-simplify",
        action="store_true",
        help="Keep every OSM interstitial node instead of collapsing straight runs.",
    )
    osm.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Where to cache Overpass responses (default: OSMnx's own cache folder).",
    )
    osm.add_argument(
        "--overpass-url",
        default=None,
        help=(
            "Overpass endpoint to use, e.g. https://overpass.private.coffee/api. "
            "Defaults to the first reachable public endpoint."
        ),
    )

    pbf = sources.add_parser(
        "pbf",
        help="Import from a local OpenStreetMap extract, with no live service.",
    )
    pbf.add_argument(
        "--region",
        required=True,
        choices=[definition.slug for definition in PILOT_REGIONS],
        help="Pilot region to clip the extract to.",
    )
    pbf.add_argument(
        "--file",
        required=True,
        type=Path,
        help="Path to a .osm.pbf extract, e.g. from download.geofabrik.de.",
    )
    pbf.add_argument(
        "--provider",
        default="geofabrik",
        help="Who published the extract. Recorded with the dataset.",
    )
    pbf.add_argument(
        "--source-timestamp",
        default=None,
        help="When the extract was produced (ISO 8601), from the provider's own listing.",
    )
    pbf.add_argument(
        "--no-elevation-required",
        action="store_true",
        help="Record that this candidate may be sealed without elevation (default: required).",
    )

    synthetic = sources.add_parser(
        "synthetic",
        help=(
            "Load the deterministic test fixture (not real data) and take it through the "
            "same seal, regression and activation gates as a real candidate."
        ),
    )
    synthetic.add_argument(
        "--no-activate", action="store_true", help="Stop at the candidate; activate nothing."
    )

    benchmark = subcommands.add_parser(
        "benchmark", help="Measure routing performance. Every number is a real timing."
    )
    benchmark_actions = benchmark.add_subparsers(dest="benchmark_command", required=True)
    routes_bench = benchmark_actions.add_parser("route", help="Time route computation.")
    routes_bench.add_argument(
        "--region",
        default=None,
        help="Measure this region's active dataset. Omit to measure a synthetic grid instead.",
    )
    routes_bench.add_argument(
        "--grid",
        type=int,
        default=None,
        help=(
            "Measure an in-memory NxN lattice of this size instead of a real dataset. "
            "Not a map of anywhere; use it to characterise scaling, and label it as such."
        ),
    )
    routes_bench.add_argument("--samples", type=int, default=50)
    routes_bench.add_argument(
        "--profile",
        action="append",
        default=None,
        help="Profile to measure; repeatable. Defaults to standard and wheelchair.",
    )

    load_bench = benchmark_actions.add_parser(
        "load",
        help=(
            "Time loading a region's active dataset into the routing graph and measure "
            "its memory. The cold-start cost of the service."
        ),
    )
    load_bench.add_argument(
        "--region", required=True, choices=sorted(region.slug for region in PILOT_REGIONS)
    )
    load_bench.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Timing runs, without tracemalloc so its overhead does not inflate the clock.",
    )
    load_bench.add_argument(
        "--heap-runs",
        type=int,
        default=1,
        help="Additional runs under tracemalloc, for peak Python heap. Slower; timed separately.",
    )
    load_bench.add_argument("--json", default=None, help="Write the full report here.")

    elevation = subcommands.add_parser(
        "elevation", help="Sample elevation for a dataset and derive segment grade."
    )
    elevation_actions = elevation.add_subparsers(dest="elevation_command", required=True)
    apply_command = elevation_actions.add_parser(
        "apply",
        help="Sample elevation into a draft candidate of a region, before it is sealed.",
    )
    apply_command.add_argument(
        "--region", required=True, choices=sorted(region.slug for region in PILOT_REGIONS)
    )
    apply_command.add_argument(
        "--provider",
        default="hrdem",
        help="Elevation source: hrdem (1 m LiDAR, Canada), opentopodata (30 m), none.",
    )
    apply_command.add_argument(
        "--dataset",
        default=None,
        help=(
            "Candidate id (or a unique prefix of at least 8 characters). Defaults to the "
            "region's only draft candidate; never the live dataset."
        ),
    )
    apply_command.add_argument("--batch-size", type=int, default=2000)

    evaluate_command = subcommands.add_parser(
        "evaluate", help="Route a fixed corpus of real journeys and report every outcome."
    )
    evaluate_command.add_argument(
        "--region", required=True, choices=sorted(region.slug for region in PILOT_REGIONS)
    )
    evaluate_command.add_argument(
        "--profile", default="wheelchair", help="Profile to compare against the standard one."
    )
    evaluate_command.add_argument("--json", default=None, help="Write the full results here.")
    evaluate_command.add_argument(
        "--algorithms",
        action="store_true",
        help="Also time Dijkstra against A* on every case.",
    )
    evaluate_command.add_argument(
        "--ablate",
        action="store_true",
        help="Also route without the unknown-data penalties, to see what they buy.",
    )

    coverage = subcommands.add_parser(
        "coverage", help="Report what the map records about a region, category by category."
    )
    coverage.add_argument(
        "--region", required=True, choices=sorted(region.slug for region in PILOT_REGIONS)
    )
    coverage.add_argument("--dataset", default=None, help="Defaults to the active dataset.")
    coverage.add_argument("--json", default=None, help="Also write the report to this path.")

    datasets = subcommands.add_parser("datasets", help="Inspect dataset versions.")
    dataset_actions = datasets.add_subparsers(dest="dataset_command", required=True)
    listing = dataset_actions.add_parser("list", help="List dataset versions, newest first.")
    listing.add_argument("--region", default=None, help="Restrict to one region slug.")
    listing.add_argument("--limit", type=int, default=20)

    reference_help = "Dataset id, or a unique prefix of at least 8 characters."
    seal = dataset_actions.add_parser(
        "seal", help="Validate a candidate's stored content, hash it, and freeze it."
    )
    seal.add_argument("dataset", help=reference_help)

    checksum = dataset_actions.add_parser(
        "checksum",
        help="Recompute a dataset's content checksum from its rows and compare it.",
    )
    checksum.add_argument("dataset", help=reference_help)
    checksum.add_argument(
        "--record",
        action="store_true",
        help="Record it for a dataset sealed before content checksums existed.",
    )

    evaluate_dataset = dataset_actions.add_parser(
        "evaluate",
        help="Route the regression corpus on a sealed candidate and on the live dataset.",
    )
    evaluate_dataset.add_argument("dataset", help=reference_help)
    evaluate_dataset.add_argument("--json", type=Path, default=None, help="Write the run here.")

    accept = dataset_actions.add_parser(
        "accept", help="Record why a regression run's differences are intended."
    )
    accept.add_argument("run", help="Regression run id, or a unique prefix of 8+ characters.")
    accept.add_argument("--reason", required=True, help="A sentence somebody can read later.")

    activate = dataset_actions.add_parser(
        "activate", help="Make a sealed, judged candidate the live network."
    )
    activate.add_argument("dataset", help=reference_help)
    activate.add_argument(
        "--run", default=None, help="The regression run to rest on (default: the latest)."
    )

    rollback_command = dataset_actions.add_parser(
        "rollback",
        help="Reactivate the previously live dataset, or a named retired one, as it was.",
    )
    rollback_command.add_argument(
        "--region", required=True, choices=[definition.slug for definition in PILOT_REGIONS]
    )
    rollback_command.add_argument(
        "--to", default=None, help="Retired dataset to reactivate (default: the previous one)."
    )
    rollback_command.add_argument("--reason", required=True, help="Why, in a sentence.")

    history = dataset_actions.add_parser(
        "history", help="Every activation and rollback recorded for a region."
    )
    history.add_argument(
        "--region", required=True, choices=[definition.slug for definition in PILOT_REGIONS]
    )

    overture = subcommands.add_parser(
        "overture",
        help="Inspect an Overture Maps release against a region. Never writes to the database.",
    )
    overture_actions = overture.add_subparsers(dest="overture_command", required=True)
    overture_actions.add_parser(
        "releases", help="Show the releases and schema versions Overture's catalog publishes now."
    )
    extract = overture_actions.add_parser(
        "extract",
        help="Read one release's transportation features for a region into local files.",
    )
    extract.add_argument(
        "--region", required=True, choices=sorted(region.slug for region in PILOT_REGIONS)
    )
    extract.add_argument(
        "--release",
        default="latest",
        help="Overture release, e.g. 2026-09-23.0. 'latest' is resolved and recorded.",
    )
    extract.add_argument(
        "--out",
        type=Path,
        default=Path(".overture-data"),
        help="Root folder; output goes to <out>/<release>/<region>. Keep it out of git.",
    )
    extract.add_argument(
        "--bridge-sample-files",
        type=int,
        default=2,
        help="Bridge files to read for cross-checking (each ~240 MB; 0 skips the check).",
    )
    extract.add_argument("--no-changelog", action="store_true")

    link = overture_actions.add_parser(
        "link",
        help=(
            "Measure how a dataset's OSM identities appear in an extract. Reads the "
            "database in a read-only transaction."
        ),
    )
    link.add_argument(
        "--region", required=True, choices=sorted(region.slug for region in PILOT_REGIONS)
    )
    link.add_argument("--extract", type=Path, required=True, help="An extract folder.")
    link.add_argument("--dataset", default=None, help="Defaults to the active dataset.")
    link.add_argument(
        "--osm-pbf",
        type=Path,
        default=None,
        help=(
            "The dataset's own source extract, to recover OSM versions. Refused unless its "
            "SHA-256 matches the one recorded when the dataset was built."
        ),
    )
    link.add_argument("--json", type=Path, default=None, help="Write the report here.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    settings = get_settings()
    configure_logging(
        # Console format regardless of configuration: this output is read by a
        # person at a terminal, not shipped to a log aggregator.
        level=settings.log_level,
        log_format="console",
        service=settings.service_name,
        version=settings.app_version,
        environment=settings.environment,
    )

    # Reading an Overture release needs the network but not the database.
    if args.command == "overture" and args.overture_command != "link":
        return _overture_offline(args)

    try:
        settings.require_database_url()
    except ConfigurationError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_MISCONFIGURED

    # Psycopg cannot run on Windows' default proactor loop; the selector factory
    # is the same one the API server uses.
    return asyncio.run(_dispatch(args), loop_factory=selector_loop_factory())


async def _dispatch(args: argparse.Namespace) -> int:
    database = build_database(get_settings())
    try:
        match args.command:
            case "regions" if args.region_command == "seed":
                return await _seed_regions(database)
            case "regions":
                return await _list_regions(database)
            case "ingest" if args.source == "osm":
                return await _ingest_osm(database, args)
            case "ingest" if args.source == "pbf":
                return await _ingest_pbf(database, args)
            case "ingest":
                return await _ingest_synthetic(database, args)
            case "elevation":
                return await _apply_elevation(database, args)
            case "coverage":
                return await _coverage(database, args)
            case "evaluate":
                return await _evaluate(database, args)
            case "benchmark" if args.benchmark_command == "load":
                return await _benchmark_load(database, args)
            case "benchmark":
                return await _benchmark(database, args)
            case "overture":
                return await _overture_link(database, args)
            case "datasets" if args.dataset_command == "seal":
                return await _seal(database, args)
            case "datasets" if args.dataset_command == "checksum":
                return await _checksum(database, args)
            case "datasets" if args.dataset_command == "evaluate":
                return await _evaluate_candidate(database, args)
            case "datasets" if args.dataset_command == "accept":
                return await _accept(database, args)
            case "datasets" if args.dataset_command == "activate":
                return await _activate(database, args)
            case "datasets" if args.dataset_command == "rollback":
                return await _rollback(database, args)
            case "datasets" if args.dataset_command == "history":
                return await _history(database, args)
            case _:
                return await _list_datasets(database, args)
    finally:
        await database.dispose()


async def _seed_regions(database: Database) -> int:
    async with database.session() as session:
        regions = await seed_pilot_regions(session)
        await session.commit()
    for region in regions:
        print(f"{region.slug}\t{region.display_name}")
    return EXIT_OK


async def _list_regions(database: Database) -> int:
    async with database.session() as session:
        rows = (await session.execute(select(PilotRegion).order_by(PilotRegion.slug))).scalars()
        found = False
        for region in rows:
            found = True
            state = "enabled" if region.enabled else "disabled"
            print(f"{region.slug}\t{state}\t{region.display_name}")
    if not found:
        print("No regions. Run `pathable regions seed`.")
    return EXIT_OK


async def _ingest_osm(database: Database, args: argparse.Namespace) -> int:
    definition = region_definition(args.region)

    # The download happens before the transaction opens. It is the slow part and
    # it touches a public service; holding a database transaction across it would
    # be rude to both.
    print(f"Downloading OpenStreetMap walk network for {definition.display_name}…")
    try:
        result = import_walk_network(
            definition.bounds,
            region_slug=definition.slug,
            cache_dir=args.cache_dir,
            simplify=not args.no_simplify,
            overpass_url=args.overpass_url,
        )
    except OverpassUnreachableError as error:
        # Fail immediately and say so. The alternative — letting the request hang
        # on an unreachable endpoint — burned an hour before this check existed.
        print(f"error: {error}", file=sys.stderr)
        print(
            "Overpass is a donated public service and rate-limits aggressively. "
            "Wait a few minutes, or pass --overpass-url to use another instance.",
            file=sys.stderr,
        )
        return EXIT_FAILED
    print(f"Retrieved {result.payload.node_count} nodes, {result.payload.edge_count} edges.")

    async with database.session() as session:
        region = await require_region(session, definition.slug)
        try:
            ingestion = await ingest_network(
                session,
                region=region,
                payload=result.payload,
                source_type=SourceType.OSM,
                source_name=f"openstreetmap:{definition.slug}",
                ingestion_configuration=result.configuration,
                source_timestamp=result.retrieved_at,
                declared_bounds=definition.bounds,
                elevation_required=not args.no_elevation_required,
            )
        except DatasetValidationError as error:
            await session.rollback()
            print(f"error: {error}", file=sys.stderr)
            for finding in error.report.errors[:10]:
                print(f"  {finding.code}: {finding.message}", file=sys.stderr)
            return EXIT_FAILED
        await session.commit()

    _report(ingestion, definition.display_name)
    return EXIT_OK


async def _ingest_pbf(database: Database, args: argparse.Namespace) -> int:
    definition = region_definition(args.region)
    path = Path(args.file)
    if not path.is_file():
        print(f"error: {path} does not exist.", file=sys.stderr)
        return EXIT_MISCONFIGURED

    source_timestamp: dt.datetime | None = None
    if args.source_timestamp:
        try:
            source_timestamp = dt.datetime.fromisoformat(args.source_timestamp)
        except ValueError:
            print("error: --source-timestamp must be ISO 8601.", file=sys.stderr)
            return EXIT_MISCONFIGURED
        if source_timestamp.tzinfo is None:
            source_timestamp = source_timestamp.replace(tzinfo=dt.UTC)

    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"Reading {path.name} ({size_mb:.0f} MB) for {definition.display_name}...")

    started = time.perf_counter()
    result = import_from_pbf(
        path,
        definition.bounds,
        region_slug=definition.slug,
        provider=args.provider,
        source_timestamp=source_timestamp,
    )
    read_seconds = time.perf_counter() - started
    print(
        f"Read {result.payload.node_count} nodes, {result.payload.edge_count} segments "
        f"in {read_seconds:.1f}s."
    )

    async with database.session() as session:
        region = await require_region(session, definition.slug)
        try:
            ingestion = await ingest_network(
                session,
                region=region,
                payload=result.payload,
                source_type=SourceType.OSM,
                source_name=f"openstreetmap-pbf:{definition.slug}",
                ingestion_configuration={
                    **result.configuration,
                    "read_seconds": round(read_seconds, 2),
                },
                source_timestamp=source_timestamp or result.retrieved_at,
                declared_bounds=definition.bounds,
                elevation_required=not args.no_elevation_required,
            )
        except DatasetValidationError as error:
            await session.rollback()
            print(f"error: {error}", file=sys.stderr)
            for finding in error.report.errors[:10]:
                print(f"  {finding.code}: {finding.message}", file=sys.stderr)
            return EXIT_FAILED
        await session.commit()

    _report(ingestion, definition.display_name)
    print(f"  source     {result.configuration['file_name']}")
    print(f"  sha256     {result.file_sha256}")
    provenance = result.configuration["osm_provenance"]
    print(
        f"  osm edits  {provenance['nodes_with_version']}/{provenance['nodes']} nodes, "
        f"{provenance['edges_with_way_version']}/{provenance['edges']} segments with a way "
        f"version, {provenance['edges_with_way_latest_edit']} with a latest member edit"
    )
    return EXIT_OK


async def _apply_elevation(database: Database, args: argparse.Namespace) -> int:
    try:
        provider = build_provider(args.provider)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_MISCONFIGURED
    if not provider.enabled:
        print("error: elevation provider is disabled; pass --provider.", file=sys.stderr)
        return EXIT_MISCONFIGURED

    definition = region_definition(args.region)
    async with database.session() as session:
        # An unseeded region is an operator mistake, not a crash. Reporting it
        # as a traceback tells somebody scripting an import nothing useful.
        try:
            region = await require_region(session, definition.slug)
        except DatasetLifecycleError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED
        try:
            wanted = (
                None
                if args.dataset is None
                else (await _dataset_by_reference(session, args.dataset)).id
            )
            dataset = await resolve_candidate(session, region.id, wanted)
        except DatasetLifecycleError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED

        print(
            f"Sampling {provider.name} ({provider.dataset}) "
            f"for {definition.display_name} candidate {dataset.id}..."
        )
        run = await enrich_with_elevation(
            session, dataset_id=dataset.id, provider=provider, batch_size=args.batch_size
        )
        await session.commit()

    print(f"Sampled in {run.duration_seconds:.1f}s.")
    for line in summarise(run):
        print(line)
    if provider.attribution:
        print(f"  attribution {provider.attribution}")
    return EXIT_OK


async def _evaluate(database: Database, args: argparse.Namespace) -> int:
    definition = region_definition(args.region)
    baseline = get_profile("standard")
    try:
        subject = get_profile(args.profile)
    except KeyError:
        print(f"error: unknown profile {args.profile!r}.", file=sys.stderr)
        return EXIT_MISCONFIGURED

    repository = GraphRepository()
    async with database.session() as session:
        graph = await repository.active_graph(session, definition.slug)

    print(
        f"{definition.display_name}: {graph.node_count} nodes, "
        f"{graph.segment_count} segments (loaded in {graph.load_seconds:.2f}s)"
    )
    print(f"Routing {len(WATERLOO_CASES)} cases: standard vs {subject.display_name}\n")

    comparisons = evaluate(graph, cases=WATERLOO_CASES, baseline=baseline, subject=subject)
    changed = sum(1 for entry in comparisons if entry.route_changed)
    unroutable = sum(1 for entry in comparisons if not entry.subject.routed)

    for entry in comparisons:
        marker = "changed" if entry.route_changed else "same   "
        detour = "" if entry.detour_m is None else f"{entry.detour_m:+8.1f} m"
        print(f"  [{marker}] {entry.case:<32} {detour:>12}  {entry.reason()}")

    print(
        f"\n{changed}/{len(comparisons)} routes changed; "
        f"{unroutable}/{len(comparisons)} had no route for {subject.display_name}."
    )

    payload: dict[str, object] = {
        "region": definition.slug,
        "dataset_checksum": graph.checksum,
        "baseline_profile": baseline.key,
        "subject_profile": subject.key,
        "cases": as_records(comparisons),
    }

    if args.algorithms:
        print("\nDijkstra vs A* (median of 3 runs each):")
        timings = compare_algorithms(graph, cases=WATERLOO_CASES, profile=subject)
        for timing in timings:
            agreement = "same cost" if timing.costs_agree else "DIFFERENT COST"
            print(
                f"  {timing.case:<32} dijkstra {timing.dijkstra_ms:7.2f} ms "
                f"({timing.dijkstra_expanded:>6} expanded)  "
                f"astar {timing.astar_ms:7.2f} ms ({timing.astar_expanded:>6} expanded)  "
                f"{agreement}"
            )
        payload["algorithms"] = [asdict(timing) for timing in timings]

    if args.ablate:
        print()
        rows = run_ablation(graph, cases=WATERLOO_CASES, profile=subject)
        for line in summarise_ablation(rows, subject):
            print(line)
        payload["ablation"] = [{"case": row.case, "distances": row.distances()} for row in rows]

    if args.json:
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return EXIT_OK


async def _coverage(database: Database, args: argparse.Namespace) -> int:
    definition = region_definition(args.region)
    async with database.session() as session:
        # An unseeded region is an operator mistake, not a crash. Reporting it
        # as a traceback tells somebody scripting an import nothing useful.
        try:
            region = await require_region(session, definition.slug)
        except DatasetLifecycleError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED
        if args.dataset:
            dataset = await session.get(DatasetVersion, uuid.UUID(args.dataset))
        else:
            dataset = await get_active_dataset(session, region.id)
        if dataset is None:
            print(f"error: no dataset found for {definition.slug}.", file=sys.stderr)
            return EXIT_FAILED

        report = await build_coverage_report(
            session, dataset=dataset, region=definition.display_name
        )

    for line in render(report):
        print(line)
    if args.json:
        Path(args.json).write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return EXIT_OK


async def _ingest_synthetic(database: Database, args: argparse.Namespace) -> int:
    async with database.session() as session:
        try:
            ingestion = await load_synthetic_dataset(session, activate=not args.no_activate)
        except (DatasetLifecycleError, DatasetValidationError) as error:
            await session.rollback()
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED
        await session.commit()

    _report(ingestion, "synthetic test network (not real data)")
    return EXIT_OK


async def _list_datasets(database: Database, args: argparse.Namespace) -> int:
    statement = (
        select(DatasetVersion, PilotRegion.slug)
        .join(PilotRegion, DatasetVersion.pilot_region_id == PilotRegion.id)
        .order_by(DatasetVersion.created_at.desc())
        .limit(max(1, min(args.limit, 200)))
    )
    if args.region:
        statement = statement.where(PilotRegion.slug == args.region)

    async with database.session() as session:
        rows = (await session.execute(statement)).all()

    if not rows:
        print("No datasets.")
        return EXIT_OK

    print(
        f"{'ID':<10}{'REGION':<20}{'STATUS':<11}{'NODES':>8}{'EDGES':>8}  "
        f"{'CHECKSUM':<14}{'CONTENT':<16}SOURCE"
    )
    for dataset, slug in rows:
        content = (
            "not recorded"
            if dataset.content_checksum is None
            else f"{dataset.content_checksum[:12]} v{dataset.content_checksum_version}"
        )
        print(
            f"{str(dataset.id)[:8]:<10}{slug:<20}{dataset.status:<11}{dataset.node_count:>8}"
            f"{dataset.edge_count:>8}  {dataset.checksum[:12]:<14}{content:<16}"
            f"{dataset.source_name}"
        )
    return EXIT_OK


async def _benchmark(database: Database, args: argparse.Namespace) -> int:
    profile_keys = args.profile or ["standard", "wheelchair"]
    profiles = [get_profile(key) for key in profile_keys]

    if args.grid is not None:
        size = max(2, min(args.grid, 200))
        payload = build_measurement_grid(size)
        graph = graph_from_payload(payload, region_slug="synthetic-grid")
        label = f"synthetic {size}x{size} grid (not a map of anywhere)"
    elif args.region is not None:
        repository = GraphRepository()
        async with database.session() as session:
            graph = await repository.active_graph(session, args.region)
        label = f"{args.region} dataset {graph.checksum[:12]} (load {graph.load_seconds:.2f}s)"
    else:
        print("error: pass --region <slug> or --grid <size>.", file=sys.stderr)
        return EXIT_MISCONFIGURED

    report = measure(graph, profiles, samples=max(1, args.samples), dataset_label=label)

    print(f"Dataset   {report.dataset}")
    print(f"Nodes     {report.node_count}")
    print(f"Segments  {report.segment_count}")
    print()
    print(f"{'PROFILE':<18}{'N':>5}{'FAIL':>6}{'p50 ms':>10}{'p95 ms':>10}{'max ms':>10}")
    for summary in report.summaries:
        print(
            f"{summary.profile:<18}{summary.samples:>5}{summary.failures:>6}"
            f"{summary.p50_ms:>10.2f}{summary.p95_ms:>10.2f}{summary.max_ms:>10.2f}"
        )
    return EXIT_OK


async def _benchmark_load(database: Database, args: argparse.Namespace) -> int:
    if args.runs < 0 or args.heap_runs < 0 or args.runs + args.heap_runs < 1:
        print("error: ask for at least one run.", file=sys.stderr)
        return EXIT_MISCONFIGURED

    async with database.session() as session:
        try:
            report = await run_load_benchmark(
                session, args.region, runs=args.runs, heap_runs=args.heap_runs
            )
        except NoActiveDatasetError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED

    for line in render_load_benchmark(report):
        print(line)

    if args.json:
        # LF regardless of platform: this file is committed as evidence and the
        # repository's formatter check rejects CRLF.
        Path(args.json).write_text(
            json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"\nWrote {args.json}")
    return EXIT_OK


def _overture_offline(args: argparse.Namespace) -> int:
    fetch_json = http_json_fetcher()
    if args.overture_command == "releases":
        try:
            latest = resolve_release(LATEST, fetch_json)
            details = [
                resolve_release(release, fetch_json) for release in latest.available_releases
            ]
        except ReleaseError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED
        for detail in details:
            marker = "  (latest)" if detail.observed == latest.latest_at_resolution else ""
            print(f"{detail.observed}\tschema {detail.schema_version}{marker}")
        return EXIT_OK

    if args.bridge_sample_files < 0:
        print("error: --bridge-sample-files cannot be negative.", file=sys.stderr)
        return EXIT_MISCONFIGURED
    definition = region_definition(args.region)
    plan = ExtractionPlan(
        region_slug=definition.slug,
        bounds=definition.bounds,
        bounds_source=f"pathable_api.geo.regions: {definition.slug}",
        release=args.release,
        bridge_sample_files=args.bridge_sample_files,
        include_changelog=not args.no_changelog,
    )
    try:
        result = run_extraction(
            plan,
            args.out,
            fetch_json=fetch_json,
            progress=print,
            measure_memory=_run_measurements,
        )
    except (ReleaseError, IncompatibleSchemaError, ExtractionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED

    print(f"\nOverture {result.release.observed} (schema {result.release.schema_version})")
    for name, artifact in sorted(result.artifacts.items()):
        received = (
            f"{artifact.http.bytes_received / 1_000_000:.1f} MB received"
            if artifact.http is not None
            else "local"
        )
        print(
            f"  {name:<14}{artifact.rows:>8} rows  {artifact.files_opened}/"
            f"{artifact.files_available} files  {artifact.seconds:6.1f}s  {received}"
        )
    for warning in result.warnings:
        print(f"  warning: {warning}")
    print(f"Wrote {result.out_dir / EXTRACT_MANIFEST}")
    return EXIT_OK


async def _overture_link(database: Database, args: argparse.Namespace) -> int:
    definition = region_definition(args.region)
    try:
        overture = load_overture_side(args.extract)
    except ExtractMismatchError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    if overture.manifest["region"]["slug"] != definition.slug:
        print(
            f"error: {args.extract} was extracted for {overture.manifest['region']['slug']}, "
            f"not {definition.slug}.",
            file=sys.stderr,
        )
        return EXIT_MISCONFIGURED
    try:
        dataset_id = uuid.UUID(args.dataset) if args.dataset else None
    except ValueError:
        print("error: --dataset must be a UUID.", file=sys.stderr)
        return EXIT_MISCONFIGURED

    started = time.perf_counter()
    async with database.session() as session:
        try:
            identities = await load_identities(
                session, region_slug=definition.slug, dataset_id=dataset_id
            )
        except (PathAbleSideError, DatasetLifecycleError) as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED

    evidence = None
    if args.osm_pbf is not None:
        print(f"Reading OSM versions from {args.osm_pbf.name}...")
        try:
            evidence = read_versions(
                args.osm_pbf,
                expected_sha256=identities.facts.source_file_sha256,
                way_ids=_osm_ids(identities.way_edges),
                node_ids=_osm_ids(identities.node_ids),
            )
        except VersionEvidenceError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED

    run: dict[str, object] = {
        "generated_at": dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
        "seconds": round(time.perf_counter() - started, 2),
        "version_evidence_seconds": round(evidence.seconds, 2) if evidence else None,
        **_run_measurements(),
    }
    report = build_report(identities, overture, evidence, run=run)

    ways = report["ways"]
    print(f"PathAble dataset {identities.facts.dataset_id} ({identities.facts.checksum[:12]})")
    print(f"Overture {overture.release}: {len(overture.segments)} segments in the extract")
    print(f"  PathAble ways          {ways['pathable_ways']}")
    for match, count in ways["by_match"].items():
        print(f"    {match:<32}{count:>8}")
    print("  linked ways by version status")
    for status, count in ways["by_version_status"].items():
        print(f"    {status:<40}{count:>8}")
    print("  linked ways by cardinality")
    for cardinality, count in ways["by_cardinality"].items():
        print(f"    {cardinality:<32}{count:>8}")
    if args.json is not None:
        write_json(args.json, report)
        print(f"\nWrote {args.json}")
    return EXIT_OK


def _osm_ids(raw_ids: Iterable[str]) -> set[int]:
    return {osm_id for osm_id in map(parse_pathable_osm_id, raw_ids) if osm_id is not None}


def _run_measurements() -> dict[str, Any]:
    """Where and on what a run happened. Recorded, never hashed."""
    memory = process_memory()
    machine = machine_memory()
    return {
        "environment": describe_environment(),
        "machine_memory_mb": machine.total_mb,
        "peak_process_memory_mb": memory.peak_rss_mb,
        "process_memory_method": memory.method,
    }


def _report(ingestion: IngestionResult, label: str) -> None:
    print(f"Dataset {ingestion.dataset_id} for {label}")
    print(f"  status     {ingestion.status}")
    print(f"  checksum   {ingestion.checksum} (as ingested, before enrichment)")
    print(f"  nodes      {ingestion.node_count}")
    print(f"  edges      {ingestion.edge_count}")
    print(f"  warnings   {len(ingestion.report.warnings)}")
    if ingestion.status == "draft":
        print(
            "  next       enrich it if required, then `pathable datasets seal`, "
            "`evaluate` and `activate`"
        )


# ---------------------------------------------------------------------------
# The gated lifecycle
# ---------------------------------------------------------------------------


def _is_prefix(text: str) -> bool:
    return len(text) >= 8 and all(character in "0123456789abcdef-" for character in text)


async def _dataset_by_reference(session: AsyncSession, reference: str) -> DatasetVersion:
    """A dataset by full id or by a unique prefix, as `datasets list` prints it."""
    text = reference.strip().lower()
    try:
        found = await session.get(DatasetVersion, uuid.UUID(text))
    except ValueError:
        found = None
        if not _is_prefix(text):
            msg = f"{reference!r} is not a dataset id or a prefix of at least 8 characters."
            raise DatasetLifecycleError(msg) from None
        matches = (
            (
                await session.execute(
                    select(DatasetVersion)
                    .where(cast(DatasetVersion.id, String).like(f"{text}%"))
                    .limit(2)
                )
            )
            .scalars()
            .all()
        )
        if len(matches) == 1:
            found = matches[0]
        elif len(matches) > 1:
            msg = f"{reference!r} matches more than one dataset; give more of the id."
            raise DatasetLifecycleError(msg) from None
    if found is None:
        msg = f"No dataset matches {reference!r}."
        raise DatasetLifecycleError(msg)
    return found


async def _run_by_reference(session: AsyncSession, reference: str) -> RouteRegressionRun:
    text = reference.strip().lower()
    try:
        found = await session.get(RouteRegressionRun, uuid.UUID(text))
    except ValueError:
        found = None
        if _is_prefix(text):
            matches = (
                (
                    await session.execute(
                        select(RouteRegressionRun)
                        .where(cast(RouteRegressionRun.id, String).like(f"{text}%"))
                        .limit(2)
                    )
                )
                .scalars()
                .all()
            )
            found = matches[0] if len(matches) == 1 else None
    if found is None:
        msg = f"No single regression run matches {reference!r}."
        raise DatasetLifecycleError(msg)
    return found


async def _seal(database: Database, args: argparse.Namespace) -> int:
    async with database.session() as session:
        try:
            dataset = await _dataset_by_reference(session, args.dataset)
            result = await seal_candidate(session, dataset.id)
        except SealRefusedError as error:
            await session.rollback()
            print(f"error: {error}", file=sys.stderr)
            for finding in error.report.errors[:10]:
                print(f"  {finding.code}: {finding.message}", file=sys.stderr)
            return EXIT_FAILED
        except DatasetLifecycleError as error:
            await session.rollback()
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED
        await session.commit()

    print(f"Sealed {result.dataset_id}")
    print(f"  content    {result.checksum.value} (v{result.checksum.version})")
    print(f"  hashed     {result.checksum.node_count} nodes, {result.checksum.edge_count} edges")
    print(f"             in {result.checksum.seconds:.2f}s")
    print("  next       `pathable datasets evaluate` against the live dataset")
    return EXIT_OK


async def _checksum(database: Database, args: argparse.Namespace) -> int:
    async with database.session() as session:
        try:
            dataset = await _dataset_by_reference(session, args.dataset)
            if args.record:
                computed = await record_content_checksum(session, dataset.id)
                await session.commit()
                print(f"Recorded {computed.value} (v{computed.version}) for {dataset.id}")
                print(f"  hashed {computed.node_count} nodes, {computed.edge_count} edges")
                print(f"  in {computed.seconds:.2f}s")
                return EXIT_OK
            verification = await verify_content_checksum(session, dataset.id)
        except DatasetLifecycleError as error:
            await session.rollback()
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED

    computed = verification.computed
    print(f"Dataset {dataset.id}")
    print(f"  recorded   {verification.recorded or 'none'}")
    print(f"  rows hash  {computed.value} (v{computed.version}, {computed.seconds:.2f}s)")
    if verification.recorded is None:
        print("  no content checksum is recorded; `--record` records this one")
        return EXIT_FAILED
    print(f"  {'matches' if verification.matches else 'DOES NOT MATCH'}")
    return EXIT_OK if verification.matches else EXIT_FAILED


async def _evaluate_candidate(database: Database, args: argparse.Namespace) -> int:
    async with database.session() as session:
        try:
            dataset = await _dataset_by_reference(session, args.dataset)
            run = await evaluate_candidate(session, dataset.id, app_version=__version__)
        except DatasetLifecycleError as error:
            await session.rollback()
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED
        await session.commit()

    print(f"Regression run {run.id}")
    print(f"  candidate  {run.candidate_dataset_id} ({run.candidate_content_checksum[:12]})")
    baseline = (
        "none — no dataset is live"
        if run.baseline_dataset_id is None
        else f"{run.baseline_dataset_id} ({(run.baseline_content_checksum or '')[:12]})"
    )
    print(f"  baseline   {baseline}")
    print(
        f"  corpus     {run.corpus_key}: {run.comparison_count} journeys x profiles, "
        f"routing policy v{run.routing_policy_version}"
    )
    print(f"  took       {run.duration_seconds:.1f}s")
    print(f"  outcome    {run.outcome} ({run.difference_count} differences)")
    for difference in run.differences[:40]:
        print(
            f"    {difference['case']:<34}{difference['profile']:<18}{difference['field']:<22}"
            f"{difference['baseline']!s:>14} -> {difference['candidate']!s}"
        )
    if run.difference_count > 40:
        print(f"    ... and {run.difference_count - 40} more (see --json)")
    if args.json is not None:
        write_json(
            args.json,
            {
                "run_id": str(run.id),
                "candidate_dataset_id": str(run.candidate_dataset_id),
                "candidate_content_checksum": run.candidate_content_checksum,
                "baseline_dataset_id": None
                if run.baseline_dataset_id is None
                else str(run.baseline_dataset_id),
                "baseline_content_checksum": run.baseline_content_checksum,
                "corpus_key": run.corpus_key,
                "corpus_fingerprint": run.corpus_fingerprint,
                "profiles": run.profiles,
                "routing_policy_version": run.routing_policy_version,
                "app_version": run.app_version,
                "outcome": run.outcome,
                "comparison_count": run.comparison_count,
                "difference_count": run.difference_count,
                "duration_seconds": run.duration_seconds,
                "started_at": run.started_at.isoformat(),
                "differences": run.differences,
                "results": run.results,
            },
        )
        print(f"\nWrote {args.json}")
    if run.outcome == IDENTICAL:
        print("  next       `pathable datasets activate`")
        return EXIT_OK
    print("  next       review; if intended, `pathable datasets accept` with a reason")
    return EXIT_REVIEW_REQUIRED


async def _accept(database: Database, args: argparse.Namespace) -> int:
    async with database.session() as session:
        try:
            run = await _run_by_reference(session, args.run)
            acceptance = await accept_regression(session, run.id, reason=args.reason)
        except DatasetLifecycleError as error:
            await session.rollback()
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED
        await session.commit()
    print(f"Accepted run {run.id} ({run.outcome}, {run.difference_count} differences)")
    print(f"  reason     {acceptance.reason}")
    return EXIT_OK


async def _activate(database: Database, args: argparse.Namespace) -> int:
    started = time.perf_counter()
    async with database.session() as session:
        try:
            dataset = await _dataset_by_reference(session, args.dataset)
            run_id = None if args.run is None else (await _run_by_reference(session, args.run)).id
            switch = await activate_candidate(session, dataset.id, regression_run_id=run_id)
        except DatasetLifecycleError as error:
            await session.rollback()
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED
        await session.commit()
    elapsed = time.perf_counter() - started
    event = switch.event
    print(f"Activated {event.to_dataset_id} ({event.to_content_checksum[:12]})")
    print(f"  retired    {switch.previous_id or 'nothing — no dataset was live'}")
    print(f"  on run     {event.regression_run_id}")
    if event.acceptance_id is not None:
        print(f"  accepted   {event.acceptance_id}")
    print(f"  switch     {switch.seconds * 1000:.1f} ms; with commit {elapsed * 1000:.1f} ms")
    return EXIT_OK


async def _rollback(database: Database, args: argparse.Namespace) -> int:
    definition = region_definition(args.region)
    async with database.session() as session:
        try:
            region = await require_region(session, definition.slug)
            wanted = None if args.to is None else (await _dataset_by_reference(session, args.to)).id
            target = await rollback_target(session, region.id, wanted)
            print(f"Verifying {target.id} against its recorded content checksum...")
            verified = await verify_rollback_target(session, target)
        except DatasetLifecycleError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED
    print(f"  verified   {verified.value[:12]} from its rows in {verified.seconds:.2f}s")

    started = time.perf_counter()
    async with database.session() as session:
        try:
            switch = await rollback(
                session,
                region_id=region.id,
                target_id=target.id,
                verified_checksum=verified.value,
                reason=args.reason,
            )
        except DatasetLifecycleError as error:
            await session.rollback()
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED
        await session.commit()
    elapsed = time.perf_counter() - started
    print(f"Rolled back {definition.slug}: {switch.previous_id} -> {target.id}")
    print(f"  switch     {switch.seconds * 1000:.1f} ms; with commit {elapsed * 1000:.1f} ms")
    return EXIT_OK


async def _history(database: Database, args: argparse.Namespace) -> int:
    definition = region_definition(args.region)
    async with database.session() as session:
        try:
            region = await require_region(session, definition.slug)
        except DatasetLifecycleError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED
        events = await activation_history(session, region.id)
        acceptances = {
            acceptance.id: acceptance
            for acceptance in (
                await session.execute(
                    select(RouteRegressionAcceptance).where(
                        RouteRegressionAcceptance.id.in_(
                            [event.acceptance_id for event in events if event.acceptance_id]
                        )
                    )
                )
            ).scalars()
        }
    if not events:
        print("No recorded activations. Datasets activated before PA-GEO-02 have none.")
        return EXIT_OK
    for event in events:
        source = "nothing" if event.from_dataset_id is None else str(event.from_dataset_id)[:8]
        print(
            f"{event.occurred_at:%Y-%m-%d %H:%M:%S}Z  {event.action:<9}"
            f"{source} -> {str(event.to_dataset_id)[:8]} ({event.to_content_checksum[:12]})"
        )
        if event.regression_run_id is not None:
            print(f"    run {event.regression_run_id}")
        accepted = acceptances.get(event.acceptance_id) if event.acceptance_id else None
        if accepted is not None:
            print(f"    accepted: {accepted.reason}")
        if event.reason:
            print(f"    reason: {event.reason}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
