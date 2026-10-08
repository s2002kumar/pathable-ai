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

Place search reads the same extract into the region's place index, which is
replaced whole and is not part of the lifecycle above::

    pathable gazetteer build --region waterloo --file ...
    pathable gazetteer search --region waterloo "Davis Centre"
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import datetime as dt
import json
import sys
import time
import uuid
from collections.abc import Iterable, Mapping, Sequence
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
from pathable_api.geo.gazetteer import import_gazetteer
from pathable_api.geo.gazetteer_store import attribution as gazetteer_attribution
from pathable_api.geo.gazetteer_store import (
    gazetteer_build,
    replace_gazetteer,
    search_gazetteer,
)
from pathable_api.geo.kitchener.arcgis import (
    DEFAULT_CHUNK_SIZE,
    ArcGISClient,
    ArcGISError,
    RequestsTransport,
)
from pathable_api.geo.kitchener.audit import AuditError, run_audit
from pathable_api.geo.kitchener.audit import write_outputs as write_kitchener_outputs
from pathable_api.geo.kitchener.conflation import load_inputs as load_conflation_inputs
from pathable_api.geo.kitchener.curb_ramp_page import render_page as render_curb_ramp_page
from pathable_api.geo.kitchener.curb_ramp_reconciliation import CurbRampError
from pathable_api.geo.kitchener.curb_ramp_run import reconcile as reconcile_curb_ramps
from pathable_api.geo.kitchener.curb_ramp_run import rejected_examples
from pathable_api.geo.kitchener.curb_ramp_run import run_study as run_curb_ramp_study
from pathable_api.geo.kitchener.curb_ramp_run import shadow_evidence as curb_ramp_evidence
from pathable_api.geo.kitchener.evaluation import (
    BenchmarkError,
    load_label_sets,
    run_benchmark,
    run_pilot,
)
from pathable_api.geo.kitchener.failures_page import render_failures
from pathable_api.geo.kitchener.geography import (
    PathAbleReadError,
    read_dataset_source,
    read_pathable_edges,
)
from pathable_api.geo.kitchener.holdout import HoldoutError, build_holdout
from pathable_api.geo.kitchener.holdout_review import blind_document, retitle
from pathable_api.geo.kitchener.holdout_review import digest as holdout_digest
from pathable_api.geo.kitchener.imagery import ImageryError, survey_imagery
from pathable_api.geo.kitchener.lineage import ESRI_MUNICIPAL_SINCE, LabelError
from pathable_api.geo.kitchener.matcher_v2_benchmark import BenchmarkV2Error
from pathable_api.geo.kitchener.matcher_v2_benchmark import (
    load_label_sets as load_matcher_v2_label_sets,
)
from pathable_api.geo.kitchener.matcher_v2_benchmark import (
    render_errors as render_matcher_v2_errors,
)
from pathable_api.geo.kitchener.matcher_v2_benchmark import (
    run_benchmark as run_matcher_v2_benchmark,
)
from pathable_api.geo.kitchener.matcher_v2_benchmark import run_pilot as run_matcher_v2_pilot
from pathable_api.geo.kitchener.matcher_v2_holdout import (
    PRIMARY_PACKS as MATCHER_V2_PRIMARY_PACKS,
)
from pathable_api.geo.kitchener.matcher_v2_holdout import (
    REPEAT_PACKS as MATCHER_V2_REPEAT_PACKS,
)
from pathable_api.geo.kitchener.matcher_v2_holdout import (
    build_holdout as build_matcher_v2_holdout,
)
from pathable_api.geo.kitchener.matcher_v2_holdout import packs as matcher_v2_packs
from pathable_api.geo.kitchener.matcher_v2_holdout import repeat_subset as matcher_v2_repeat
from pathable_api.geo.kitchener.matcher_v2_labels import DEFINITIONS as MATCHER_V2_DEFINITIONS
from pathable_api.geo.kitchener.matcher_v2_labels import (
    LABELS_VERSION as MATCHER_V2_LABELS_VERSION,
)
from pathable_api.geo.kitchener.matcher_v2_labels import (
    collect_labels as collect_matcher_v2_labels,
)
from pathable_api.geo.kitchener.matcher_v2_labels import (
    development_labels as matcher_v2_development_labels,
)
from pathable_api.geo.kitchener.matcher_v2_labels import label_facts as matcher_v2_label_facts
from pathable_api.geo.kitchener.matcher_v2_labels import parse_labels as parse_matcher_v2_labels
from pathable_api.geo.kitchener.matcher_v2_review import blind as matcher_v2_blind
from pathable_api.geo.kitchener.matcher_v2_review import digest as matcher_v2_digest
from pathable_api.geo.kitchener.matcher_v2_review import elements_by_record as matcher_v2_elements
from pathable_api.geo.kitchener.matcher_v2_review import retitle as matcher_v2_retitle
from pathable_api.geo.kitchener.normalize import NormalizationError, normalize_snapshot
from pathable_api.geo.kitchener.osm_extract import (
    EXTRACT_FORMAT_VERSION,
    ExtractSourceError,
    load_study_extract,
    read_study_extract,
    write_study_extract,
)
from pathable_api.geo.kitchener.osm_history import (
    OHSOME_API,
    ChangesetDump,
    HistoryError,
    dump_identity,
    fetch_history,
    ohsome_metadata,
    ohsome_requests,
)
from pathable_api.geo.kitchener.reconciliation_run import (
    ReconciliationError,
    RunInputs,
    compare_runs,
    load_run_inputs,
    reconciliation_evidence,
    reconciliation_manifest,
    run_reconciliation,
    write_reconciliation_artifact,
)
from pathable_api.geo.kitchener.review import render_review
from pathable_api.geo.kitchener.shadow_overlay import ShadowError, load_surface_evidence
from pathable_api.geo.kitchener.shadow_page import render_changes
from pathable_api.geo.kitchener.shadow_run import (
    active_dataset,
    compare_shadow_runs,
    load_active,
    read_only,
    shadow_evidence,
    validation_queue,
)
from pathable_api.geo.kitchener.shadow_run import run_study as run_shadow_study
from pathable_api.geo.kitchener.shadow_study import study_profiles
from pathable_api.geo.kitchener.snapshot import SnapshotError, SnapshotPlan, take_snapshot
from pathable_api.geo.kitchener.study import ATTRIBUTION as KITCHENER_OSM_ATTRIBUTION
from pathable_api.geo.kitchener.study import (
    StudyError,
    history_document,
    history_elements,
    load_history,
    load_inputs,
    run_study,
    slim,
)
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
from pathable_api.geo.overture.evidence import content_sha256, file_sha256, write_json
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

    gazetteer = subcommands.add_parser(
        "gazetteer",
        help="Build or query a region's place index for search. Not a routing dataset.",
    )
    gazetteer_actions = gazetteer.add_subparsers(dest="gazetteer_command", required=True)
    gazetteer_build_command = gazetteer_actions.add_parser(
        "build",
        help=(
            "Read places, addresses and streets from a local OpenStreetMap extract and "
            "replace the region's place index with them."
        ),
    )
    gazetteer_build_command.add_argument(
        "--region", required=True, choices=[definition.slug for definition in PILOT_REGIONS]
    )
    gazetteer_build_command.add_argument(
        "--file",
        required=True,
        type=Path,
        help="Path to a .osm.pbf extract, the one the active network was built from.",
    )
    gazetteer_build_command.add_argument(
        "--provider", default="geofabrik", help="Who published the extract. Recorded."
    )
    gazetteer_build_command.add_argument(
        "--source-timestamp",
        default=None,
        help=(
            "When the extract's data is current to (ISO 8601). Defaults to the extract's own "
            "header; left unknown if neither says."
        ),
    )
    gazetteer_search_command = gazetteer_actions.add_parser(
        "search", help="Search a region's place index exactly as the API does."
    )
    gazetteer_search_command.add_argument(
        "--region", required=True, choices=[definition.slug for definition in PILOT_REGIONS]
    )
    gazetteer_search_command.add_argument("query", help="Place name, address or street.")
    gazetteer_search_command.add_argument("--limit", type=int, default=5, choices=range(1, 6))

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

    kitchener = subcommands.add_parser(
        "kitchener",
        help=(
            "Audit the City of Kitchener Active Transportation inventory. Never writes to the "
            "database and never affects routing."
        ),
    )
    kitchener_actions = kitchener.add_subparsers(dest="kitchener_command", required=True)
    snapshot = kitchener_actions.add_parser(
        "snapshot", help="Freeze a complete snapshot of the City's publications into local files."
    )
    snapshot.add_argument(
        "--out",
        type=Path,
        default=Path(".kitchener-data/snapshots"),
        help="Root folder; each snapshot gets its own new folder. Keep it out of git.",
    )
    snapshot.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help="Features per request (capped at the service's maxRecordCount).",
    )
    snapshot.add_argument("--json", type=Path, default=None, help="Also copy the manifest here.")
    normalize = kitchener_actions.add_parser(
        "normalize", help="Build the analytical GeoParquet file from a snapshot. Offline."
    )
    normalize.add_argument("--snapshot", type=Path, required=True, help="A snapshot folder.")
    normalize.add_argument(
        "--out", type=Path, required=True, help="A new folder for the output; never overwritten."
    )
    normalize.add_argument("--json", type=Path, default=None, help="Also copy the manifest here.")
    audit = kitchener_actions.add_parser(
        "audit",
        help=(
            "Profile a normalized snapshot, relate it to a pilot region and draw the PA-GEO-04 "
            "sample. Reads PathAble in a read-only transaction."
        ),
    )
    audit.add_argument(
        "--region", required=True, choices=sorted(region.slug for region in PILOT_REGIONS)
    )
    audit.add_argument("--snapshot", type=Path, required=True)
    audit.add_argument("--normalized", type=Path, required=True)
    audit.add_argument("--dataset", default=None, help="Defaults to the active dataset.")
    audit.add_argument("--json", type=Path, required=True, help="Write the profile here.")
    audit.add_argument("--sample", type=Path, required=True, help="Write the GeoJSON sample here.")

    lineage_extract = kitchener_actions.add_parser(
        "lineage-extract",
        help=(
            "Freeze the OSM side of the PA-GEO-04 lineage study from the dataset's own source "
            "extract, refused unless its SHA-256 matches. Reads PathAble read-only."
        ),
    )
    lineage_extract.add_argument(
        "--region", required=True, choices=sorted(region.slug for region in PILOT_REGIONS)
    )
    lineage_extract.add_argument("--dataset", default=None, help="Defaults to the active dataset.")
    lineage_extract.add_argument("--pbf", type=Path, required=True, help="The source extract.")
    lineage_extract.add_argument(
        "--out", type=Path, required=True, help="Write the study extract (.jsonl.gz) here."
    )
    lineage_extract.add_argument(
        "--json", type=Path, required=True, help="Write its manifest here."
    )

    lineage_study = kitchener_actions.add_parser(
        "lineage-study",
        help=(
            "PA-GEO-04: candidates, review page and evidence for the Kitchener sample against "
            "the frozen OSM extract. Offline; never touches the database."
        ),
    )
    lineage_study.add_argument(
        "--sample", type=Path, required=True, help="The PA-GEO-03 sample GeoJSON."
    )
    lineage_study.add_argument(
        "--sample-sha256", default=None, help="Refuse the sample unless it hashes to this."
    )
    lineage_study.add_argument(
        "--normalized", type=Path, required=True, help="The normalized snapshot folder."
    )
    lineage_study.add_argument(
        "--extract", type=Path, required=True, help="The frozen OSM study extract."
    )
    lineage_study.add_argument("--extract-manifest", type=Path, required=True)
    lineage_study.add_argument(
        "--history", type=Path, default=None, help="From the lineage-history command."
    )
    lineage_study.add_argument(
        "--labels", type=Path, default=None, help="The labels the results use."
    )
    lineage_study.add_argument(
        "--first-pass-labels",
        type=Path,
        default=None,
        help="The first labelling pass as labelled, for consistency (default: --labels).",
    )
    lineage_study.add_argument(
        "--repeat-labels", type=Path, default=None, help="The repeat pass as labelled."
    )
    lineage_study.add_argument(
        "--repeat-refined-labels",
        type=Path,
        default=None,
        help="The repeat pass re-reviewed under refined definitions.",
    )
    lineage_study.add_argument(
        "--json", type=Path, required=True, help="Write the evidence document here."
    )
    lineage_study.add_argument(
        "--full-json",
        type=Path,
        default=None,
        help="Also write the unabridged document, every candidate's metrics included.",
    )
    lineage_study.add_argument("--html", type=Path, default=None, help="Write the review here.")
    lineage_study.add_argument(
        "--blind-html",
        type=Path,
        default=None,
        help="Write a page of the repeat-review subset without labels or history here.",
    )

    def history_sources(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--dump", type=Path, required=True, help="A planet changesets-*.osm.bz2 file."
        )
        command.add_argument(
            "--dump-index",
            type=Path,
            default=None,
            help="The dump's stream index; built beside the dump when missing.",
        )
        command.add_argument(
            "--cache",
            type=Path,
            default=Path(".kitchener-data/osm/ohsome"),
            help="ohsome answers, kept by request hash and reused.",
        )
        command.add_argument("--ohsome-url", default=OHSOME_API)
        command.add_argument(
            "--out",
            type=Path,
            required=True,
            help="Write the history here. It holds changeset comments: keep it out of git.",
        )

    lineage_history = kitchener_actions.add_parser(
        "lineage-history",
        help=(
            "Read the edit history of the study's OSM candidates from the ohsome API and their "
            "changesets from a planet changeset dump. Never uses the OSM editing API."
        ),
    )
    lineage_history.add_argument(
        "--study", type=Path, required=True, help="A document from the lineage-study command."
    )
    lineage_history.add_argument("--extract", type=Path, required=True)
    lineage_history.add_argument("--extract-manifest", type=Path, required=True)
    history_sources(lineage_history)

    imagery_metadata = kitchener_actions.add_parser(
        "imagery-metadata",
        help=(
            "Read Esri World Imagery's metadata over Kitchener: which photographs its finest "
            "layer showed, now and in archived releases. Metadata only, never imagery."
        ),
    )
    imagery_metadata.add_argument(
        "--json", type=Path, required=True, help="Write the metadata evidence here."
    )

    def frozen_inputs(command: argparse.ArgumentParser) -> None:
        command.add_argument("--normalized", type=Path, required=True)
        command.add_argument("--extract", type=Path, required=True)
        command.add_argument("--extract-manifest", type=Path, required=True)

    holdout = kitchener_actions.add_parser(
        "holdout",
        help=(
            "Draw PA-GEO-05's held-out benchmark sample: eligible records minus PA-GEO-04's "
            "development set, stratified, in seeded hash order."
        ),
    )
    frozen_inputs(holdout)
    holdout.add_argument(
        "--development-sample",
        type=Path,
        required=True,
        help="PA-GEO-04's sample file: its records are the development set.",
    )
    holdout.add_argument("--development-sample-sha256", default=None)
    holdout.add_argument("--out", type=Path, required=True, help="Write the sample GeoJSON here.")

    matcher_v2_holdout = kitchener_actions.add_parser(
        "matcher-v2-holdout",
        help=(
            "Draw PA-GEO-08's held-out sample for matcher v2: eligible records minus both "
            "earlier samples, stratified on what matcher v1 could not settle, in seeded hash order."
        ),
    )
    frozen_inputs(matcher_v2_holdout)
    matcher_v2_holdout.add_argument(
        "--development-sample",
        type=Path,
        action="append",
        required=True,
        help="An earlier sample file whose records are development data (repeat for each).",
    )
    matcher_v2_holdout.add_argument(
        "--development-sample-sha256",
        action="append",
        default=None,
        help="The recorded hash of each --development-sample, in the same order.",
    )
    matcher_v2_holdout.add_argument("--out", type=Path, required=True)

    matcher_v2_review = kitchener_actions.add_parser(
        "matcher-v2-review",
        help=(
            "Write the blind review page, text digest and labelling packs for PA-GEO-08's "
            "held-out records: no strata, no labels, no matcher output, candidates in OSM-id order."
        ),
    )
    frozen_inputs(matcher_v2_review)
    matcher_v2_review.add_argument("--sample", type=Path, required=True)
    matcher_v2_review.add_argument("--sample-sha256", default=None)
    matcher_v2_review.add_argument("--html", type=Path, required=True)
    matcher_v2_review.add_argument("--digest", type=Path, required=True)
    matcher_v2_review.add_argument(
        "--packs-dir",
        type=Path,
        default=None,
        help="Also write one folder per labelling pack: its records, and the elements each may cite.",
    )

    matcher_v2_development = kitchener_actions.add_parser(
        "matcher-v2-development-labels",
        help=(
            "Re-read PA-GEO-04's and PA-GEO-05's committed labels under definitions version 2, "
            "recording every change: matcher v2's development set."
        ),
    )
    frozen_inputs(matcher_v2_development)
    matcher_v2_development.add_argument("--evidence-dir", type=Path, required=True)
    matcher_v2_development.add_argument("--out", type=Path, required=True)

    matcher_v2_collect = kitchener_actions.add_parser(
        "matcher-v2-collect-labels",
        help="Merge one labelling pass's validated pack files into the committed label file.",
    )
    matcher_v2_collect.add_argument("--packs-dir", type=Path, required=True)
    matcher_v2_collect.add_argument("--pass", dest="labelling_pass", required=True)
    matcher_v2_collect.add_argument("--sample", type=Path, required=True)
    matcher_v2_collect.add_argument("--guide", type=Path, required=True)
    matcher_v2_collect.add_argument("--review-page", type=Path, required=True)
    matcher_v2_collect.add_argument("--digest", type=Path, required=True)
    matcher_v2_collect.add_argument("--out", type=Path, required=True)

    matcher_v2_benchmark = kitchener_actions.add_parser(
        "matcher-v2-benchmark",
        help=(
            "Run PA-GEO-08's benchmark: check the development grid still selects matcher v2's "
            "frozen policy, then score the baselines, matcher v1 and matcher v2 against the frozen "
            "held-out labels; optionally run the full-pilot dry run."
        ),
    )
    frozen_inputs(matcher_v2_benchmark)
    matcher_v2_benchmark.add_argument("--evidence-dir", type=Path, required=True)
    matcher_v2_benchmark.add_argument(
        "--failure-analysis",
        type=Path,
        default=None,
        help="Causes recorded for the failures, for these exact decisions.",
    )
    matcher_v2_benchmark.add_argument("--json", type=Path, required=True)
    matcher_v2_benchmark.add_argument("--errors-html", type=Path, default=None)
    matcher_v2_benchmark.add_argument(
        "--pilot", action="store_true", help="Also run both matchers over every eligible record."
    )

    matcher_v2_validate = kitchener_actions.add_parser(
        "matcher-v2-validate-labels",
        help="Check a PA-GEO-08 label file against definitions version 2 and its pack.",
    )
    matcher_v2_validate.add_argument("--labels", type=Path, required=True)
    matcher_v2_validate.add_argument(
        "--pack-elements",
        type=Path,
        required=True,
        help="The pack's elements.json: its records, in order, and what each may cite.",
    )

    holdout_review = kitchener_actions.add_parser(
        "holdout-review",
        help=(
            "Write the blind review page and text digest for PA-GEO-05's held-out records: "
            "no strata, no labels, no matcher output, candidates in OSM-id order."
        ),
    )
    frozen_inputs(holdout_review)
    holdout_review.add_argument("--sample", type=Path, required=True)
    holdout_review.add_argument("--sample-sha256", default=None)
    holdout_review.add_argument("--html", type=Path, required=True)
    holdout_review.add_argument("--digest", type=Path, required=True)

    benchmark = kitchener_actions.add_parser(
        "benchmark",
        help=(
            "Run PA-GEO-05's benchmark: check the development grid still selects the frozen "
            "policy, then score the matcher, baselines and ablations against the frozen held-out "
            "labels; optionally run the full-pilot dry run and write its research artifact."
        ),
    )
    frozen_inputs(benchmark)
    benchmark.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
        help="The folder holding the committed sample and label files.",
    )
    benchmark.add_argument(
        "--failure-analysis",
        type=Path,
        default=None,
        help="Causes recorded for the failures, for these exact decisions.",
    )
    benchmark.add_argument("--json", type=Path, required=True)
    benchmark.add_argument("--errors-html", type=Path, default=None)
    benchmark.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help="Run the full pilot and write the research artifact here (never committed).",
    )

    def reconciliation_inputs(command: argparse.ArgumentParser) -> None:
        frozen_inputs(command)
        command.add_argument(
            "--geo05-artifact",
            type=Path,
            required=True,
            help="PA-GEO-05's full-pilot artifact: its decisions are read, never re-made.",
        )
        command.add_argument(
            "--evidence-dir",
            type=Path,
            required=True,
            help="The folder holding the committed Kitchener snapshot evidence.",
        )

    reconcile_history = kitchener_actions.add_parser(
        "reconcile-history",
        help=(
            "Read the edit history of the OSM elements PA-GEO-06 compares with the City, from "
            "the ohsome API and a planet changeset dump. Never uses the OSM editing API."
        ),
    )
    reconciliation_inputs(reconcile_history)
    history_sources(reconcile_history)

    reconcile = kitchener_actions.add_parser(
        "reconcile",
        help=(
            "Run PA-GEO-06: where PA-GEO-05's correspondences are accepted, keep what OSM and "
            "the City each assert, classify how they relate, and write the research artifact "
            "(never committed, never read by routing) and its evidence summary."
        ),
    )
    reconciliation_inputs(reconcile)
    reconcile.add_argument(
        "--history",
        type=Path,
        default=None,
        help="From reconcile-history. Without it, lineage is recorded as not assessed.",
    )
    reconcile.add_argument("--artifact-dir", type=Path, required=True)
    reconcile.add_argument("--json", type=Path, required=True)
    reconcile.add_argument(
        "--compare-to",
        type=Path,
        default=None,
        help="An earlier run's artifact folder: record whether every file is byte-identical.",
    )

    shadow = kitchener_actions.add_parser(
        "shadow-routing",
        help=(
            "Run PA-GEO-07's offline shadow-routing study: route deterministic journeys on the "
            "active graph and on a shadow copy with City-only surfaces filled in, with the "
            "production router. Reads the database only, in READ ONLY transactions."
        ),
    )
    shadow.add_argument("--region", default="waterloo")
    shadow.add_argument(
        "--geo06-artifact",
        type=Path,
        required=True,
        help="PA-GEO-06's reconciliation artifact folder.",
    )
    shadow.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
        help="The folder holding PA-GEO-06's committed evidence.",
    )
    shadow.add_argument("--extract", type=Path, required=True)
    shadow.add_argument("--extract-manifest", type=Path, required=True)
    shadow.add_argument("--broad-size", type=int, default=200)
    shadow.add_argument("--per-stratum", type=int, default=6)
    shadow.add_argument("--seed", default="pathable-pa-geo-07-v1")
    shadow.add_argument("--json", type=Path, required=True)
    shadow.add_argument("--html", type=Path, default=None)
    shadow.add_argument(
        "--compare-to",
        type=Path,
        default=None,
        help="An earlier run's evidence: record whether every outcome is identical.",
    )

    curb = kitchener_actions.add_parser(
        "curb-ramp-shadow-routing",
        help=(
            "Run PA-GEO-09's offline curb-ramp study: reconcile matcher v2's way-extent curb "
            "ramps, map each to the crossing segment where routing charges a kerb, and route "
            "deterministic journeys on the active graph and on a shadow copy. Reads the "
            "database only, in READ ONLY transactions."
        ),
    )
    curb.add_argument("--region", default="waterloo")
    curb.add_argument("--normalized", type=Path, required=True)
    curb.add_argument("--extract", type=Path, required=True)
    curb.add_argument("--extract-manifest", type=Path, required=True)
    curb.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
        help="The folder holding PA-GEO-08's committed evidence.",
    )
    curb.add_argument(
        "--artifact-dir",
        type=Path,
        required=True,
        help="Where to write the reconciliation rows: the ignored data folder.",
    )
    curb.add_argument("--broad-size", type=int, default=300)
    curb.add_argument("--per-stratum", type=int, default=12)
    curb.add_argument("--seed", default="pathable-pa-geo-07-v1")
    curb.add_argument("--json", type=Path, required=True)
    curb.add_argument("--html", type=Path, default=None)
    curb.add_argument(
        "--compare-to",
        type=Path,
        default=None,
        help="An earlier run's evidence: record whether every outcome is identical.",
    )

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
    # Freezing and normalizing a Kitchener snapshot need no database either.
    if args.command == "kitchener" and args.kitchener_command in _KITCHENER_OFFLINE:
        return _kitchener_offline(args)

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
            case "gazetteer" if args.gazetteer_command == "build":
                return await _gazetteer_build(database, args)
            case "gazetteer":
                return await _gazetteer_search(database, args)
            case "overture":
                return await _overture_link(database, args)
            case "kitchener" if args.kitchener_command == "lineage-extract":
                return await _kitchener_lineage_extract(database, args)
            case "kitchener" if args.kitchener_command == "shadow-routing":
                return await _kitchener_shadow_routing(database, args)
            case "kitchener" if args.kitchener_command == "curb-ramp-shadow-routing":
                return await _kitchener_curb_ramp_shadow_routing(database, args)
            case "kitchener":
                return await _kitchener_audit(database, args)
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


def _source_timestamp(value: str | None) -> dt.datetime | None:
    """An ISO 8601 argument as an aware datetime; naive input is taken as UTC."""
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)


async def _gazetteer_build(database: Database, args: argparse.Namespace) -> int:
    definition = region_definition(args.region)
    path = Path(args.file)
    if not path.is_file():
        print(f"error: {path} does not exist.", file=sys.stderr)
        return EXIT_MISCONFIGURED
    try:
        source_timestamp = _source_timestamp(args.source_timestamp)
    except ValueError:
        print("error: --source-timestamp must be ISO 8601.", file=sys.stderr)
        return EXIT_MISCONFIGURED
    # Checked before the read, which takes minutes on a province-sized extract.
    async with database.session() as session:
        try:
            await require_region(session, definition.slug)
        except DatasetLifecycleError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_MISCONFIGURED

    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"Reading places from {path.name} ({size_mb:.0f} MB) for {definition.display_name}...")
    started = time.perf_counter()
    extract = import_gazetteer(
        path,
        definition.bounds,
        region_slug=definition.slug,
        provider=args.provider,
        source_timestamp=source_timestamp,
    )
    read_seconds = time.perf_counter() - started
    extract.configuration["read_seconds"] = round(read_seconds, 2)

    async with database.session() as session:
        region = await require_region(session, definition.slug)
        build = await replace_gazetteer(
            session,
            region=region,
            source_name=f"openstreetmap-pbf:{definition.slug}",
            extract=extract,
        )
        active = await get_active_dataset(session, region.id)
        await session.commit()

    print(f"Place index for {definition.display_name} replaced; read took {read_seconds:.1f}s.")
    print(f"  places     {build.place_count}")
    print(f"  addresses  {build.address_count}")
    print(f"  streets    {build.street_count}")
    print(f"  source     {extract.file_name}")
    print(f"  sha256     {extract.file_sha256}")
    as_of = extract.source_timestamp.isoformat() if extract.source_timestamp else "unknown"
    told_by = extract.configuration["source_timestamp_from"] or "unrecorded"
    print(f"  data as of {as_of} ({told_by})")
    # Search and routing should describe the same map. Reported, not enforced:
    # the index decides no route, and an operator may rebuild either one first.
    network_sha = active.ingestion_configuration.get("file_sha256") if active else None
    if network_sha is None:
        print("  network    no active network records an extract to compare with")
    elif network_sha == extract.file_sha256:
        print("  network    built from the same extract as the active network")
    else:
        print(f"  network    WARNING: the active network came from {network_sha[:16]}, not this")
    return EXIT_OK


async def _gazetteer_search(database: Database, args: argparse.Namespace) -> int:
    definition = region_definition(args.region)
    async with database.session() as session:
        build = await gazetteer_build(session, definition.slug)
        if build is None:
            print(
                f"error: {definition.display_name} has no place index. "
                "Run `pathable gazetteer build` first.",
                file=sys.stderr,
            )
            return EXIT_FAILED
        matches = await search_gazetteer(session, build.id, args.query, limit=args.limit)
    if not matches:
        print("No matches.")
    for match in matches:
        category = f"  [{match.category}]" if match.category else ""
        print(f"{match.latitude:.6f},{match.longitude:.6f}  {match.label}{category}")
    print(gazetteer_attribution(build))
    return EXIT_OK


async def _ingest_pbf(database: Database, args: argparse.Namespace) -> int:
    definition = region_definition(args.region)
    path = Path(args.file)
    if not path.is_file():
        print(f"error: {path} does not exist.", file=sys.stderr)
        return EXIT_MISCONFIGURED

    try:
        source_timestamp = _source_timestamp(args.source_timestamp)
    except ValueError:
        print("error: --source-timestamp must be ISO 8601.", file=sys.stderr)
        return EXIT_MISCONFIGURED

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


def _kitchener_offline(args: argparse.Namespace) -> int:
    if args.kitchener_command == "lineage-study":
        return _kitchener_lineage_study(args)
    if args.kitchener_command == "imagery-metadata":
        return _kitchener_imagery_metadata(args)
    if args.kitchener_command == "holdout":
        return _kitchener_holdout(args)
    if args.kitchener_command == "matcher-v2-holdout":
        return _kitchener_matcher_v2_holdout(args)
    if args.kitchener_command == "matcher-v2-review":
        return _kitchener_matcher_v2_review(args)
    if args.kitchener_command == "matcher-v2-development-labels":
        return _kitchener_matcher_v2_development(args)
    if args.kitchener_command == "matcher-v2-collect-labels":
        return _kitchener_matcher_v2_collect(args)
    if args.kitchener_command == "matcher-v2-benchmark":
        return _kitchener_matcher_v2_benchmark(args)
    if args.kitchener_command == "matcher-v2-validate-labels":
        return _kitchener_matcher_v2_validate(args)
    if args.kitchener_command == "holdout-review":
        return _kitchener_holdout_review(args)
    if args.kitchener_command == "benchmark":
        return _kitchener_benchmark(args)
    if args.kitchener_command == "lineage-history":
        return _kitchener_lineage_history(args)
    if args.kitchener_command == "reconcile-history":
        return _kitchener_reconcile_history(args)
    if args.kitchener_command == "reconcile":
        return _kitchener_reconcile(args)
    if args.kitchener_command == "snapshot":
        if args.chunk_size < 1:
            print("error: --chunk-size must be at least 1.", file=sys.stderr)
            return EXIT_MISCONFIGURED
        try:
            result = take_snapshot(
                ArcGISClient(RequestsTransport()),
                args.out,
                plan=SnapshotPlan(chunk_size=args.chunk_size),
                progress=print,
                measure=_run_measurements,
            )
        except (ArcGISError, SnapshotError) as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED
        manifest = result.manifest
        print(f"\nSnapshot {result.snapshot_id[:12]} retrieved {manifest['retrieved_at']}")
        for key, record in manifest["publications"].items():
            print(
                f"  {key:<24}{record['features']['records']:>8} features  "
                f"sha256 {record['features']['sha256'][:12]}  "
                f"edited {record['layer']['edit_info']['lastEditDate']}"
            )
        print(f"  licence terms as recorded: {'yes' if result.licence_matches else 'NO'}")
        for warning in result.warnings:
            print(f"  warning: {warning}")
        if args.json is not None:
            write_json(args.json, manifest)
            print(f"Wrote {args.json}")
        print(f"Wrote {result.folder}")
        # A licence that no longer says what the audit relies on stops the card.
        return EXIT_OK if result.licence_matches else EXIT_REVIEW_REQUIRED

    try:
        normalized = normalize_snapshot(
            args.snapshot, args.out, progress=print, measure=_run_measurements
        )
    except (SnapshotError, NormalizationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    output = normalized.manifest["output"]
    # ASCII only: a Windows console piped to a file is cp1252, and a character it
    # cannot encode would fail the command after the work was done.
    print(
        f"\nNormalized {output['rows']} records into {normalized.folder / output['file']} "
        f"({output['bytes']} bytes, sha256 {output['sha256'][:12]})"
    )
    if args.json is not None:
        write_json(args.json, normalized.manifest)
        print(f"Wrote {args.json}")
    return EXIT_OK


async def _kitchener_audit(database: Database, args: argparse.Namespace) -> int:
    definition = region_definition(args.region)
    try:
        dataset_id = uuid.UUID(args.dataset) if args.dataset else None
    except ValueError:
        print("error: --dataset must be a UUID.", file=sys.stderr)
        return EXIT_MISCONFIGURED
    async with database.session() as session:
        try:
            edges = await read_pathable_edges(
                session, region_slug=definition.slug, dataset_id=dataset_id
            )
        except PathAbleReadError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED
    try:
        result = run_audit(
            args.snapshot,
            args.normalized,
            definition,
            edges,
            measure=_run_measurements,
            progress=print,
        )
    except (SnapshotError, NormalizationError, AuditError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    write_kitchener_outputs(result, args.json, args.sample)

    profile = result.profile
    geography = profile["geography"]
    print(f"\nKitchener snapshot {profile['snapshot']['snapshot_id'][:12]}")
    print(f"  records                     {profile['overall']['records']:>8}")
    for name, count in profile["overall"]["physical_class"].items():
        print(f"    {name:<26}{count:>8}")
    print(f"  intersecting {definition.slug:<14}{geography['records_intersecting_study_area']:>8}")
    print(f"  sample                      {profile['sample']['records']:>8}")
    print(f"Wrote {args.json}")
    print(f"Wrote {args.sample}")
    return EXIT_OK


#: `pathable kitchener` commands that need no database.
_KITCHENER_OFFLINE = frozenset(
    {
        "snapshot",
        "normalize",
        "lineage-study",
        "lineage-history",
        "imagery-metadata",
        "holdout",
        "holdout-review",
        "benchmark",
        "matcher-v2-holdout",
        "matcher-v2-review",
        "matcher-v2-validate-labels",
        "matcher-v2-development-labels",
        "matcher-v2-collect-labels",
        "matcher-v2-benchmark",
        "reconcile-history",
        "reconcile",
    }
)


def _kitchener_holdout_review(args: argparse.Namespace) -> int:
    try:
        inputs = load_inputs(
            args.sample,
            args.normalized,
            args.extract,
            args.extract_manifest,
            expected_sample_sha256=args.sample_sha256,
            progress=print,
        )
        document = blind_document(run_study(inputs, progress=print))
    except (StudyError, NormalizationError, ExtractSourceError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    features = inputs.kitchener.features

    def describe(ids: Sequence[int]) -> list[str]:
        return [
            f"{i} {features[i].subcategory} ({features[i].physical_class}, "
            f"{features[i].geometry.length:.1f} m)"
            for i in sorted(ids)
            if i in features
        ]

    page = retitle(render_review(document, inputs.kitchener, inputs.osm, blind=True))
    for path, text in ((args.html, page), (args.digest, holdout_digest(document, describe))):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"Wrote {path}")
    return EXIT_OK


def _kitchener_benchmark(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    try:
        sets = load_label_sets(args.evidence_dir)
        inputs = load_conflation_inputs(
            args.normalized, args.extract, args.extract_manifest, progress=print
        )
        loaded = time.perf_counter()
        causes = (
            json.loads(args.failure_analysis.read_text("utf-8"))
            if args.failure_analysis is not None
            else None
        )
        report, timings, decisions = run_benchmark(
            inputs, sets, failure_causes=causes, progress=print
        )
        if args.artifact_dir is not None:
            pilot, pilot_timings = run_pilot(
                inputs, args.artifact_dir, check=decisions, progress=print
            )
            report["full_pilot_dry_run"] = pilot
            timings.update(pilot_timings)
    except (BenchmarkError, LabelError, ExtractSourceError, NormalizationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    report["inputs"] = inputs.identity
    report["attribution"] = KITCHENER_OSM_ATTRIBUTION
    timings["load_inputs_s"] = round(loaded - started, 2)
    timings["total_s"] = round(time.perf_counter() - started, 2)
    report["run"] = {**_run_measurements(), "timings": timings}
    if args.artifact_dir is not None:
        manifest = {
            "artifact_version": report["full_pilot_dry_run"]["artifact"]["version"],
            "purpose": "PA-GEO-05 research artifact: never read by routing",
            "inputs": inputs.identity,
            "policy": report["policy"],
            "decisions_sha256": report["full_pilot_dry_run"]["decisions_sha256"],
            "files": report["full_pilot_dry_run"]["artifact"]["files"],
            "attribution": KITCHENER_OSM_ATTRIBUTION,
            "run": report["run"],
        }
        write_json(args.artifact_dir / "manifest.json", manifest)
    report["content_sha256"] = content_sha256(report)
    write_json(args.json, report)
    holdout = report["holdout"]
    print(f"\nHeld-out records {holdout['records']}; decisions {holdout['decisions_sha256'][:16]}")
    for name, value in holdout["matcher"]["records_level"].items():
        print(f"  {name:<44}{value}")
    print(f"  pairs {holdout['matcher']['pairs']}")
    print(f"Wrote {args.json}")
    if args.errors_html is not None:
        page = render_failures(
            report, inputs.population.physical, inputs.osm, KITCHENER_OSM_ATTRIBUTION
        )
        args.errors_html.parent.mkdir(parents=True, exist_ok=True)
        args.errors_html.write_text(page, encoding="utf-8", newline="\n")
        print(f"Wrote {args.errors_html}")
    return EXIT_OK


def _kitchener_holdout(args: argparse.Namespace) -> int:
    try:
        inputs = load_conflation_inputs(
            args.normalized, args.extract, args.extract_manifest, progress=print
        )
        document = build_holdout(
            inputs,
            args.development_sample,
            expected_development_sha256=args.development_sample_sha256,
            progress=print,
        )
    except (HoldoutError, ExtractSourceError, NormalizationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    metadata = document["metadata"]
    print(
        f"\nHeld-out sample: {len(document['features'])} records from a pool of {metadata['pool']}"
    )
    for name, stratum in metadata["strata"].items():
        print(f"  {name:<28}{stratum['sampled']:>4} of {stratum['population']:>6}")
    print(f"Wrote {args.out} (sha256 {file_sha256(args.out)})")
    return EXIT_OK


def _kitchener_matcher_v2_holdout(args: argparse.Namespace) -> int:
    hashes = args.development_sample_sha256 or [None] * len(args.development_sample)
    if len(hashes) != len(args.development_sample):
        print("error: give one --development-sample-sha256 per sample, or none", file=sys.stderr)
        return EXIT_FAILED
    try:
        inputs = load_conflation_inputs(
            args.normalized, args.extract, args.extract_manifest, progress=print
        )
        document = build_matcher_v2_holdout(
            inputs, list(zip(args.development_sample, hashes, strict=True)), progress=print
        )
    except (HoldoutError, ExtractSourceError, NormalizationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    metadata = document["metadata"]
    print(
        f"\nHeld-out sample: {len(document['features'])} records from a pool of {metadata['pool']}"
    )
    for name, stratum in metadata["strata"].items():
        print(f"  {name:<30}{stratum['sampled']:>4} of {stratum['population']:>6}")
    print(f"Wrote {args.out} (sha256 {file_sha256(args.out)})")
    return EXIT_OK


def _kitchener_matcher_v2_review(args: argparse.Namespace) -> int:
    try:
        inputs = load_inputs(
            args.sample,
            args.normalized,
            args.extract,
            args.extract_manifest,
            expected_sample_sha256=args.sample_sha256,
            progress=print,
        )
        document = matcher_v2_blind(run_study(inputs, progress=print))
    except (StudyError, NormalizationError, ExtractSourceError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    features = inputs.kitchener.features

    def describe(ids: Sequence[int]) -> list[str]:
        return [
            f"{i} {features[i].subcategory} ({features[i].physical_class}, "
            f"{features[i].geometry.length:.1f} m)"
            for i in sorted(ids)
            if i in features
        ]

    page = matcher_v2_retitle(render_review(document, inputs.kitchener, inputs.osm, blind=True))
    text = matcher_v2_digest(document, describe, inputs.osm)
    for path, content in ((args.html, page), (args.digest, text)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"Wrote {path}")
    if args.packs_dir is not None:
        sample = json.loads(args.sample.read_text("utf-8"))
        ids = [int(f["properties"]["activetransportid"]) for f in sample["features"]]
        allowed = matcher_v2_elements(document)
        dealt = {
            **matcher_v2_packs(ids, MATCHER_V2_PRIMARY_PACKS, "primary"),
            **matcher_v2_packs(matcher_v2_repeat(sample), MATCHER_V2_REPEAT_PACKS, "repeat"),
        }
        for name, members in dealt.items():
            folder = args.packs_dir / name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "records.txt").write_text(
                matcher_v2_digest(document, describe, inputs.osm, members),
                encoding="utf-8",
                newline="\n",
            )
            write_json(
                folder / "elements.json",
                {
                    "pack": name,
                    "records": members,
                    "elements": {str(i): allowed[i] for i in members},
                },
            )
        write_json(
            args.packs_dir / "packs.json",
            {"sample_sha256": file_sha256(args.sample), "packs": dealt},
        )
        print(f"Wrote {len(dealt)} packs to {args.packs_dir}")
    return EXIT_OK


def _kitchener_matcher_v2_development(args: argparse.Namespace) -> int:
    try:
        inputs = load_conflation_inputs(
            args.normalized, args.extract, args.extract_manifest, progress=print
        )
        geo04 = json.loads(
            (args.evidence_dir / "kitchener-geo05-development-labels.json").read_text("utf-8")
        )
        geo05 = json.loads(
            (args.evidence_dir / "kitchener-geo05-holdout-labels.json").read_text("utf-8")
        )
        document = matcher_v2_development_labels(
            geo04, geo05, **matcher_v2_label_facts(inputs, [geo04, geo05])
        )
    except (LabelError, ValueError, ExtractSourceError, NormalizationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    document["inputs"] = {
        name: {"file": path.name, "sha256": file_sha256(path)}
        for name, path in (
            (
                "geo04_development_labels",
                args.evidence_dir / "kitchener-geo05-development-labels.json",
            ),
            ("geo05_holdout_labels", args.evidence_dir / "kitchener-geo05-holdout-labels.json"),
        )
    }
    document["definitions"] = {"version": MATCHER_V2_LABELS_VERSION, **MATCHER_V2_DEFINITIONS}
    write_json(args.out, document)
    counts = collections.Counter(r["correspondence"] for r in document["records"])
    print(f"development labels: {len(document['records'])} records {dict(sorted(counts.items()))}")
    print(f"conversions: {len(document['conversions'])}")
    print(f"Wrote {args.out}")
    return EXIT_OK


def _kitchener_matcher_v2_collect(args: argparse.Namespace) -> int:
    folders = sorted(
        f
        for f in args.packs_dir.iterdir()
        if f.is_dir() and f.name.startswith(f"{args.labelling_pass}-")
    )
    sample = json.loads(args.sample.read_text("utf-8"))
    material = {
        "holdout": {
            "file": args.sample.name,
            "sha256": file_sha256(args.sample),
            "sample_version": sample["metadata"]["sample_version"],
            "records": len(sample["features"]),
        },
        "labelling_guide": {"file": args.guide.name, "sha256": file_sha256(args.guide)},
        "blind_material": {
            "review_page": args.review_page.name,
            "review_page_sha256": file_sha256(args.review_page),
            "digest_sha256": file_sha256(args.digest),
            "contents": (
                "For each record: its geometry and attributes, every OSM candidate with its tags, "
                "measures and connections, and tagged nodes near it, as text and a map. No "
                "matcher decision, no baseline output, no other labeller's labels, no stratum."
            ),
        },
    }
    try:
        packs = {
            folder.name: json.loads((folder / "labels.json").read_text("utf-8"))
            for folder in folders
        }
        document = collect_matcher_v2_labels(
            packs, labelling_pass=args.labelling_pass, sample=sample, material=material
        )
    except (LabelError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    write_json(args.out, document)
    print(f"{args.labelling_pass}: {len(document['records'])} records from {len(packs)} packs")
    print(f"Wrote {args.out}")
    return EXIT_OK


def _kitchener_matcher_v2_benchmark(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    try:
        sets = load_matcher_v2_label_sets(args.evidence_dir)
        inputs = load_conflation_inputs(
            args.normalized, args.extract, args.extract_manifest, progress=print
        )
        loaded = time.perf_counter()
        causes = (
            json.loads(args.failure_analysis.read_text("utf-8"))
            if args.failure_analysis is not None
            else None
        )
        report, timings, decisions = run_matcher_v2_benchmark(
            inputs, sets, failure_causes=causes, progress=print
        )
        if args.pilot:
            pilot, pilot_timings = run_matcher_v2_pilot(inputs, check=decisions, progress=print)
            report["full_pilot_dry_run"] = pilot
            timings.update(pilot_timings)
    except (BenchmarkV2Error, LabelError, ExtractSourceError, NormalizationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    report["inputs"] = inputs.identity
    report["attribution"] = KITCHENER_OSM_ATTRIBUTION
    timings["load_inputs_s"] = round(loaded - started, 2)
    timings["total_s"] = round(time.perf_counter() - started, 2)
    report["run"] = {**_run_measurements(), "timings": timings}
    report["content_sha256"] = content_sha256(report)
    write_json(args.json, report)
    holdout = report["holdout"]
    print(f"\nHeld-out records {holdout['records']}; decisions {holdout['decisions_sha256'][:16]}")
    print(f"Wrote {args.json}")
    if args.errors_html is not None:
        page = render_matcher_v2_errors(
            report, inputs.population.physical, inputs.osm, KITCHENER_OSM_ATTRIBUTION
        )
        args.errors_html.parent.mkdir(parents=True, exist_ok=True)
        args.errors_html.write_text(page, encoding="utf-8", newline="\n")
        print(f"Wrote {args.errors_html}")
    return EXIT_OK


def _kitchener_matcher_v2_validate(args: argparse.Namespace) -> int:
    pack = json.loads(args.pack_elements.read_text("utf-8"))
    try:
        document = json.loads(args.labels.read_text("utf-8"))
        labels = parse_matcher_v2_labels(document)
    except (LabelError, ValueError, KeyError) as error:
        print(f"invalid: {error}", file=sys.stderr)
        return EXIT_FAILED
    problems = []
    order = [int(i) for i in pack["records"]]
    listed = [int(item["activetransportid"]) for item in document.get("records", [])]
    if listed != order:
        problems.append("the records are not exactly the pack's, in the order of records.txt")
    for record_id, label in labels.items():
        allowed = set(pack["elements"].get(str(record_id), []))
        extra = sorted(label.osm - allowed)
        if extra:
            problems.append(f"record {record_id} cites elements not in its pack: {extra}")
    for problem in problems:
        print(f"invalid: {problem}", file=sys.stderr)
    if problems:
        return EXIT_FAILED
    print(f"valid: {len(labels)} records")
    return EXIT_OK


def _kitchener_imagery_metadata(args: argparse.Namespace) -> int:
    try:
        document = survey_imagery(RequestsTransport(timeout_seconds=120.0), progress=print)
    except ImageryError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    document["run"] = _run_measurements()
    write_json(args.json, document)
    municipal = document["municipal_imagery"]
    print(
        f"\nMunicipal photography first in {municipal['first_release_showing_it']} "
        f"(after {municipal['last_release_before_it']}); earliest source date "
        f"{municipal['earliest_source_date']}"
    )
    print(f"Wrote {args.json}")
    # The lineage rules carry this date as a constant; a different measurement
    # means the rules no longer describe what Esri served.
    if municipal["earliest_source_date"] != ESRI_MUNICIPAL_SINCE:
        print(
            f"warning: the lineage rules use {ESRI_MUNICIPAL_SINCE}; review them.",
            file=sys.stderr,
        )
        return EXIT_REVIEW_REQUIRED
    return EXIT_OK


def _kitchener_lineage_study(args: argparse.Namespace) -> int:
    try:
        inputs = load_inputs(
            args.sample,
            args.normalized,
            args.extract,
            args.extract_manifest,
            expected_sample_sha256=args.sample_sha256,
            progress=print,
        )
        history = load_history(args.history) if args.history else None

        def read(path: Path | None) -> Any:
            return json.loads(path.read_text("utf-8")) if path else None

        document = run_study(
            inputs,
            history=history,
            labels=read(args.labels),
            repeat=read(args.repeat_labels),
            first_pass=read(args.first_pass_labels),
            repeat_refined=read(args.repeat_refined_labels),
            progress=print,
        )
    except (StudyError, NormalizationError, ExtractSourceError, LabelError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    document["run"] = _run_measurements()
    evidence = slim(document)
    evidence["content_sha256"] = content_sha256(evidence)
    write_json(args.json, evidence)
    if args.full_json is not None:
        write_json(args.full_json, document)
    print(f"\nLineage study over {len(document['records'])} records")
    summary = document.get("summary")
    if summary is not None:
        for name, count in summary["all"]["correspondence"].items():
            print(f"  {name:<28}{count:>4}")
    print(f"Wrote {args.json}")
    for path, blind in ((args.html, False), (args.blind_html, True)):
        if path is None:
            continue
        subset = document["method"]["repeat_subset"]["records"] if blind else None
        page = render_review(document, inputs.kitchener, inputs.osm, blind=blind, only=subset)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page, encoding="utf-8", newline="\n")
        print(f"Wrote {path}")
    return EXIT_OK


def _kitchener_lineage_history(args: argparse.Namespace) -> int:
    study = json.loads(args.study.read_text("utf-8"))
    return _write_osm_history(history_elements(study), args)


def _write_osm_history(elements: Sequence[str], args: argparse.Namespace) -> int:
    """The edit history of these OSM elements and their changesets, as one local file."""
    manifest = json.loads(args.extract_manifest.read_text("utf-8"))
    transport = RequestsTransport(timeout_seconds=300.0)
    try:
        extract = load_study_extract(args.extract, expected_sha256=manifest["output"]["sha256"])
        metadata = ohsome_metadata(transport, base_url=args.ohsome_url)
        west, south, east, north = manifest["dataset"]["source_bbox"]
        # ohsome keeps elements that intersect the box; a margin keeps candidates
        # that lie just outside it.
        margin = 0.01
        requests = ohsome_requests(
            elements,
            bbox=(west - margin, south - margin, east + margin, north + margin),
            time_range=(metadata["temporal_extent"]["from"], metadata["temporal_extent"]["to"]),
        )
        print(f"{len(elements)} elements in {len(requests)} ohsome requests")
        fetched = fetch_history(
            requests,
            transport=transport,
            cache_dir=args.cache,
            base_url=args.ohsome_url,
            progress=print,
        )
        wanted = sorted({c.changeset for c in fetched.contributions})
        index = args.dump_index or args.dump.with_name(args.dump.name + ".streams.json")
        dump = ChangesetDump.open(args.dump, index, workers=16, progress=print)
        changesets = dump.lookup(wanted)
        identity = {
            "role": (
                "metadata about how the frozen geometry came to be: history ends where the "
                "ohsome extent ends, and none of it is the geometry compared"
            ),
            "frozen_extract_sha256": manifest["output"]["sha256"],
            "ohsome": {**metadata, "requests": fetched.requests},
            "changeset_dump": dump_identity(args.dump),
            "elements_requested": len(elements),
            "elements_with_history": len({c.element for c in fetched.contributions}),
            "contributions": len(fetched.contributions),
            "changesets_requested": len(wanted),
            "changesets_found": len(changesets),
            "privacy": (
                "changeset user names and ids are dropped while parsing; comments stay in this "
                "local file and reach committed evidence only as matched source phrases"
            ),
        }
    except (HistoryError, ExtractSourceError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    document = history_document(fetched.contributions, changesets, extract, identity)
    write_json(args.out, document)
    reaching = sum(1 for item in document["elements"].values() if item["reaches_frozen_state"])
    print(
        f"\n{identity['elements_with_history']} elements with history, {reaching} reaching the "
        f"frozen state; {len(changesets)} of {len(wanted)} changesets found"
    )
    print(f"Wrote {args.out}")
    return EXIT_OK


#: The committed snapshot evidence the reconciliation reads its source registry from.
KITCHENER_SNAPSHOT_EVIDENCE = "kitchener-active-transport-snapshot.json"


def _reconciliation_inputs(args: argparse.Namespace) -> RunInputs:
    return load_run_inputs(
        args.normalized,
        args.extract,
        args.extract_manifest,
        args.geo05_artifact,
        args.evidence_dir / KITCHENER_SNAPSHOT_EVIDENCE,
        progress=print,
    )


def _kitchener_reconcile_history(args: argparse.Namespace) -> int:
    try:
        reconciled = run_reconciliation(_reconciliation_inputs(args), None, progress=print)
    except (ReconciliationError, ExtractSourceError, NormalizationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    return _write_osm_history(reconciled.history_elements(), args)


def _history_identity(path: Path, identity: Mapping[str, Any]) -> dict[str, Any]:
    """What the lineage was read from, without the per-request list."""
    ohsome = identity.get("ohsome", {})
    requests = ohsome.get("requests", [])
    return {
        "file_sha256": file_sha256(path),
        "frozen_extract_sha256": identity.get("frozen_extract_sha256"),
        "ohsome": {
            "api": ohsome.get("api"),
            "api_version": ohsome.get("api_version"),
            "temporal_extent": ohsome.get("temporal_extent"),
            "requests": len(requests),
            "response_bytes": sum(int(r.get("response_bytes", 0)) for r in requests),
        },
        "changeset_dump": identity.get("changeset_dump"),
        "elements_requested": identity.get("elements_requested"),
        "elements_with_history": identity.get("elements_with_history"),
        "changesets_found": identity.get("changesets_found"),
        "rules": "PA-GEO-04's lineage rules, unchanged",
    }


def _kitchener_reconcile(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    timings: dict[str, float] = {}
    try:
        run_inputs = _reconciliation_inputs(args)
        timings["load_inputs_s"] = round(time.perf_counter() - started, 2)
        history = None
        if args.history is not None:
            mark = time.perf_counter()
            history = load_history(args.history)
            timings["load_history_s"] = round(time.perf_counter() - mark, 2)
            frozen = run_inputs.identity["osm_frozen"]["extract_sha256"]
            if history.identity.get("frozen_extract_sha256") != frozen:
                print("error: the history was read for a different OSM extract.", file=sys.stderr)
                return EXIT_FAILED
        mark = time.perf_counter()
        reconciled = run_reconciliation(run_inputs, history, progress=print)
        timings["reconcile_s"] = round(time.perf_counter() - mark, 2)
        mark = time.perf_counter()
        files = write_reconciliation_artifact(args.artifact_dir, run_inputs, reconciled)
        timings["artifact_write_s"] = round(time.perf_counter() - mark, 2)
    except (ReconciliationError, ExtractSourceError, NormalizationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    identity = _history_identity(args.history, history.identity) if history is not None else None
    document = reconciliation_evidence(run_inputs, reconciled, files, identity)
    timings["total_s"] = round(time.perf_counter() - started, 2)
    measurements: dict[str, Any] = {**_run_measurements(), "timings": timings}
    if args.compare_to is not None:
        measurements["determinism"] = compare_runs(files, args.compare_to)
    write_json(
        args.artifact_dir / "manifest.json",
        reconciliation_manifest(run_inputs, files, identity, measurements),
    )
    document["content_sha256"] = content_sha256(document)
    document["run"] = measurements
    write_json(args.json, document)
    print(
        f"\nReconciliations {len(reconciled.reconciliations)}; "
        f"assertions {len(reconciled.assertions)}"
    )
    for topic, block in document["outcomes"].items():
        print(f"  {topic:<10}{block['semantic_relationship']}")
    if "determinism" in measurements:
        print(f"  byte-identical to {args.compare_to}: {measurements['determinism']['identical']}")
    print(f"Wrote {args.artifact_dir} and {args.json}")
    return EXIT_OK


#: PA-GEO-06's committed evidence, which the shadow study binds its artifact to.
GEO06_EVIDENCE = "kitchener-geo06-reconciliation.json"


async def _kitchener_shadow_routing(database: Database, args: argparse.Namespace) -> int:
    started = time.perf_counter()
    try:
        evidence = load_surface_evidence(args.geo06_artifact, args.evidence_dir / GEO06_EVIDENCE)
        manifest = json.loads(args.extract_manifest.read_text("utf-8"))
        extract = load_study_extract(args.extract, expected_sha256=manifest["output"]["sha256"])
    except (ShadowError, ExtractSourceError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    async with database.session() as session:
        await read_only(session)
        before = await active_dataset(session, args.region)
        graph, sources = await load_active(session, before, args.region)
        await session.rollback()
    if str(before.dataset_id) != manifest["dataset"]["dataset_id"]:
        print("error: the OSM study extract was not cut for the active dataset.", file=sys.stderr)
        return EXIT_FAILED
    loaded = time.perf_counter()
    print(f"graph: {graph.segment_count} segments, loaded read-only in {loaded - started:.1f} s")
    output = run_shadow_study(
        graph,
        sources,
        evidence,
        extract,
        bounds=tuple(manifest["dataset"]["source_bbox"]),
        broad_size=args.broad_size,
        seed=args.seed,
        per_stratum=args.per_stratum,
        progress=print,
    )
    queue = validation_queue(evidence, output, graph)
    async with database.session() as session:
        await read_only(session)
        after = await active_dataset(session, args.region)
        await session.rollback()
    document = shadow_evidence(
        evidence=evidence,
        output=output,
        dataset_before=before,
        dataset_after=after,
        extract_sha256=manifest["output"]["sha256"],
        seed=args.seed,
        queue=queue,
        attribution=KITCHENER_OSM_ATTRIBUTION,
    )
    document["run"]["timings_s"]["load_graph_s"] = round(loaded - started, 2)
    document["run"]["timings_s"]["total_s"] = round(time.perf_counter() - started, 2)
    document["run"].update(_run_measurements())
    if args.compare_to is not None:
        earlier = json.loads(args.compare_to.read_text("utf-8"))
        document["run"]["determinism"] = compare_shadow_runs(
            earlier, document, args.compare_to.name
        )
    document["content_sha256"] = content_sha256(document)
    write_json(args.json, document)
    if args.html is not None:
        page = render_changes(
            output.results,
            output.pairs,
            {p.key: p for p in study_profiles()},
            output.plan.fills,
            KITCHENER_OSM_ATTRIBUTION,
        )
        args.html.parent.mkdir(parents=True, exist_ok=True)
        args.html.write_text(page, encoding="utf-8", newline="\n")
    isolation = document["production_isolation"]
    print(f"\nShadow study: {len(output.results)} journey-profile pairs")
    for corpus, profiles in document["results"].items():
        for key, block in profiles.items():
            print(f"  {corpus:<9}{key:<40}{block['categories']}")
    print(f"  database unchanged: {isolation['database']['unchanged']}")
    print(f"  baseline graph unchanged: {isolation['baseline_graph_unchanged']}")
    if "determinism" in document["run"]:
        print(f"  identical to {args.compare_to}: {document['run']['determinism']}")
    print(f"Wrote {args.json}")
    return EXIT_OK


async def _kitchener_curb_ramp_shadow_routing(database: Database, args: argparse.Namespace) -> int:
    started = time.perf_counter()
    try:
        reconciled = reconcile_curb_ramps(
            normalized=args.normalized,
            extract_path=args.extract,
            extract_manifest=args.extract_manifest,
            evidence_dir=args.evidence_dir,
            artifact_dir=args.artifact_dir,
            attribution=KITCHENER_OSM_ATTRIBUTION,
            progress=print,
        )
    except (CurbRampError, ExtractSourceError, NormalizationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    manifest = json.loads(args.extract_manifest.read_text("utf-8"))
    reconciled_at = time.perf_counter()
    async with database.session() as session:
        await read_only(session)
        before = await active_dataset(session, args.region)
        graph, sources = await load_active(session, before, args.region)
        await session.rollback()
    if str(before.dataset_id) != manifest["dataset"]["dataset_id"]:
        print("error: the OSM study extract was not cut for the active dataset.", file=sys.stderr)
        return EXIT_FAILED
    loaded = time.perf_counter()
    print(
        f"graph: {graph.segment_count} segments, loaded read-only in {loaded - reconciled_at:.1f} s"
    )
    output = run_curb_ramp_study(
        graph,
        sources,
        reconciled,
        bounds=tuple(manifest["dataset"]["source_bbox"]),
        broad_size=args.broad_size,
        seed=args.seed,
        per_stratum=args.per_stratum,
        progress=print,
    )
    async with database.session() as session:
        await read_only(session)
        after = await active_dataset(session, args.region)
        await session.rollback()
    document = curb_ramp_evidence(
        reconciled=reconciled,
        output=output,
        dataset_before=before,
        dataset_after=after,
        extract_sha256=manifest["output"]["sha256"],
        seed=args.seed,
        attribution=KITCHENER_OSM_ATTRIBUTION,
    )
    document["run"]["timings_s"]["load_graph_s"] = round(loaded - reconciled_at, 2)
    document["run"]["timings_s"]["total_s"] = round(time.perf_counter() - started, 2)
    document["run"].update(_run_measurements())
    if args.compare_to is not None:
        earlier = json.loads(args.compare_to.read_text("utf-8"))
        document["run"]["determinism"] = compare_shadow_runs(
            earlier, document, args.compare_to.name
        )
    document["content_sha256"] = content_sha256(document)
    write_json(args.json, document)
    if args.html is not None:
        page = render_curb_ramp_page(
            output.results,
            output.pairs,
            {p.key: p for p in output.profiles},
            output.plan.substitutions,
            rejected_examples(reconciled, output.plan, graph),
            KITCHENER_OSM_ATTRIBUTION,
        )
        args.html.parent.mkdir(parents=True, exist_ok=True)
        args.html.write_text(page, encoding="utf-8", newline="\n")
    isolation = document["production_isolation"]
    funnel = document["input_funnel"]
    print(f"\nCurb-ramp shadow study: {len(output.results)} journey-profile pairs")
    print(
        f"  funnel: {funnel['candidates_for_routing_mapping']} candidates -> "
        f"{funnel['final_shadow_eligible_assertions']} eligible on "
        f"{funnel['final_affected_crossing_segments']} crossing segments"
    )
    for corpus, profiles in document["results"].items():
        for key, block in profiles.items():
            print(f"  {corpus:<9}{key:<20}{block['categories']}")
    print(f"  defects: {document['defects']}")
    print(f"  database unchanged: {isolation['database']['unchanged']}")
    print(f"  baseline graph unchanged: {isolation['baseline_graph_unchanged']}")
    agreement = document["algorithm_agreement"]
    print(f"  dijkstra/a* agree: {agreement['agree']} of {agreement['checked']}")
    if "determinism" in document["run"]:
        print(f"  identical to {args.compare_to}: {document['run']['determinism']}")
    print(f"Wrote {args.json}")
    return EXIT_OK


async def _kitchener_lineage_extract(database: Database, args: argparse.Namespace) -> int:
    try:
        dataset_id = uuid.UUID(args.dataset) if args.dataset else None
    except ValueError:
        print("error: --dataset must be a UUID.", file=sys.stderr)
        return EXIT_MISCONFIGURED
    async with database.session() as session:
        try:
            source = await read_dataset_source(
                session, region_slug=args.region, dataset_id=dataset_id
            )
        except PathAbleReadError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_FAILED
    if source.file_sha256 is None or source.bbox is None:
        print(
            "error: the dataset records no source-extract SHA-256 or bounding box; "
            "its OSM side cannot be frozen from a file.",
            file=sys.stderr,
        )
        return EXIT_FAILED
    started = time.perf_counter()
    try:
        extract, facts = read_study_extract(
            args.pbf, expected_sha256=source.file_sha256, bounds=source.bbox, progress=print
        )
    except ExtractSourceError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    sha256 = write_study_extract(extract, args.out)
    manifest: dict[str, Any] = {
        "kitchener_osm_extract_version": EXTRACT_FORMAT_VERSION,
        "dataset": source.as_dict(),
        "selection": (
            "every way with a highway tag that has a node inside the dataset's recorded "
            "bounding box, kept whole however far it runs beyond it; the nodes they use; and "
            "tagged nodes inside the box carrying kerb, crossing, barrier or highway facts"
        ),
        "source": {k: facts[k] for k in ("source_file", "source_sha256", "bounds")},
        "counts": {
            k: facts[k] for k in ("fact_nodes", "ways", "ways_with_unresolved_nodes", "nodes")
        },
        "output": {"file": args.out.name, "bytes": args.out.stat().st_size, "sha256": sha256},
        "run": {"seconds": round(time.perf_counter() - started, 2), **_run_measurements()},
    }
    manifest["content_sha256"] = content_sha256(manifest)
    write_json(args.json, manifest)
    print(f"\nFrozen OSM study extract: {facts['ways']} ways, {facts['nodes']} nodes")
    print(f"  source {source.file_name} sha256 {source.file_sha256[:12]} (verified)")
    print(f"  wrote {args.out} sha256 {sha256[:12]}")
    print(f"Wrote {args.json}")
    return EXIT_OK


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
    journeys = run.comparison_count // max(len(run.profiles), 1)
    print(
        f"  corpus     {run.corpus_key}: {journeys} journeys x {len(run.profiles)} profiles "
        f"= {run.comparison_count} comparisons, routing policy v{run.routing_policy_version}"
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
