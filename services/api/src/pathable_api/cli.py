"""The ``pathable`` command line.

Operational tasks that are not HTTP requests: seeding regions, importing a
network, and inspecting what is currently live. Argparse rather than a CLI
framework — the surface is small, and a dependency that only saves a few lines of
argument wiring is not worth carrying.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select

from pathable_api.core.config import ConfigurationError, get_settings
from pathable_api.core.event_loop import selector_loop_factory
from pathable_api.core.logging import configure_logging, get_logger
from pathable_api.db.session import Database, build_database
from pathable_api.geo.datasets import (
    DatasetLifecycleError,
    DatasetValidationError,
    IngestionResult,
    ingest_network,
    require_region,
)
from pathable_api.geo.enums import SourceType
from pathable_api.geo.fixtures import load_synthetic_dataset
from pathable_api.geo.models import DatasetVersion, PilotRegion
from pathable_api.geo.osm import OverpassUnreachableError, import_walk_network
from pathable_api.geo.pbf import import_from_pbf
from pathable_api.geo.regions import PILOT_REGIONS, region_definition, seed_pilot_regions
from pathable_api.routing.benchmark import build_measurement_grid, measure
from pathable_api.routing.graph import GraphRepository, graph_from_payload
from pathable_api.routing.profiles import get_profile

logger = get_logger(__name__)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_MISCONFIGURED = 2


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
        "--no-activate",
        action="store_true",
        help="Validate and store the dataset without making it the live network.",
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
    pbf.add_argument("--no-activate", action="store_true")

    synthetic = sources.add_parser(
        "synthetic", help="Load the deterministic test fixture (not real data)."
    )
    synthetic.add_argument("--no-activate", action="store_true")

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

    datasets = subcommands.add_parser("datasets", help="Inspect dataset versions.")
    dataset_actions = datasets.add_subparsers(dest="dataset_command", required=True)
    listing = dataset_actions.add_parser("list", help="List dataset versions, newest first.")
    listing.add_argument("--region", default=None, help="Restrict to one region slug.")
    listing.add_argument("--limit", type=int, default=20)

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
            case "benchmark":
                return await _benchmark(database, args)
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
                activate=not args.no_activate,
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
                activate=not args.no_activate,
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

    print(f"{'REGION':<22}{'STATUS':<12}{'NODES':>8}{'EDGES':>8}  {'CHECKSUM':<14}SOURCE")
    for dataset, slug in rows:
        print(
            f"{slug:<22}{dataset.status:<12}{dataset.node_count:>8}{dataset.edge_count:>8}  "
            f"{dataset.checksum[:12]:<14}{dataset.source_name}"
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


def _report(ingestion: IngestionResult, label: str) -> None:
    print(f"Dataset {ingestion.dataset_id} for {label}")
    print(f"  status     {ingestion.status}")
    print(f"  checksum   {ingestion.checksum}")
    print(f"  nodes      {ingestion.node_count}")
    print(f"  edges      {ingestion.edge_count}")
    print(f"  warnings   {len(ingestion.report.warnings)}")
    if not ingestion.activated:
        print("  not activated (--no-activate)")


if __name__ == "__main__":
    raise SystemExit(main())
