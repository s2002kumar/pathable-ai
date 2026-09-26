"""Candidate OpenStreetMap ways for a Kitchener record, and the signals that describe them.

This is deliberately permissive: every ``highway`` way within
:data:`CANDIDATE_RADIUS_M` of the record is a candidate, whatever its kind. The
point is to put the right answer *and* the plausible wrong ones in front of a
reviewer, so the labels can later show which signals separate them. Nothing
here decides a match, the display order is only an order, and none of the
distances below is a threshold for matching.

All geometry is in the Kitchener source's native NAD83 / UTM zone 17N metres.
OSM coordinates are converted with the same PROJ path the audit used: a null
datum shift, whose stated accuracy is 4 m.

Signals, per record and candidate:

- **closest approach** — 0 for a line that merely touches;
- **worst point** — the record sampled every metre, the largest distance to
  the candidate (a directed Hausdorff distance), with the mean and median;
- **overlap** — the share of the record's samples within 2 m and 5 m of the
  candidate, and the reverse: the share of the candidate within 5 m of the record;
- **orientation** — the median angle between the two where they are near, 0 to 90°;
- **endpoints** — how far each end of the record is from the candidate;
- **class** — whether the OSM tags describe the same kind of facility;
- **road** — which road each is beside, and on which side; whether each
  crosses it;
- **vertices** — whether the candidate's vertices sit on the record's own
  vertices with one common displacement, which tracing two sources
  independently rarely produces. It is a lineage question, not a match signal.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import pyproj
import shapely
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from pathable_api.geo.kitchener.osm_extract import OsmNode, StudyExtract
from pathable_api.geo.kitchener.source import NATIVE_WKID

CANDIDATE_RADIUS_M = 25.0
SAMPLE_SPACING_M = 1.0
#: How near a candidate must be for its local direction to be compared.
ORIENTATION_NEAR_M = 10.0
#: How far to look for the road a record is beside.
ROAD_SEARCH_M = 40.0
#: A point this close to a road centreline has no meaningful side.
SIDE_DEAD_BAND_M = 1.0
#: How near a tagged kerb, crossing or barrier node must be to be listed.
NODE_NEAR_M = 8.0
#: A Kitchener record lies "along" an OSM way when this share of it is within this distance.
ALONG_DISTANCE_M = 3.0
ALONG_SHARE = 0.5
#: Two Kitchener records "touch" when their ends are this close.
ENDPOINT_TOUCH_M = 1.0
#: For the vertex comparison: OSM vertices this near the record, paired with a
#: Kitchener vertex this near them.
VERTEX_STRETCH_M = 3.0
VERTEX_PAIR_M = 2.0

ROAD_HIGHWAYS = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "unclassified",
        "residential",
        "living_street",
    }
)
PATH_HIGHWAYS = frozenset(
    {"footway", "path", "pedestrian", "cycleway", "bridleway", "track", "corridor"}
)
#: OSM tags a reviewer needs to see on a road, beyond its class and name.
ROAD_SIDEWALK_KEYS = ("sidewalk", "sidewalk:both", "sidewalk:left", "sidewalk:right")


class CoordinateTransform(Protocol):
    """What the indexes need from a transformer: pyproj's, or a test's identity."""

    def transform(self, xx: Any, yy: Any) -> Any: ...


def to_native() -> pyproj.Transformer:
    return pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{NATIVE_WKID}", always_xy=True)


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------


def osm_class(tags: Mapping[str, str]) -> str:
    """What kind of facility an OSM way's tags describe, in the study's terms."""
    highway = tags.get("highway")
    if highway == "steps":
        return "steps"
    kinds = {tags.get(key) for key in ("footway", "path", "cycleway")}
    if "sidewalk" in kinds:
        return "sidewalk"
    if "crossing" in kinds or (highway in PATH_HIGHWAYS and "crossing" in tags):
        return "crossing"
    if highway in PATH_HIGHWAYS:
        return "path"
    if highway in ROAD_HIGHWAYS:
        return "road"
    if highway == "service":
        return "service"
    return "other"


def kitchener_family(subcategory: str | None, feature_type: str | None, role: str) -> str:
    """What kind of facility a Kitchener record describes, in the same terms."""
    if feature_type == "STAIRS":
        return "stairs"
    if role == "virtual_link":
        return "virtual_link"
    if role == "unofficial_connection":
        return "connection"
    if role == "unresolved":
        return "unresolved"
    if subcategory in ("SIDEWALK", "CONTINUOUS SIDEWALK"):
        return "sidewalk"
    if subcategory == "WALKWAY":
        return "walkway"
    if subcategory in ("MUT", "BMUT", "MAJOR TRAIL", "MINOR TRAIL"):
        return "trail"
    if role in ("pedestrian_crossing", "cycling_or_shared_crossing"):
        return "crossing"
    if role == "cycling_facility":
        return "cycling"
    if role == "maintenance_access":
        return "maintenance"
    return "other"


#: Kitchener family → OSM class → how the two descriptions relate. Anything
#: missing is ``different``. ``different_representation`` means OSM may carry
#: the same facility another way — a sidewalk as a tag on its road, say.
_COMPATIBLE: dict[str, dict[str, str]] = {
    "sidewalk": {"sidewalk": "same", "path": "plausible", "road": "different_representation"},
    "walkway": {"path": "same", "sidewalk": "plausible", "steps": "plausible"},
    "trail": {"path": "same", "sidewalk": "plausible", "service": "plausible"},
    "crossing": {"crossing": "same", "path": "plausible", "road": "different_representation"},
    "virtual_link": {
        "crossing": "plausible",
        "path": "plausible",
        "road": "different_representation",
    },
    "stairs": {"steps": "same", "path": "plausible"},
    "connection": {"service": "plausible", "path": "plausible", "road": "plausible"},
    "cycling": {"road": "same", "path": "plausible", "sidewalk": "plausible"},
    "maintenance": {"path": "plausible", "service": "plausible"},
    "unresolved": {"path": "plausible", "sidewalk": "plausible", "crossing": "plausible"},
}


def class_compatibility(family: str, osm: str) -> str:
    return _COMPATIBLE.get(family, {}).get(osm, "different")


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def parts(geometry: BaseGeometry) -> list[LineString]:
    """The line parts of a record, in order; empty parts dropped."""
    if isinstance(geometry, LineString):
        return [geometry] if not geometry.is_empty else []
    if isinstance(geometry, MultiLineString):
        return [part for part in geometry.geoms if not part.is_empty]
    return []


def ends(geometry: BaseGeometry) -> list[Point]:
    """Both ends of every part."""
    points: list[Point] = []
    for part in parts(geometry):
        points.extend((Point(part.coords[0]), Point(part.coords[-1])))
    return points


def _samples(line: BaseGeometry, spacing: float = SAMPLE_SPACING_M) -> np.ndarray[Any, Any]:
    return np.asarray(shapely.get_coordinates(shapely.segmentize(line, spacing)))


def _bearing(a: Sequence[float], b: Sequence[float]) -> float | None:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0 and dy == 0:
        return None
    return math.degrees(math.atan2(dy, dx))


def line_angle(first: float, second: float) -> float:
    """The angle between two undirected lines, 0 to 90°."""
    difference = abs(first - second) % 180.0
    return min(difference, 180.0 - difference)


def local_bearing(line: LineString, along: float, span: float = 1.0) -> float | None:
    start = line.interpolate(max(along - span, 0.0))
    end = line.interpolate(min(along + span, line.length))
    return _bearing((start.x, start.y), (end.x, end.y))


@dataclass(frozen=True, slots=True)
class PairMetrics:
    """Descriptive distances between one record and one candidate. Not a score."""

    min_distance_m: float
    max_offset_m: float
    mean_offset_m: float
    median_offset_m: float
    overlap_2m: float
    overlap_5m: float
    osm_share_within_5m: float
    orientation_deg: float | None
    end_distances_m: tuple[float, ...]
    nearest_endpoint_pair_m: float
    bbox_intersects: bool
    record_length_m: float
    osm_length_m: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "min_distance_m": round(self.min_distance_m, 2),
            "max_offset_m": round(self.max_offset_m, 2),
            "mean_offset_m": round(self.mean_offset_m, 2),
            "median_offset_m": round(self.median_offset_m, 2),
            "overlap_2m": round(self.overlap_2m, 3),
            "overlap_5m": round(self.overlap_5m, 3),
            "osm_share_within_5m": round(self.osm_share_within_5m, 3),
            "orientation_deg": self.orientation_deg,
            "end_distances_m": [round(value, 2) for value in self.end_distances_m],
            "nearest_endpoint_pair_m": round(self.nearest_endpoint_pair_m, 2),
            "bbox_intersects": self.bbox_intersects,
            "record_length_m": round(self.record_length_m, 2),
            "osm_length_m": round(self.osm_length_m, 2),
        }


def pair_metrics(record: BaseGeometry, osm: LineString) -> PairMetrics:
    """The descriptive distances between a record and one candidate way."""
    samples = shapely.points(_samples(record))
    distances = np.asarray(shapely.distance(samples, osm), dtype=float)
    reverse = np.asarray(shapely.distance(shapely.points(_samples(osm)), record), dtype=float)

    angles: list[float] = []
    for part in parts(record):
        for x, y in _samples(part):
            point = Point(x, y)
            if point.distance(osm) > ORIENTATION_NEAR_M:
                continue
            record_bearing = local_bearing(part, part.project(point))
            osm_bearing = local_bearing(osm, osm.project(point))
            if record_bearing is not None and osm_bearing is not None:
                angles.append(line_angle(record_bearing, osm_bearing))
    osm_ends = (Point(osm.coords[0]), Point(osm.coords[-1]))
    record_ends = ends(record)
    return PairMetrics(
        min_distance_m=float(record.distance(osm)),
        max_offset_m=float(distances.max()),
        mean_offset_m=float(distances.mean()),
        median_offset_m=float(np.median(distances)),
        overlap_2m=float((distances <= 2.0).mean()),
        overlap_5m=float((distances <= 5.0).mean()),
        osm_share_within_5m=float((reverse <= 5.0).mean()),
        orientation_deg=round(float(np.median(angles)), 1) if angles else None,
        end_distances_m=tuple(float(end.distance(osm)) for end in record_ends),
        nearest_endpoint_pair_m=float(min(p.distance(q) for p in record_ends for q in osm_ends)),
        bbox_intersects=bool(shapely.box(*record.bounds).intersects(shapely.box(*osm.bounds))),
        record_length_m=float(record.length),
        osm_length_m=float(osm.length),
    )


@dataclass(frozen=True, slots=True)
class VertexAgreement:
    """Whether a candidate's vertices sit on the record's vertices with one displacement."""

    osm_vertices_near: int
    paired: int
    median_displacement_m: float | None
    displacement_spread_m: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "osm_vertices_within_3m": self.osm_vertices_near,
            "paired_with_kitchener_vertex_within_2m": self.paired,
            "median_displacement_m": _round(self.median_displacement_m, 2),
            "displacement_spread_m": _round(self.displacement_spread_m, 2),
        }


def vertex_agreement(record: BaseGeometry, osm: LineString) -> VertexAgreement:
    """Pair each OSM vertex near the record with the nearest Kitchener vertex.

    The spread is the median distance of each pair's displacement vector from
    the median vector, so a common shift — a different datum transformation on
    import, say — does not hide shared vertices.
    """
    kitchener = np.asarray(shapely.get_coordinates(record))
    near = [(x, y) for x, y in osm.coords if Point(x, y).distance(record) <= VERTEX_STRETCH_M]
    vectors: list[tuple[float, float]] = []
    for x, y in near:
        offsets = kitchener - np.array([x, y])
        lengths = np.hypot(offsets[:, 0], offsets[:, 1])
        index = int(np.argmin(lengths))
        if lengths[index] <= VERTEX_PAIR_M:
            vectors.append((float(offsets[index, 0]), float(offsets[index, 1])))
    if not vectors:
        return VertexAgreement(len(near), 0, None, None)
    array = np.asarray(vectors)
    median = np.median(array, axis=0)
    spread = float(np.median(np.hypot(*(array - median).T)))
    return VertexAgreement(len(near), len(vectors), float(np.median(np.hypot(*array.T))), spread)


def side_of(line: LineString, point: Point) -> int:
    """+1 left of the line's direction, -1 right, 0 within the dead band."""
    along = line.project(point)
    foot = line.interpolate(along)
    if foot.distance(point) < SIDE_DEAD_BAND_M:
        return 0
    bearing = local_bearing(line, along)
    if bearing is None:
        return 0
    heading = math.radians(bearing)
    cross = math.cos(heading) * (point.y - foot.y) - math.sin(heading) * (point.x - foot.x)
    return 1 if cross > 0 else -1


def _round(value: float | None, digits: int) -> float | None:
    return round(value, digits) if value is not None else None


# ---------------------------------------------------------------------------
# Street names
# ---------------------------------------------------------------------------

_ABBREVIATIONS = {
    "ST": "STREET",
    "AVE": "AVENUE",
    "AV": "AVENUE",
    "RD": "ROAD",
    "DR": "DRIVE",
    "CRES": "CRESCENT",
    "CRT": "COURT",
    "CT": "COURT",
    "BLVD": "BOULEVARD",
    "PL": "PLACE",
    "TERR": "TERRACE",
    "TER": "TERRACE",
    "PKWY": "PARKWAY",
    "HWY": "HIGHWAY",
    "LN": "LANE",
    "CIR": "CIRCLE",
    "SQ": "SQUARE",
    "GT": "GATE",
    "TRL": "TRAIL",
    "W": "WEST",
    "E": "EAST",
    "N": "NORTH",
    "S": "SOUTH",
}


def street_tokens(name: str | None) -> frozenset[str]:
    if not name:
        return frozenset()
    words = re.findall(r"[A-Z0-9']+", name.upper())
    return frozenset(_ABBREVIATIONS.get(word, word) for word in words)


def same_street(kitchener: str | None, osm: str | None) -> bool | None:
    """Whether two names name the same street; ``None`` when either is missing."""
    first, second = street_tokens(kitchener), street_tokens(osm)
    if not first or not second:
        return None
    return first == second


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------


def way_geometries(
    extract: StudyExtract, transformer: CoordinateTransform
) -> dict[int, LineString]:
    lines: dict[int, LineString] = {}
    for way_id, way in extract.ways.items():
        lons = [extract.nodes[ref].lon for ref in way.refs]
        lats = [extract.nodes[ref].lat for ref in way.refs]
        xs, ys = transformer.transform(lons, lats)
        lines[way_id] = LineString(list(zip(xs, ys, strict=True)))
    return lines


def node_points(nodes: Iterable[OsmNode], transformer: CoordinateTransform) -> dict[int, Point]:
    items = list(nodes)
    if not items:
        return {}
    xs, ys = transformer.transform([n.lon for n in items], [n.lat for n in items])
    return {node.id: Point(x, y) for node, x, y in zip(items, xs, ys, strict=True)}


@dataclass(slots=True)
class OsmIndex:
    """The frozen OSM side, projected and indexed once."""

    extract: StudyExtract
    lines: dict[int, LineString]
    way_ids: list[int]
    tree: shapely.STRtree
    road_ids: list[int]
    road_tree: shapely.STRtree
    fact_points: dict[int, Point]
    fact_ids: list[int]
    fact_tree: shapely.STRtree
    #: node id → the ways that use it.
    node_ways: dict[int, list[int]]

    @classmethod
    def build(cls, extract: StudyExtract, transformer: CoordinateTransform) -> OsmIndex:
        lines = way_geometries(extract, transformer)
        way_ids = sorted(lines)
        roads = [w for w in way_ids if extract.ways[w].tags.get("highway") in ROAD_HIGHWAYS]
        fact_points = node_points((n for n in extract.nodes.values() if n.tags), transformer)
        fact_ids = sorted(fact_points)
        node_ways: dict[int, list[int]] = {}
        for way_id in way_ids:
            for ref in dict.fromkeys(extract.ways[way_id].refs):
                node_ways.setdefault(ref, []).append(way_id)
        return cls(
            extract=extract,
            lines=lines,
            way_ids=way_ids,
            tree=shapely.STRtree([lines[w] for w in way_ids]),
            road_ids=roads,
            road_tree=shapely.STRtree([lines[w] for w in roads]),
            fact_points=fact_points,
            fact_ids=fact_ids,
            fact_tree=shapely.STRtree([fact_points[n] for n in fact_ids]),
            node_ways=node_ways,
        )


@dataclass(frozen=True, slots=True)
class KitchenerFeature:
    activetransportid: int
    physical_class: str
    network_role: str
    subcategory: str | None
    geometry: BaseGeometry


@dataclass(slots=True)
class KitchenerIndex:
    """Every Kitchener record with a geometry, for neighbours and N:1 questions."""

    features: dict[int, KitchenerFeature]
    ids: list[int]
    tree: shapely.STRtree

    @classmethod
    def build(cls, features: Iterable[KitchenerFeature]) -> KitchenerIndex:
        by_id = {f.activetransportid: f for f in features}
        ids = sorted(by_id)
        return cls(by_id, ids, shapely.STRtree([by_id[i].geometry for i in ids]))

    def near(self, geometry: BaseGeometry, distance: float) -> list[int]:
        hits = self.tree.query(geometry, predicate="dwithin", distance=distance)
        return sorted(self.ids[int(hit)] for hit in hits)


# ---------------------------------------------------------------------------
# Road context
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoadContext:
    """The OSM road a record is beside, as the record's midpoint sees it."""

    osm_id: int | None
    name: str | None
    highway: str | None
    sidewalk_tags: dict[str, str]
    distance_m: float | None
    record_side: int
    street_matches: bool | None
    record_crosses_road: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "osm": f"way/{self.osm_id}" if self.osm_id is not None else None,
            "name": self.name,
            "highway": self.highway,
            "sidewalk_tags": self.sidewalk_tags,
            "distance_m": _round(self.distance_m, 2),
            "record_side": self.record_side,
            "street_matches_kitchener_street": self.street_matches,
            "record_crosses_road": self.record_crosses_road,
        }


def _midpoint(geometry: BaseGeometry) -> Point:
    longest = max(parts(geometry), key=lambda part: part.length)
    return longest.interpolate(0.5, normalized=True)


def nearest_road(point: Point, index: OsmIndex) -> int | None:
    hits = index.road_tree.query(point, predicate="dwithin", distance=ROAD_SEARCH_M)
    if len(hits) == 0:
        return None
    road_ids = [index.road_ids[int(hit)] for hit in hits]
    return min(road_ids, key=lambda way: (index.lines[way].distance(point), way))


def road_context(record: BaseGeometry, street: str | None, index: OsmIndex) -> RoadContext:
    midpoint = _midpoint(record)
    road_id = nearest_road(midpoint, index)
    if road_id is None:
        return RoadContext(None, None, None, {}, None, 0, None, False)
    road = index.lines[road_id]
    tags = index.extract.ways[road_id].tags
    return RoadContext(
        osm_id=road_id,
        name=tags.get("name"),
        highway=tags.get("highway"),
        sidewalk_tags={key: tags[key] for key in ROAD_SIDEWALK_KEYS if key in tags},
        distance_m=float(road.distance(midpoint)),
        record_side=side_of(road, midpoint),
        street_matches=same_street(street, tags.get("name")),
        record_crosses_road=bool(record.crosses(road)),
    )


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Candidate:
    osm_id: int
    osm_class: str
    compatibility: str
    reasons: tuple[str, ...]
    metrics: PairMetrics
    vertices: VertexAgreement
    #: The candidate's own nearest road, and whether it is the record's.
    nearest_road: int | None
    same_road_as_record: bool | None
    same_side_as_record: bool | None
    crosses_record_road: bool | None
    is_record_road: bool
    #: Kitchener records at least half of which lie within 3 m of this way.
    kitchener_records_along: tuple[int, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "osm": f"way/{self.osm_id}",
            "osm_class": self.osm_class,
            "class_compatibility": self.compatibility,
            "reasons": list(self.reasons),
            "metrics": self.metrics.as_dict(),
            "vertices": self.vertices.as_dict(),
            "nearest_road": f"way/{self.nearest_road}" if self.nearest_road is not None else None,
            "same_road_as_record": self.same_road_as_record,
            "same_side_as_record": self.same_side_as_record,
            "crosses_record_road": self.crosses_record_road,
            "is_record_road": self.is_record_road,
            "kitchener_records_along": list(self.kitchener_records_along),
        }


def candidates_for(
    record: BaseGeometry,
    family: str,
    road: RoadContext,
    index: OsmIndex,
    kitchener: KitchenerIndex,
) -> list[Candidate]:
    """Every way within :data:`CANDIDATE_RADIUS_M`, in display order."""
    hits = index.tree.query(record, predicate="dwithin", distance=CANDIDATE_RADIUS_M)
    road_line = index.lines[road.osm_id] if road.osm_id is not None else None
    roads = set(index.road_ids)
    found: list[Candidate] = []
    for osm_id in sorted(index.way_ids[int(hit)] for hit in hits):
        line = index.lines[osm_id]
        tags = index.extract.ways[osm_id].tags
        metrics = pair_metrics(record, line)
        klass = osm_class(tags)
        compatibility = class_compatibility(family, klass)
        near_point = nearest_points(line, record)[0]
        own_road = osm_id if osm_id in roads else nearest_road(near_point, index)
        is_road = osm_id == road.osm_id
        same_road: bool | None = None
        same_side: bool | None = None
        crosses: bool | None = None
        if road_line is not None and not is_road:
            same_road = own_road == road.osm_id
            candidate_side = side_of(road_line, near_point)
            if road.record_side != 0 and candidate_side != 0:
                same_side = candidate_side == road.record_side
            crosses = bool(line.crosses(road_line))
        reasons = [f"within_{CANDIDATE_RADIUS_M:g}m"]
        if metrics.overlap_5m >= 0.5:
            reasons.append("half_of_record_within_5m")
        if metrics.nearest_endpoint_pair_m <= 5.0:
            reasons.append("endpoint_within_5m")
        if compatibility != "different":
            reasons.append(f"class_{compatibility}")
        if same_side:
            reasons.append("same_side_of_road")
        if crosses and road.record_crosses_road:
            reasons.append("crosses_same_road")
        found.append(
            Candidate(
                osm_id=osm_id,
                osm_class=klass,
                compatibility=compatibility,
                reasons=tuple(reasons),
                metrics=metrics,
                vertices=vertex_agreement(record, line),
                nearest_road=own_road,
                same_road_as_record=same_road,
                same_side_as_record=same_side,
                crosses_record_road=crosses,
                is_record_road=is_road,
                kitchener_records_along=records_along(line, kitchener),
            )
        )
    found.sort(
        key=lambda c: (
            -round(c.metrics.overlap_5m, 3),
            round(c.metrics.max_offset_m, 2),
            round(c.metrics.min_distance_m, 2),
            c.osm_id,
        )
    )
    return found


def records_along(osm: LineString, kitchener: KitchenerIndex) -> tuple[int, ...]:
    """Kitchener records at least half of which lie within 3 m of an OSM way."""
    along: list[int] = []
    for record_id in kitchener.near(osm, ALONG_DISTANCE_M):
        samples = shapely.points(_samples(kitchener.features[record_id].geometry))
        share = float((np.asarray(shapely.distance(samples, osm)) <= ALONG_DISTANCE_M).mean())
        if share >= ALONG_SHARE:
            along.append(record_id)
    return tuple(along)


def nodes_near(record: BaseGeometry, index: OsmIndex) -> list[dict[str, Any]]:
    """Tagged kerb, crossing and barrier nodes near a record, nearest first."""
    hits = index.fact_tree.query(record, predicate="dwithin", distance=NODE_NEAR_M)
    items = []
    for hit in hits:
        node_id = index.fact_ids[int(hit)]
        node = index.extract.nodes[node_id]
        items.append(
            {
                "osm": f"node/{node_id}",
                "distance_m": round(float(index.fact_points[node_id].distance(record)), 2),
                "osm_version": node.version,
                "osm_timestamp": node.timestamp,
                "osm_tags": dict(sorted(node.tags.items())),
                "on_ways": [f"way/{w}" for w in index.node_ways.get(node_id, [])],
            }
        )
    items.sort(key=lambda item: (item["distance_m"], item["osm"]))
    return items


def kitchener_end_neighbours(
    record_id: int, record: BaseGeometry, kitchener: KitchenerIndex
) -> list[list[int]]:
    """For each end of each part, the other Kitchener records that touch it."""
    return [
        [other for other in kitchener.near(end, ENDPOINT_TOUCH_M) if other != record_id]
        for end in ends(record)
    ]


def osm_end_junctions(way_id: int, index: OsmIndex) -> list[dict[str, Any]]:
    """For each end of an OSM way, the other highway ways that share its end node."""
    way = index.extract.ways[way_id]
    result = []
    for ref in (way.refs[0], way.refs[-1]):
        others = [w for w in index.node_ways.get(ref, []) if w != way_id]
        result.append(
            {
                "node": f"node/{ref}",
                "ways": [f"way/{w}" for w in others],
                "classes": sorted({osm_class(index.extract.ways[w].tags) for w in others}),
            }
        )
    return result
