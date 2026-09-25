"""A miniature Overture release on disk, so no test ever touches the network.

It has the real shapes — a STAC catalog with one item per file, GeoParquet with
Overture's nested ``sources`` struct, a hive-partitioned changelog and OSM
bridge files — and one deliberately chosen case for each category the linkage
reports. The region is an invented box far from Waterloo so nothing here can be
mistaken for real data.

Every segment's purpose is in its id. The expected outcome of each is written
next to it, because the tests assert those outcomes, not whatever the code
happens to produce.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from pathable_api.geo.overture.extract import ExtractionPlan, OvertureLocation, run_extraction
from pathable_api.geo.overture.osm_versions import ElementState, VersionEvidence
from pathable_api.geo.overture.pathable import DatasetFacts, PathAbleIdentities

RELEASE = "2026-09-23.0"
OLDER_RELEASE = "2026-08-19.0"
REGION = (10.0, 10.0, 11.0, 11.0)
INSIDE = (10.2, 10.2, 10.3, 10.3)
OSM_SNAPSHOT = "2026-09-09"
#: After the fixture dataset's source timestamp (2026-08-16T23:08:23Z), before OSM_SNAPSHOT.
AFTER = "2026-08-20T11:49:48Z"

SEGMENT_DDL = """
    id VARCHAR, subtype VARCHAR, class VARCHAR, subclass VARCHAR,
    connectors STRUCT(connector_id VARCHAR, "at" DOUBLE)[],
    sources STRUCT(property VARCHAR, dataset VARCHAR, license VARCHAR, record_id VARCHAR,
        update_time VARCHAR, confidence DOUBLE, "between" DOUBLE[], provider VARCHAR,
        resource VARCHAR, "version" VARCHAR)[],
    geometry GEOMETRY, version INTEGER,
    bbox STRUCT(xmin DOUBLE, xmax DOUBLE, ymin DOUBLE, ymax DOUBLE),
    theme VARCHAR, type VARCHAR
"""

CONNECTOR_DDL = """
    id VARCHAR,
    sources STRUCT(property VARCHAR, dataset VARCHAR, license VARCHAR, record_id VARCHAR,
        update_time VARCHAR, confidence DOUBLE, "between" DOUBLE[], provider VARCHAR,
        resource VARCHAR, "version" VARCHAR)[],
    geometry GEOMETRY, version INTEGER,
    bbox STRUCT(xmin DOUBLE, xmax DOUBLE, ymin DOUBLE, ymax DOUBLE),
    theme VARCHAR, type VARCHAR
"""

BRIDGE_DDL = """
    id VARCHAR, dataset VARCHAR, record_id VARCHAR, update_time VARCHAR, resource VARCHAR,
    version VARCHAR, "between" DOUBLE[], dataset_between DOUBLE[]
"""

CHANGELOG_DDL = """
    id VARCHAR, bbox STRUCT(xmin DOUBLE, xmax DOUBLE, ymin DOUBLE, ymax DOUBLE),
    columns_changed VARCHAR[]
"""


def src(
    record_id: str | None,
    *,
    dataset: str = "OpenStreetMap",
    prop: str = "",
    between: list[float] | None = None,
    update_time: str | None = "2024-01-01T00:00:00Z",
    version: str | None = OSM_SNAPSHOT,
) -> dict[str, Any]:
    return {
        "property": prop,
        "dataset": dataset,
        "license": "ODbL-1.0",
        "record_id": record_id,
        "update_time": update_time,
        "confidence": None,
        "between": between,
        "provider": "osm" if dataset == "OpenStreetMap" else dataset.lower(),
        "resource": "planet" if dataset == "OpenStreetMap" else None,
        "version": version,
    }


@dataclass(frozen=True)
class Seg:
    id: str
    sources: Sequence[dict[str, Any]]
    bbox: tuple[float, float, float, float] = INSIDE
    feature_class: str = "footway"
    subclass: str | None = None


#: One case per category. Expected way-level outcome after the arrow.
SEGMENTS: tuple[Seg, ...] = (
    Seg("seg-one", [src("w100@3")]),  # w100 one_to_one
    Seg("seg-split-a", [src("w200@1")]),  # w200 one_to_many (split across two)
    Seg("seg-split-b", [src("w200@1")]),
    Seg(  # w300, w301 many_to_one, with the segment ranges preserved
        "seg-merge",
        [src("w300@2", between=[0.0, 0.5]), src("w301@1", between=[0.5, 1.0])],
    ),
    Seg(  # w400 many_to_many; w401 many_to_one
        "seg-mm-a",
        [src("w400@1", between=[0.0, 0.6]), src("w401@1", between=[0.6, 1.0])],
    ),
    Seg("seg-mm-b", [src("w400@1")]),
    Seg(  # w500 one_to_one; the relation only contributed a property
        "seg-routes",
        [src("w500@4"), src("r900@2", prop="/routes", update_time=None)],
    ),
    Seg(  # no OSM identity at all
        "seg-tomtom",
        [src(None, dataset="TomTom", update_time=None, version="2637")],
        feature_class="unknown",
    ),
    Seg(  # both rows malformed, so the segment is unresolved
        "seg-malformed",
        [src("w600"), src("w601@1", between=[0.7, 0.2])],
    ),
    Seg(  # duplicate row; w700 one_to_one. A node moved after PathAble's snapshot.
        "seg-dup",
        [src("w700@1", update_time=AFTER), src("w700@1", update_time=AFTER)],
    ),
    Seg("seg-conflict-a", [src("w800@1")]),  # w800 cited at two versions
    Seg("seg-conflict-b", [src("w800@2")]),
    Seg(  # not in PathAble, crosses the region boundary
        "seg-boundary",
        [src("w900@1")],
        bbox=(10.9, 10.5, 11.2, 10.6),
        feature_class="secondary",
    ),
    Seg("seg-motorway", [src("w950@1")], feature_class="motorway"),  # not in PathAble
    # Outside the region. Also cites w100: if the bbox filter leaked, w100 would
    # stop being one_to_one.
    Seg("seg-outside", [src("w100@3")], bbox=(12.0, 12.0, 12.1, 12.1)),
)
EXTRACTED_SEGMENTS = [seg.id for seg in SEGMENTS if seg.id != "seg-outside"]

CONNECTORS: tuple[tuple[str, dict[str, Any], tuple[float, float, float, float]], ...] = (
    ("con-a", src("n10@1"), INSIDE),  # a PathAble node
    ("con-b", src("n12@1"), INSIDE),  # an OSM node PathAble does not have
    ("con-c", src(None), INSIDE),  # OSM, but no record id
    ("con-d", src("n11@x"), INSIDE),  # malformed
    ("con-e", src("n13@0", update_time=None), INSIDE),  # version 0: id kept, version refused
    ("con-out", src("n10@1"), (12.0, 12.0, 12.0, 12.0)),  # outside the region
)

#: (file, gers id, record id, between). Only part-00000 is read with a 1-file sample.
BRIDGE: tuple[tuple[str, str, str, list[float] | None], ...] = (
    ("part-00000", "seg-one", "w100@3", None),  # matches a segment source
    ("part-00000", "seg-routes", "r900@2", None),  # matches only the /routes property source
    ("part-00000", "seg-one", "w999@1", None),  # in the bridge, not in the segment's sources
    ("part-00000", "seg-outside", "w100@3", None),  # not an extracted segment
    ("part-00001", "seg-merge", "w300@2", [0.0, 0.5]),
)

#: (type, change type, id, columns changed)
CHANGELOG: tuple[tuple[str, str, str, list[str]], ...] = (
    ("segment", "added", "seg-one", []),
    ("segment", "data_changed", "seg-merge", ["geometry", "sources"]),
    ("segment", "removed", "seg-gone", []),
    *(
        ("segment", "unchanged", seg_id, [])
        for seg_id in EXTRACTED_SEGMENTS
        if seg_id not in {"seg-one", "seg-merge"}
    ),
    *(("connector", "unchanged", con[0], []) for con in CONNECTORS if con[0] != "con-out"),
    ("segment", "unchanged", "seg-outside", []),
)


@dataclass(frozen=True)
class FixtureRelease:
    root: Path

    @property
    def stac_root(self) -> str:
        return (self.root / "stac" / "catalog.json").as_posix()

    @property
    def bucket(self) -> str:
        return (self.root / "bucket").as_posix()

    @property
    def location(self) -> OvertureLocation:
        return OvertureLocation(stac_root=self.stac_root, bucket=self.bucket)

    def fetch_json(self, url: str) -> dict[str, Any]:
        document: dict[str, Any] = json.loads(Path(url).read_text(encoding="utf-8"))
        return document


def build_release(
    root: Path,
    *,
    schema_version: str = "2.0.0",
    segment_ddl: str = SEGMENT_DDL,
    changelog: Sequence[tuple[str, str, str, list[str]]] = CHANGELOG,
) -> FixtureRelease:
    fixture = FixtureRelease(root)
    data = root / "data"
    data.mkdir(parents=True)
    connection = duckdb.connect()
    try:
        segment_file = data / "segment-00000.parquet"
        _write_segments(connection, segment_file, segment_ddl)
        # A file whose catalog box misses the region. It is not Parquet at all,
        # so if anything ever opens it the extraction fails loudly.
        unreachable = data / "segment-00001.parquet"
        unreachable.write_bytes(b"not a parquet file")
        connector_file = data / "connector-00000.parquet"
        _write_connectors(connection, connector_file)
        _write_bridge(connection, root / "bucket")
        _write_changelog(connection, root / "bucket", changelog)
    finally:
        connection.close()

    stac = root / "stac"
    _write_catalog(stac, schema_version)
    _write_collection(
        stac / RELEASE / "transportation" / "segment",
        [("00000", segment_file, (9.5, 9.5, 12.5, 12.5)), ("00001", unreachable, (50, 50, 51, 51))],
    )
    _write_collection(
        stac / RELEASE / "transportation" / "connector",
        [("00000", connector_file, (9.5, 9.5, 12.5, 12.5))],
    )
    return fixture


def extract(
    fixture: FixtureRelease,
    out_root: Path,
    *,
    bridge_sample_files: int = 1,
    region_slug: str = "fixture-region",
) -> Path:
    """Run the real extraction against the fixture and return the extract folder."""
    result = run_extraction(
        ExtractionPlan(
            region_slug=region_slug,
            bounds=REGION,
            bounds_source="tests.overture_fixture.REGION",
            release=RELEASE,
            bridge_sample_files=bridge_sample_files,
        ),
        out_root,
        fetch_json=fixture.fetch_json,
        location=fixture.location,
    )
    return result.out_dir


def identities() -> PathAbleIdentities:
    """What a PathAble dataset over the fixture region would store."""
    way_edges = {
        "100": 2,
        "200": 3,
        "300": 1,
        "301": 1,
        "400": 2,
        "401": 1,
        "500": 1,
        "700": 1,
        "800": 1,
        "1000": 4,  # not cited by Overture at all
        "synthetic-1": 1,  # not an OSM id
    }
    return PathAbleIdentities(
        facts=DatasetFacts(
            dataset_id="00000000-0000-0000-0000-000000000001",
            region_slug="fixture-region",
            status="active",
            checksum="c" * 64,
            source_type="osm",
            source_name="openstreetmap-pbf:fixture",
            source_timestamp="2026-08-16T23:08:23+00:00",
            acquired_at="2026-08-17T23:52:02+00:00",
            node_count=4,
            edge_count=sum(way_edges.values()),
            source_file_name="fixture.osm.pbf",
            source_file_sha256="f" * 64,
            source_provider="fixture",
        ),
        way_edges=way_edges,
        way_highway={way: ("corridor" if way == "1000" else "footway") for way in way_edges},
        node_ids={"10", "11", "13", "n-a"},
    )


def evidence() -> VersionEvidence:
    """Versions and edit times as the dataset's source extract would record them.

    Every fixture source carries ``update_time`` 2024-01-01, which is what
    Overture would write if the latest edit across the way and its nodes was
    then.
    """
    stamp = "2024-01-01T00:00:00Z"
    earlier = "2023-01-01T00:00:00Z"
    return VersionEvidence(
        file_name="fixture.osm.pbf",
        file_sha256="f" * 64,
        ways={
            100: ElementState(3, stamp, stamp),  # exact: the way's own edit time
            200: ElementState(1, stamp, stamp),  # exact
            300: ElementState(1, stamp, stamp),  # Overture has v2: PathAble older
            301: ElementState(1, earlier, stamp),  # exact: a node's later edit time
            400: ElementState(1, stamp, stamp),  # exact
            401: ElementState(1, stamp, None),  # a member node was unreadable
            500: ElementState(5, stamp, stamp),  # Overture has v4: PathAble newer
            700: ElementState(1, earlier, earlier),  # same version; a node moved after
            800: ElementState(1, stamp, stamp),  # Overture cites v1 and v2: ambiguous
        },
        nodes={10: ElementState(1, stamp, stamp)},
        ways_requested=10,
        nodes_requested=3,
    )


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def _write_segments(connection: duckdb.DuckDBPyConnection, path: Path, ddl: str) -> None:
    connection.execute(f"CREATE OR REPLACE TABLE seg ({ddl})")
    columns = [row[0] for row in connection.execute("DESCRIBE seg").fetchall()]
    for seg in SEGMENTS:
        values: dict[str, Any] = {
            "id": seg.id,
            "subtype": "road",
            "class": seg.feature_class,
            "subclass": seg.subclass,
            "connectors": [{"connector_id": "con-a", "at": 0.0}],
            "sources": list(seg.sources),
            "geometry": _line(seg.bbox),
            "version": 1,
            "bbox": _bbox(seg.bbox),
            "theme": "transportation",
            "type": "segment",
        }
        _insert(connection, "seg", columns, values)
    connection.table("seg").write_parquet(path.as_posix())


def _write_connectors(connection: duckdb.DuckDBPyConnection, path: Path) -> None:
    connection.execute(f"CREATE OR REPLACE TABLE con ({CONNECTOR_DDL})")
    columns = [row[0] for row in connection.execute("DESCRIBE con").fetchall()]
    for connector_id, source, bbox in CONNECTORS:
        _insert(
            connection,
            "con",
            columns,
            {
                "id": connector_id,
                "sources": [source],
                "geometry": f"POINT ({bbox[0]} {bbox[1]})",
                "version": 1,
                "bbox": _bbox(bbox),
                "theme": "transportation",
                "type": "connector",
            },
        )
    connection.table("con").write_parquet(path.as_posix())


def _write_bridge(connection: duckdb.DuckDBPyConnection, bucket: Path) -> None:
    folder = bucket / "bridgefiles" / RELEASE / "provider=osm/theme=transportation/type=segment"
    folder.mkdir(parents=True)
    for part in sorted({row[0] for row in BRIDGE}):
        connection.execute(f"CREATE OR REPLACE TABLE bridge ({BRIDGE_DDL})")
        for _, gers_id, record_id, between in (row for row in BRIDGE if row[0] == part):
            connection.execute(
                "INSERT INTO bridge VALUES (?, 'OpenStreetMap', ?, ?, 'planet', ?, ?, NULL)",
                [
                    gers_id,
                    record_id,
                    None if record_id.startswith("r") else "2024-01-01T00:00:00Z",
                    OSM_SNAPSHOT,
                    between,
                ],
            )
        connection.table("bridge").write_parquet((folder / f"{part}.parquet").as_posix())


def _write_changelog(
    connection: duckdb.DuckDBPyConnection,
    bucket: Path,
    rows: Sequence[tuple[str, str, str, list[str]]],
) -> None:
    base = bucket / "changelog" / RELEASE / "theme=transportation"
    boxes = {seg.id: seg.bbox for seg in SEGMENTS} | {con[0]: con[2] for con in CONNECTORS}
    for feature_type, change_type in sorted({(row[0], row[1]) for row in rows}):
        folder = base / f"type={feature_type}" / f"change_type={change_type}"
        folder.mkdir(parents=True)
        connection.execute(f"CREATE OR REPLACE TABLE changes ({CHANGELOG_DDL})")
        for _, _, feature_id, columns_changed in (
            row for row in rows if row[0] == feature_type and row[1] == change_type
        ):
            connection.execute(
                "INSERT INTO changes VALUES (?, ?, ?)",
                [feature_id, _bbox(boxes.get(feature_id, INSIDE)), columns_changed],
            )
        connection.table("changes").write_parquet((folder / "part-0.parquet").as_posix())


def _write_catalog(stac: Path, schema_version: str) -> None:
    release_dir = stac / RELEASE
    release_dir.mkdir(parents=True)
    root = {
        "type": "Catalog",
        "latest": RELEASE,
        "links": [
            {"rel": "child", "href": (stac / OLDER_RELEASE / "catalog.json").as_posix()},
            {"rel": "child", "href": (release_dir / "catalog.json").as_posix()},
        ],
    }
    (stac / "catalog.json").write_text(json.dumps(root), encoding="utf-8")
    release = {"release:version": RELEASE, "schema:version": schema_version, "links": []}
    (release_dir / "catalog.json").write_text(json.dumps(release), encoding="utf-8")
    older = stac / OLDER_RELEASE
    older.mkdir()
    (older / "catalog.json").write_text(
        json.dumps({"release:version": OLDER_RELEASE, "schema:version": "1.18.0"}),
        encoding="utf-8",
    )


def _write_collection(
    folder: Path, items: Sequence[tuple[str, Path, tuple[float, float, float, float]]]
) -> None:
    folder.mkdir(parents=True)
    links = []
    for item_id, data_file, bbox in items:
        item_path = folder / f"{item_id}.json"
        item_path.write_text(
            json.dumps(
                {
                    "id": item_id,
                    "bbox": list(bbox),
                    "properties": {"num_rows": 1},
                    "assets": {
                        "aws": {"href": data_file.as_posix(), "file:size": data_file.stat().st_size}
                    },
                }
            ),
            encoding="utf-8",
        )
        links.append({"rel": "item", "href": item_path.as_posix()})
    (folder / "collection.json").write_text(json.dumps({"links": links}), encoding="utf-8")


def _insert(
    connection: duckdb.DuckDBPyConnection, table: str, columns: list[str], values: dict[str, Any]
) -> None:
    placeholders = ", ".join("?::GEOMETRY" if name == "geometry" else "?" for name in columns)
    connection.execute(
        f"INSERT INTO {table} VALUES ({placeholders})",  # noqa: S608 - fixed test table names
        [values.get(name) for name in columns],
    )


def _bbox(box: tuple[float, float, float, float]) -> dict[str, float]:
    return {"xmin": box[0], "xmax": box[2], "ymin": box[1], "ymax": box[3]}


def _line(box: tuple[float, float, float, float]) -> str:
    return f"LINESTRING ({box[0]} {box[1]}, {box[2]} {box[3]})"
