"""Route computation.

Dijkstra over the in-memory graph, with the cost model deciding what each
segment is worth. There is one engine, not two: the "standard" route is the same
algorithm run with a profile whose penalties are all zero, so the two routes in a
comparison can never diverge because of an implementation difference rather than
a preference difference.

Search is bounded. An unbounded shortest-path query over a city-scale graph is a
denial-of-service primitive, so both the geographic span of a request and the
number of edges the search may evaluate are capped.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass

from shapely.geometry import LineString, Point

from pathable_api.core.logging import get_logger
from pathable_api.geo.enums import KerbType, SmoothnessClass, SurfaceClass, TriState
from pathable_api.geo.geometry import geodesic_distance_m
from pathable_api.routing.cost import BlockReason, CostComponent, EdgeCost, evaluate_edge
from pathable_api.routing.graph import DirectedEdge, RoutableEdge, RoutableGraph, SnappedPoint
from pathable_api.routing.profiles import MobilityProfile
from pathable_api.routing.search import (
    Algorithm,
    NoPathError,
    SearchLimitError,
    SearchResult,
    search,
)
from pathable_api.routing.snapping import EdgeSnap, prorate, split_geometry, virtual_node_id

logger = get_logger(__name__)

#: Farthest apart an origin and destination may be, as the crow flies. Waterloo's
#: pilot extent is about 12 km across; anything beyond this is not a walking
#: journey and is almost certainly a mistake or an attempt to make the server work.
MAX_REQUEST_SPAN_M = 15_000.0

#: How far a requested coordinate may be from the nearest mapped path before we
#: refuse rather than silently starting the route somewhere else.
#:
#: Lower than it used to need to be. Snapping now finds the nearest point *along*
#: a segment rather than the nearest junction, so a genuine doorstep is metres
#: away, and a large distance now means the request really is off-network.
MAX_SNAP_DISTANCE_M = 150.0

#: Ceiling on edge evaluations per search. Reached only by pathological requests;
#: a normal cross-Waterloo route evaluates a small fraction of this.
MAX_EDGE_EVALUATIONS = 750_000

#: Metres per second, by profile. Rough averages for planning, not measurements
#: of any individual — which is why the API calls the result an estimate.
_WALKING_SPEED_MPS: Mapping[str, float] = {
    "standard": 1.35,
    "wheelchair": 0.95,
    "walker": 0.65,
    "crutches": 0.75,
    "stroller": 1.15,
    "reduced_mobility": 0.90,
    "custom": 0.95,
}
_DEFAULT_SPEED_MPS = 1.0

#: Seconds added for obstacles that cost time rather than distance.
_SECONDS_PER_STEP = 2.5
_SECONDS_PER_CROSSING = 20.0


class RoutingError(RuntimeError):
    """Base class for a request that cannot produce a route."""


class RequestTooLargeError(RoutingError):
    """Origin and destination are too far apart to route between."""


class PointOffNetworkError(RoutingError):
    """A requested coordinate has no mapped path near it."""

    def __init__(self, label: str, distance_m: float) -> None:
        self.label = label
        self.distance_m = distance_m
        super().__init__(
            f"The {label} is {distance_m:.0f} m from the nearest mapped path, which is "
            f"further than PathAble will guess. Choose a point closer to a street or footpath."
        )


class NoRouteFoundError(RoutingError):
    """No path exists under this profile's constraints."""

    def __init__(self, profile: MobilityProfile) -> None:
        self.profile = profile
        super().__init__(
            f"No route satisfies the {profile.display_name.lower()} profile between these points."
        )


class SearchLimitExceededError(RoutingError):
    """The search hit its evaluation ceiling."""


@dataclass(frozen=True, slots=True)
class RouteSegment:
    """One edge as it appears on a computed route."""

    edge_identity: str
    name: str | None
    length_m: float
    effective_metres: float
    coordinates: tuple[tuple[float, float], ...]
    highway: str | None
    surface: str | None
    surface_class: SurfaceClass
    smoothness_class: SmoothnessClass
    steps: TriState
    step_count: int | None
    incline_percent: float | None
    #: Grade inferred from a terrain model. Kept apart from `incline_percent`
    #: all the way to the interface, because "somebody measured this path" and
    #: "we inferred it from the ground beneath it" are different claims.
    derived_grade_percent: float | None
    kerb: KerbType
    is_crossing: bool
    #: Carried so a 'no route' diagnostic can report a width that blocked a
    #: profile. Without it the reason list silently omits narrow segments.
    width_m: float | None
    unknown_attributes: tuple[str, ...]
    cost_components: tuple[CostComponent, ...]


@dataclass(frozen=True, slots=True)
class Route:
    """A computed route and the evidence behind it."""

    profile_key: str
    profile_display_name: str
    distance_m: float
    effective_distance_m: float
    estimated_duration_seconds: float
    coordinates: tuple[tuple[float, float], ...]
    segments: tuple[RouteSegment, ...]
    origin: SnappedPoint
    destination: SnappedPoint
    computation_ms: float
    #: Which search produced this route, and how much work it took. Reported so
    #: a performance claim can be checked rather than believed.
    algorithm: Algorithm = Algorithm.ASTAR
    expanded_nodes: int = 0

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    @property
    def step_count(self) -> int:
        """Total steps on this route, counting an unrecorded stairway as unknown."""
        return sum(
            segment.step_count or 0 for segment in self.segments if segment.steps is TriState.YES
        )

    @property
    def stairway_count(self) -> int:
        return sum(1 for segment in self.segments if segment.steps is TriState.YES)

    @property
    def crossing_count(self) -> int:
        return sum(1 for segment in self.segments if segment.is_crossing)

    @property
    def unknown_kerb_crossing_count(self) -> int:
        return sum(
            1
            for segment in self.segments
            if segment.is_crossing and segment.kerb is KerbType.UNKNOWN
        )

    @property
    def steepest_incline_percent(self) -> float | None:
        gradients = [
            abs(segment.incline_percent)
            for segment in self.segments
            if segment.incline_percent is not None
        ]
        return max(gradients) if gradients else None

    @property
    def length_with_unknown_data_m(self) -> float:
        return sum(segment.length_m for segment in self.segments if segment.unknown_attributes)

    @property
    def unknown_data_fraction(self) -> float:
        """How much of this route runs over segments with missing accessibility data."""
        if self.distance_m <= 0:
            return 0.0
        return min(1.0, self.length_with_unknown_data_m / self.distance_m)

    @property
    def evidence_coverage(self) -> dict[str, float]:
        """Share of this route's length with no record, per category.

        One number for "missing accessibility data" cannot be acted on: a route
        missing every surface tag and one missing every gradient are the same
        percentage and completely different journeys. Reported per category so
        the interface can say which fact is absent rather than how much is.
        """
        if self.distance_m <= 0:
            return {}

        missing = {
            "surface": 0.0,
            "smoothness": 0.0,
            "gradient": 0.0,
            "width": 0.0,
            "kerb": 0.0,
        }
        crossing_length = 0.0
        for segment in self.segments:
            if segment.surface_class is SurfaceClass.UNKNOWN:
                missing["surface"] += segment.length_m
            if segment.smoothness_class is SmoothnessClass.UNKNOWN:
                missing["smoothness"] += segment.length_m
            if segment.incline_percent is None and segment.derived_grade_percent is None:
                missing["gradient"] += segment.length_m
            if segment.width_m is None:
                missing["width"] += segment.length_m
            if segment.is_crossing:
                crossing_length += segment.length_m
                if segment.kerb is KerbType.UNKNOWN:
                    missing["kerb"] += segment.length_m

        coverage = {
            name: min(1.0, value / self.distance_m)
            for name, value in missing.items()
            if name != "kerb"
        }
        # Kerb is only a fact about crossings, so it is measured over crossings.
        # Against the whole route it would always look excellent.
        coverage["kerb"] = min(1.0, missing["kerb"] / crossing_length) if crossing_length else 0.0
        return coverage

    @property
    def gradient_source(self) -> str | None:
        """Where this route's gradient information came from, if anywhere.

        A gradient a surveyor recorded and one a terrain model inferred are
        different kinds of claim, and the interface has to be able to say which
        it is showing.
        """
        has_osm = any(segment.incline_percent is not None for segment in self.segments)
        has_derived = any(segment.derived_grade_percent is not None for segment in self.segments)
        if has_osm and has_derived:
            return "mixed"
        if has_osm:
            return "osm_incline"
        if has_derived:
            return "derived_elevation"
        return None


def compute_route(
    graph: RoutableGraph,
    *,
    origin: tuple[float, float],
    destination: tuple[float, float],
    profile: MobilityProfile,
    algorithm: Algorithm = Algorithm.ASTAR,
) -> Route:
    """Find the best route between two coordinates for one profile.

    Coordinates are ``(longitude, latitude)``.

    Both endpoints attach to the nearest point *along* a segment, not to the
    nearest junction. Where that lands mid-segment, the segment is split for
    this request only: the cached graph is shared between concurrent requests
    and keyed on a dataset version that is supposed to be immutable, so it is
    never mutated.
    """
    span = geodesic_distance_m(Point(*origin), Point(*destination))
    if span > MAX_REQUEST_SPAN_M:
        msg = (
            f"Origin and destination are {span / 1000:.1f} km apart, beyond the "
            f"{MAX_REQUEST_SPAN_M / 1000:.0f} km limit for a walking route."
        )
        raise RequestTooLargeError(msg)

    start_snap = _snap_or_fail(graph, origin, "origin", profile)
    end_snap = _snap_or_fail(graph, destination, "destination", profile)

    started = time.perf_counter()
    overlay = _Overlay(graph)
    start_node = overlay.attach(start_snap, "origin")
    goal_node = overlay.attach(end_snap, "destination")

    goal_position = overlay.position(goal_node)

    def heuristic(node: str) -> float:
        # Straight-line metres to the goal. Admissible because every edge cost
        # is at least its own length: accessibility contributions never subtract.
        longitude, latitude = overlay.position(node)
        return geodesic_distance_m(
            Point(longitude, latitude), Point(goal_position[0], goal_position[1])
        )

    def weight(edge: DirectedEdge) -> float:
        return _edge_cost(edge, profile).effective_metres

    try:
        found: SearchResult = search(
            start_node,
            goal_node,
            neighbours=overlay.neighbours,
            weight=weight,
            heuristic=heuristic,
            algorithm=algorithm,
            max_expansions=MAX_EDGE_EVALUATIONS,
        )
    except NoPathError as error:
        raise NoRouteFoundError(profile) from error
    except SearchLimitError as error:
        raise SearchLimitExceededError(str(error)) from error

    segments = [_to_segment(edge, _edge_cost(edge, profile)) for edge in found.edges]
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    distance_m = sum(segment.length_m for segment in segments)
    effective_m = sum(segment.effective_metres for segment in segments)

    return Route(
        profile_key=profile.key,
        profile_display_name=profile.display_name,
        distance_m=distance_m,
        effective_distance_m=effective_m,
        estimated_duration_seconds=_estimate_duration(segments, profile),
        coordinates=_stitch(segments),
        segments=tuple(segments),
        origin=_as_snapped_point(start_snap),
        destination=_as_snapped_point(end_snap),
        computation_ms=elapsed_ms,
        algorithm=found.algorithm,
        expanded_nodes=found.expanded,
    )


def _as_snapped_point(snap: EdgeSnap) -> SnappedPoint:
    return SnappedPoint(
        node_id=snap.node_id or snap.edge.identity,
        longitude=snap.longitude,
        latitude=snap.latitude,
        distance_m=snap.distance_m,
    )


class _Overlay:
    """Request-local additions to a shared, immutable graph.

    Everything a snap introduces lives here: the virtual node, the two partial
    segments it creates, and their positions. The underlying graph is only ever
    read.
    """

    __slots__ = ("_adjacency", "_graph", "_positions")

    def __init__(self, graph: RoutableGraph) -> None:
        self._graph = graph
        self._adjacency: dict[str, list[tuple[str, DirectedEdge]]] = {}
        self._positions: dict[str, tuple[float, float]] = {}

    def attach(self, snap: EdgeSnap, label: str) -> str:
        """Introduce a snap point and return the node routing should use."""
        if snap.is_on_node and snap.node_id is not None:
            return snap.node_id

        # Landing on an endpoint needs no split — the junction is already there.
        if snap.fraction <= 1e-9:
            return snap.edge.source_u
        if snap.fraction >= 1.0 - 1e-9:
            return snap.edge.source_v

        node = virtual_node_id(label)
        self._positions[node] = (snap.longitude, snap.latitude)

        head_geometry, tail_geometry = split_geometry(snap.edge.geometry, snap.fraction)
        edge = snap.edge

        forward_head = DirectedEdge(edge=edge, features=edge.features, reversed=False)
        forward_tail = DirectedEdge(edge=edge, features=edge.features, reversed=False)
        backward_head = DirectedEdge(edge=edge, features=edge.features.reversed(), reversed=True)
        backward_tail = DirectedEdge(edge=edge, features=edge.features.reversed(), reversed=True)

        # Direction survives the split: half of a one-way segment is still
        # one-way, and the half running against the permitted direction must
        # never appear.
        if edge.foot_forward:
            # u -> node -> v
            self._link(edge.source_u, node, prorate(forward_head, head_geometry))
            self._link(node, edge.source_v, prorate(forward_tail, tail_geometry))
        if edge.foot_backward:
            # v -> node -> u
            self._link(edge.source_v, node, prorate(backward_tail, _reverse(tail_geometry)))
            self._link(node, edge.source_u, prorate(backward_head, _reverse(head_geometry)))

        return node

    def _link(self, source: str, target: str, edge: DirectedEdge) -> None:
        self._adjacency.setdefault(source, []).append((target, edge))

    def neighbours(self, node: str) -> list[tuple[str, DirectedEdge]]:
        found = list(self._adjacency.get(node, ()))
        graph = self._graph.graph
        if node in graph:
            for target, parallel in graph[node].items():
                for data in parallel.values():
                    found.append((str(target), data["edge"]))
        return found

    def position(self, node: str) -> tuple[float, float]:
        known = self._positions.get(node)
        if known is not None:
            return known
        return self._graph.node_positions.get(node, (0.0, 0.0))


def _reverse(geometry: LineString) -> LineString:
    return LineString(list(geometry.coords)[::-1])


def _snap_or_fail(
    graph: RoutableGraph,
    coordinate: tuple[float, float],
    label: str,
    profile: MobilityProfile,
) -> EdgeSnap:
    """Attach a requested point to a segment this profile can actually walk.

    Snapping to the geometrically nearest segment regardless of the profile
    produced a real failure on the Waterloo network: a point in Waterloo Park
    landed 12 m onto a `foot=no` cycleway, so every route to it failed while a
    walkable path sat metres further away. The nearest line to somebody's finger
    is not necessarily a line they are allowed on.
    """
    snapped = graph.snap_to_edge(
        coordinate[0],
        coordinate[1],
        accept=lambda edge: _usable_for(edge, profile),
        max_distance_m=MAX_SNAP_DISTANCE_M,
    )
    if snapped is None:
        raise PointOffNetworkError(label, float("inf"))
    if snapped.distance_m > MAX_SNAP_DISTANCE_M:
        raise PointOffNetworkError(label, snapped.distance_m)
    return snapped


def _to_segment(edge: DirectedEdge, cost: EdgeCost) -> RouteSegment:
    # Geometry and features both already point along travel.
    coordinates = edge.coordinates()
    features = edge.features
    return RouteSegment(
        edge_identity=edge.identity,
        name=edge.name,
        length_m=edge.length_m,
        effective_metres=cost.effective_metres,
        coordinates=coordinates,
        highway=features.highway,
        surface=features.surface,
        surface_class=features.surface_class,
        smoothness_class=features.smoothness_class,
        steps=features.steps,
        step_count=features.step_count,
        incline_percent=features.incline_percent,
        derived_grade_percent=features.derived_grade_percent,
        kerb=features.kerb,
        is_crossing=features.is_crossing,
        width_m=features.width_m,
        unknown_attributes=features.unknown_attributes,
        cost_components=cost.components,
    )


def _stitch(segments: list[RouteSegment]) -> tuple[tuple[float, float], ...]:
    """Join segment geometries into one polyline without duplicating junctions."""
    coordinates: list[tuple[float, float]] = []
    for segment in segments:
        for position in segment.coordinates:
            if coordinates and coordinates[-1] == position:
                continue
            coordinates.append(position)
    return tuple(coordinates)


def _estimate_duration(segments: list[RouteSegment], profile: MobilityProfile) -> float:
    """A planning estimate, from distance and obstacle counts.

    Deliberately *not* derived from effective metres: those encode preference as
    well as effort, and a route that avoids an unrecorded kerb is not slower for
    having done so.
    """
    speed = _WALKING_SPEED_MPS.get(profile.key, _DEFAULT_SPEED_MPS)
    seconds = sum(segment.length_m for segment in segments) / speed

    for segment in segments:
        if segment.steps is TriState.YES:
            seconds += _SECONDS_PER_STEP * (segment.step_count or profile.assumed_step_count)
        if segment.is_crossing:
            seconds += _SECONDS_PER_CROSSING
    return seconds


def _edge_cost(edge: DirectedEdge, profile: MobilityProfile) -> EdgeCost:
    """Cost this segment *in the direction of travel*.

    `edge.features` is already oriented, which is what makes an uphill climb
    cost more than the same slope going down.
    """
    return evaluate_edge(edge.features, edge.length_m, profile)


def blocked_reason_for(edge: DirectedEdge, profile: MobilityProfile) -> BlockReason | None:
    """Why this profile cannot use a segment, if it cannot. Used by diagnostics."""
    return _edge_cost(edge, profile).blocked_reason


def _usable_for(edge: RoutableEdge, profile: MobilityProfile) -> bool:
    """Whether a route for this profile could traverse a segment either way.

    A segment is acceptable to snap to if it is walkable in at least one
    direction. Requiring both would refuse a legitimate one-way path; requiring
    neither is what caused a park to become unreachable.
    """
    return any(
        _edge_cost(directed, profile).blocked_reason is None for directed in _both_directions(edge)
    )


def _both_directions(edge: RoutableEdge) -> tuple[DirectedEdge, ...]:
    directions: list[DirectedEdge] = []
    if edge.foot_forward:
        directions.append(DirectedEdge(edge=edge, features=edge.features, reversed=False))
    if edge.foot_backward:
        directions.append(DirectedEdge(edge=edge, features=edge.features.reversed(), reversed=True))
    return tuple(directions)
