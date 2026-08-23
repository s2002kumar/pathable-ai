"""Route the real network and record what actually happened.

Every number this produces comes from a route that was computed. Nothing here
estimates, extrapolates or rounds up, because the whole point is to be able to
say "on the real Waterloo network, this profile detoured 240 m to avoid two
crossings with no kerb information" and have that be a fact rather than a claim.

**Cases are not filtered by outcome.** A case where the accessible profile
returns exactly the same route as the standard one is reported as exactly that,
and so is a case where no route exists at all. Keeping only the cases where
accessibility routing visibly changed something would turn an evaluation into a
demo, and would hide the two most important findings a pilot can produce: that
the data is too sparse to change the answer, and that some journeys cannot be
made at all.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from pathable_api.geo.enums import KerbType, SmoothnessClass, SurfaceClass, TriState
from pathable_api.routing.engine import (
    NoRouteFoundError,
    PointOffNetworkError,
    RequestTooLargeError,
    Route,
    RoutingError,
    compute_route,
)
from pathable_api.routing.search import Algorithm

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from pathable_api.routing.graph import RoutableGraph
    from pathable_api.routing.profiles import MobilityProfile


@dataclass(frozen=True, slots=True)
class RouteCase:
    """One journey somebody might actually want to make."""

    key: str
    description: str
    origin: tuple[float, float]
    destination: tuple[float, float]


@dataclass(slots=True)
class RouteOutcome:
    """What the engine did for one case and one profile."""

    case: str
    profile: str
    routed: bool
    #: Present only when `routed` is true.
    distance_m: float | None = None
    effective_distance_m: float | None = None
    duration_seconds: float | None = None
    segments: int = 0
    computation_ms: float | None = None
    expanded_nodes: int | None = None
    origin_snap_m: float | None = None
    destination_snap_m: float | None = None
    #: Why no route, when there is none. A real product outcome, not an error.
    failure: str | None = None
    failure_kind: str | None = None
    #: What the route ran into, counted rather than described.
    barriers: dict[str, int] = field(default_factory=dict)
    #: Attributes the map said nothing about, per category.
    unknown: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class CaseComparison:
    """One case, standard profile against an accessibility profile."""

    case: str
    description: str
    baseline: RouteOutcome
    subject: RouteOutcome

    @property
    def route_changed(self) -> bool:
        """Whether the accessibility profile produced a different journey.

        Compared on real distance rather than cost: two routes with the same
        geometry can have very different effective distances, and it is the
        geometry that a person walks.
        """
        if not (self.baseline.routed and self.subject.routed):
            return self.baseline.routed != self.subject.routed
        if self.baseline.segments != self.subject.segments:
            return True
        assert self.baseline.distance_m is not None  # noqa: S101
        assert self.subject.distance_m is not None  # noqa: S101
        return abs(self.subject.distance_m - self.baseline.distance_m) > 1.0

    @property
    def detour_m(self) -> float | None:
        if self.baseline.distance_m is None or self.subject.distance_m is None:
            return None
        return self.subject.distance_m - self.baseline.distance_m

    @property
    def detour_fraction(self) -> float | None:
        if self.detour_m is None or not self.baseline.distance_m:
            return None
        return self.detour_m / self.baseline.distance_m

    def reason(self) -> str:
        """Why the routes differ, in terms of what was actually avoided.

        Derived from the difference in what each route ran into, so it cannot
        drift from the evidence: if the accessible route meets fewer unknown
        kerbs, that is what it says.
        """
        if not self.subject.routed:
            return self.subject.failure or "no route"
        if not self.route_changed:
            return "identical route — nothing on the direct path costs this profile anything"

        reasons: list[str] = []
        for name, before in self.baseline.barriers.items():
            after = self.subject.barriers.get(name, 0)
            if after < before:
                reasons.append(f"avoids {before - after} {name}")
        for name, before in self.baseline.unknown.items():
            after = self.subject.unknown.get(name, 0)
            if after < before:
                reasons.append(f"avoids {before - after} segments with unknown {name}")
        if not reasons:
            return "different path with no reduction in recorded barriers"
        return "; ".join(sorted(reasons))


def evaluate(
    graph: RoutableGraph,
    *,
    cases: Sequence[RouteCase],
    baseline: MobilityProfile,
    subject: MobilityProfile,
    algorithm: Algorithm = Algorithm.ASTAR,
) -> list[CaseComparison]:
    """Route every case under both profiles and keep every result."""
    return [
        CaseComparison(
            case=case.key,
            description=case.description,
            baseline=run_case(graph, case=case, profile=baseline, algorithm=algorithm),
            subject=run_case(graph, case=case, profile=subject, algorithm=algorithm),
        )
        for case in cases
    ]


def run_case(
    graph: RoutableGraph,
    *,
    case: RouteCase,
    profile: MobilityProfile,
    algorithm: Algorithm = Algorithm.ASTAR,
) -> RouteOutcome:
    """One route, with its failure treated as a result rather than an exception."""
    try:
        route = compute_route(
            graph,
            origin=case.origin,
            destination=case.destination,
            profile=profile,
            algorithm=algorithm,
        )
    except (NoRouteFoundError, PointOffNetworkError, RequestTooLargeError) as error:
        return RouteOutcome(
            case=case.key,
            profile=profile.key,
            routed=False,
            failure=str(error),
            failure_kind=type(error).__name__,
        )
    except RoutingError as error:  # pragma: no cover - defensive
        return RouteOutcome(
            case=case.key,
            profile=profile.key,
            routed=False,
            failure=str(error),
            failure_kind=type(error).__name__,
        )

    return _describe(case, profile, route)


def _describe(case: RouteCase, profile: MobilityProfile, route: Route) -> RouteOutcome:
    barriers: dict[str, int] = {}
    unknown: dict[str, int] = {}

    def bump(bucket: dict[str, int], name: str) -> None:
        bucket[name] = bucket.get(name, 0) + 1

    for segment in route.segments:
        if segment.steps is TriState.YES:
            bump(barriers, "step segments")
        if segment.is_crossing:
            bump(barriers, "crossings")
            if segment.kerb is KerbType.RAISED:
                bump(barriers, "raised kerbs")
            elif segment.kerb is KerbType.UNKNOWN:
                bump(unknown, "kerb information")
        if segment.surface_class is SurfaceClass.UNKNOWN:
            bump(unknown, "surface")
        if segment.smoothness_class is SmoothnessClass.UNKNOWN:
            bump(unknown, "smoothness")
        if segment.incline_percent is None:
            bump(unknown, "gradient")
        if segment.width_m is None:
            bump(unknown, "width")

    return RouteOutcome(
        case=case.key,
        profile=profile.key,
        routed=True,
        distance_m=round(route.distance_m, 1),
        effective_distance_m=round(route.effective_distance_m, 1),
        duration_seconds=round(route.estimated_duration_seconds, 1),
        segments=len(route.segments),
        computation_ms=round(route.computation_ms, 2),
        expanded_nodes=route.expanded_nodes,
        origin_snap_m=round(route.origin.distance_m, 1),
        destination_snap_m=round(route.destination.distance_m, 1),
        barriers=barriers,
        unknown=unknown,
    )


# ---------------------------------------------------------------------------
# Algorithm comparison
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AlgorithmComparison:
    """Dijkstra against A* on the same case, measured rather than assumed."""

    case: str
    profile: str
    dijkstra_ms: float
    astar_ms: float
    dijkstra_expanded: int
    astar_expanded: int
    dijkstra_cost: float
    astar_cost: float

    @property
    def costs_agree(self) -> bool:
        """Whether A* found a route of the same cost.

        This is the correctness claim. A* may legitimately return a different
        path of equal cost when several are tied, but it must never return a
        worse one — that would mean the heuristic is not admissible.
        """
        return abs(self.astar_cost - self.dijkstra_cost) < 0.01

    @property
    def speedup(self) -> float:
        return self.dijkstra_ms / self.astar_ms if self.astar_ms else 0.0


def compare_algorithms(
    graph: RoutableGraph,
    *,
    cases: Sequence[RouteCase],
    profile: MobilityProfile,
    repeats: int = 3,
) -> list[AlgorithmComparison]:
    """Time both searches on the same journeys.

    Repeats and takes the median, because a single timing on a warm cache says
    more about the machine's mood than about the algorithm.
    """
    results: list[AlgorithmComparison] = []
    for case in cases:
        measured: dict[Algorithm, tuple[float, int, float]] = {}
        for algorithm in (Algorithm.DIJKSTRA, Algorithm.ASTAR):
            timings: list[float] = []
            route: Route | None = None
            for _ in range(repeats):
                started = time.perf_counter()
                try:
                    route = compute_route(
                        graph,
                        origin=case.origin,
                        destination=case.destination,
                        profile=profile,
                        algorithm=algorithm,
                    )
                except RoutingError:
                    route = None
                    break
                timings.append((time.perf_counter() - started) * 1000.0)
            if route is None:
                break
            measured[algorithm] = (
                statistics.median(timings),
                route.expanded_nodes,
                route.effective_distance_m,
            )

        if len(measured) != 2:
            continue
        dijkstra = measured[Algorithm.DIJKSTRA]
        astar = measured[Algorithm.ASTAR]
        results.append(
            AlgorithmComparison(
                case=case.key,
                profile=profile.key,
                dijkstra_ms=round(dijkstra[0], 2),
                astar_ms=round(astar[0], 2),
                dijkstra_expanded=dijkstra[1],
                astar_expanded=astar[1],
                dijkstra_cost=round(dijkstra[2], 3),
                astar_cost=round(astar[2], 3),
            )
        )
    return results


def as_records(comparisons: Sequence[CaseComparison]) -> list[dict[str, object]]:
    """Flatten to rows, keeping every case including the uninteresting ones."""
    return [
        {
            "case": comparison.case,
            "description": comparison.description,
            "route_changed": comparison.route_changed,
            "detour_m": (None if comparison.detour_m is None else round(comparison.detour_m, 1)),
            "detour_fraction": (
                None if comparison.detour_fraction is None else round(comparison.detour_fraction, 4)
            ),
            "reason": comparison.reason(),
            "baseline": asdict(comparison.baseline),
            "subject": asdict(comparison.subject),
        }
        for comparison in comparisons
    ]
