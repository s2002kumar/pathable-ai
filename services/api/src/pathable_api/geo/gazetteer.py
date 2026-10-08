"""A bounded place index for one pilot region, read from an OpenStreetMap extract.

Place search needs names and addresses, and the routing network holds neither:
it keeps walkable ways, so it knows "King Street North" but not the library on
it or the number on the door. Every name and address a person would type *is*
in the extract the network was built from, so this module reads that same file
a second time and keeps what search needs — and nothing is sent anywhere.

Three kinds of entry, kept apart because they rank differently:

* **places** — a named amenity, shop, park, campus building, station or square,
  from a node, a way or a multipolygon relation;
* **addresses** — a house number on a street, wherever a mapper recorded one;
* **streets** — a named way, one entry per connected stretch of it, so two
  unconnected streets that share a name stay two results.

Each entry is a single point a route can start from: the node itself, a point
guaranteed to lie inside a building or park, or the middle of a street. That
point is only ever a *search result*. It is snapped to the network by the
routing endpoint like any map click, and it never becomes a routing fact.

Read in three passes for the same reason :mod:`pathable_api.geo.pbf` reads in
two: keeping only the nodes near the region bounds memory by the size of the
region rather than the size of the province.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from itertools import pairwise
from pathlib import Path
from typing import Any

import osmium
from shapely import STRtree
from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.ops import polygonize, unary_union

from pathable_api.core.logging import get_logger
from pathable_api.geo.enums import PlaceKind
from pathable_api.geo.pbf import CLIP_MARGIN_DEGREES, EXCLUDED_HIGHWAYS, file_sha256
from pathable_api.geo.place_text import category_tier, normalise_text

logger = get_logger(__name__)

#: Bumped whenever extraction or normalisation changes what an extract becomes,
#: so a stored index says which rules produced it.
GAZETTEER_VERSION = 1

# --- What counts as a place -----------------------------------------------------

#: Keys whose named features are places somebody would search for, in the order
#: that decides what a feature is called when it carries several.
_PLACE_KEYS = (
    "amenity",
    "shop",
    "tourism",
    "leisure",
    "healthcare",
    "office",
    "craft",
    "historic",
    "public_transport",
    "railway",
    "place",
    "building",
)
_RAILWAY_PLACES = frozenset({"station", "halt", "tram_stop"})
#: A stop position is where a vehicle halts on the road; the platform beside it
#: is where a person waits, and it carries the same name.
_TRANSIT_PLACES = frozenset({"station", "platform"})
_TRANSIT_HIGHWAYS = frozenset({"bus_stop", "platform"})
_PATH_HIGHWAYS = frozenset({"footway", "path", "cycleway", "bridleway", "track", "corridor"})

#: Names a feature is also known by. Searched, never shown.
_ALTERNATIVE_NAME_KEYS = ("alt_name", "short_name", "official_name", "loc_name", "old_name")


def place_category(tags: Mapping[str, str]) -> str | None:
    """What a named feature is, in words, or None when it is not a place."""
    if tags.get("highway") in _TRANSIT_HIGHWAYS:
        return "transit stop"
    for key in _PLACE_KEYS:
        value = tags.get(key, "").strip().lower()
        if not value or value == "no":
            continue
        if key == "railway" and value not in _RAILWAY_PLACES:
            continue
        if key == "public_transport" and value not in _TRANSIT_PLACES:
            continue
        readable = value.replace("_", " ")
        if key == "building":
            return "building" if readable == "yes" else f"{readable} building"
        if key == "public_transport":
            return f"transit {readable}"
        return key if readable == "yes" else readable
    return None


def street_category(tags: Mapping[str, str]) -> str | None:
    """What a named way is, or None when it is not something to search for."""
    highway = tags.get("highway", "").strip().lower()
    if not highway or highway in EXCLUDED_HIGHWAYS or highway in _TRANSIT_HIGHWAYS:
        return None
    if highway == "steps":
        return None
    if highway in _PATH_HIGHWAYS:
        return "path"
    if highway == "pedestrian":
        return "pedestrian street"
    return "street"


def _name(tags: Mapping[str, str]) -> str | None:
    name = tags.get("name", "").strip()
    return name or None


def _search_text(primary: str, tags: Mapping[str, str]) -> str:
    """The primary text first, so prefix ranking favours it, then any other names."""
    parts = [primary]
    for key in _ALTERNATIVE_NAME_KEYS:
        parts.extend(value for value in tags.get(key, "").split(";") if value.strip())
    return normalise_text(" ".join(parts))


def _address(tags: Mapping[str, str]) -> tuple[str, str, str | None] | None:
    housenumber = tags.get("addr:housenumber", "").strip()
    street = tags.get("addr:street", "").strip()
    if not housenumber or not street:
        return None
    city = tags.get("addr:city", "").strip() or None
    return housenumber, street, city


def _is_candidate(tags: Mapping[str, str]) -> bool:
    name = _name(tags)
    if name is not None and place_category(tags) is not None:
        return True
    return _address(tags) is not None


# --- Entries --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlaceEntry:
    """One searchable point."""

    kind: PlaceKind
    label: str
    category: str | None
    #: :func:`normalise_text` of the label and any alternative names.
    search_text: str
    longitude: float
    latitude: float
    osm_type: str
    osm_id: int
    osm_version: int | None


def _entries_for(
    tags: Mapping[str, str],
    point: tuple[float, float],
    *,
    osm_type: str,
    osm_id: int,
    osm_version: int | None,
) -> list[PlaceEntry]:
    """The place and address entries one tagged element contributes."""
    entries: list[PlaceEntry] = []
    longitude, latitude = point
    address = _address(tags)

    name = _name(tags)
    category = place_category(tags) if name is not None else None
    if name is not None and category is not None:
        # A name alone is ambiguous across a city — there are many coffee shops
        # called the same thing — so a recorded address is shown beside it.
        label = name if address is None else f"{name}, {address[0]} {address[1]}"
        searched = name if address is None else f"{name} {address[0]} {address[1]}"
        entries.append(
            PlaceEntry(
                kind=PlaceKind.PLACE,
                label=label,
                category=category,
                search_text=_search_text(searched, tags),
                longitude=longitude,
                latitude=latitude,
                osm_type=osm_type,
                osm_id=osm_id,
                osm_version=osm_version,
            )
        )

    # A named place already carries its address in its label and its search text.
    # A second, nameless entry for the same door would only repeat it — on a
    # campus where every building shares one address, five times over.
    if address is not None and not entries:
        housenumber, street, city = address
        label = f"{housenumber} {street}" + (f", {city}" if city else "")
        entries.append(
            PlaceEntry(
                kind=PlaceKind.ADDRESS,
                label=label,
                category="address",
                search_text=normalise_text(label),
                longitude=longitude,
                latitude=latitude,
                osm_type=osm_type,
                osm_id=osm_id,
                osm_version=osm_version,
            )
        )
    return entries


def _inside(point: tuple[float, float], bounds: tuple[float, float, float, float]) -> bool:
    longitude, latitude = point
    min_lon, min_lat, max_lon, max_lat = bounds
    return min_lon <= longitude <= max_lon and min_lat <= latitude <= max_lat


def _positive(osm_version: int) -> int | None:
    return osm_version if osm_version > 0 else None


def _tags(element: Any) -> dict[str, str]:
    return {tag.k: tag.v for tag in element.tags}


# --- Geometry -------------------------------------------------------------------


def way_point(coordinates: list[tuple[float, float]]) -> tuple[float, float] | None:
    """A point that belongs to the way: inside it when closed, halfway along otherwise."""
    if len(coordinates) < 2:
        return None
    if len(coordinates) >= 4 and coordinates[0] == coordinates[-1]:
        outline = Polygon(coordinates)
        # A self-touching outline still encloses somewhere a person can go.
        area = outline if outline.is_valid else outline.buffer(0)
        if not area.is_empty and area.area > 0:
            point = area.representative_point()
            return (point.x, point.y)
    line = LineString(coordinates)
    if line.length == 0:
        return None
    middle = line.interpolate(0.5, normalized=True)
    return (middle.x, middle.y)


def relation_point(rings: Iterable[list[tuple[float, float]]]) -> tuple[float, float] | None:
    """A point inside a multipolygon assembled from its outer member ways."""
    lines = [LineString(ring) for ring in rings if len(ring) >= 2]
    polygons = list(polygonize(lines))
    if not polygons:
        return None
    area = unary_union(polygons)
    if area.is_empty:
        return None
    point = area.representative_point()
    return (point.x, point.y)


def _planar_length(coordinates: list[tuple[float, float]]) -> float:
    """Length in degrees with longitude scaled for latitude — enough to compare ways."""
    if len(coordinates) < 2:
        return 0.0
    scale = math.cos(math.radians(coordinates[0][1]))
    return sum(
        math.hypot((x2 - x1) * scale, y2 - y1) for (x1, y1), (x2, y2) in pairwise(coordinates)
    )


# --- Streets --------------------------------------------------------------------


@dataclass(slots=True)
class _StreetWay:
    way_id: int
    osm_version: int | None
    tags: dict[str, str]
    refs: list[int]
    coordinates: list[tuple[float, float]]


def _components(ways: list[_StreetWay]) -> list[list[_StreetWay]]:
    """Group ways that share a node: one stretch of street per group."""
    parent = list(range(len(ways)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    first_way_at: dict[int, int] = {}
    for index, way in enumerate(ways):
        for ref in way.refs:
            other = first_way_at.setdefault(ref, index)
            if other != index:
                parent[find(index)] = find(other)

    groups: dict[int, list[_StreetWay]] = defaultdict(list)
    for index, way in enumerate(ways):
        groups[find(index)].append(way)
    return list(groups.values())


#: Same-named ways closer than this are one street. OpenStreetMap often names a
#: sidewalk or a cycle track after the road beside it and maps it as its own line,
#: sharing no node with the road; grouped by shared nodes alone, one street became
#: a dozen results. About 65 m at this latitude — a sidewalk's distance from its
#: road, and far less than the gap between two different streets of one name.
_SAME_STREET_DEGREES = 0.0006


def _stretches(ways: list[_StreetWay]) -> list[list[_StreetWay]]:
    """Connected groups of a name, joined again where they run alongside each other."""
    components = _components(ways)
    if len(components) < 2:
        return components
    # Longitude scaled for latitude, so the distance threshold means the same
    # thing east-west as north-south.
    scale = math.cos(math.radians(components[0][0].coordinates[0][1]))
    shapes = [
        MultiLineString([[(x * scale, y) for x, y in way.coordinates] for way in component])
        for component in components
    ]
    parent = list(range(len(components)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    pairs = STRtree(shapes).query(shapes, predicate="dwithin", distance=_SAME_STREET_DEGREES)
    for left, right in zip(pairs[0].tolist(), pairs[1].tolist(), strict=True):
        parent[find(left)] = find(right)

    groups: dict[int, list[_StreetWay]] = defaultdict(list)
    for index, component in enumerate(components):
        groups[find(index)].extend(component)
    return list(groups.values())


def _representative(
    stretch: list[_StreetWay], bounds: tuple[float, float, float, float]
) -> tuple[_StreetWay, tuple[float, float]] | None:
    """The way a street's point goes on: a road before a path, the longest first.

    Only a way whose midpoint lies inside the region qualifies. A street that
    runs out of town, as King Street North does, otherwise put its point on the
    long rural stretch beyond the boundary and vanished from the index.
    """
    ordered = sorted(
        stretch,
        key=lambda way: (street_category(way.tags) == "path", -_planar_length(way.coordinates)),
    )
    for way in ordered:
        point = way_point(way.coordinates)
        if point is not None and _inside(point, bounds):
            return way, point
    return None


#: How far around a stretch of street an address may be and still say which city
#: the street is in. About 300 m at this latitude.
_CITY_SEARCH_DEGREES = 0.003


def _street_entries(
    streets: Mapping[str, list[_StreetWay]],
    cities_by_street: Mapping[str, list[tuple[float, float, str]]],
    bounds: tuple[float, float, float, float],
) -> list[PlaceEntry]:
    entries: list[PlaceEntry] = []
    for key, ways in streets.items():
        for stretch in _stretches(ways):
            chosen = _representative(stretch, bounds)
            if chosen is None:
                continue
            way, point = chosen
            name = _name(way.tags) or key
            label = name
            # Two stretches of "Queen Street" read identically in a list; the city
            # the neighbouring addresses give is what tells them apart.
            city = _city_near(stretch, cities_by_street.get(key, ()))
            if city is not None:
                label = f"{name}, {city}"
            entries.append(
                PlaceEntry(
                    kind=PlaceKind.STREET,
                    label=label,
                    category=street_category(way.tags),
                    search_text=_search_text(label, way.tags),
                    longitude=point[0],
                    latitude=point[1],
                    osm_type="way",
                    osm_id=way.way_id,
                    osm_version=way.osm_version,
                )
            )
    return entries


def _city_near(
    component: list[_StreetWay], addresses: Iterable[tuple[float, float, str]]
) -> str | None:
    coordinates = [point for way in component for point in way.coordinates]
    min_lon = min(x for x, _ in coordinates) - _CITY_SEARCH_DEGREES
    max_lon = max(x for x, _ in coordinates) + _CITY_SEARCH_DEGREES
    min_lat = min(y for _, y in coordinates) - _CITY_SEARCH_DEGREES
    max_lat = max(y for _, y in coordinates) + _CITY_SEARCH_DEGREES
    counts = Counter(
        city
        for longitude, latitude, city in addresses
        if min_lon <= longitude <= max_lon and min_lat <= latitude <= max_lat
    )
    if not counts:
        return None
    return counts.most_common(1)[0][0]


# --- Reading --------------------------------------------------------------------


@dataclass(slots=True)
class _Pending:
    """Ways and relations read, waiting for geometry from a later pass."""

    relations: dict[int, tuple[dict[str, str], list[int], int | None]] = field(default_factory=dict)
    member_rings: dict[int, list[tuple[float, float]]] = field(default_factory=dict)
    streets: dict[str, list[_StreetWay]] = field(default_factory=lambda: defaultdict(list))
    #: Where each street's addresses are, and which city they say they are in.
    cities_by_street: dict[str, list[tuple[float, float, str]]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def record(
        self,
        tags: Mapping[str, str],
        point: tuple[float, float],
        *,
        osm_type: str,
        osm_id: int,
        osm_version: int | None,
    ) -> list[PlaceEntry]:
        """The entries one element contributes, noting its address's city on the way."""
        address = _address(tags)
        if address is not None and address[2] is not None:
            longitude, latitude = point
            self.cities_by_street[normalise_text(address[1])].append(
                (longitude, latitude, address[2])
            )
        return _entries_for(tags, point, osm_type=osm_type, osm_id=osm_id, osm_version=osm_version)


def read_places(
    path: Path,
    bounds: tuple[float, float, float, float],
    *,
    margin_degrees: float = CLIP_MARGIN_DEGREES,
) -> list[PlaceEntry]:
    """Every searchable place, address and street inside ``bounds``.

    **Relations, then nodes, then ways.** A multipolygon's shape is spread across
    member ways that carry no tags of their own, so the relations are read first
    to learn which ways to keep. Nodes are kept only near the region, as in the
    network import. Each entry's point must fall inside ``bounds``; the margin
    only lets a building that straddles the edge resolve its outline.
    """
    min_lon, min_lat, max_lon, max_lat = bounds
    keep = (
        min_lon - margin_degrees,
        min_lat - margin_degrees,
        max_lon + margin_degrees,
        max_lat + margin_degrees,
    )
    pending = _Pending()
    entries: list[PlaceEntry] = []

    # --- Pass 1: named multipolygons -------------------------------------------
    for relation in osmium.FileProcessor(str(path), osmium.osm.RELATION):
        tags = _tags(relation)
        if tags.get("type") != "multipolygon" or not _is_candidate(tags):
            continue
        outer = [
            int(member.ref)
            for member in relation.members  # type: ignore[union-attr]
            if member.type == "w" and member.role in {"outer", ""}
        ]
        if outer:
            pending.relations[int(relation.id)] = (
                tags,
                outer,
                _positive(int(relation.version)),  # type: ignore[union-attr]
            )
    member_ways = {ref for _, refs, _ in pending.relations.values() for ref in refs}

    # --- Pass 2: nodes near the region ------------------------------------------
    coordinates: dict[int, tuple[float, float]] = {}
    for node in osmium.FileProcessor(str(path), osmium.osm.NODE):
        location = node.location  # type: ignore[union-attr]
        point = (float(location.lon), float(location.lat))
        if not _inside(point, keep):
            continue
        coordinates[int(node.id)] = point
        if not node.tags or not _inside(point, bounds):
            continue
        tags = _tags(node)
        if _is_candidate(tags):
            entries.extend(
                pending.record(
                    tags,
                    point,
                    osm_type="node",
                    osm_id=int(node.id),
                    osm_version=_positive(int(node.version)),  # type: ignore[union-attr]
                )
            )
    logger.info("Read nodes near the region", extra={"nodes": len(coordinates)})

    # --- Pass 3: ways ---------------------------------------------------------------
    for way in osmium.FileProcessor(str(path), osmium.osm.WAY):
        way_id = int(way.id)
        is_member = way_id in member_ways
        if not way.tags and not is_member:
            continue
        refs = [int(node.ref) for node in way.nodes]  # type: ignore[union-attr]
        resolved = [coordinates[ref] for ref in refs if ref in coordinates]
        if len(resolved) < 2:
            continue
        complete = len(resolved) == len(refs)
        if is_member and complete:
            pending.member_rings[way_id] = resolved

        tags = _tags(way)
        osm_version = _positive(int(way.version))  # type: ignore[union-attr]
        name = _name(tags)
        if _is_candidate(tags):
            # An outline missing a corner would put its "inside" point anywhere.
            at = way_point(resolved) if complete else None
            if at is not None and _inside(at, bounds):
                entries.extend(
                    pending.record(tags, at, osm_type="way", osm_id=way_id, osm_version=osm_version)
                )
        elif name is not None and street_category(tags) is not None:
            pending.streets[normalise_text(name)].append(
                _StreetWay(way_id, osm_version, tags, refs, resolved)
            )

    # --- Relations, now their members have shape ----------------------------------
    for relation_id, (tags, outer, osm_version) in pending.relations.items():
        # Only the outer ways read in full. A place can span cities — the
        # University of Waterloo's campus relation also holds its Cambridge and
        # Stratford sites — and requiring every ring dropped the campus from the
        # index. A ring cut by the reading margin is still left out: it no longer
        # closes, so it contributes no area rather than a guessed one.
        rings = [pending.member_rings[ref] for ref in outer if ref in pending.member_rings]
        if not rings:
            continue
        at = relation_point(rings)
        if at is not None and _inside(at, bounds):
            entries.extend(
                pending.record(
                    tags, at, osm_type="relation", osm_id=relation_id, osm_version=osm_version
                )
            )

    entries.extend(_street_entries(pending.streets, pending.cities_by_street, bounds))

    deduplicated = deduplicate(entries)
    logger.info(
        "Read places from extract",
        extra={"entries": len(deduplicated), "before_deduplication": len(entries)},
    )
    return deduplicated


#: Two entries of the same kind and text closer than roughly this are one place
#: mapped twice — a shop as a node inside a building way of the same name.
_DUPLICATE_CELL_DEGREES = 0.002


def deduplicate(entries: Iterable[PlaceEntry]) -> list[PlaceEntry]:
    """Drop repeats, keeping the one somebody is more likely to be going to.

    Ties keep the first, which is a node — read first, and usually the more
    specific of a shop and the building around it. But a node is not always the
    better of two: the University of Waterloo's information board shares the
    campus's name and lands in the same cell as the campus's own point, and
    keeping the first dropped the campus from the index. The lower
    :func:`~pathable_api.geo.place_text.category_tier` wins.
    """
    position: dict[tuple[PlaceKind, str, int, int], int] = {}
    kept: list[PlaceEntry] = []
    for entry in entries:
        key = (
            entry.kind,
            entry.search_text,
            round(entry.longitude / _DUPLICATE_CELL_DEGREES),
            round(entry.latitude / _DUPLICATE_CELL_DEGREES),
        )
        index = position.get(key)
        if index is None:
            position[key] = len(kept)
            kept.append(entry)
        elif category_tier(entry.category) < category_tier(kept[index].category):
            kept[index] = entry
    return kept


# --- Provenance -----------------------------------------------------------------


def extract_timestamp(path: Path) -> dt.datetime | None:
    """The time the extract's data is current to, from its own header, if it says.

    Geofabrik writes ``osmosis_replication_timestamp`` into every extract. A file
    without it has an unknown date, and that is what gets recorded — never the
    time it was downloaded or read.
    """
    reader = osmium.io.Reader(str(path), osmium.osm.NOTHING)
    try:
        value = reader.header().get("osmosis_replication_timestamp")
    finally:
        reader.close()
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)


def _osmium_version() -> str:
    try:
        return version("osmium")
    except PackageNotFoundError:  # pragma: no cover - packaging accident only
        return "unknown"


@dataclass(frozen=True, slots=True)
class GazetteerImport:
    entries: list[PlaceEntry]
    file_name: str
    file_sha256: str
    #: When the OSM data is current to. None when the extract does not say.
    source_timestamp: dt.datetime | None
    configuration: dict[str, Any]

    def count(self, kind: PlaceKind) -> int:
        return sum(1 for entry in self.entries if entry.kind is kind)


def import_gazetteer(
    path: Path,
    bounds: tuple[float, float, float, float],
    *,
    region_slug: str,
    provider: str = "unknown",
    source_timestamp: dt.datetime | None = None,
) -> GazetteerImport:
    """Read an extract into a place index for one region, with its provenance."""
    from_header = extract_timestamp(path)
    timestamp = source_timestamp or from_header
    timestamp_source = (
        "argument" if source_timestamp is not None else "pbf-header" if from_header else None
    )
    entries = read_places(path, bounds)
    return GazetteerImport(
        entries=entries,
        file_name=path.name,
        file_sha256=file_sha256(path),
        source_timestamp=timestamp,
        configuration={
            "source": "openstreetmap",
            "provider": provider,
            "acquisition": "local-pbf-extract",
            "reader": f"osmium {_osmium_version()}",
            "gazetteer_version": GAZETTEER_VERSION,
            "region": region_slug,
            "bbox": list(bounds),
            "source_timestamp_from": timestamp_source,
            "attribution": "© OpenStreetMap contributors, ODbL 1.0",
        },
    )
