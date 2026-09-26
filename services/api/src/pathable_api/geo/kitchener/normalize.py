"""The first analytical representation of a Kitchener snapshot: one GeoParquet file.

One row per municipal record, joined across the two publications on
``ACTIVETRANSPORTID``. It keeps the City's raw attributes under their own
names, both geometries — the City's own NAD83 / UTM 17N coordinates, untouched,
and a longitude/latitude copy — and the analysis classifications from
:mod:`pathable_api.geo.kitchener.semantics`. It is not PathAble's canonical
cross-source model; it is what the profile and the later matching work read.

What it deliberately does not do:

- **resolve disagreements.** Where both publications carry a field, both are
  compared, and any difference is listed on the row, not settled;
- **carry personal data.** ``CREATE_BY`` and ``UPDATE_BY`` hold staff user
  names; they stay in the raw snapshot, and only whether an update came from a
  named system account is kept here;
- **join records it cannot identify.** A record with no permanent id, or one
  whose id repeats inside a publication, gets its own row and is never joined.

The coordinate conversion is PROJ's default NAD83 → WGS 84 path, which is a
null datum shift with a stated accuracy of a few metres. The pipeline and its
accuracy are recorded in the manifest. Distances in this package are measured
in the native projected coordinates, never in degrees.

Output is byte-reproducible: rows are sorted, the writer runs single-threaded,
and the GeoParquet metadata is built here rather than left to the writer.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pyproj
import shapely
from shapely.geometry.base import BaseGeometry

from pathable_api.geo.kitchener.semantics import (
    FieldSchema,
    FieldState,
    field_state,
    lifecycle,
    network_role,
    physical_class,
    schemas_from_layer,
    source_class,
    source_year,
    structure,
    update_account,
    value_origin,
)
from pathable_api.geo.kitchener.snapshot import SnapshotError, load_manifest, verified_features
from pathable_api.geo.kitchener.source import (
    ACTIVE_TRANSPORTATION,
    IDENTITY_FIELD,
    NATIVE_WKID,
    OBJECT_ID_FIELD,
    PUBLICATIONS,
    WALKABILITY,
)
from pathable_api.geo.overture.evidence import content_sha256, file_sha256, write_json

NORMALIZED_FILE = "kitchener-active-transport.parquet"
NORMALIZED_MANIFEST = "normalized-manifest.json"
NORMALIZED_FORMAT_VERSION = 1
GEOPARQUET_VERSION = "1.1.0"

SOURCE_PROVIDER = "city-of-kitchener"
SOURCE_DATASET = "GIS_DATA.ACTIVE_TRANSPORTATION"

#: Raw fields that stay in the snapshot and never enter the analytical artifact.
EXCLUDED_FIELDS = frozenset({OBJECT_ID_FIELD, "CREATE_BY", "UPDATE_BY"})

#: Fields whose state (null / unknown / default / ...) is classified per row.
STATE_FIELDS: tuple[str, ...] = (
    "STATUS",
    "STATUS_DATE",
    "CATEGORY",
    "SUBCATEGORY",
    "FEATURE_TYPE",
    "SURFACE_MATERIAL",
    "WIDTH_M",
    "GRADE",
    "RAILING",
    "CURBCUT",
    "SURFACE_CONDITION",
    "LAST_INSPECTION_YEAR",
    "CONDITION_SCORE",
    "CONDITION_DATE",
    "INSTALLATION_YEAR",
    "SIDEWALKER_PROGRAM",
    "SLOPE_GRADIENT_PERCENT",
    "SLOPE_GRADIENT_CLASS",
    "SLOPE_GRADIENT_MAX",
    "GRADE_CATEGORY_MAX",
    "SOURCE",
    "SOURCE_DATE",
    "CREATE_DATE",
    "UPDATE_DATE",
    "ROADSEGMENTID",
    "ROADSEGMENT_SIDE",
    "STREET",
    "NOTES",
)

#: Fields whose per-row evidence origin is classified.
ORIGIN_FIELDS: tuple[str, ...] = (
    "STATUS",
    "FEATURE_TYPE",
    "SURFACE_MATERIAL",
    "WIDTH_M",
    "GRADE",
    "RAILING",
    "CURBCUT",
    "SURFACE_CONDITION",
    "LAST_INSPECTION_YEAR",
    "CONDITION_SCORE",
    "SLOPE_GRADIENT_PERCENT",
    "SLOPE_GRADIENT_CLASS",
    "GRADE_CATEGORY_MAX",
    "INSTALLATION_YEAR",
)

_DUCK_TYPES = {
    "esriFieldTypeOID": "BIGINT",
    "esriFieldTypeInteger": "BIGINT",
    "esriFieldTypeSmallInteger": "BIGINT",
    "esriFieldTypeBigInteger": "BIGINT",
    "esriFieldTypeDouble": "DOUBLE",
    "esriFieldTypeSingle": "DOUBLE",
    "esriFieldTypeString": "VARCHAR",
    "esriFieldTypeDate": "TIMESTAMPTZ",
}

Progress = Callable[[str], None]


class NormalizationError(RuntimeError):
    """The snapshot cannot be normalized into something trustworthy."""


@dataclass(frozen=True, slots=True)
class Record:
    publication: str
    object_id: int
    attributes: dict[str, Any]
    geometry: dict[str, Any] | None


@dataclass(slots=True)
class Joined:
    identity: int | None
    identity_state: str
    records: dict[str, Record] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizationResult:
    folder: Path
    manifest: dict[str, Any]


def normalize_snapshot(
    snapshot: Path,
    out_dir: Path,
    *,
    progress: Progress | None = None,
    measure: Callable[[], dict[str, Any]] | None = None,
) -> NormalizationResult:
    """Build the GeoParquet file and its manifest from one frozen snapshot."""
    say = progress or (lambda _message: None)
    started = time.perf_counter()
    manifest = load_manifest(snapshot)
    if not manifest["licence"]["matches_recorded_terms"]:
        msg = (
            "The snapshot's licence text no longer contains every term the audit relies on. "
            "Review the licence before normalizing."
        )
        raise NormalizationError(msg)
    if out_dir.exists():
        msg = f"{out_dir} already exists; normalized output is never overwritten."
        raise NormalizationError(msg)

    schemas: dict[str, dict[str, FieldSchema]] = {}
    raw_fields: dict[str, list[dict[str, Any]]] = {}
    records: dict[str, list[Record]] = {}
    for publication in PUBLICATIONS:
        layer = json.loads(
            (snapshot / "metadata" / f"{publication.key}.layer.json").read_text("utf-8")
        )
        if "fields" not in layer:
            msg = f"{publication.key}: the archived layer description lists no fields."
            raise NormalizationError(msg)
        schemas[publication.key] = schemas_from_layer(layer)
        raw_fields[publication.key] = list(layer["fields"])
        records[publication.key] = _records(
            publication.key, verified_features(snapshot, manifest, publication.key)
        )
        say(f"{publication.key}: {len(records[publication.key])} records verified.")

    joined = join_publications(records)
    columns = _raw_columns(raw_fields[ACTIVE_TRANSPORTATION.key])
    transformer = pyproj.Transformer.from_crs(f"EPSG:{NATIVE_WKID}", "OGC:CRS84", always_xy=True)
    rows, geometry = _rows(manifest["snapshot_id"], joined, columns, schemas, transformer)
    say(f"joined: {len(rows)} rows.")

    out_dir.mkdir(parents=True)
    output = out_dir / NORMALIZED_FILE
    geo = _geo_metadata(geometry)
    table_columns = _table_columns(columns)
    seconds_write = _write_parquet(output, table_columns, rows, geo)

    document: dict[str, Any] = {
        "kitchener_normalized_version": NORMALIZED_FORMAT_VERSION,
        "snapshot_id": manifest["snapshot_id"],
        "inputs": {
            "snapshot_manifest_sha256": file_sha256(snapshot / "snapshot-manifest.json"),
            "snapshot_manifest_content_sha256": manifest["content_sha256"],
            "features": {
                key: manifest["publications"][key]["features"]["sha256"] for key in records
            },
        },
        "output": {
            "file": NORMALIZED_FILE,
            "bytes": output.stat().st_size,
            "sha256": file_sha256(output),
            "rows": len(rows),
        },
        "geoparquet": geo,
        "crs": {
            "native": f"EPSG:{NATIVE_WKID}",
            "primary": "OGC:CRS84",
            "transformation": transformer.description,
            "transformation_accuracy_m": transformer.accuracy,
            "proj_pipeline": transformer.definition,
        },
        "columns": [{"name": name, "type": kind} for name, kind in table_columns],
        "excluded_fields": sorted(EXCLUDED_FIELDS),
        "joins": _join_summary(joined),
        "tools": {
            "duckdb": version("duckdb"),
            "shapely": version("shapely"),
            "geos": shapely.geos_version_string,
            "pyproj": version("pyproj"),
            "proj": pyproj.proj_version_str,
        },
        "run": {
            "seconds": round(time.perf_counter() - started, 2),
            "write_seconds": round(seconds_write, 2),
            **(measure() if measure is not None else {}),
        },
    }
    document["content_sha256"] = content_sha256(document)
    write_json(out_dir / NORMALIZED_MANIFEST, document)
    return NormalizationResult(folder=out_dir, manifest=document)


def _records(key: str, path: Path) -> list[Record]:
    records = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            feature = json.loads(line)
            attributes = dict(feature.get("attributes") or {})
            object_id = attributes.get(OBJECT_ID_FIELD)
            if not isinstance(object_id, int):
                msg = f"{path} holds a feature without an integer {OBJECT_ID_FIELD}."
                raise SnapshotError(msg)
            records.append(Record(key, object_id, attributes, feature.get("geometry")))
    return records


def join_publications(records: Mapping[str, Sequence[Record]]) -> list[Joined]:
    """Join on the permanent id; never join what cannot be identified.

    An id that repeats inside *any* publication is unjoinable in *every*
    publication: with two candidates on one side there is no way to know which
    record the other side's copy describes.

    Output order is deterministic: joined ids ascending, then unjoinable records
    by publication and object id.
    """
    repeated: set[int] = set()
    for publication_records in records.values():
        counts = Counter(
            identity
            for record in publication_records
            if isinstance(identity := record.attributes.get(IDENTITY_FIELD), int)
        )
        repeated.update(identity for identity, count in counts.items() if count > 1)

    by_id: dict[int, Joined] = {}
    unjoinable: list[Joined] = []
    for key, publication_records in records.items():
        for record in publication_records:
            identity = record.attributes.get(IDENTITY_FIELD)
            if not isinstance(identity, int):
                unjoinable.append(Joined(None, "null", {key: record}))
            elif identity in repeated:
                unjoinable.append(Joined(identity, "duplicate", {key: record}))
            else:
                by_id.setdefault(identity, Joined(identity, "unique")).records[key] = record
    ordered = [by_id[identity] for identity in sorted(by_id)]
    unjoinable.sort(
        key=lambda item: (
            next(iter(item.records)),
            next(iter(item.records.values())).object_id,
        )
    )
    return ordered + unjoinable


def _raw_columns(fields: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    """(source field, column name, DuckDB type) for every raw field kept."""
    columns = []
    for item in fields:
        name = str(item["name"])
        if name in EXCLUDED_FIELDS:
            continue
        kind = _DUCK_TYPES.get(str(item.get("type")))
        if kind is None:
            msg = f"Field {name} has unsupported type {item.get('type')}."
            raise NormalizationError(msg)
        columns.append((name, _column(name), kind))
    return columns


def _column(field_name: str) -> str:
    return "shape_length_m" if field_name == "Shape__Length" else field_name.lower()


def _table_columns(raw: Sequence[tuple[str, str, str]]) -> list[tuple[str, str]]:
    columns: list[tuple[str, str]] = [
        ("source_provider", "VARCHAR"),
        ("source_dataset", "VARCHAR"),
        ("snapshot_id", "VARCHAR"),
        ("activetransportid", "BIGINT"),
        ("identity_state", "VARCHAR"),
        ("in_active_transportation", "BOOLEAN"),
        ("in_walkability", "BOOLEAN"),
        ("objectid_active_transportation", "BIGINT"),
        ("objectid_walkability", "BIGINT"),
        ("attributes_from", "VARCHAR"),
        ("publication_disagreements", "VARCHAR[]"),
    ]
    columns.extend((name, kind) for source, name, kind in raw if source != IDENTITY_FIELD)
    columns.extend(
        [
            ("update_account", "VARCHAR"),
            ("lifecycle", "VARCHAR"),
            ("network_role", "VARCHAR"),
            ("role_note", "VARCHAR"),
            ("physical_class", "VARCHAR"),
            ("structure", "VARCHAR"),
            ("source_class", "VARCHAR"),
            ("source_year", "INTEGER"),
        ]
    )
    columns.extend((f"state_{name.lower()}", "VARCHAR") for name in STATE_FIELDS)
    columns.extend((f"origin_{name.lower()}", "VARCHAR") for name in ORIGIN_FIELDS)
    columns.extend(
        [
            ("length_m", "DOUBLE"),
            ("part_count", "INTEGER"),
            ("vertex_count", "INTEGER"),
            ("geometry_issue", "VARCHAR"),
            ("bbox", "STRUCT(xmin DOUBLE, ymin DOUBLE, xmax DOUBLE, ymax DOUBLE)"),
            ("geometry", "BLOB"),
            ("geometry_native", "BLOB"),
        ]
    )
    return columns


@dataclass(slots=True)
class GeometrySummary:
    types_primary: set[str] = field(default_factory=set)
    types_native: set[str] = field(default_factory=set)
    bounds_primary: list[float] | None = None
    bounds_native: list[float] | None = None


def _rows(
    snapshot_id: str,
    joined: Sequence[Joined],
    raw: Sequence[tuple[str, str, str]],
    schemas: Mapping[str, Mapping[str, FieldSchema]],
    transformer: pyproj.Transformer,
) -> tuple[list[tuple[Any, ...]], GeometrySummary]:
    native = [_native_geometry(_primary_record(item).geometry) for item in joined]
    converted = _to_crs84(native, transformer)
    summary = GeometrySummary()
    rows = []
    for item, geometry_native, geometry in zip(joined, native, converted, strict=True):
        rows.append(_row(snapshot_id, item, raw, schemas, geometry_native, geometry, summary))
    return rows, summary


def _primary_record(item: Joined) -> Record:
    for publication in PUBLICATIONS:
        if publication.key in item.records:
            return item.records[publication.key]
    raise AssertionError("a joined row always holds a record")  # pragma: no cover


def _row(
    snapshot_id: str,
    item: Joined,
    raw: Sequence[tuple[str, str, str]],
    schemas: Mapping[str, Mapping[str, FieldSchema]],
    geometry_native: BaseGeometry | None,
    geometry: BaseGeometry | None,
    summary: GeometrySummary,
) -> tuple[Any, ...]:
    primary = _primary_record(item)
    attributes = primary.attributes
    schema = schemas[primary.publication]
    # Both publications serve one internal layer, but only Active_Transportation
    # publishes its defaults and domains (Walkability strips them). Those are the
    # layer's, so they classify every record; the record's own publication only
    # decides whether a field was published at all.
    reference = schemas[ACTIVE_TRANSPORTATION.key]
    at = item.records.get(ACTIVE_TRANSPORTATION.key)
    walk = item.records.get(WALKABILITY.key)

    def value(name: str) -> Any:
        return attributes.get(name) if name in schema else None

    status_published = "STATUS" in schema
    role = network_role(
        value("CATEGORY"), value("SUBCATEGORY"), value("FEATURE_TYPE"), value("SURFACE_MATERIAL")
    )
    state = lifecycle(value("STATUS"), published=status_published)
    states = {
        name: field_state(reference.get(name), value(name), published=name in schema)
        for name in STATE_FIELDS
    }

    row: list[Any] = [
        SOURCE_PROVIDER,
        SOURCE_DATASET,
        snapshot_id,
        item.identity,
        item.identity_state,
        at is not None,
        walk is not None,
        at.object_id if at is not None else None,
        walk.object_id if walk is not None else None,
        primary.publication,
        _disagreements(item),
    ]
    for source, _name, kind in raw:
        if source == IDENTITY_FIELD:
            continue
        row.append(_cast(value(source), kind))
    row.extend(
        [
            update_account(value("UPDATE_BY")),
            str(state),
            str(role.role),
            role.note,
            str(physical_class(role.role, state)),
            structure(value("FEATURE_TYPE")),
            str(source_class(value("SOURCE"))),
            source_year(value("SOURCE")),
        ]
    )
    row.extend(str(states[name]) for name in STATE_FIELDS)
    row.extend(str(value_origin(name, states[name])) for name in ORIGIN_FIELDS)
    row.extend(_geometry_columns(geometry_native, geometry, summary))
    return tuple(row)


def _disagreements(item: Joined) -> list[str]:
    """Fields both publications carry for this record, where they differ."""
    at = item.records.get(ACTIVE_TRANSPORTATION.key)
    walk = item.records.get(WALKABILITY.key)
    if at is None or walk is None:
        return []
    shared = sorted((set(at.attributes) & set(walk.attributes)) - {OBJECT_ID_FIELD, IDENTITY_FIELD})
    different = [name for name in shared if at.attributes[name] != walk.attributes[name]]
    if at.geometry != walk.geometry:
        different.append("geometry")
    return different


def _cast(value: Any, kind: str) -> Any:
    if value is None:
        return None
    if kind == "TIMESTAMPTZ":
        if isinstance(value, int | float) and not isinstance(value, bool):
            return dt.datetime.fromtimestamp(value / 1000, tz=dt.UTC)
        msg = f"Date value {value!r} is not epoch milliseconds."
        raise NormalizationError(msg)
    return value


def _native_geometry(geometry: Mapping[str, Any] | None) -> BaseGeometry | None:
    if geometry is None:
        return None
    paths = geometry.get("paths")
    if not isinstance(paths, list):
        msg = "A feature geometry has no paths; only polylines are supported."
        raise NormalizationError(msg)
    parts = [[(float(x), float(y)) for x, y, *_rest in path] for path in paths]
    if not parts:
        return shapely.LineString()
    if len(parts) == 1:
        return shapely.LineString(parts[0])
    return shapely.MultiLineString(parts)


def _to_crs84(
    geometries: Sequence[BaseGeometry | None], transformer: pyproj.Transformer
) -> list[BaseGeometry | None]:
    present = [geometry for geometry in geometries if geometry is not None]

    def project(coordinates: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        lon, lat = transformer.transform(coordinates[:, 0], coordinates[:, 1])
        return np.column_stack([lon, lat])

    converted = iter(shapely.transform(np.array(present, dtype=object), project))
    return [next(converted) if geometry is not None else None for geometry in geometries]


def _geometry_columns(
    native: BaseGeometry | None,
    primary: BaseGeometry | None,
    summary: GeometrySummary,
) -> list[Any]:
    if native is None or primary is None:
        return [None, None, None, "missing", None, None, None]
    parts = len(native.geoms) if isinstance(native, shapely.MultiLineString) else 1
    vertices = int(shapely.get_num_coordinates(native))
    issue = geometry_issue(native)
    if native.is_empty:
        return [0.0, 0, 0, issue, None, None, None]
    summary.types_native.add(native.geom_type)
    summary.types_primary.add(primary.geom_type)
    summary.bounds_native = _union(summary.bounds_native, native.bounds)
    summary.bounds_primary = _union(summary.bounds_primary, primary.bounds)
    xmin, ymin, xmax, ymax = primary.bounds
    return [
        float(native.length),
        parts,
        vertices,
        issue,
        {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
        shapely.to_wkb(primary, byte_order=1, output_dimension=2, flavor="iso"),
        shapely.to_wkb(native, byte_order=1, output_dimension=2, flavor="iso"),
    ]


def geometry_issue(geometry: BaseGeometry | None) -> str | None:
    """Why a geometry cannot be used as-is, or ``None`` when it can."""
    if geometry is None:
        return "missing"
    if geometry.is_empty:
        return "empty"
    if not geometry.is_valid:
        return "invalid"
    if geometry.length == 0:
        return "zero_length"
    return None


def _union(current: list[float] | None, bounds: Iterable[float]) -> list[float]:
    xmin, ymin, xmax, ymax = (float(value) for value in bounds)
    if current is None:
        return [xmin, ymin, xmax, ymax]
    return [
        min(current[0], xmin),
        min(current[1], ymin),
        max(current[2], xmax),
        max(current[3], ymax),
    ]


def _geo_metadata(summary: GeometrySummary) -> dict[str, Any]:
    """GeoParquet 1.1.0 file metadata, written by us rather than inferred.

    The primary column omits ``crs``, which the specification defines as
    OGC:CRS84. The native column carries its CRS as PROJJSON.
    """
    primary: dict[str, Any] = {
        "encoding": "WKB",
        "geometry_types": sorted(summary.types_primary),
        "covering": {
            "bbox": {
                "xmin": ["bbox", "xmin"],
                "ymin": ["bbox", "ymin"],
                "xmax": ["bbox", "xmax"],
                "ymax": ["bbox", "ymax"],
            }
        },
    }
    native: dict[str, Any] = {
        "encoding": "WKB",
        "geometry_types": sorted(summary.types_native),
        "crs": pyproj.CRS.from_epsg(NATIVE_WKID).to_json_dict(),
    }
    # The specification allows the bbox to be absent, not empty.
    if summary.bounds_primary is not None:
        primary["bbox"] = summary.bounds_primary
    if summary.bounds_native is not None:
        native["bbox"] = summary.bounds_native
    return {
        "version": GEOPARQUET_VERSION,
        "primary_column": "geometry",
        "columns": {"geometry": primary, "geometry_native": native},
    }


def _write_parquet(
    output: Path,
    columns: Sequence[tuple[str, str]],
    rows: Sequence[tuple[Any, ...]],
    geo: Mapping[str, Any],
) -> float:
    """Stage the rows as newline-delimited JSON, then let DuckDB type and write them.

    Row-by-row inserts from Python took minutes for the real snapshot; one typed
    ``read_json`` takes seconds. Binary and timestamp values travel as text
    (hex, ISO 8601) and are cast back exactly.
    """
    started = time.perf_counter()
    staging = output.with_name(f".{output.name}.rows.ndjson")
    with staging.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            record = {
                name: _json_value(value, kind)
                for (name, kind), value in zip(columns, row, strict=True)
            }
            handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")

    connection = duckdb.connect(database=":memory:")
    try:
        # One thread and a fixed session time zone: the file's bytes must not
        # depend on the machine that wrote it.
        connection.execute("SET threads = 1")
        connection.execute("SET TimeZone = 'UTC'")
        connection.execute("SET autoinstall_known_extensions = false")
        connection.execute("SET autoload_known_extensions = false")
        json_types = ", ".join(f"'{name}': '{_staged_type(kind)}'" for name, kind in columns)
        selected = ", ".join(_from_staged(name, kind) for name, kind in columns)
        # Column names and types come from this module; the path is quoted. DuckDB
        # accepts no bound parameters in these positions.
        connection.execute(
            f"CREATE TABLE normalized AS SELECT {selected} FROM read_json("  # noqa: S608
            f"'{_sql_path(staging)}', format = 'newline_delimited', "
            f"columns = {{{json_types}}})"
        )
        metadata = json.dumps(geo, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        literal = metadata.replace("'", "''")
        connection.execute(
            f"COPY normalized TO '{_sql_path(output)}' "
            f"(FORMAT parquet, COMPRESSION zstd, KV_METADATA {{geo: '{literal}'}})"
        )
    finally:
        connection.close()
        staging.unlink(missing_ok=True)
    return time.perf_counter() - started


def _json_value(value: Any, kind: str) -> Any:
    if value is None:
        return None
    if kind == "BLOB":
        return bytes(value).hex()
    if kind == "TIMESTAMPTZ":
        return value.isoformat()
    return value


def _staged_type(kind: str) -> str:
    return "VARCHAR" if kind in ("BLOB", "TIMESTAMPTZ") else kind


def _from_staged(name: str, kind: str) -> str:
    if kind == "BLOB":
        return f'from_hex("{name}") AS "{name}"'
    if kind == "TIMESTAMPTZ":
        return f'CAST("{name}" AS TIMESTAMPTZ) AS "{name}"'
    return f'"{name}"'


def _sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def _join_summary(joined: Sequence[Joined]) -> dict[str, Any]:
    states: Counter[str] = Counter(item.identity_state for item in joined)
    presence: Counter[str] = Counter(
        "+".join(sorted(item.records)) for item in joined if item.identity_state == "unique"
    )
    disagreements: dict[str, int] = defaultdict(int)
    for item in joined:
        for name in _disagreements(item):
            disagreements[name] += 1
    return {
        "rows": len(joined),
        "identity_states": dict(sorted(states.items())),
        "publications_per_identity": dict(sorted(presence.items())),
        "fields_differing_between_publications": dict(sorted(disagreements.items())),
    }


def load_normalized(folder: Path) -> tuple[Path, dict[str, Any]]:
    """The normalized file and its manifest, refused unless the hash matches."""
    manifest_path = folder / NORMALIZED_MANIFEST
    if not manifest_path.is_file():
        msg = f"{folder} holds no {NORMALIZED_MANIFEST}."
        raise NormalizationError(msg)
    manifest = json.loads(manifest_path.read_text("utf-8"))
    output = folder / str(manifest["output"]["file"])
    if not output.is_file() or file_sha256(output) != manifest["output"]["sha256"]:
        msg = f"{output} is missing or does not match its recorded SHA-256."
        raise NormalizationError(msg)
    return output, manifest


__all__ = [
    "NORMALIZED_FILE",
    "NORMALIZED_MANIFEST",
    "FieldState",
    "NormalizationError",
    "geometry_issue",
    "join_publications",
    "load_normalized",
    "normalize_snapshot",
]
