"""Comparing the standard route with an accessibility-aware one.

The comparison is the product. A single "accessible route" tells someone where to
walk; showing it against the shortest route tells them *what it cost them and
why*, which is what lets them decide whether the trade is worth making today.

Every statement produced here is derived from attributes recorded in the dataset
and cites the evidence that produced it. Nothing is inferred, predicted or
softened: if the accessible route is longer, it says so, and if the data behind
it is thin, it says that too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pathable_api.geo.enums import KerbType, SmoothnessClass, SurfaceClass, TriState
from pathable_api.geo.features import EdgeFeatures
from pathable_api.routing.cost import evaluate_edge
from pathable_api.routing.engine import Route, RouteSegment, RoutingError, compute_route
from pathable_api.routing.graph import RoutableGraph
from pathable_api.routing.profiles import STANDARD, MobilityProfile

#: Below this the two routes are the same journey and saying "3 m longer" would
#: be noise dressed up as information.
_MATERIAL_DIFFERENCE_M = 15.0

#: A route where more than this fraction of the distance has missing
#: accessibility data gets an explicit caution rather than a quiet footnote.
_THIN_DATA_FRACTION = 0.5


@dataclass(frozen=True, slots=True)
class Explanation:
    """One evidence-backed statement about the accessible route."""

    code: str
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Caution:
    """Something the user should weigh before trusting the route."""

    code: str
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RouteComparison:
    profile: MobilityProfile
    standard_route: Route | None
    accessible_route: Route | None
    explanations: tuple[Explanation, ...]
    cautions: tuple[Caution, ...]
    standard_failure: str | None = None
    accessible_failure: str | None = None

    #: Always false in this phase. PathAble contains no model, and the field is
    #: explicit rather than absent so a client can never infer otherwise from
    #: silence — and so the day it becomes true is a visible change.
    ml_predictions_used: bool = False

    @property
    def extra_distance_m(self) -> float | None:
        if self.standard_route is None or self.accessible_route is None:
            return None
        return self.accessible_route.distance_m - self.standard_route.distance_m

    @property
    def extra_distance_fraction(self) -> float | None:
        if self.standard_route is None or self.accessible_route is None:
            return None
        if self.standard_route.distance_m <= 0:
            return None
        return self.extra_distance_m / self.standard_route.distance_m  # type: ignore[operator]

    @property
    def routes_are_equivalent(self) -> bool:
        extra = self.extra_distance_m
        return extra is not None and abs(extra) < _MATERIAL_DIFFERENCE_M


def compare_routes(
    graph: RoutableGraph,
    *,
    origin: tuple[float, float],
    destination: tuple[float, float],
    profile: MobilityProfile,
) -> RouteComparison:
    """Compute both routes and explain the difference.

    Each route is computed independently: one failing must not hide the other.
    A profile with no possible route is a real and useful answer — but only if we
    can still show the shortest route and say what makes it impassable.
    """
    standard_route: Route | None = None
    standard_failure: str | None = None
    try:
        standard_route = compute_route(
            graph, origin=origin, destination=destination, profile=STANDARD
        )
    except RoutingError as error:
        standard_failure = str(error)

    accessible_route: Route | None = None
    accessible_failure: str | None = None
    if not profile.is_standard:
        try:
            accessible_route = compute_route(
                graph, origin=origin, destination=destination, profile=profile
            )
        except RoutingError as error:
            accessible_failure = str(error)

    return RouteComparison(
        profile=profile,
        standard_route=standard_route,
        accessible_route=accessible_route,
        standard_failure=standard_failure,
        accessible_failure=accessible_failure,
        explanations=_explain(standard_route, accessible_route, profile),
        cautions=_cautions(standard_route, accessible_route, profile),
    )


# ---------------------------------------------------------------------------
# Explanations
# ---------------------------------------------------------------------------


def _explain(
    standard: Route | None, accessible: Route | None, profile: MobilityProfile
) -> tuple[Explanation, ...]:
    if accessible is None or standard is None:
        return ()

    explanations: list[Explanation] = []
    avoided = _avoided_segments(standard, accessible)

    explanations.extend(_explain_stairs(avoided, profile))
    explanations.extend(_explain_kerbs(avoided))
    explanations.extend(_explain_surfaces(avoided))
    explanations.extend(_explain_gradients(avoided, accessible))
    explanations.append(_explain_distance(standard, accessible))

    return tuple(explanations)


def _avoided_segments(standard: Route, accessible: Route) -> tuple[RouteSegment, ...]:
    """Segments the shortest route uses that the accessible route does not.

    This is the evidence base for every "avoids…" statement — each one names
    something that is actually on the other route.
    """
    accessible_ids = {segment.edge_identity for segment in accessible.segments}
    return tuple(
        segment for segment in standard.segments if segment.edge_identity not in accessible_ids
    )


def _explain_stairs(
    avoided: tuple[RouteSegment, ...], profile: MobilityProfile
) -> list[Explanation]:
    stairways = [segment for segment in avoided if segment.steps is TriState.YES]
    if not stairways:
        return []

    counted = sum(segment.step_count for segment in stairways if segment.step_count)
    unrecorded = sum(1 for segment in stairways if segment.step_count is None)

    if counted and not unrecorded:
        detail = f"{counted} steps in total"
    elif counted:
        detail = f"{counted} steps in total, plus {unrecorded} with no recorded step count"
    else:
        detail = "the step counts are not recorded"

    stairway_word = "stairway" if len(stairways) == 1 else "stairways"
    verb = "Avoids" if profile.hard_limits.exclude_steps else "Routes around"
    return [
        Explanation(
            code="avoids_stairs",
            summary=f"{verb} {len(stairways)} {stairway_word} ({detail}).",
            evidence={
                "stairway_count": len(stairways),
                "step_count": counted,
                "stairways_without_step_count": unrecorded,
                "segments": [segment.edge_identity for segment in stairways[:10]],
            },
        )
    ]


def _explain_kerbs(avoided: tuple[RouteSegment, ...]) -> list[Explanation]:
    unknown = [
        segment for segment in avoided if segment.is_crossing and segment.kerb is KerbType.UNKNOWN
    ]
    raised = [
        segment for segment in avoided if segment.is_crossing and segment.kerb is KerbType.RAISED
    ]

    explanations: list[Explanation] = []
    if raised:
        explanations.append(
            Explanation(
                code="avoids_raised_kerbs",
                summary=(
                    f"Avoids {len(raised)} crossing"
                    f"{'' if len(raised) == 1 else 's'} with a recorded raised kerb."
                ),
                evidence={"crossing_count": len(raised)},
            )
        )
    if unknown:
        explanations.append(
            Explanation(
                code="avoids_unrecorded_kerbs",
                summary=(
                    f"Avoids {len(unknown)} crossing"
                    f"{'' if len(unknown) == 1 else 's'} where no kerb has been recorded, "
                    f"so nobody has confirmed it is dropped."
                ),
                evidence={"crossing_count": len(unknown)},
            )
        )
    return explanations


def _explain_surfaces(avoided: tuple[RouteSegment, ...]) -> list[Explanation]:
    rough = [segment for segment in avoided if segment.surface_class is SurfaceClass.ROUGH]
    poor = [
        segment
        for segment in avoided
        if segment.smoothness_class is SmoothnessClass.BAD
        and segment.surface_class is not SurfaceClass.ROUGH
    ]
    if not rough and not poor:
        return []

    total_length = sum(segment.length_m for segment in (*rough, *poor))
    described = sorted({segment.surface for segment in rough if segment.surface})
    surfaces = f" ({', '.join(described)})" if described else ""

    return [
        Explanation(
            code="avoids_rough_surface",
            summary=(f"Avoids {total_length:.0f} m of rough or poorly surfaced path{surfaces}."),
            evidence={
                "segment_count": len(rough) + len(poor),
                "length_m": round(total_length, 1),
                "surfaces": described,
            },
        )
    ]


def _explain_gradients(avoided: tuple[RouteSegment, ...], accessible: Route) -> list[Explanation]:
    gradients = [
        abs(segment.incline_percent) for segment in avoided if segment.incline_percent is not None
    ]
    if not gradients:
        return []

    steepest_avoided = max(gradients)
    steepest_taken = accessible.steepest_incline_percent
    if steepest_taken is not None and steepest_taken >= steepest_avoided:
        return []

    taken = (
        f"; the steepest recorded gradient on this route is {steepest_taken:.0f}%"
        if steepest_taken is not None
        else ""
    )
    return [
        Explanation(
            code="avoids_steep_gradient",
            summary=f"Avoids a recorded gradient of {steepest_avoided:.0f}%{taken}.",
            evidence={
                "avoided_max_incline_percent": round(steepest_avoided, 1),
                "route_max_incline_percent": (
                    round(steepest_taken, 1) if steepest_taken is not None else None
                ),
            },
        )
    ]


def _explain_distance(standard: Route, accessible: Route) -> Explanation:
    extra = accessible.distance_m - standard.distance_m

    if abs(extra) < _MATERIAL_DIFFERENCE_M:
        return Explanation(
            code="same_distance",
            summary="This route is essentially the same length as the shortest route.",
            evidence={
                "standard_distance_m": round(standard.distance_m),
                "accessible_distance_m": round(accessible.distance_m),
            },
        )

    fraction = extra / standard.distance_m if standard.distance_m > 0 else 0.0
    direction = "longer" if extra > 0 else "shorter"
    return Explanation(
        code="distance_difference",
        summary=(
            f"{abs(extra):.0f} m {direction} than the shortest route "
            f"({_format_distance(accessible.distance_m)} instead of "
            f"{_format_distance(standard.distance_m)}, {abs(fraction) * 100:.0f}% {direction})."
        ),
        evidence={
            "standard_distance_m": round(standard.distance_m),
            "accessible_distance_m": round(accessible.distance_m),
            "extra_distance_m": round(extra),
            "extra_fraction": round(fraction, 3),
        },
    )


# ---------------------------------------------------------------------------
# Cautions
# ---------------------------------------------------------------------------


def _cautions(
    standard: Route | None,
    accessible: Route | None,
    profile: MobilityProfile,
) -> tuple[Caution, ...]:
    cautions: list[Caution] = []

    if accessible is None and not profile.is_standard:
        cautions.append(
            Caution(
                code="no_accessible_route",
                summary=(
                    f"PathAble could not find a route that meets the "
                    f"{profile.display_name.lower()} profile between these points."
                ),
                evidence=_blocking_evidence(standard, profile),
            )
        )

    route = accessible or standard
    if route is not None:
        fraction = route.unknown_data_fraction
        if fraction > 0:
            level = "most" if fraction > _THIN_DATA_FRACTION else "some"
            # Says which route, and what the figure counts. The fraction is the
            # share of the route's length over segments missing *at least one*
            # routing-relevant attribute — a recorded stairway on such a segment
            # is still recorded — so "no accessibility details" overstated it.
            cautions.append(
                Caution(
                    code="missing_accessibility_data",
                    summary=(
                        f"On {level} of the {route.profile_display_name.lower()} route "
                        f"({fraction * 100:.0f}% of its length) at least one accessibility "
                        f"attribute — surface, surface condition, gradient, steps or kerb — "
                        f"has no record in OpenStreetMap. Missing data is not evidence that "
                        f"a path is clear."
                    ),
                    evidence={
                        "unknown_data_fraction": round(fraction, 3),
                        "unknown_data_length_m": round(route.length_with_unknown_data_m),
                        "route_distance_m": round(route.distance_m),
                    },
                )
            )

        if route.unknown_kerb_crossing_count:
            cautions.append(
                Caution(
                    code="unrecorded_kerbs_on_route",
                    summary=(
                        f"{route.unknown_kerb_crossing_count} crossing"
                        f"{'' if route.unknown_kerb_crossing_count == 1 else 's'} on this route "
                        f"have no recorded kerb."
                    ),
                    evidence={"crossing_count": route.unknown_kerb_crossing_count},
                )
            )

    # A structural caution, not a data one: snapping to the nearest junction means
    # the route starts where the network does, which may not be the doorway.
    if route is not None and max(route.origin.distance_m, route.destination.distance_m) > 50:
        cautions.append(
            Caution(
                code="snapped_far_from_request",
                summary=(
                    "The route starts and ends at the nearest mapped path, which is some "
                    "distance from the points you chose."
                ),
                evidence={
                    "origin_snap_distance_m": round(route.origin.distance_m),
                    "destination_snap_distance_m": round(route.destination.distance_m),
                },
            )
        )

    return tuple(cautions)


def _blocking_evidence(standard: Route | None, profile: MobilityProfile) -> dict[str, Any]:
    """Name what on the shortest route this profile cannot use.

    "No route found" is only useful if it comes with the reason, and the reason
    has to be a fact about specific segments rather than a general apology.
    """
    if standard is None:
        return {}

    reasons: dict[str, int] = {}
    examples: list[str] = []
    for segment in standard.segments:
        cost = evaluate_edge(_features_of(segment), segment.length_m, profile)
        if cost.passable or cost.blocked_reason is None:
            continue
        reasons[cost.blocked_reason.value] = reasons.get(cost.blocked_reason.value, 0) + 1
        if len(examples) < 5:
            examples.append(f"{segment.name or segment.edge_identity}: {cost.blocked_detail}")

    return {
        "blocked_segments_on_shortest_route": sum(reasons.values()),
        "reasons": reasons,
        "examples": examples,
    }


def _features_of(segment: RouteSegment) -> EdgeFeatures:
    """Rebuild the feature record a segment was derived from.

    Only the attributes that can block a segment are needed here. Carrying the
    whole feature object onto every segment would roughly double the size of a
    route payload for the benefit of this one diagnostic path.
    """
    return EdgeFeatures(
        highway=segment.highway,
        steps=segment.steps,
        step_count=segment.step_count,
        surface=segment.surface,
        surface_class=segment.surface_class,
        smoothness_class=segment.smoothness_class,
        incline_percent=segment.incline_percent,
        kerb=segment.kerb,
        is_crossing=segment.is_crossing,
        width_m=segment.width_m,
    )


def _format_distance(metres: float) -> str:
    if metres >= 1000:
        return f"{metres / 1000:.1f} km"
    return f"{metres:.0f} m"
