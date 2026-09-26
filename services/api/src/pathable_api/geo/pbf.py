"""Import a pedestrian network from a local OpenStreetMap PBF extract.

Overpass is the convenient path and a fragile one: it is a donated service with
strict rate limits, and an import that depends on it can simply stop working —
as it did here for over an hour when repeated diagnostic requests earned a
block. A pre-built extract from Geofabrik or BBBike is the channel intended for
bulk data, needs no live service, and can be re-read as often as we like.

Both paths must produce the *same interpretation of the same facts*. So this
module's only job is to get OSM ways and nodes out of a file; every accessibility
decision is made by :mod:`pathable_api.geo.features`,
:mod:`pathable_api.geo.directionality` and :mod:`pathable_api.geo.node_evidence`,
exactly as it is for an Overpass import. A parity test routes the same area from
both sources and requires identical normalised attributes.

**Provenance.** An extract carries every element's version and the time that
version was saved, and they are recorded with the dataset: for each node, its
own; for each segment, its way's, plus the latest edit across the way and every
node it references. A way keeps its version when one of its nodes moves, so
"same way, same version" does not mean "same shape" — the latest member edit is
what tells the two apart. An Overpass import has neither and records neither.

Reader choice: ``osmium`` (pyosmium). It is BSD-2, ships Python 3.13 wheels for
Windows and Linux, depends on neither numpy nor pandas — so it cannot conflict
with the geospatial stack — and exposes node tags, which most alternatives do
not. `pyrosm` was the obvious candidate and is currently uninstallable on
Windows: it requires `cykhash`, which publishes no wheels at all.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from itertools import pairwise
from pathlib import Path
from typing import Any

import osmium
from shapely.geometry import LineString, Point

from pathable_api.core.logging import get_logger
from pathable_api.geo.directionality import normalise_foot_direction
from pathable_api.geo.features import normalise_edge
from pathable_api.geo.network import NetworkEdge, NetworkNode, NetworkPayload, OsmEdit
from pathable_api.geo.node_evidence import apply_to_crossing, read_node_evidence

logger = get_logger(__name__)

#: `highway` values a pedestrian may use. Deliberately generous: excluding a way
#: type removes real connections, and access tags plus the cost model are the
#: right place to decide whether a person should actually walk there.
WALKABLE_HIGHWAYS: frozenset[str] = frozenset(
    {
        "footway",
        "path",
        "pedestrian",
        "steps",
        "corridor",
        "living_street",
        "residential",
        "unclassified",
        "service",
        "track",
        "tertiary",
        "tertiary_link",
        "secondary",
        "secondary_link",
        "primary",
        "primary_link",
        "road",
        "crossing",
        "elevator",
        "platform",
        "cycleway",
    }
)

#: Way types nobody walks on, whatever else they are tagged.
EXCLUDED_HIGHWAYS: frozenset[str] = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "construction",
        "proposed",
        "abandoned",
        "razed",
        "raceway",
        "bus_guideway",
    }
)

#: Node tags worth keeping. A node carrying none of these is pure geometry.
INFORMATIVE_NODE_TAGS: frozenset[str] = frozenset(
    {
        "barrier",
        "kerb",
        "crossing",
        "crossing:markings",
        "highway",
        "tactile_paving",
        "wheelchair",
        "traffic_signals",
        "ramp",
    }
)


@dataclass(frozen=True, slots=True)
class PbfImport:
    payload: NetworkPayload
    configuration: dict[str, Any]
    retrieved_at: dt.datetime
    #: Content hash of the source file, so a dataset can be traced to the exact
    #: bytes it came from rather than to a filename somebody may have replaced.
    file_sha256: str
    file_bytes: int


@dataclass(slots=True)
class _Collected:
    """Raw OSM content for the requested area, before interpretation."""

    node_coordinates: dict[int, tuple[float, float]] = field(default_factory=dict)
    node_tags: dict[int, dict[str, str]] = field(default_factory=dict)
    ways: list[tuple[int, dict[str, str], list[int]]] = field(default_factory=list)
    #: (version, edit time as UNIX seconds or None) per node read. Integers
    #: rather than datetimes: this holds every node near the region until the
    #: unreferenced ones are dropped.
    node_edits: dict[int, tuple[int, int | None]] = field(default_factory=dict)
    way_edits: dict[int, tuple[int, int | None]] = field(default_factory=dict)


def _epoch(timestamp: dt.datetime | None) -> int | None:
    """An edit time as UNIX seconds, or None where the file carries none.

    Extracts written without metadata report the epoch itself; that is an
    absence, not a date.
    """
    if timestamp is None:
        return None
    seconds = int(timestamp.timestamp())
    return seconds if seconds > 0 else None


def _instant(seconds: int | None) -> dt.datetime | None:
    return None if seconds is None else dt.datetime.fromtimestamp(seconds, tz=dt.UTC)


def _positive(version: int) -> int | None:
    # Version 0 is what osmium reports when the file carries no versions.
    return version if version > 0 else None


def _osmium_version() -> str:
    try:
        return version("osmium")
    except PackageNotFoundError:  # pragma: no cover - packaging accident only
        return "unknown"


def file_sha256(path: Path, *, chunk_bytes: int = 1 << 20) -> str:
    """Content hash of a downloaded extract.

    Provenance means being able to say *which bytes* produced a dataset. A
    filename cannot say that: extracts are republished under the same name every
    day.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


#: How far outside the requested region to keep nodes, in degrees. A way that
#: leaves the region and comes back needs its outside nodes, or it arrives with
#: a hole in it. ~2 km at this latitude.
CLIP_MARGIN_DEGREES = 0.02


def read_pbf(
    path: Path,
    bounds: tuple[float, float, float, float],
    *,
    margin_degrees: float = CLIP_MARGIN_DEGREES,
) -> _Collected:
    """Pull walkable ways and their nodes out of an extract, within ``bounds``.

    **Nodes first, then ways.** The obvious order — ways, then the nodes they
    reference — reads a province-sized extract into memory: every walkable way in
    Ontario contributes its node references before anything is clipped, which
    measured at 2.4 GB and climbing. Reading nodes first and keeping only those
    near the region bounds the memory by the size of the region instead of the
    size of the file.

    A margin is kept around the region so a way that dips outside and comes back
    still resolves rather than arriving with a hole in it. The margin is a
    *reading* device only: :func:`collected_to_payload` emits no segment that
    leaves the declared region, so the dataset stays inside the bounds it claims.
    """
    min_lon, min_lat, max_lon, max_lat = bounds
    keep_min_lon = min_lon - margin_degrees
    keep_max_lon = max_lon + margin_degrees
    keep_min_lat = min_lat - margin_degrees
    keep_max_lat = max_lat + margin_degrees

    collected = _Collected()

    # --- Pass 1: node coordinates near the region -------------------------
    node_reader = osmium.FileProcessor(str(path)).with_filter(
        osmium.filter.EntityFilter(osmium.osm.NODE)
    )
    for node in node_reader:
        location = node.location  # type: ignore[union-attr]
        longitude = float(location.lon)
        latitude = float(location.lat)
        if not (keep_min_lon <= longitude <= keep_max_lon):
            continue
        if not (keep_min_lat <= latitude <= keep_max_lat):
            continue

        node_id = int(node.id)
        collected.node_coordinates[node_id] = (longitude, latitude)
        version = _positive(int(node.version))  # type: ignore[union-attr]
        if version is not None:
            collected.node_edits[node_id] = (version, _epoch(node.timestamp))  # type: ignore[union-attr]
        tags = {tag.k: tag.v for tag in node.tags}
        if tags and INFORMATIVE_NODE_TAGS.intersection(tags):
            collected.node_tags[node_id] = tags

    logger.info(
        "Read nodes near the region",
        extra={"path": str(path), "nodes": len(collected.node_coordinates)},
    )

    # --- Pass 2: walkable ways whose geometry we can actually build --------
    inside = {
        node_id
        for node_id, (longitude, latitude) in collected.node_coordinates.items()
        if min_lon <= longitude <= max_lon and min_lat <= latitude <= max_lat
    }

    way_reader = (
        osmium.FileProcessor(str(path))
        .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
        .with_filter(osmium.filter.KeyFilter("highway"))
    )
    for way in way_reader:
        tags = {tag.k: tag.v for tag in way.tags}
        if not _is_walkable(tags):
            continue
        refs = [int(node.ref) for node in way.nodes]  # type: ignore[union-attr]
        if len(refs) < 2:
            continue
        # Touching the region is enough to keep it; every reference must resolve
        # or the geometry would have a gap in it.
        if not any(ref in inside for ref in refs):
            continue
        collected.ways.append((int(way.id), tags, refs))
        version = _positive(int(way.version))  # type: ignore[union-attr]
        if version is not None:
            collected.way_edits[int(way.id)] = (version, _epoch(way.timestamp))  # type: ignore[union-attr]

    # Drop coordinates nothing referenced, so the payload does not carry the
    # whole margin as isolated nodes.
    referenced = {ref for _, _, refs in collected.ways for ref in refs}
    collected.node_coordinates = {
        node_id: position
        for node_id, position in collected.node_coordinates.items()
        if node_id in referenced
    }
    collected.node_tags = {
        node_id: tags for node_id, tags in collected.node_tags.items() if node_id in referenced
    }
    collected.node_edits = {
        node_id: edit for node_id, edit in collected.node_edits.items() if node_id in referenced
    }

    logger.info(
        "Read walkable ways from extract",
        extra={
            "path": str(path),
            "ways": len(collected.ways),
            "nodes": len(collected.node_coordinates),
        },
    )
    return collected


def _osm_edit(edit: tuple[int, int | None] | None) -> OsmEdit | None:
    if edit is None:
        return None
    version, seconds = edit
    return OsmEdit(version=version, edited_at=_instant(seconds))


def latest_member_edit(
    way_edit: tuple[int, int | None] | None,
    refs: list[int],
    node_edits: Mapping[int, tuple[int, int | None]],
) -> dt.datetime | None:
    """The latest edit across a way and every node it references.

    Unknown — None — as soon as any one of them is: a node outside the area that
    was read, or an element whose edit time the file does not carry. A maximum
    over the ones that could be read would look like evidence and be a guess.
    """
    if way_edit is None or way_edit[1] is None:
        return None
    latest = way_edit[1]
    for ref in refs:
        node_edit = node_edits.get(ref)
        if node_edit is None or node_edit[1] is None:
            return None
        latest = max(latest, node_edit[1])
    return _instant(latest)


def _is_walkable(tags: dict[str, str]) -> bool:
    highway = tags.get("highway", "").strip().lower()
    if highway in EXCLUDED_HIGHWAYS:
        return False
    if highway not in WALKABLE_HIGHWAYS:
        return False
    # An area is a polygon, not a line to walk along.
    return tags.get("area", "").lower() != "yes"


def collected_to_payload(
    collected: _Collected,
    bounds: tuple[float, float, float, float] | None = None,
) -> NetworkPayload:
    """Interpret raw OSM content with exactly the rules an Overpass import uses.

    Each way becomes one segment per consecutive node pair. That is the
    unsimplified shape — every geometry vertex is a junction — which keeps every
    accessibility transition and every kerb node exactly where the mapper put it.

    Per-segment emission is what makes clipping honest: a way that crosses the
    region boundary contributes the segments inside it and nothing else, so the
    dataset never extends past the bounds it declares. Cutting whole ways instead
    would either drop a path that merely grazes the edge or smuggle kilometres of
    out-of-region geometry in behind it.
    """

    def within(position: tuple[float, float] | None) -> bool:
        if position is None:
            return False
        if bounds is None:
            return True
        longitude, latitude = position
        min_lon, min_lat, max_lon, max_lat = bounds
        return min_lon <= longitude <= max_lon and min_lat <= latitude <= max_lat

    evidence = {
        str(node_id): read_node_evidence(dict(tags))
        for node_id, tags in collected.node_tags.items()
    }
    evidence = {key: value for key, value in evidence.items() if value.is_informative}

    used_nodes: set[int] = set()
    edges: list[NetworkEdge] = []

    for way_id, tags, refs in collected.ways:
        features_base = normalise_edge(dict(tags))
        direction = normalise_foot_direction(dict(tags))
        way_edit = collected.way_edits.get(way_id)
        way_osm = _osm_edit(way_edit)
        way_latest = latest_member_edit(way_edit, refs, collected.node_edits)

        for index, (start_ref, end_ref) in enumerate(pairwise(refs)):
            if start_ref == end_ref:
                continue
            start = collected.node_coordinates.get(start_ref)
            end = collected.node_coordinates.get(end_ref)
            if start is None or end is None or start == end:
                continue
            if not (within(start) and within(end)):
                continue

            used_nodes.add(start_ref)
            used_nodes.add(end_ref)

            features = apply_to_crossing(
                features_base,
                evidence.get(str(start_ref)),
                evidence.get(str(end_ref)),
            )
            edges.append(
                NetworkEdge(
                    source_u=str(start_ref),
                    source_v=str(end_ref),
                    # Distinguishes the rare case of one way visiting the same
                    # node pair twice.
                    edge_key=index,
                    geometry=LineString([start, end]),
                    features=features,
                    source_way_id=str(way_id),
                    direction=direction,
                    osm_way=way_osm,
                    osm_way_latest_edit_at=way_latest,
                )
            )

    nodes = [
        NetworkNode(
            source_node_id=str(node_id),
            geometry=Point(*collected.node_coordinates[node_id]),
            raw_tags=dict(collected.node_tags.get(node_id, {})),
            osm=_osm_edit(collected.node_edits.get(node_id)),
        )
        for node_id in sorted(used_nodes)
    ]
    return NetworkPayload(nodes=nodes, edges=edges)


def import_from_pbf(
    path: Path,
    bounds: tuple[float, float, float, float],
    *,
    region_slug: str,
    provider: str = "unknown",
    source_timestamp: dt.datetime | None = None,
) -> PbfImport:
    """Read a local extract into the same payload an Overpass import produces."""
    retrieved_at = dt.datetime.now(tz=dt.UTC)
    digest = file_sha256(path)
    size = path.stat().st_size

    collected = read_pbf(path, bounds)
    payload = collected_to_payload(collected, bounds)
    provenance = describe_provenance(payload)

    logger.info(
        "PBF network imported",
        extra={
            "region": region_slug,
            "node_count": payload.node_count,
            "edge_count": payload.edge_count,
            "file_sha256": digest[:16],
        },
    )

    return PbfImport(
        payload=payload,
        configuration={
            "source": "openstreetmap",
            "provider": provider,
            "acquisition": "local-pbf-extract",
            "reader": f"osmium {_osmium_version()}",
            "file_name": path.name,
            "file_sha256": digest,
            "file_bytes": size,
            "region": region_slug,
            "bbox": list(bounds),
            "walkable_highways": sorted(WALKABLE_HIGHWAYS),
            "excluded_highways": sorted(EXCLUDED_HIGHWAYS),
            "simplify": False,
            "attribution": "© OpenStreetMap contributors, ODbL 1.0",
            "osm_provenance": provenance,
        },
        retrieved_at=retrieved_at,
        file_sha256=digest,
        file_bytes=size,
    )


def describe_provenance(payload: NetworkPayload) -> dict[str, Any]:
    """How much of the dataset carries OSM edit provenance, counted."""
    nodes_with = sum(1 for node in payload.nodes if node.osm is not None)
    edges_with = sum(1 for edge in payload.edges if edge.osm_way is not None)
    edges_latest = sum(1 for edge in payload.edges if edge.osm_way_latest_edit_at is not None)
    return {
        "captured": True,
        "method": "element version and edit time read from the extract at ingestion",
        "nodes": payload.node_count,
        "nodes_with_version": nodes_with,
        "edges": payload.edge_count,
        "edges_with_way_version": edges_with,
        "edges_with_way_latest_edit": edges_latest,
    }
