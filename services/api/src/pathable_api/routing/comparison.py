"""Comparing the standard route with an accessibility-aware one.

The comparison is the product. A single "accessible route" tells someone where to
walk; showing it against the shortest route tells them *what it cost them and
why*, which is what lets them decide whether the trade is worth making today.

Every statement produced here is derived from attributes recorded in the dataset
and cites the evidence that produced it. Nothing is inferred, predicted or
softened: if the accessible route is longer, it says so, and if the data behind
it is thin, it says that too.

Why the routes differ is read from the cost model itself. Both routes are costed
under the chosen profile — the same `evaluate_edge` the router minimised — and
every constraint the profile weighs is compared: the hard limits the shortest
route breaks, and each penalty the chosen route incurs less of. One statement is
made for every constraint that differs, so nothing that shaped the route goes
unmentioned and nothing that did not is claimed. Stairs are one constraint among
several; a detour caused by kerbs, surfaces and missing data says so.

Each statement also names the kind of evidence it rests on. "A mapper recorded a
raised kerb" and "nobody recorded the kerb" are opposite facts, and labelling
both "recorded" is how an absence starts to read as an observation.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pathable_api.geo.enums import KerbType, SmoothnessClass, SurfaceClass, TriState
from pathable_api.routing.cost import (
    MARKED_CROSSING_TYPES,
    BlockReason,
    CostCode,
    EdgeCost,
    evaluate_edge,
    grade_beyond,
)
from pathable_api.routing.engine import (
    GradeExtreme,
    Route,
    RouteSegment,
    RoutingError,
    compute_route,
    summarise_gradients,
)
from pathable_api.routing.graph import RoutableGraph
from pathable_api.routing.profiles import STANDARD, MobilityProfile, plain_number

#: Below this the two routes are the same journey and saying "3 m longer" would
#: be noise dressed up as information.
_MATERIAL_DIFFERENCE_M = 15.0

#: A route where more than this fraction of the distance has missing
#: accessibility data gets an explicit caution rather than a quiet footnote.
_THIN_DATA_FRACTION = 0.5

#: Below this, a difference in what the two routes cost under one constraint is
#: arithmetic rather than something the profile's rules actually weighed.
_MATERIAL_COST_M = 1.0

#: How many segment identities a statement lists. Its counts are always
#: complete; the list is a sample for tracing a statement back to the map.
_CITED_SEGMENTS = 10

#: What a statement rests on:
#:
#: * ``recorded`` — attributes a mapper recorded in OpenStreetMap;
#: * ``estimated`` — gradients inferred from the elevation model;
#: * ``mixed`` — recorded and estimated gradients together;
#: * ``not_recorded`` — the statement is about data nobody has recorded;
#: * ``profile_rule`` — a consequence of the profile's rules, not an observation.
EvidenceBasis = Literal["recorded", "estimated", "mixed", "not_recorded", "profile_rule"]


@dataclass(frozen=True, slots=True)
class Explanation:
    """One evidence-backed statement about the accessible route."""

    code: str
    summary: str
    basis: EvidenceBasis
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

    #: For each segment of the standard route, the chosen profile's hard limit
    #: that rules it out, or None where the profile can use it. Empty when there
    #: is no standard route to compare.
    standard_exclusions: tuple[BlockReason | None, ...] = ()

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

    shortest: tuple[_Costed, ...] = ()
    if standard_route is not None and not profile.is_standard:
        # Both routes are timed at the traveller's assumed pace, so the two
        # estimates differ only because the routes do. See Route.with_pace_of.
        standard_route = standard_route.with_pace_of(profile)
        shortest = _cost_under(standard_route, profile)

    return RouteComparison(
        profile=profile,
        standard_route=standard_route,
        accessible_route=accessible_route,
        standard_failure=standard_failure,
        accessible_failure=accessible_failure,
        explanations=_explain(standard_route, accessible_route, profile),
        cautions=_cautions(standard_route, accessible_route, profile),
        standard_exclusions=tuple(item.cost.blocked_reason for item in shortest),
    )


# ---------------------------------------------------------------------------
# Costing a route under the chosen profile
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Costed:
    """One segment of a route, costed under the chosen profile."""

    segment: RouteSegment
    cost: EdgeCost

    def spent(self, code: CostCode) -> float:
        """Effective metres this segment cost under one constraint."""
        return sum(
            component.effective_metres
            for component in self.cost.components
            if component.code is code
        )


def _cost_under(route: Route, profile: MobilityProfile) -> tuple[_Costed, ...]:
    """Cost every segment of a route exactly as the router would for `profile`.

    The segment carries the full features it was costed from, so this is the
    same computation the search minimised — not a reconstruction of it.
    """
    return tuple(
        _Costed(segment, evaluate_edge(segment.features, segment.length_m, profile))
        for segment in route.segments
    )


def _anywhere(_segment: RouteSegment) -> bool:
    return True


def _spent(
    costed: Sequence[_Costed],
    code: CostCode,
    where: Callable[[RouteSegment], bool] = _anywhere,
) -> float:
    """What a route cost under one constraint, over the segments `where` selects."""
    return sum(item.spent(code) for item in costed if where(item.segment))


def _usable(costed: Sequence[_Costed], where: Callable[[RouteSegment], bool]) -> list[_Costed]:
    """The segments a route can use under the profile that `where` selects."""
    return [item for item in costed if item.cost.passable and where(item.segment)]


def _cited(items: Iterable[_Costed], used: set[str]) -> list[str]:
    """Identities of shortest-route segments the chosen route does not use.

    A statement about what the chosen route avoids must never name a segment it
    actually travels, so anything it uses is left out of the sample.
    """
    cited: list[str] = []
    for item in items:
        identity = item.segment.edge_identity
        if identity in used or identity in cited:
            continue
        cited.append(identity)
        if len(cited) == _CITED_SEGMENTS:
            break
    return cited


def _length(items: Iterable[_Costed]) -> float:
    return sum(item.segment.length_m for item in items)


def _plural(count: int, word: str) -> str:
    return word if count == 1 else f"{word}s"


def _count_of(count: int, noun: str) -> str:
    """Count a noun in words: no crossings, 1 crossing, 2 crossings."""
    if count == 0:
        return f"no {noun}s"
    return f"{count} {_plural(count, noun)}"


def _grade_basis(sources: Iterable[str | None]) -> EvidenceBasis:
    """The basis of a statement about gradients, from where they came from."""
    found = {source for source in sources if source is not None}
    if found == {"osm_incline"}:
        return "recorded"
    if "osm_incline" in found:
        return "mixed"
    return "estimated"


def _grade_kind(source: str | None) -> str:
    return "recorded" if source == "osm_incline" else "estimated"


def _grade_phrase(extreme: GradeExtreme) -> str:
    return f"{extreme.percent:.1f}% ({_grade_kind(extreme.source)})"


# ---------------------------------------------------------------------------
# Explanations
# ---------------------------------------------------------------------------


def _explain(
    standard: Route | None, accessible: Route | None, profile: MobilityProfile
) -> tuple[Explanation, ...]:
    if accessible is None or standard is None:
        return ()

    shortest = _cost_under(standard, profile)
    chosen = _cost_under(accessible, profile)
    used = {segment.edge_identity for segment in accessible.segments}

    explanations: list[Explanation] = list(_explain_hard_limits(shortest, used, profile))

    # Penalties the chosen route incurs less of, largest difference first: the
    # order is the order in which they mattered to the profile.
    penalties: list[tuple[float, Explanation]] = []
    for explainer in _PENALTY_EXPLAINERS:
        penalties.extend(explainer(shortest, chosen, used, profile))
    penalties.sort(key=lambda pair: (-pair[0], pair[1].code))
    explanations.extend(explanation for _, explanation in penalties)

    explanations.append(_explain_distance(standard, accessible))
    return tuple(explanations)


# --- Hard limits ------------------------------------------------------------


def _explain_hard_limits(
    shortest: Sequence[_Costed], used: set[str], profile: MobilityProfile
) -> list[Explanation]:
    """What on the shortest route the profile rules out altogether."""
    blocked: dict[BlockReason, list[_Costed]] = {}
    for item in shortest:
        reason = item.cost.blocked_reason
        # Foot access applies to every profile, the baseline included, so the
        # shortest route can never contain a segment blocked for that reason.
        if reason is None or reason is BlockReason.FOOT_PROHIBITED:
            continue
        blocked.setdefault(reason, []).append(item)

    explanations: list[Explanation] = []
    # In the enum's order, so the statements do not depend on where along the
    # route each barrier happens to sit.
    for reason in BlockReason:
        items = blocked.get(reason)
        if not items:
            continue
        if reason is BlockReason.STEPS:
            explanations.append(_hard_stairs(items, used))
        elif reason is BlockReason.TOO_STEEP:
            explanations.append(_hard_gradient(items, used, profile))
        elif reason is BlockReason.TOO_NARROW:
            explanations.append(_hard_width(items, used, profile))
        elif reason is BlockReason.SURFACE_EXCLUDED:
            explanations.append(_hard_surface(items, used))
        else:
            explanations.append(_hard_other(reason, items, used))
    return explanations


def _step_detail(counted: int, unrecorded: int) -> str:
    if counted and not unrecorded:
        return f"{counted} steps in total"
    if counted:
        return f"{counted} steps in total, plus {unrecorded} with no recorded step count"
    return "the step counts are not recorded"


def _hard_stairs(items: list[_Costed], used: set[str]) -> Explanation:
    segments = [item.segment for item in items]
    counted = sum(segment.step_count for segment in segments if segment.step_count)
    unrecorded = sum(1 for segment in segments if segment.step_count is None)
    count = len(segments)
    return Explanation(
        code="avoids_stairs",
        summary=(
            f"Avoids {count} recorded {_plural(count, 'stairway')} on the shortest route "
            f"({_step_detail(counted, unrecorded)}), which this profile excludes."
        ),
        basis="recorded",
        evidence={
            "hard_limit": True,
            "stairway_count": count,
            "step_count": counted,
            "stairways_without_step_count": unrecorded,
            "segments": _cited(items, used),
        },
    )


def _hard_gradient(items: list[_Costed], used: set[str], profile: MobilityProfile) -> Explanation:
    limit = profile.hard_limits.max_incline_percent
    assert limit is not None  # noqa: S101 — only this limit produces TOO_STEEP
    graded = [
        (grade, item.segment.features.grade_source)
        for item in items
        if (grade := item.segment.features.effective_grade_percent) is not None
    ]
    steepest, steepest_source = max(graded, key=lambda pair: pair[0])
    count = len(items)
    return Explanation(
        code="avoids_gradient_above_limit",
        summary=(
            f"Avoids {count} {_plural(count, 'segment')} of the shortest route that "
            f"{'climbs' if count == 1 else 'climb'} more steeply than the "
            f"{plain_number(limit)}% you set (steepest {grade_beyond(steepest, limit)}% "
            f"uphill, {_grade_kind(steepest_source)})."
        ),
        basis=_grade_basis(source for _, source in graded),
        evidence={
            "hard_limit": True,
            "segment_count": count,
            "limit_percent": limit,
            "steepest_percent": round(steepest, 2),
            "steepest_source": steepest_source,
            "segments": _cited(items, used),
        },
    )


def _hard_width(items: list[_Costed], used: set[str], profile: MobilityProfile) -> Explanation:
    limit = profile.hard_limits.min_width_m
    assert limit is not None  # noqa: S101 — only this limit produces TOO_NARROW
    widths = [item.segment.width_m for item in items if item.segment.width_m is not None]
    count = len(items)
    return Explanation(
        code="avoids_width_below_limit",
        summary=(
            f"Avoids {count} {_plural(count, 'segment')} of the shortest route narrower "
            f"than the {plain_number(limit)} m you need (narrowest recorded width "
            f"{plain_number(min(widths))} m)."
        ),
        basis="recorded",
        evidence={
            "hard_limit": True,
            "segment_count": count,
            "limit_m": limit,
            "narrowest_m": min(widths),
            "segments": _cited(items, used),
        },
    )


def _hard_surface(items: list[_Costed], used: set[str]) -> Explanation:
    values = sorted({item.segment.surface for item in items if item.segment.surface})
    described = f" ({', '.join(values)})" if values else ""
    count = len(items)
    return Explanation(
        code="avoids_excluded_surface",
        summary=(
            f"Avoids {count} {_plural(count, 'segment')} of the shortest route with a "
            f"recorded unpaved surface{described}, which you excluded."
        ),
        basis="recorded",
        evidence={
            "hard_limit": True,
            "segment_count": count,
            "surfaces": values,
            "segments": _cited(items, used),
        },
    )


def _hard_other(reason: BlockReason, items: list[_Costed], used: set[str]) -> Explanation:
    """Any hard limit without its own wording, stated from the cost model's reason."""
    count = len(items)
    return Explanation(
        code=f"avoids_{reason.value}",
        summary=(
            f"Avoids {count} {_plural(count, 'segment')} of the shortest route that this "
            f"profile excludes: {items[0].cost.blocked_detail}"
        ),
        basis="recorded",
        evidence={"hard_limit": True, "segment_count": count, "segments": _cited(items, used)},
    )


# --- Penalties ----------------------------------------------------------------

_Penalty = list[tuple[float, Explanation]]


def _penalty_stairs(
    shortest: Sequence[_Costed], chosen: Sequence[_Costed], used: set[str], _: MobilityProfile
) -> _Penalty:
    """Stairs a profile allows but charges for, such as crutches."""

    def stairway(segment: RouteSegment) -> bool:
        return segment.steps is TriState.YES

    difference = _spent(shortest, CostCode.STEPS) - _spent(chosen, CostCode.STEPS)
    if difference <= _MATERIAL_COST_M:
        return []

    theirs = _usable(shortest, stairway)
    ours = _usable(chosen, stairway)
    avoided = [item for item in theirs if item.segment.edge_identity not in used]
    counted = sum(item.segment.step_count or 0 for item in avoided)
    unrecorded = sum(1 for item in avoided if item.segment.step_count is None)
    count = len(avoided)
    return [
        (
            difference,
            Explanation(
                code="avoids_stairs",
                summary=(
                    f"Routes around {count} recorded {_plural(count, 'stairway')} on the "
                    f"shortest route ({_step_detail(counted, unrecorded)}). This profile "
                    f"allows stairs but counts every step as effort; this route has "
                    f"{_count_of(len(ours), 'recorded stairway')}."
                ),
                basis="recorded",
                evidence={
                    "hard_limit": False,
                    "stairway_count": count,
                    "step_count": counted,
                    "stairways_without_step_count": unrecorded,
                    "shortest_route_stairways": len(theirs),
                    "route_stairways": len(ours),
                    "cost_difference_effective_m": round(difference, 1),
                    "segments": _cited(avoided, used),
                },
            ),
        )
    ]


#: One statement per kerb kind the cost model charges, because each is charged
#: at its own flat rate and each is a different fact about the crossing.
_KERB_STATEMENTS: tuple[tuple[KerbType, str, str, EvidenceBasis], ...] = (
    (KerbType.RAISED, "avoids_raised_kerbs", "with a recorded raised kerb", "recorded"),
    (KerbType.ROLLED, "avoids_rolled_kerbs", "with a recorded rolled kerb", "recorded"),
    (
        KerbType.PRESENT_UNKNOWN,
        "avoids_unmeasured_kerbs",
        "where a kerb is recorded but its height is not",
        "recorded",
    ),
    (
        KerbType.UNKNOWN,
        "avoids_unrecorded_kerbs",
        "where no kerb has been recorded, so nobody has confirmed it is dropped",
        "not_recorded",
    ),
)


def _penalty_kerbs(
    shortest: Sequence[_Costed], chosen: Sequence[_Costed], used: set[str], _: MobilityProfile
) -> _Penalty:
    results: _Penalty = []
    for kerb, code, described, basis in _KERB_STATEMENTS:

        def at(segment: RouteSegment, kerb: KerbType = kerb) -> bool:
            return segment.is_crossing and segment.kerb is kerb

        difference = _spent(shortest, CostCode.KERB, at) - _spent(chosen, CostCode.KERB, at)
        if difference <= _MATERIAL_COST_M:
            continue
        theirs = _usable(shortest, at)
        ours = _usable(chosen, at)
        fewer = len(theirs) - len(ours)
        results.append(
            (
                difference,
                Explanation(
                    code=code,
                    summary=(
                        f"Avoids {fewer} {_plural(fewer, 'crossing')} {described} "
                        f"({len(ours)} on this route, {len(theirs)} on the shortest route)."
                    ),
                    basis=basis,
                    evidence={
                        "hard_limit": False,
                        "crossing_count": fewer,
                        "shortest_route_count": len(theirs),
                        "route_count": len(ours),
                        "cost_difference_effective_m": round(difference, 1),
                        "segments": _cited(theirs, used),
                    },
                ),
            )
        )
    return results


def _penalty_crossings(
    shortest: Sequence[_Costed], chosen: Sequence[_Costed], used: set[str], _: MobilityProfile
) -> _Penalty:
    """Road crossings, in the two groups the cost model charges differently."""

    def marked(segment: RouteSegment) -> bool:
        return segment.is_crossing and segment.features.crossing_type in MARKED_CROSSING_TYPES

    def unmarked(segment: RouteSegment) -> bool:
        return segment.is_crossing and segment.features.crossing_type not in MARKED_CROSSING_TYPES

    groups: tuple[tuple[Callable[[RouteSegment], bool], str, str], ...] = (
        (unmarked, "fewer_unmarked_crossings", "unmarked or unspecified"),
        (marked, "fewer_marked_crossings", "signalised or marked"),
    )
    results: _Penalty = []
    for where, code, described in groups:
        difference = _spent(shortest, CostCode.CROSSING, where) - _spent(
            chosen, CostCode.CROSSING, where
        )
        if difference <= _MATERIAL_COST_M:
            continue
        theirs = _usable(shortest, where)
        ours = _usable(chosen, where)
        results.append(
            (
                difference,
                Explanation(
                    code=code,
                    summary=(
                        f"Has {_count_of(len(ours), f'{described} road crossing')}, against "
                        f"{len(theirs)} on the shortest route."
                    ),
                    basis="recorded",
                    evidence={
                        "hard_limit": False,
                        "shortest_route_count": len(theirs),
                        "route_count": len(ours),
                        "cost_difference_effective_m": round(difference, 1),
                        "segments": _cited(theirs, used),
                    },
                ),
            )
        )
    return results


#: Surface classes the cost model charges, each stated on its own.
_SURFACE_STATEMENTS: tuple[tuple[SurfaceClass, str, str, EvidenceBasis], ...] = (
    (SurfaceClass.ROUGH, "avoids_rough_surface", "of recorded rough surface", "recorded"),
    (
        SurfaceClass.COMPACTED,
        "avoids_compacted_surface",
        "of recorded compacted or fine-gravel surface",
        "recorded",
    ),
    (
        SurfaceClass.UNKNOWN,
        "avoids_unrecorded_surface",
        "of path with no recorded surface",
        "not_recorded",
    ),
)

#: Surface-condition classes the cost model charges, each stated on its own.
_SMOOTHNESS_STATEMENTS: tuple[tuple[SmoothnessClass, str, str, EvidenceBasis], ...] = (
    (
        SmoothnessClass.BAD,
        "avoids_bad_surface_condition",
        "of path whose surface condition is recorded as bad or worse",
        "recorded",
    ),
    (
        SmoothnessClass.INTERMEDIATE,
        "avoids_intermediate_surface_condition",
        "of path whose surface condition is recorded as intermediate",
        "recorded",
    ),
    (
        SmoothnessClass.UNKNOWN,
        "avoids_unrecorded_surface_condition",
        "of path with no recorded surface condition",
        "not_recorded",
    ),
)


def _penalty_surfaces(
    shortest: Sequence[_Costed], chosen: Sequence[_Costed], used: set[str], _: MobilityProfile
) -> _Penalty:
    results: _Penalty = []
    for surface, code, described, basis in _SURFACE_STATEMENTS:

        def on(segment: RouteSegment, surface: SurfaceClass = surface) -> bool:
            return segment.surface_class is surface

        results.extend(
            _length_statement(
                shortest,
                chosen,
                used,
                (CostCode.SURFACE, on),
                (code, described, basis),
                lambda segment: segment.surface,
            )
        )
    for smoothness, code, described, basis in _SMOOTHNESS_STATEMENTS:

        def rated(segment: RouteSegment, smoothness: SmoothnessClass = smoothness) -> bool:
            return segment.smoothness_class is smoothness

        results.extend(
            _length_statement(
                shortest,
                chosen,
                used,
                (CostCode.SMOOTHNESS, rated),
                (code, described, basis),
                lambda segment: segment.features.smoothness,
            )
        )
    return results


def _length_statement(
    shortest: Sequence[_Costed],
    chosen: Sequence[_Costed],
    used: set[str],
    charged: tuple[CostCode, Callable[[RouteSegment], bool]],
    wording: tuple[str, str, EvidenceBasis],
    value_of: Callable[[RouteSegment], str | None],
) -> _Penalty:
    """A statement about a length-proportional penalty on one class of path.

    `value_of` reads the raw OpenStreetMap value the class was derived from, so
    a statement about recorded gravel can say "gravel" and a statement about
    surface condition names the condition rather than the surface.
    """
    code, where = charged
    explanation_code, described, basis = wording
    difference = _spent(shortest, code, where) - _spent(chosen, code, where)
    if difference <= _MATERIAL_COST_M:
        return []
    theirs = _usable(shortest, where)
    ours = _usable(chosen, where)
    their_length = _length(theirs)
    our_length = _length(ours)
    values = sorted(
        {
            value
            for item in theirs
            if item.segment.edge_identity not in used and (value := value_of(item.segment))
        }
    )
    # A raw value the sentence already says ("recorded as intermediate") adds
    # nothing; one it does not ("gravel", "very_bad") is the evidence itself.
    shown = [value for value in values if value not in described]
    named = f" ({', '.join(shown)})" if shown and basis == "recorded" else ""
    return [
        (
            difference,
            Explanation(
                code=explanation_code,
                summary=(
                    f"Avoids {their_length - our_length:.0f} m {described}{named} "
                    f"({our_length:.0f} m on this route, {their_length:.0f} m on the "
                    f"shortest route)."
                ),
                basis=basis,
                evidence={
                    "hard_limit": False,
                    "length_m": round(their_length - our_length, 1),
                    "shortest_route_length_m": round(their_length, 1),
                    "route_length_m": round(our_length, 1),
                    "recorded_values": values,
                    "cost_difference_effective_m": round(difference, 1),
                    "segments": _cited(theirs, used),
                },
            ),
        )
    ]


def _steeper_length(costed: Sequence[_Costed], threshold: float, *, uphill: bool) -> float:
    """Length of usable path steeper than `threshold`, climbing or descending."""
    total = 0.0
    for item in costed:
        grade = item.segment.features.effective_grade_percent
        if not item.cost.passable or grade is None:
            continue
        if (uphill and grade > threshold) or (not uphill and grade < -threshold):
            total += item.segment.length_m
    return total


def _penalty_gradient(
    shortest: Sequence[_Costed], chosen: Sequence[_Costed], used: set[str], profile: MobilityProfile
) -> _Penalty:
    """Gradient, recorded or estimated, as the profile charges it in either direction."""
    difference = _spent(shortest, CostCode.INCLINE) - _spent(chosen, CostCode.INCLINE)
    if difference <= _MATERIAL_COST_M:
        return []

    theirs = summarise_gradients(tuple(item.segment for item in shortest if item.cost.passable))
    ours = summarise_gradients(tuple(item.segment for item in chosen))
    comfortable = profile.comfortable_incline_percent
    their_climb = _steeper_length(shortest, comfortable, uphill=True)
    our_climb = _steeper_length(chosen, comfortable, uphill=True)
    their_descent = _steeper_length(shortest, comfortable, uphill=False)
    our_descent = _steeper_length(chosen, comfortable, uphill=False)

    # Only the measures that actually improved are stated, so no clause claims
    # an improvement the numbers beside it contradict.
    parts: list[str] = []
    their_steepest = theirs.steepest_uphill
    our_steepest = ours.steepest_uphill
    if their_steepest is not None and (
        our_steepest is None or our_steepest.percent < their_steepest.percent
    ):
        ours_described = (
            "it has no climb on record"
            if our_steepest is None
            else f"its steepest climb is {_grade_phrase(our_steepest)}"
        )
        parts.append(
            f"{ours_described}, against {_grade_phrase(their_steepest)} on the shortest route"
        )
    if our_climb < their_climb:
        parts.append(
            f"{our_climb:.0f} m of it climbs more steeply than this profile's comfortable "
            f"{plain_number(comfortable)}%, against {their_climb:.0f} m of the shortest route"
        )
    if our_descent < their_descent:
        parts.append(
            f"{our_descent:.0f} m of it descends more steeply than "
            f"{plain_number(comfortable)}%, against {their_descent:.0f} m"
        )
    if not parts:
        parts.append("its gradients cost less effort under this profile's rules")

    contributing = [item for item in (*shortest, *chosen) if item.spent(CostCode.INCLINE) > 0]
    return [
        (
            difference,
            Explanation(
                code="avoids_steep_gradient",
                summary="Gentler gradients than the shortest route: " + "; ".join(parts) + ".",
                basis=_grade_basis(item.segment.features.grade_source for item in contributing),
                evidence={
                    "hard_limit": False,
                    "shortest_route_steepest_uphill_percent": (
                        None if their_steepest is None else round(their_steepest.percent, 2)
                    ),
                    "shortest_route_steepest_uphill_source": (
                        None if their_steepest is None else their_steepest.source
                    ),
                    "route_steepest_uphill_percent": (
                        None if our_steepest is None else round(our_steepest.percent, 2)
                    ),
                    "route_steepest_uphill_source": (
                        None if our_steepest is None else our_steepest.source
                    ),
                    "comfortable_percent": comfortable,
                    "shortest_route_steeper_climb_m": round(their_climb, 1),
                    "route_steeper_climb_m": round(our_climb, 1),
                    "shortest_route_steeper_descent_m": round(their_descent, 1),
                    "route_steeper_descent_m": round(our_descent, 1),
                    "cost_difference_effective_m": round(difference, 1),
                    "segments": _cited(
                        (item for item in shortest if item.spent(CostCode.INCLINE) > 0), used
                    ),
                },
            ),
        )
    ]


def _penalty_width(
    shortest: Sequence[_Costed], chosen: Sequence[_Costed], used: set[str], profile: MobilityProfile
) -> _Penalty:
    """Recorded widths below what the profile prefers."""
    difference = _spent(shortest, CostCode.WIDTH) - _spent(chosen, CostCode.WIDTH)
    if difference <= _MATERIAL_COST_M or profile.narrow_width_m is None:
        return []

    theirs = [item for item in shortest if item.spent(CostCode.WIDTH) > 0]
    ours = [item for item in chosen if item.spent(CostCode.WIDTH) > 0]
    their_length = _length(theirs)
    our_length = _length(ours)
    their_narrowest = min(item.segment.width_m or 0.0 for item in theirs)
    our_widths = [item.segment.width_m for item in ours if item.segment.width_m is not None]
    preferred = plain_number(profile.narrow_width_m)

    parts: list[str] = []
    if our_length < their_length:
        parts.append(
            f"{our_length:.0f} m of it is recorded as narrower than the {preferred} m this "
            f"profile prefers, against {their_length:.0f} m of the shortest route"
        )
    if not our_widths or min(our_widths) > their_narrowest:
        narrowest = f"{plain_number(min(our_widths))} m" if our_widths else "none below"
        parts.append(
            f"its narrowest recorded width is {narrowest}, against "
            f"{plain_number(their_narrowest)} m on the shortest route"
        )
    if not parts:
        parts.append("its narrow stretches cost less under this profile's rules")

    return [
        (
            difference,
            Explanation(
                code="avoids_narrow_paths",
                summary="Fewer narrow stretches than the shortest route: " + "; ".join(parts) + ".",
                basis="recorded",
                evidence={
                    "hard_limit": False,
                    "preferred_width_m": profile.narrow_width_m,
                    "shortest_route_narrow_length_m": round(their_length, 1),
                    "route_narrow_length_m": round(our_length, 1),
                    "shortest_route_narrowest_m": their_narrowest,
                    "cost_difference_effective_m": round(difference, 1),
                    "segments": _cited(theirs, used),
                },
            ),
        )
    ]


#: The attributes whose absence the uncertainty penalty counts, and how a
#: sentence names each. Surface and smoothness are charged through their own
#: unknown classes instead, and have their own statements.
_UNCERTAIN_ATTRIBUTES: tuple[tuple[str, str], ...] = (
    ("incline", "no gradient on record"),
    ("steps", "no step information"),
    ("kerb", "no kerb recorded at a crossing"),
)


def _penalty_missing_data(
    shortest: Sequence[_Costed], chosen: Sequence[_Costed], used: set[str], profile: MobilityProfile
) -> _Penalty:
    """Missing records the profile charges as risk."""
    difference = _spent(shortest, CostCode.UNCERTAINTY) - _spent(chosen, CostCode.UNCERTAINTY)
    if difference <= _MATERIAL_COST_M:
        return []

    ignored = set(profile.ignore_unknown_attributes)

    def missing(costed: Sequence[_Costed], attribute: str) -> float:
        return _length(
            item
            for item in costed
            if item.cost.passable
            and attribute not in ignored
            and attribute in item.segment.features.unknown_attributes
        )

    parts: list[str] = []
    lengths: dict[str, dict[str, float]] = {}
    for attribute, described in _UNCERTAIN_ATTRIBUTES:
        theirs = missing(shortest, attribute)
        ours = missing(chosen, attribute)
        lengths[attribute] = {"shortest_route_m": round(theirs, 1), "route_m": round(ours, 1)}
        if ours < theirs:
            parts.append(f"{described}: {ours:.0f} m, against {theirs:.0f} m")
    if not parts:
        parts.append("less of it lacks the records this profile counts as risk")

    return [
        (
            difference,
            Explanation(
                code="avoids_unrecorded_data",
                summary="Less path with missing records than the shortest route — "
                + "; ".join(parts)
                + ".",
                basis="not_recorded",
                evidence={
                    "hard_limit": False,
                    "missing_length_m": lengths,
                    "cost_difference_effective_m": round(difference, 1),
                    "segments": _cited(
                        (item for item in shortest if item.spent(CostCode.UNCERTAINTY) > 0), used
                    ),
                },
            ),
        )
    ]


_PENALTY_EXPLAINERS: tuple[
    Callable[[Sequence[_Costed], Sequence[_Costed], set[str], MobilityProfile], _Penalty], ...
] = (
    _penalty_stairs,
    _penalty_kerbs,
    _penalty_crossings,
    _penalty_surfaces,
    _penalty_gradient,
    _penalty_width,
    _penalty_missing_data,
)


def _explain_distance(standard: Route, accessible: Route) -> Explanation:
    extra = accessible.distance_m - standard.distance_m

    if abs(extra) < _MATERIAL_DIFFERENCE_M:
        return Explanation(
            code="same_distance",
            summary="This route is essentially the same length as the shortest route.",
            basis="profile_rule",
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
        basis="profile_rule",
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

    Each segment is costed from the features it carries. This used to rebuild
    them from a handful of copied fields, which dropped the derived grade — so a
    slope limit that blocked only estimated gradients reported no reason at all.
    """
    if standard is None:
        return {}

    reasons: dict[str, int] = {}
    examples: list[str] = []
    for item in _cost_under(standard, profile):
        cost = item.cost
        if cost.passable or cost.blocked_reason is None:
            continue
        reasons[cost.blocked_reason.value] = reasons.get(cost.blocked_reason.value, 0) + 1
        if len(examples) < 5:
            segment = item.segment
            examples.append(f"{segment.name or segment.edge_identity}: {cost.blocked_detail}")

    return {
        "blocked_segments_on_shortest_route": sum(reasons.values()),
        "reasons": reasons,
        "examples": examples,
    }


def _format_distance(metres: float) -> str:
    if metres >= 1000:
        return f"{metres / 1000:.1f} km"
    return f"{metres:.0f} m"
