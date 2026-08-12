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
from itertools import pairwise
from typing import Any, cast

import networkx as nx
from shapely.geometry import Point

from pathable_api.core.logging import get_logger
from pathable_api.geo.enums import KerbType, SmoothnessClass, SurfaceClass, TriState
from pathable_api.geo.geometry import geodesic_distance_m
from pathable_api.routing.cost import BlockReason, CostComponent, EdgeCost, evaluate_edge
from pathable_api.routing.graph import RoutableEdge, RoutableGraph, SnappedPoint
from pathable_api.routing.profiles import MobilityProfile

logger = get_logger(__name__)

#: Farthest apart an origin and destination may be, as the crow flies. Waterloo's
#: pilot extent is about 12 km across; anything beyond this is not a walking
#: journey and is almost certainly a mistake or an attempt to make the server work.
MAX_REQUEST_SPAN_M = 15_000.0

#: How far a requested coordinate may be from the nearest mapped path before we
#: refuse rather than silently starting the route somewhere else.
MAX_SNAP_DISTANCE_M = 300.0

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
    kerb: KerbType
    is_crossing: bool
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


def compute_route(
    graph: RoutableGraph,
    *,
    origin: tuple[float, float],
    destination: tuple[float, float],
    profile: MobilityProfile,
) -> Route:
    """Find the best route between two coordinates for one profile.

    Coordinates are ``(longitude, latitude)``.
    """
    span = geodesic_distance_m(Point(*origin), Point(*destination))
    if span > MAX_REQUEST_SPAN_M:
        msg = (
            f"Origin and destination are {span / 1000:.1f} km apart, beyond the "
            f"{MAX_REQUEST_SPAN_M / 1000:.0f} km limit for a walking route."
        )
        raise RequestTooLargeError(msg)

    start = _snap_or_fail(graph, origin, "origin")
    end = _snap_or_fail(graph, destination, "destination")

    started = time.perf_counter()
    node_path = _shortest_path(graph, start.node_id, end.node_id, profile)
    segments = _segments_for(graph, node_path, profile)
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
        origin=start,
        destination=end,
        computation_ms=elapsed_ms,
    )


def _snap_or_fail(
    graph: RoutableGraph, coordinate: tuple[float, float], label: str
) -> SnappedPoint:
    snapped = graph.snap(coordinate[0], coordinate[1])
    if snapped is None:
        raise PointOffNetworkError(label, float("inf"))
    if snapped.distance_m > MAX_SNAP_DISTANCE_M:
        raise PointOffNetworkError(label, snapped.distance_m)
    return snapped


def _shortest_path(
    graph: RoutableGraph, source: str, target: str, profile: MobilityProfile
) -> list[str]:
    if source == target:
        return [source]

    budget = _EvaluationBudget(MAX_EDGE_EVALUATIONS)

    def weight(u: str, v: str, parallel: dict[int, dict[str, Any]]) -> float | None:
        budget.spend()
        best = min(
            (_edge_cost(data["edge"], profile).effective_metres for data in parallel.values()),
            default=float("inf"),
        )
        # Returning None tells NetworkX the edge does not exist for this search,
        # which is exactly what a hard constraint means.
        return None if best == float("inf") else best

    try:
        # NetworkX types `weight` for simple graphs; on a multigraph the callable
        # receives the whole parallel-edge mapping, which the stubs do not model.
        _, path = nx.bidirectional_dijkstra(
            graph.graph,
            source,
            target,
            weight=weight,  # type: ignore[arg-type]
        )
    except nx.NetworkXNoPath as error:
        raise NoRouteFoundError(profile) from error
    except nx.NodeNotFound as error:
        raise NoRouteFoundError(profile) from error

    return [str(node) for node in path]


def _segments_for(
    graph: RoutableGraph, node_path: list[str], profile: MobilityProfile
) -> list[RouteSegment]:
    segments: list[RouteSegment] = []

    for u, v in pairwise(node_path):
        # The stubs type an adjacency view's keys as node labels; on a multigraph
        # the inner mapping is keyed by edge key, which is an int.
        parallel = cast("dict[int, dict[str, Any]]", dict(graph.graph[u][v]))
        chosen_key: int | None = None
        chosen_cost: EdgeCost | None = None

        for key in sorted(parallel):
            edge: RoutableEdge = parallel[key]["edge"]
            cost = _edge_cost(edge, profile)
            if not cost.passable:
                continue
            if chosen_cost is None or cost.effective_metres < chosen_cost.effective_metres:
                chosen_key, chosen_cost = key, cost

        if chosen_key is None or chosen_cost is None:
            # Only reachable if the graph changed under us mid-request, which the
            # dataset-version cache key is designed to prevent.
            raise NoRouteFoundError(profile)

        edge = parallel[chosen_key]["edge"]
        segments.append(_to_segment(edge, chosen_cost, oriented_from=u, graph=graph))

    return segments


def _to_segment(
    edge: RoutableEdge, cost: EdgeCost, *, oriented_from: str, graph: RoutableGraph
) -> RouteSegment:
    coordinates = tuple((float(x), float(y)) for x, y, *_ in edge.geometry.coords)
    # Stored geometry runs source_u → source_v; a route may traverse it either way.
    if edge.source_u != oriented_from:
        coordinates = tuple(reversed(coordinates))

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
        kerb=features.kerb,
        is_crossing=features.is_crossing,
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


class _EvaluationBudget:
    """Counts edge evaluations so one request cannot search forever."""

    __slots__ = ("_limit", "_spent")

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._spent = 0

    def spend(self) -> None:
        self._spent += 1
        if self._spent > self._limit:
            msg = f"Route search exceeded {self._limit} edge evaluations. Try a shorter journey."
            raise SearchLimitExceededError(msg)


def _edge_cost(edge: RoutableEdge, profile: MobilityProfile) -> EdgeCost:
    return evaluate_edge(edge.features, edge.length_m, profile)


def blocked_reason_for(edge: RoutableEdge, profile: MobilityProfile) -> BlockReason | None:
    """Why this profile cannot use a segment, if it cannot. Used by diagnostics."""
    return _edge_cost(edge, profile).blocked_reason
