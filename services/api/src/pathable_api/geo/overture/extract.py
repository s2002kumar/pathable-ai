"""Bounded extraction of one Overture transportation release for one region.

The global transportation theme is roughly 97 GB of segments and connectors,
and the OSM bridge files another 23 GB. A pilot region needs a few megabytes of
it. Reading that few megabytes — and being able to prove that is all that was
read — is the job of this module.

How the bound is enforced, cheapest first:

1. **Files.** The release catalog gives every Parquet file a bounding box. A
   file whose box misses the region is never opened.
2. **Row groups.** Overture writes features in spatial order and stores a
   ``bbox`` struct per feature, so Parquet statistics let DuckDB skip row groups
   that cannot contain the region.
3. **Rows.** A feature is kept when its ``bbox`` intersects the region's
   bounds. That is a box test, not a geometry clip: a long segment that crosses
   the boundary is kept whole, with every property it carries.

Two artifacts cannot be bounded that way and are handled honestly instead. The
changelog has no catalog but is spatially ordered, so every footer is read and
row-group statistics do the rest. The bridge files are neither catalogued nor
spatially ordered — a GERS id is a random UUID — so a regional read would be a
full 23 GB scan. Only a small, deterministic sample of bridge files is read,
to check that the bridge agrees with the segments' own ``sources`` column,
which is where the linkage actually comes from.

Every query is a constant string with bound parameters, and the manifest
records both, so a run can be repeated exactly. Nothing here touches the
PathAble database.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import duckdb

from pathable_api.geo.overture.catalog import (
    STAC_ROOT,
    CatalogItem,
    JsonFetcher,
    ReleaseIdentity,
    collection_url,
    list_collection_items,
    resolve_release,
    select_items,
)
from pathable_api.geo.overture.contract import (
    IncompatibleSchemaError,
    SchemaCheck,
    check_schema,
    observe,
)
from pathable_api.geo.overture.evidence import content_sha256, file_sha256, write_json

#: Where Overture's public bucket lives. The changelog and bridge files are
#: listed from here; release data is addressed through the catalog instead.
OVERTURE_BUCKET = "s3://overturemaps-us-west-2"
OVERTURE_BUCKET_REGION = "us-west-2"
_OVERTURE_HTTPS = f"https://overturemaps-us-west-2.s3.{OVERTURE_BUCKET_REGION}.amazonaws.com/"

EXTRACT_MANIFEST = "extract-manifest.json"
EXTRACT_FORMAT_VERSION = 1

SEGMENT_FILE = "segment.parquet"
CONNECTOR_FILE = "connector.parquet"
CHANGELOG_FILE = "changelog.parquet"
BRIDGE_SAMPLE_FILE = "bridge-sample.parquet"

#: How local files appear in a manifest, so it never carries a machine's paths.
_LOCAL = "<extract>/"

# The four `?` after each WHERE are, in order: max_lon, min_lon, max_lat, min_lat —
# a feature's box intersects the region's box. See `_bbox_parameters`.
_REGION_QUERY = (
    "SELECT * FROM read_parquet(?, hive_partitioning = false) "
    "WHERE bbox.xmin <= ? AND bbox.xmax >= ? AND bbox.ymin <= ? AND bbox.ymax >= ? "
    "ORDER BY id"
)
_CHANGELOG_QUERY = (
    "SELECT id, type, change_type, columns_changed, bbox "
    "FROM read_parquet(?, hive_partitioning = true) "
    "WHERE bbox.xmin <= ? AND bbox.xmax >= ? AND bbox.ymin <= ? AND bbox.ymax >= ? "
    "ORDER BY type, change_type, id"
)
_BRIDGE_QUERY = (
    "SELECT id, dataset, record_id, update_time, resource, version, between, dataset_between "
    "FROM read_parquet(?, hive_partitioning = false) "
    "WHERE id IN (SELECT id FROM read_parquet(?)) ORDER BY id, record_id"
)
_SCHEMA_QUERY = "SELECT * FROM read_parquet(?, hive_partitioning = false) LIMIT 0"
_SCHEMA_QUERY_HIVE = "SELECT * FROM read_parquet(?, hive_partitioning = true) LIMIT 0"
_COUNT_QUERY = "SELECT count(*) FROM read_parquet(?)"
_CANDIDATE_ROWS_QUERY = """
WITH groups AS (
    SELECT file_name, row_group_id, any_value(row_group_num_rows) AS n,
        min(TRY_CAST(stats_min_value AS DOUBLE)) FILTER (WHERE path_in_schema = 'bbox, xmin') AS xmin,
        max(TRY_CAST(stats_max_value AS DOUBLE)) FILTER (WHERE path_in_schema = 'bbox, xmax') AS xmax,
        min(TRY_CAST(stats_min_value AS DOUBLE)) FILTER (WHERE path_in_schema = 'bbox, ymin') AS ymin,
        max(TRY_CAST(stats_max_value AS DOUBLE)) FILTER (WHERE path_in_schema = 'bbox, ymax') AS ymax
    FROM parquet_metadata(?) GROUP BY ALL
)
SELECT sum(n) FILTER (WHERE xmin <= ? AND xmax >= ? AND ymin <= ? AND ymax >= ?),
    count(*) FILTER (WHERE xmin IS NULL OR xmax IS NULL OR ymin IS NULL OR ymax IS NULL)
FROM groups
"""
_CONSISTENCY_QUERY = """
SELECT
    (SELECT count(*) FROM read_parquet(?) c WHERE c.id NOT IN
        (SELECT id FROM read_parquet(?) WHERE type = ? AND change_type <> 'removed')),
    (SELECT count(*) FROM read_parquet(?) l WHERE l.type = ? AND l.change_type <> 'removed'
        AND l.id NOT IN (SELECT id FROM read_parquet(?)))
"""

Bounds = tuple[float, float, float, float]
Progress = Callable[[str], None]


class ExtractionError(RuntimeError):
    """The extraction could not produce a trustworthy result."""


@dataclass(frozen=True, slots=True)
class ExtractionPlan:
    region_slug: str
    bounds: Bounds
    #: Where the bounds came from, so a reader can find the definition.
    bounds_source: str
    release: str
    bridge_sample_files: int = 2
    include_changelog: bool = True


@dataclass(frozen=True, slots=True)
class OvertureLocation:
    """Where to read from. Tests point both at local directories."""

    stac_root: str = STAC_ROOT
    bucket: str = OVERTURE_BUCKET

    @property
    def remote(self) -> bool:
        return _is_remote(self.stac_root) or _is_remote(self.bucket)


@dataclass(frozen=True, slots=True)
class HttpStats:
    get_requests: int
    head_requests: int
    #: Sum of GET response ``Content-Length`` — the bytes actually transferred.
    bytes_received: int

    def as_dict(self) -> dict[str, int]:
        return {
            "get_requests": self.get_requests,
            "head_requests": self.head_requests,
            "bytes_received": self.bytes_received,
        }


@dataclass(frozen=True, slots=True)
class SourceFile:
    """One upstream file that was actually read, and what identified it at the time."""

    location: str
    catalog_item: str | None = None
    catalog_size_bytes: int | None = None
    size_bytes: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    #: S3's lifecycle header — when this release file is scheduled to disappear.
    expiration: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "location": self.location,
            "catalog_item": self.catalog_item,
            "catalog_size_bytes": self.catalog_size_bytes,
            "size_bytes": self.size_bytes,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "expiration": self.expiration,
        }


@dataclass(frozen=True, slots=True)
class ArtifactExtraction:
    kind: str
    selection: str
    files_available: int
    #: Files whose footer or data was actually read over the network.
    files_opened: int
    sources: tuple[SourceFile, ...]
    schema: SchemaCheck
    query: str
    parameters: tuple[Any, ...]
    output_file: str
    output_bytes: int
    output_sha256: str
    rows: int
    #: Rows in row groups whose bbox statistics could not rule the region out —
    #: the most the query could have had to decode. Read from Parquet footers.
    rows_in_candidate_row_groups: int | None
    seconds: float
    http: HttpStats | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "selection": self.selection,
            "files_available": self.files_available,
            "files_opened": self.files_opened,
            "sources": [source.as_dict() for source in self.sources],
            "schema": self.schema.as_dict(),
            "query": self.query,
            "parameters": list(self.parameters),
            "output": {
                "file": self.output_file,
                "bytes": self.output_bytes,
                "sha256": self.output_sha256,
                "rows": self.rows,
            },
            "rows_in_candidate_row_groups": self.rows_in_candidate_row_groups,
            "measurement": {
                "seconds": round(self.seconds, 2),
                "http": self.http.as_dict() if self.http is not None else None,
            },
        }


@dataclass(slots=True)
class ExtractionResult:
    plan: ExtractionPlan
    release: ReleaseIdentity
    location: OvertureLocation
    out_dir: Path
    artifacts: dict[str, ArtifactExtraction] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    tools: dict[str, str | None] = field(default_factory=dict)
    acquired_at: str = ""
    run: dict[str, Any] = field(default_factory=dict)

    def manifest(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "overture_extract_version": EXTRACT_FORMAT_VERSION,
            "region": {
                "slug": self.plan.region_slug,
                "bounds": list(self.plan.bounds),
                "bounds_source": self.plan.bounds_source,
                "selection_rule": "feature bbox intersects region bounds (a box test, not a clip)",
            },
            "release": self.release.as_dict(),
            "configuration": {
                "stac_root": self.location.stac_root,
                "bucket": self.location.bucket,
                "bridge_sample_files": self.plan.bridge_sample_files,
                "include_changelog": self.plan.include_changelog,
            },
            "tools": dict(self.tools),
            "artifacts": {name: art.as_dict() for name, art in sorted(self.artifacts.items())},
            "warnings": sorted(self.warnings),
            "acquired_at": self.acquired_at,
            "run": self.run,
        }
        document["content_sha256"] = content_sha256(document)
        return document


def run_extraction(
    plan: ExtractionPlan,
    out_root: Path,
    *,
    fetch_json: JsonFetcher,
    location: OvertureLocation | None = None,
    progress: Progress | None = None,
    measure_memory: Callable[[], dict[str, Any]] | None = None,
) -> ExtractionResult:
    """Resolve the release, read the region's features, and write a manifest.

    Output goes to ``out_root/<observed release>/<region>``, named after the
    release actually resolved — never after "latest".
    """
    where = location or OvertureLocation()
    say = progress or (lambda _message: None)
    if plan.bridge_sample_files < 0:
        msg = "bridge_sample_files cannot be negative."
        raise ExtractionError(msg)

    started = time.perf_counter()
    release = resolve_release(plan.release, fetch_json, root_url=where.stac_root)
    say(f"Release {release.observed} (schema {release.schema_version}).")
    out_dir = out_root / release.observed / plan.region_slug
    result = ExtractionResult(
        plan=plan,
        release=release,
        location=where,
        out_dir=out_dir,
        warnings=list(release.warnings),
        acquired_at=dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        _extract_all(plan, where, release, out_dir, result, fetch_json, say)
    except duckdb.Error as error:
        # Network failures surface here as DuckDB IO/HTTP errors. Stop and say so;
        # there is no cached copy to fall back on, by design.
        msg = f"Reading Overture failed: {error}"
        raise ExtractionError(msg) from error

    result.run = {
        "seconds": round(time.perf_counter() - started, 2),
        **(measure_memory() if measure_memory is not None else {}),
    }
    write_json(out_dir / EXTRACT_MANIFEST, result.manifest())
    return result


def _extract_all(
    plan: ExtractionPlan,
    where: OvertureLocation,
    release: ReleaseIdentity,
    out_dir: Path,
    result: ExtractionResult,
    fetch_json: JsonFetcher,
    say: Progress,
) -> None:
    connection = _connect(remote=where.remote)
    try:
        result.tools = _tools(connection)
        for feature_type, output in (("segment", SEGMENT_FILE), ("connector", CONNECTOR_FILE)):
            items = list_collection_items(
                collection_url(release, "transportation", feature_type), fetch_json
            )
            chosen = select_items(items, plan.bounds)
            say(f"{feature_type}: {len(chosen)} of {len(items)} files intersect the region.")
            result.artifacts[feature_type] = _extract_catalogued(
                connection, feature_type, items, chosen, plan.bounds, out_dir / output
            )

        if plan.include_changelog:
            say("changelog: reading footers and matching row groups...")
            result.artifacts["changelog"] = _extract_changelog(
                connection, where.bucket, release.observed, plan.bounds, out_dir / CHANGELOG_FILE
            )
            result.warnings.extend(_changelog_consistency(connection, out_dir))

        if plan.bridge_sample_files > 0:
            say(f"bridge: sampling {plan.bridge_sample_files} file(s)...")
            result.artifacts["bridge_sample"] = _extract_bridge_sample(
                connection,
                where.bucket,
                release.observed,
                plan.bridge_sample_files,
                out_dir / SEGMENT_FILE,
                out_dir / BRIDGE_SAMPLE_FILE,
            )
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


def _extract_catalogued(
    connection: duckdb.DuckDBPyConnection,
    feature_type: str,
    items: Sequence[CatalogItem],
    chosen: Sequence[CatalogItem],
    bounds: Bounds,
    output: Path,
) -> ArtifactExtraction:
    if not chosen:
        msg = f"No {feature_type} file in the catalog intersects {bounds}."
        raise ExtractionError(msg)
    locations = [item.href for item in chosen]
    schema = _require_schema(connection, feature_type, locations[0], hive=False)

    parameters = (locations, *_bbox_parameters(bounds))
    seconds, http = _write(connection, _REGION_QUERY, parameters, output)
    heads = _head_responses(connection)
    _reset_log(connection)

    sources: list[SourceFile] = []
    for item in chosen:
        source = _source_file(item.href, heads, item)
        if (
            source.size_bytes is not None
            and item.size_bytes is not None
            and source.size_bytes != item.size_bytes
        ):
            msg = (
                f"{item.href} is {source.size_bytes} bytes but the catalog says "
                f"{item.size_bytes}; the release changed underneath its catalog."
            )
            raise ExtractionError(msg)
        sources.append(source)

    return _artifact(
        connection,
        kind=feature_type,
        selection="catalog item bbox intersects region",
        files_available=len(items),
        files_opened=len(chosen),
        sources=sources,
        schema=schema,
        query=_REGION_QUERY,
        parameters=parameters,
        output=output,
        seconds=seconds,
        http=http,
        candidate_rows=_candidate_rows(connection, locations, bounds),
    )


def _extract_changelog(
    connection: duckdb.DuckDBPyConnection,
    bucket: str,
    release: str,
    bounds: Bounds,
    output: Path,
) -> ArtifactExtraction:
    pattern = f"{bucket}/changelog/{release}/theme=transportation/type=*/change_type=*/*.parquet"
    files = _glob(connection, pattern)
    if not files:
        msg = f"No changelog files at {pattern}."
        raise ExtractionError(msg)
    schema = _require_schema(connection, "changelog", files[0], hive=True)

    parameters = (pattern, *_bbox_parameters(bounds))
    seconds, http = _write(connection, _CHANGELOG_QUERY, parameters, output)
    _reset_log(connection)
    return _artifact(
        connection,
        kind="changelog",
        selection="every file's footer read; row groups pruned by bbox statistics",
        files_available=len(files),
        files_opened=len(files),
        sources=[SourceFile(location=pattern)],
        schema=schema,
        query=_CHANGELOG_QUERY,
        parameters=parameters,
        output=output,
        seconds=seconds,
        http=http,
        candidate_rows=_candidate_rows(connection, files, bounds),
    )


def _extract_bridge_sample(
    connection: duckdb.DuckDBPyConnection,
    bucket: str,
    release: str,
    sample_files: int,
    segments: Path,
    output: Path,
) -> ArtifactExtraction:
    pattern = (
        f"{bucket}/bridgefiles/{release}/provider=osm/theme=transportation/type=segment/*.parquet"
    )
    files = _glob(connection, pattern)
    if not files:
        msg = f"No OSM transportation bridge files at {pattern}."
        raise ExtractionError(msg)
    # The first files by name, not a random draw: deterministic, and because GERS
    # ids are random UUIDs, any file holds an unbiased slice of every region.
    chosen = files[:sample_files]
    schema = _require_schema(connection, "bridge", chosen[0], hive=False)

    seconds, http = _write(connection, _BRIDGE_QUERY, (chosen, segments.as_posix()), output)
    heads = _head_responses(connection)
    _reset_log(connection)
    return _artifact(
        connection,
        kind="bridge_sample",
        selection=f"first {len(chosen)} of {len(files)} files by name; rows for extracted segments",
        files_available=len(files),
        files_opened=len(chosen),
        sources=[_source_file(location, heads, None) for location in chosen],
        schema=schema,
        query=_BRIDGE_QUERY,
        parameters=(chosen, _LOCAL + segments.name),
        output=output,
        seconds=seconds,
        http=http,
        candidate_rows=None,
    )


def _changelog_consistency(connection: duckdb.DuckDBPyConnection, out_dir: Path) -> list[str]:
    """Every current feature must appear in the changelog as added, changed or unchanged.

    The changelog and the release are separate artifacts built by the same
    pipeline; when they disagree about which features exist in the region, the
    evidence built on them says so instead of quietly trusting one.
    """
    warnings: list[str] = []
    changelog = (out_dir / CHANGELOG_FILE).as_posix()
    for feature_type, file_name in (("segment", SEGMENT_FILE), ("connector", CONNECTOR_FILE)):
        current = (out_dir / file_name).as_posix()
        row = connection.execute(
            _CONSISTENCY_QUERY,
            [current, changelog, feature_type, changelog, feature_type, current],
        ).fetchone()
        missing, extra = (int(row[0]), int(row[1])) if row is not None else (0, 0)
        if missing or extra:
            warnings.append(
                f"changelog/{feature_type}: {missing} current feature(s) absent from the "
                f"changelog, {extra} changelog feature(s) absent from the release extract."
            )
    return warnings


# ---------------------------------------------------------------------------
# DuckDB plumbing
# ---------------------------------------------------------------------------


def _connect(*, remote: bool) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(database=":memory:")
    if remote:
        # httpfs is downloaded from DuckDB's signed extension repository the first
        # time; signature checking is on by default and is not relaxed here.
        connection.execute("INSTALL httpfs")
        connection.execute("LOAD httpfs")
        connection.execute("SET s3_region = ?", [OVERTURE_BUCKET_REGION])
        connection.execute("CALL enable_logging('HTTP')")
    else:
        # A local run must never reach for the network, not even for an extension.
        connection.execute("SET autoinstall_known_extensions = false")
        connection.execute("SET autoload_known_extensions = false")
    return connection


def _tools(connection: duckdb.DuckDBPyConnection) -> dict[str, str | None]:
    row = connection.execute(
        "SELECT extension_version FROM duckdb_extensions() "
        "WHERE extension_name = 'httpfs' AND loaded"
    ).fetchone()
    return {
        "duckdb": version("duckdb"),
        "httpfs": str(row[0]) if row is not None else None,
    }


def _require_schema(
    connection: duckdb.DuckDBPyConnection, artifact: str, location: str, *, hive: bool
) -> SchemaCheck:
    relation = connection.sql(_SCHEMA_QUERY_HIVE if hive else _SCHEMA_QUERY, params=[location])
    check = check_schema(artifact, relation.columns, [observe(t) for t in relation.types])
    if not check.compatible:
        raise IncompatibleSchemaError(check, location)
    return check


def _write(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: Sequence[Any],
    output: Path,
) -> tuple[float, HttpStats | None]:
    _reset_log(connection)
    started = time.perf_counter()
    connection.sql(query, params=list(parameters)).write_parquet(
        output.as_posix(), compression="zstd"
    )
    return time.perf_counter() - started, _http_stats(connection)


def _http_stats(connection: duckdb.DuckDBPyConnection) -> HttpStats | None:
    try:
        row = connection.execute(
            "SELECT count(*) FILTER (WHERE request.type = 'GET'), "
            "count(*) FILTER (WHERE request.type = 'HEAD'), "
            "coalesce(sum(TRY_CAST(response.headers['Content-Length'] AS BIGINT)) "
            "FILTER (WHERE request.type = 'GET'), 0) "
            "FROM duckdb_logs_parsed('HTTP')"
        ).fetchone()
    except duckdb.Error:
        # No HTTP logging on a local run: there was no network traffic to count.
        return None
    if row is None or (row[0] == 0 and row[1] == 0):
        return None
    return HttpStats(int(row[0]), int(row[1]), int(row[2]))


def _head_responses(connection: duckdb.DuckDBPyConnection) -> dict[str, dict[str, str]]:
    try:
        rows = connection.execute(
            "SELECT request.url, response.headers FROM duckdb_logs_parsed('HTTP') "
            "WHERE request.type = 'HEAD'"
        ).fetchall()
    except duckdb.Error:
        return {}
    # DuckDB percent-encodes S3 keys (`type=segment` is logged as `type%3Dsegment`).
    return {unquote(str(url)): dict(headers or {}) for url, headers in rows}


def _reset_log(connection: duckdb.DuckDBPyConnection) -> None:
    try:
        connection.execute("CALL truncate_duckdb_logs()")
    except duckdb.Error:
        return


def _source_file(
    location: str, heads: dict[str, dict[str, str]], item: CatalogItem | None
) -> SourceFile:
    headers = heads.get(location) or heads.get(_https_form(location)) or {}
    size = headers.get("Content-Length")
    if not headers and not _is_remote(location):
        path = Path(location)
        size = str(path.stat().st_size) if path.is_file() else None
    return SourceFile(
        location=location,
        catalog_item=item.item_id if item is not None else None,
        catalog_size_bytes=item.size_bytes if item is not None else None,
        size_bytes=int(size) if size is not None else None,
        etag=headers.get("ETag"),
        last_modified=headers.get("Last-Modified"),
        expiration=headers.get("x-amz-expiration"),
    )


def _candidate_rows(
    connection: duckdb.DuckDBPyConnection, locations: Sequence[str], bounds: Bounds
) -> int | None:
    """Rows in row groups whose bbox statistics intersect the region."""
    try:
        row = connection.execute(
            _CANDIDATE_ROWS_QUERY, [list(locations), *_bbox_parameters(bounds)]
        ).fetchone()
    finally:
        _reset_log(connection)
    if row is None or row[1]:
        # A row group without bbox statistics cannot be judged; say nothing
        # rather than undercount.
        return None
    return int(row[0] or 0)


def _artifact(
    connection: duckdb.DuckDBPyConnection,
    *,
    kind: str,
    selection: str,
    files_available: int,
    files_opened: int,
    sources: Sequence[SourceFile],
    schema: SchemaCheck,
    query: str,
    parameters: Sequence[Any],
    output: Path,
    seconds: float,
    http: HttpStats | None,
    candidate_rows: int | None,
) -> ArtifactExtraction:
    counted = connection.execute(_COUNT_QUERY, [output.as_posix()]).fetchone()
    return ArtifactExtraction(
        kind=kind,
        selection=selection,
        files_available=files_available,
        files_opened=files_opened,
        sources=tuple(sources),
        schema=schema,
        query=query,
        parameters=tuple(parameters),
        output_file=output.name,
        output_bytes=output.stat().st_size,
        output_sha256=file_sha256(output),
        rows=int(counted[0]) if counted is not None else 0,
        rows_in_candidate_row_groups=candidate_rows,
        seconds=seconds,
        http=http,
    )


def _glob(connection: duckdb.DuckDBPyConnection, pattern: str) -> list[str]:
    rows = connection.execute("SELECT file FROM glob(?) ORDER BY file", [pattern]).fetchall()
    return [str(row[0]) for row in rows]


def _bbox_parameters(bounds: Bounds) -> tuple[float, float, float, float]:
    """Parameters for the bbox predicates: a feature box intersects the region box."""
    min_lon, min_lat, max_lon, max_lat = (float(value) for value in bounds)
    return (max_lon, min_lon, max_lat, min_lat)


def _is_remote(location: str) -> bool:
    return location.startswith(("http://", "https://", "s3://"))


def _https_form(location: str) -> str:
    prefix = f"{OVERTURE_BUCKET}/"
    if location.startswith(prefix):
        return _OVERTURE_HTTPS + location[len(prefix) :]
    return location
