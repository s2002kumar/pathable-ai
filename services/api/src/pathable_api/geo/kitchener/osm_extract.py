"""The OpenStreetMap side of the lineage study, frozen from PathAble's own source extract.

The comparison is against the map PathAble routes on, not against today's OSM.
PathAble's live dataset records the SHA-256 of the extract it was built from, so
the study reads that same file — refused unless the hash matches — and keeps:

- every way with a ``highway`` tag that touches the pilot box, roads as well as
  paths, because the road beside a sidewalk decides which side it is on;
- every node those ways use, for their geometry;
- the tagged nodes inside the box that carry kerb and crossing facts, with their
  OSM version and edit time.

Nothing is simplified or clipped: a way is kept whole, exactly as mapped at the
extract's timestamp. Output is one gzipped JSON-lines file, sorted by type and
id, written with a fixed gzip timestamp, so the same source always produces the
same bytes and the file's hash identifies the frozen OSM side of every
comparison. Live OSM data is never substituted for it.
"""

from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import osmium

from pathable_api.geo.overture.evidence import file_sha256

EXTRACT_FORMAT_VERSION = 1

#: Node keys whose tags carry a kerb, crossing or barrier fact worth keeping.
NODE_FACT_KEYS = frozenset(
    {
        "kerb",
        "barrier",
        "highway",
        "crossing",
        "crossing:markings",
        "tactile_paving",
        "traffic_signals",
        "railway",
    }
)

#: Degrees of margin read around the box, so ways that dip out and back resolve.
READ_MARGIN_DEGREES = 0.005

Progress = Callable[[str], None]
Bounds = tuple[float, float, float, float]


class ExtractSourceError(RuntimeError):
    """The file offered as PathAble's source extract is not the one it was built from."""


@dataclass(frozen=True, slots=True)
class OsmNode:
    id: int
    lon: float
    lat: float
    version: int | None
    timestamp: str | None
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OsmWay:
    id: int
    version: int | None
    timestamp: str | None
    tags: dict[str, str]
    refs: tuple[int, ...]


@dataclass(slots=True)
class StudyExtract:
    nodes: dict[int, OsmNode] = field(default_factory=dict)
    ways: dict[int, OsmWay] = field(default_factory=dict)


def read_study_extract(
    pbf: Path,
    *,
    expected_sha256: str,
    bounds: Bounds,
    margin_degrees: float = READ_MARGIN_DEGREES,
    progress: Progress | None = None,
) -> tuple[StudyExtract, dict[str, Any]]:
    """Read the pilot box out of the verified source extract. Two passes.

    Nodes first, then ways, for the reason :func:`pathable_api.geo.pbf.read_pbf`
    gives: reading ways first holds every node reference in the province.
    """
    say = progress or (lambda _message: None)
    started = time.perf_counter()
    actual = file_sha256(pbf)
    if actual != expected_sha256:
        msg = (
            f"{pbf.name} hashes to {actual}, not {expected_sha256} recorded for the dataset; "
            "a different extract would describe a different map."
        )
        raise ExtractSourceError(msg)

    min_lon, min_lat, max_lon, max_lat = bounds
    say(f"nodes: reading {pbf.name}...")
    coordinates: dict[int, tuple[float, float]] = {}
    fact_nodes: dict[int, OsmNode] = {}
    for node in osmium.FileProcessor(str(pbf)).with_filter(
        osmium.filter.EntityFilter(osmium.osm.NODE)
    ):
        location = node.location  # type: ignore[union-attr]
        lon = float(location.lon)
        lat = float(location.lat)
        if not (min_lon - margin_degrees <= lon <= max_lon + margin_degrees):
            continue
        if not (min_lat - margin_degrees <= lat <= max_lat + margin_degrees):
            continue
        node_id = int(node.id)
        coordinates[node_id] = (lon, lat)
        if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
            continue
        tags = {tag.k: tag.v for tag in node.tags}
        if NODE_FACT_KEYS.intersection(tags):
            fact_nodes[node_id] = OsmNode(
                node_id,
                lon,
                lat,
                _version(node.version),  # type: ignore[union-attr]
                _timestamp(node.timestamp),  # type: ignore[union-attr]
                tags,
            )
    inside = {
        node_id
        for node_id, (lon, lat) in coordinates.items()
        if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat
    }
    say(f"nodes: {len(coordinates)} near the box, {len(fact_nodes)} carrying facts.")

    say("ways: reading highway ways...")
    extract = StudyExtract()
    for way in (
        osmium.FileProcessor(str(pbf))
        .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
        .with_filter(osmium.filter.KeyFilter("highway"))
    ):
        refs = tuple(int(node.ref) for node in way.nodes)  # type: ignore[union-attr]
        if len(refs) < 2 or not any(ref in inside for ref in refs):
            continue
        if not all(ref in coordinates for ref in refs):
            continue
        extract.ways[int(way.id)] = OsmWay(
            int(way.id),
            _version(way.version),  # type: ignore[union-attr]
            _timestamp(way.timestamp),  # type: ignore[union-attr]
            {tag.k: tag.v for tag in way.tags},
            refs,
        )

    referenced = {ref for way in extract.ways.values() for ref in way.refs}
    for node_id in sorted(referenced | set(fact_nodes)):
        known = fact_nodes.get(node_id)
        if known is not None:
            extract.nodes[node_id] = known
            continue
        lon, lat = coordinates[node_id]
        extract.nodes[node_id] = OsmNode(node_id, lon, lat, None, None, {})
    say(f"ways: {len(extract.ways)} kept; {len(extract.nodes)} nodes kept.")
    facts = {
        "source_file": pbf.name,
        "source_sha256": actual,
        "bounds": list(bounds),
        "read_margin_degrees": margin_degrees,
        "nodes_near_box": len(coordinates),
        "fact_nodes": len(fact_nodes),
        "ways": len(extract.ways),
        "nodes": len(extract.nodes),
        "seconds": round(time.perf_counter() - started, 2),
    }
    return extract, facts


def _version(value: int) -> int | None:
    version = int(value)
    return version if version > 0 else None


def _timestamp(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    moment = value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
    if moment.timestamp() <= 0:
        return None
    return moment.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lines(extract: StudyExtract) -> Iterator[str]:
    for node_id in sorted(extract.nodes):
        node = extract.nodes[node_id]
        yield _canonical(
            {
                "type": "node",
                "id": node.id,
                "lon": node.lon,
                "lat": node.lat,
                "version": node.version,
                "timestamp": node.timestamp,
                "tags": node.tags,
            }
        )
    for way_id in sorted(extract.ways):
        way = extract.ways[way_id]
        yield _canonical(
            {
                "type": "way",
                "id": way.id,
                "version": way.version,
                "timestamp": way.timestamp,
                "tags": way.tags,
                "refs": list(way.refs),
            }
        )


def _canonical(document: dict[str, Any]) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def write_study_extract(extract: StudyExtract, path: Path) -> str:
    """Write the extract deterministically; returns the file's SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    # mtime=0 and no file name in the header: identical content, identical bytes.
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as handle:
        for line in _lines(extract):
            handle.write(line.encode("utf-8"))
            handle.write(b"\n")
    path.write_bytes(buffer.getvalue())
    return file_sha256(path)


def load_study_extract(path: Path, *, expected_sha256: str | None = None) -> StudyExtract:
    if expected_sha256 is not None and file_sha256(path) != expected_sha256:
        msg = f"{path} does not match its recorded SHA-256."
        raise ExtractSourceError(msg)
    extract = StudyExtract()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            if item["type"] == "node":
                extract.nodes[int(item["id"])] = OsmNode(
                    int(item["id"]),
                    float(item["lon"]),
                    float(item["lat"]),
                    item["version"],
                    item["timestamp"],
                    dict(item["tags"]),
                )
            else:
                extract.ways[int(item["id"])] = OsmWay(
                    int(item["id"]),
                    item["version"],
                    item["timestamp"],
                    dict(item["tags"]),
                    tuple(int(ref) for ref in item["refs"]),
                )
    return extract


__all__ = [
    "EXTRACT_FORMAT_VERSION",
    "ExtractSourceError",
    "OsmNode",
    "OsmWay",
    "StudyExtract",
    "load_study_extract",
    "read_study_extract",
    "write_study_extract",
]
