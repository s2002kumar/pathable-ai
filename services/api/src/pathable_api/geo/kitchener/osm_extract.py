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
extract's timestamp, however far it runs beyond the box — osmium's node location
index resolves every node it uses. (An earlier version resolved nodes only near
the box and silently dropped long ways that crossed its edge.) Output is one
gzipped JSON-lines file, sorted by type and id, written with a fixed gzip
timestamp, so the same source always produces the same bytes and the file's
hash identifies the frozen OSM side of every comparison. Live OSM data is never
substituted for it.
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
    progress: Progress | None = None,
) -> tuple[StudyExtract, dict[str, Any]]:
    """Read the pilot box out of the verified source extract. Two passes.

    The first reads only nodes that carry a fact key, filtered in C++. The
    second reads every way with a ``highway`` tag, with node locations filled
    in by osmium's location index, and keeps those with a node inside the box.
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

    def inside(lon: float, lat: float) -> bool:
        return bounds[0] <= lon <= bounds[2] and bounds[1] <= lat <= bounds[3]

    say(f"nodes: reading tagged nodes from {pbf.name}...")
    fact_nodes: dict[int, OsmNode] = {}
    for node in (
        osmium.FileProcessor(str(pbf), osmium.osm.NODE)
        .with_filter(osmium.filter.EntityFilter(osmium.osm.NODE))
        .with_filter(osmium.filter.KeyFilter(*sorted(NODE_FACT_KEYS)))
    ):
        location = node.location  # type: ignore[union-attr]
        lon, lat = float(location.lon), float(location.lat)
        if not inside(lon, lat):
            continue
        node_id = int(node.id)
        fact_nodes[node_id] = OsmNode(
            node_id,
            lon,
            lat,
            _version(node.version),  # type: ignore[union-attr]
            _timestamp(node.timestamp),  # type: ignore[union-attr]
            {tag.k: tag.v for tag in node.tags},
        )
    say(f"nodes: {len(fact_nodes)} carrying facts inside the box.")

    say("ways: reading highway ways with node locations...")
    extract = StudyExtract()
    coordinates: dict[int, tuple[float, float]] = {}
    unresolved = 0
    for way in (
        osmium.FileProcessor(str(pbf))
        .with_locations()
        .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
        .with_filter(osmium.filter.KeyFilter("highway"))
    ):
        refs: list[int] = []
        points: list[tuple[float, float]] = []
        complete = True
        for ref in way.nodes:  # type: ignore[union-attr]
            location = ref.location
            if not location.valid():
                complete = False
                break
            refs.append(int(ref.ref))
            points.append((float(location.lon), float(location.lat)))
        if len(points) < 2 or not any(inside(lon, lat) for lon, lat in points):
            continue
        if not complete:
            unresolved += 1
            continue
        extract.ways[int(way.id)] = OsmWay(
            int(way.id),
            _version(way.version),  # type: ignore[union-attr]
            _timestamp(way.timestamp),  # type: ignore[union-attr]
            {tag.k: tag.v for tag in way.tags},
            tuple(refs),
        )
        coordinates.update(zip(refs, points, strict=True))

    for node_id in sorted(set(coordinates) | set(fact_nodes)):
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
        "fact_nodes": len(fact_nodes),
        "ways": len(extract.ways),
        "ways_with_unresolved_nodes": unresolved,
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
