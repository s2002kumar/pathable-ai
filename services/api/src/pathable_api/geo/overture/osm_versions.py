"""OSM element versions recovered from the exact extract a dataset was built from.

PathAble does not store OSM versions, so on its own it can only ever say "the
same way id". But a dataset built from a local extract records that file's
SHA-256, and an OSM ``(id, version)`` pair never changes once published. If the
file on disk still hashes to the recorded value, the versions it contains are
the versions PathAble ingested — evidence, not inference.

If the hash does not match, the file is refused outright. A different extract
of the same area would supply plausible versions that describe some other
moment, which is worse than supplying none.

**A way's version is not the whole story.** Moving one of a way's nodes changes
the way's shape without changing the way's version. So for every way this also
records the latest edit time across the way *and all of its nodes*. On the
Waterloo data (2026-09-25), Overture's ``update_time`` for an OSM way equalled
exactly that value for 38,200 of 38,226 same-version ways; the other 26 were
later than anything in PathAble's snapshot — nodes moved after PathAble read
the map. That comparison is how a same-version match that has nevertheless
changed shape is told apart from one that has not.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import osmium

from pathable_api.geo.overture.evidence import file_sha256


class VersionEvidenceError(RuntimeError):
    """The extract cannot stand as evidence for this dataset."""


@dataclass(frozen=True, slots=True)
class ElementState:
    version: int
    #: When this version was saved, UTC, as OSM records it.
    timestamp: str | None
    #: The latest save across the element and, for a way, every node it uses.
    #: ``None`` when any of those could not be read.
    latest_member_timestamp: str | None = None


@dataclass(slots=True)
class VersionEvidence:
    file_name: str
    file_sha256: str
    ways: dict[int, ElementState] = field(default_factory=dict)
    nodes: dict[int, ElementState] = field(default_factory=dict)
    ways_requested: int = 0
    nodes_requested: int = 0
    member_nodes_read: int = 0
    seconds: float = 0.0

    def describe(self) -> dict[str, Any]:
        return {
            "method": "OSM element versions read from the dataset's own source extract, "
            "after its SHA-256 matched the value recorded at ingestion",
            "file_name": self.file_name,
            "file_sha256": self.file_sha256,
            "ways_requested": self.ways_requested,
            "ways_found": len(self.ways),
            "nodes_requested": self.nodes_requested,
            "nodes_found": len(self.nodes),
            "member_nodes_read_for_way_edit_times": self.member_nodes_read,
        }


def read_versions(
    path: Path,
    *,
    expected_sha256: str | None,
    way_ids: Collection[int],
    node_ids: Collection[int],
) -> VersionEvidence:
    """Read version and edit times for the requested ways and nodes."""
    if expected_sha256 is None:
        msg = (
            "The dataset recorded no source-file hash, so no extract can be shown to be "
            "the one it was built from."
        )
        raise VersionEvidenceError(msg)
    if not path.is_file():
        msg = f"{path} does not exist."
        raise VersionEvidenceError(msg)
    actual = file_sha256(path)
    if actual != expected_sha256:
        msg = (
            f"{path.name} hashes to {actual}, but the dataset was built from "
            f"{expected_sha256}. Refusing to read versions from a different extract."
        )
        raise VersionEvidenceError(msg)

    started = time.perf_counter()
    ways, members = _read_ways(path, way_ids)
    member_nodes = {ref for refs in members.values() for ref in refs}
    nodes = _read_nodes(path, set(node_ids) | member_nodes)

    evidence = VersionEvidence(
        file_name=path.name,
        file_sha256=actual,
        ways_requested=len(way_ids),
        nodes_requested=len(node_ids),
        member_nodes_read=len(member_nodes),
    )
    for way_id, (version, timestamp) in ways.items():
        times = [timestamp] + [
            nodes[ref].timestamp if ref in nodes else None for ref in members[way_id]
        ]
        evidence.ways[way_id] = ElementState(
            version=version,
            timestamp=timestamp,
            latest_member_timestamp=None if None in times else max(t for t in times if t),
        )
    wanted = set(node_ids)
    evidence.nodes = {node_id: state for node_id, state in nodes.items() if node_id in wanted}
    evidence.seconds = time.perf_counter() - started
    return evidence


def _read_ways(
    path: Path, ids: Collection[int]
) -> tuple[dict[int, tuple[int, str | None]], dict[int, list[int]]]:
    ways: dict[int, tuple[int, str | None]] = {}
    members: dict[int, list[int]] = {}
    if not ids:
        return ways, members
    # Both filters run in libosmium's C++ layer, so the millions of elements that
    # are not asked for never become Python objects.
    reader = (
        osmium.FileProcessor(str(path))
        .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
        .with_filter(osmium.filter.IdFilter(ids))
    )
    for way in reader:
        if not isinstance(way, osmium.osm.Way):
            continue
        ways[int(way.id)] = (int(way.version), _iso(way.timestamp))
        members[int(way.id)] = [int(node.ref) for node in way.nodes]
    return ways, members


def _read_nodes(path: Path, ids: Collection[int]) -> dict[int, ElementState]:
    nodes: dict[int, ElementState] = {}
    if not ids:
        return nodes
    reader = (
        osmium.FileProcessor(str(path))
        .with_filter(osmium.filter.EntityFilter(osmium.osm.NODE))
        .with_filter(osmium.filter.IdFilter(ids))
    )
    for node in reader:
        if not isinstance(node, osmium.osm.Node):
            continue
        stamp = _iso(node.timestamp)
        nodes[int(node.id)] = ElementState(int(node.version), stamp, stamp)
    return nodes


def _iso(timestamp: dt.datetime | None) -> str | None:
    """OSM's own UTC second-resolution form — the one Overture's ``update_time`` uses."""
    if timestamp is None or timestamp.year <= 1970:
        return None
    return timestamp.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
