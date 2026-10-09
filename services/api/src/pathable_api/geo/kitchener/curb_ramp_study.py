"""The curb-ramp shadow-routing study: the same journeys, routed on the baseline and on the shadow (PA-GEO-09).

Every route is computed by PathAble's own router and explained by its own
comparison, with the production profiles and cost model. The only difference
between the two runs of a journey is the graph: the loaded dataset, or the
shadow copy in which eligible City curb ramps replace an unknown kerb on their
crossing segment (:mod:`curb_ramp_shadow`).

Each journey and profile lands in exactly one category, the most consequential
that applies, as PA-GEO-07 defined them:

- ``feasibility_changed`` — a route exists in one run and not the other (kerb
  evidence has no hard-limit path, so any such case is a defect to explain);
- ``route_changed_weighted_preference`` — both runs route, differently;
- ``cost_only_same_path`` — the same path at a different accessibility cost;
- ``evidence_only`` — the same path and cost, with what the product says
  about kerbs changed;
- ``no_effect`` — a route meets a substituted crossing and nothing changes;
- ``not_exposed`` — neither route touches one.

A change on a journey where neither path meets a substituted crossing is
``unexplained`` and counted as a defect.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from pathable_api.geo.enums import KerbType
from pathable_api.geo.features import EdgeFeatures
from pathable_api.geo.geometry import geodesic_distance_m
from pathable_api.geo.kitchener.curb_ramp_shadow import Substitution
from pathable_api.geo.kitchener.shadow_study import (
    Category,
    Journey,
    Pair,
    _offset,
    _order,
    _point,
    chosen_route,
    compare_on,
)
from pathable_api.routing.comparison import RouteComparison
from pathable_api.routing.cost import CostCode, evaluate_edge
from pathable_api.routing.engine import Route
from pathable_api.routing.graph import RoutableEdge, RoutableGraph
from pathable_api.routing.profiles import MobilityProfile

BROAD_CORPUS_VERSION = "geo07-broad-corpus-v1"
TARGETED_CORPUS_VERSION = "geo09-targeted-corpus-v1"

#: Targeted journeys start and end this far either side of a substituted
#: crossing, along the crossing's own direction, so the journey crosses the
#: road there or nearby.
TARGETED_HALF_SPAN_M = 250.0
TARGETED_DENSE_RADIUS_M = 200.0
TARGETED_DENSE_COUNT = 3
TARGETED_PER_STRATUM = 12

CHANGED = frozenset({Category.FEASIBILITY_CHANGED, Category.ROUTE_CHANGED, Category.COST_ONLY})


# ---------------------------------------------------------------------------
# Targeted journeys
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Anchor:
    """One substituted crossing segment, as a place to route across."""

    identity: str
    records: tuple[int, ...]
    ends_asserted: int
    marked: bool
    midpoint: tuple[float, float]
    #: Unit direction along the crossing, in east/north metres.
    direction: tuple[float, float]
    neighbours: int = 0

    @property
    def stratum(self) -> str:
        ends = "both_ends" if self.ends_asserted >= 2 else "one_end"
        marking = "marked" if self.marked else "unmarked"
        density = "dense" if self.neighbours >= TARGETED_DENSE_COUNT else "sparse"
        return f"{ends}/{marking}/{density}"


_METRES_PER_DEGREE_LAT = 111_320.0


def anchors(graph: RoutableGraph, substitutions: Mapping[str, Substitution]) -> list[Anchor]:
    """Every substituted crossing segment: where it is and which way it runs."""
    by_identity = {e.identity: e for e in graph.segments}
    found: list[Anchor] = []
    for identity in sorted(substitutions):
        edge = by_identity.get(identity)
        if edge is None:
            continue
        item = substitutions[identity]
        coords = list(edge.geometry.coords)
        lon = sum(p[0] for p in coords) / len(coords)
        lat = sum(p[1] for p in coords) / len(coords)
        per_lon = _METRES_PER_DEGREE_LAT * math.cos(math.radians(lat))
        dx = (coords[-1][0] - coords[0][0]) * per_lon
        dy = (coords[-1][1] - coords[0][1]) * _METRES_PER_DEGREE_LAT
        norm = math.hypot(dx, dy) or 1.0
        found.append(
            Anchor(
                identity,
                item.records,
                item.ends_asserted,
                item.marked,
                (lon, lat),
                (dx / norm, dy / norm) if math.hypot(dx, dy) else (1.0, 0.0),
            )
        )
    for i, anchor in enumerate(found):
        near = sum(
            1
            for j, other in enumerate(found)
            if i != j
            and geodesic_distance_m(_point(anchor.midpoint), _point(other.midpoint))
            <= TARGETED_DENSE_RADIUS_M
        )
        found[i] = replace(anchor, neighbours=near)
    return found


def targeted_corpus(
    found: Sequence[Anchor],
    *,
    seed: str,
    per_stratum: int = TARGETED_PER_STRATUM,
    routable: Callable[[tuple[float, float], tuple[float, float]], bool] | None = None,
) -> list[Journey]:
    """Journeys across the substituted crossings, a few per stratum. Targeted on purpose."""
    strata: dict[str, list[Anchor]] = defaultdict(list)
    for anchor in sorted(found, key=lambda a: _order(seed, a.identity)):
        strata[anchor.stratum].append(anchor)
    journeys: list[Journey] = []
    for stratum in sorted(strata):
        taken = 0
        for anchor in strata[stratum]:
            if taken >= per_stratum:
                break
            east, north = anchor.direction
            origin = _offset(
                anchor.midpoint, -east * TARGETED_HALF_SPAN_M, -north * TARGETED_HALF_SPAN_M
            )
            destination = _offset(
                anchor.midpoint, east * TARGETED_HALF_SPAN_M, north * TARGETED_HALF_SPAN_M
            )
            if routable is not None and not routable(origin, destination):
                continue
            journeys.append(
                Journey(
                    f"B{len(journeys):03d}",
                    "targeted",
                    (round(origin[0], 7), round(origin[1], 7)),
                    (round(destination[0], 7), round(destination[1], 7)),
                    stratum,
                    anchor.records,
                )
            )
            taken += 1
    return journeys


# ---------------------------------------------------------------------------
# One route, summarised
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KerbRouteFacts:
    exists: bool
    failure: str | None = None
    path: tuple[str, ...] = ()
    distance_m: float = 0.0
    effective_m: float = 0.0
    #: Every cost component total, by code.
    cost_by_code: Mapping[str, float] = field(default_factory=dict)
    kerb_cost_m: float = 0.0
    uncertainty_cost_m: float = 0.0
    crossings: int = 0
    unknown_kerb_crossings: int = 0
    #: Substituted crossing segments on this route.
    substituted: tuple[str, ...] = ()
    substituted_m: float = 0.0
    #: The same on the standard route the explanation compares this one with.
    standard_substituted: tuple[str, ...] = ()
    records: tuple[int, ...] = ()
    explanation_codes: tuple[str, ...] = ()
    caution_codes: tuple[str, ...] = ()
    explanation_digest: str = ""
    origin: str | None = None
    destination: str | None = None
    algorithm: str | None = None
    computation_ms: float = 0.0

    def outcome(self) -> dict[str, Any]:
        """Everything but the timing: what determinism is checked on."""
        found = asdict(self)
        found.pop("computation_ms")
        found["cost_by_code"] = dict(sorted(self.cost_by_code.items()))
        return found


def route_facts(
    comparison: RouteComparison,
    profile: MobilityProfile,
    substitutions: Mapping[str, Substitution],
) -> KerbRouteFacts:
    route, failure = chosen_route(comparison, profile)
    explanations = tuple(sorted({e.code for e in comparison.explanations}))
    cautions = tuple(sorted({c.code for c in comparison.cautions}))
    stated = sorted(
        [("explanation", e.code, e.summary) for e in comparison.explanations]
        + [("caution", c.code, c.summary) for c in comparison.cautions]
    )
    digest = hashlib.sha256(json.dumps(stated).encode("utf-8")).hexdigest()[:16]
    standard = comparison.standard_route
    standard_substituted = (
        tuple(s.edge_identity for s in standard.segments if s.edge_identity in substitutions)
        if standard is not None
        else ()
    )
    if route is None:
        return KerbRouteFacts(
            False,
            failure,
            standard_substituted=standard_substituted,
            explanation_codes=explanations,
            caution_codes=cautions,
            explanation_digest=digest,
        )
    by_code: dict[str, float] = defaultdict(float)
    substituted: list[str] = []
    substituted_m = 0.0
    records: set[int] = set()
    for segment in route.segments:
        for component in segment.cost_components:
            by_code[str(component.code)] += component.effective_metres
        item = substitutions.get(segment.edge_identity)
        if item is not None:
            substituted.append(segment.edge_identity)
            substituted_m += segment.length_m
            records.update(item.records)
    return KerbRouteFacts(
        exists=True,
        path=tuple(s.edge_identity for s in route.segments),
        distance_m=round(route.distance_m, 3),
        effective_m=round(route.effective_distance_m, 3),
        cost_by_code={k: round(v, 3) for k, v in sorted(by_code.items())},
        kerb_cost_m=round(by_code.get(str(CostCode.KERB), 0.0), 3),
        uncertainty_cost_m=round(by_code.get(str(CostCode.UNCERTAINTY), 0.0), 3),
        crossings=route.crossing_count,
        unknown_kerb_crossings=route.unknown_kerb_crossing_count,
        substituted=tuple(substituted),
        substituted_m=round(substituted_m, 3),
        standard_substituted=standard_substituted,
        records=tuple(sorted(records)),
        explanation_codes=explanations,
        caution_codes=cautions,
        explanation_digest=digest,
        origin=route.origin.node_id,
        destination=route.destination.node_id,
        algorithm=str(route.algorithm),
        computation_ms=round(route.computation_ms, 3),
    )


# ---------------------------------------------------------------------------
# Baseline against shadow
# ---------------------------------------------------------------------------


def kerb_lookup(graph: RoutableGraph) -> dict[str, KerbType]:
    return {e.identity: e.features.kerb for e in graph.segments}


def _with_kerb(
    features: EdgeFeatures, lookup: Mapping[str, KerbType], identity: str
) -> EdgeFeatures:
    kerb = lookup.get(identity, features.kerb)
    return features if kerb is features.kerb else replace(features, kerb=kerb)


def cost_under(route: Route, lookup: Mapping[str, KerbType], profile: MobilityProfile) -> float:
    """What this exact path costs with another graph's kerbs: segment by segment, oriented."""
    total = 0.0
    for segment in route.segments:
        features = _with_kerb(segment.features, lookup, segment.edge_identity)
        total += evaluate_edge(features, segment.length_m, profile).effective_metres
    return total


def kerb_cost_under(
    route: Route, lookup: Mapping[str, KerbType], profile: MobilityProfile
) -> float:
    """Only the flat kerb penalties of this path with another graph's kerbs."""
    total = 0.0
    for segment in route.segments:
        features = _with_kerb(segment.features, lookup, segment.edge_identity)
        found = evaluate_edge(features, segment.length_m, profile)
        total += sum(c.effective_metres for c in found.components if c.code is CostCode.KERB)
    return total


def newly_blocked(
    route: Route, lookup: Mapping[str, KerbType], profile: MobilityProfile
) -> list[str]:
    """Segments of this path the other graph's kerbs make unusable. Always empty: no hard limit reads a kerb."""
    blocked = []
    for segment in route.segments:
        features = _with_kerb(segment.features, lookup, segment.edge_identity)
        if features is segment.features:
            continue
        if not evaluate_edge(features, segment.length_m, profile).passable:
            blocked.append(segment.edge_identity)
    return blocked


def classify(base: KerbRouteFacts, shadow: KerbRouteFacts, *, blocked: bool) -> Category:
    exposed = any(f.substituted or f.standard_substituted for f in (base, shadow))
    if not base.exists and not shadow.exists:
        return Category.NO_ROUTE_EITHER
    if base.exists != shadow.exists or blocked:
        return Category.FEASIBILITY_CHANGED
    if (base.path, base.origin, base.destination) != (
        shadow.path,
        shadow.origin,
        shadow.destination,
    ):
        return Category.ROUTE_CHANGED
    if abs(base.effective_m - shadow.effective_m) > 1e-6:
        return Category.COST_ONLY
    evidence = ("unknown_kerb_crossings", "explanation_digest")
    if any(getattr(base, name) != getattr(shadow, name) for name in evidence):
        return Category.EVIDENCE_ONLY
    return Category.NO_EFFECT if exposed else Category.NOT_EXPOSED


def feasibility_direction(base: KerbRouteFacts, shadow: KerbRouteFacts) -> str | None:
    if base.exists and not shadow.exists:
        return "route_to_no_route"
    if shadow.exists and not base.exists:
        return "no_route_to_route"
    return None


@dataclass(slots=True)
class Result:
    journey: Journey
    profile_key: str
    base: KerbRouteFacts
    shadow: KerbRouteFacts
    category: Category
    #: For a changed path: the costs of both paths under both graphs, and why.
    cause: dict[str, Any] | None = None
    blocked: tuple[str, ...] = ()
    #: A change on a journey where neither route meets a substituted crossing: a defect.
    unexplained: bool = False
    feasibility: str | None = None


def _substituted_segments(
    route: Route, substitutions: Mapping[str, Substitution], baseline: Mapping[str, KerbType]
) -> list[dict[str, Any]]:
    found = []
    for segment in route.segments:
        item = substitutions.get(segment.edge_identity)
        if item is None:
            continue
        found.append(
            {
                "segment": segment.edge_identity,
                "length_m": round(segment.length_m, 2),
                "kerb_before": baseline.get(segment.edge_identity, KerbType.UNKNOWN).value,
                "kerb_shadow": item.kerb_shadow.value,
                "ends_asserted": item.ends_asserted,
                "records": list(item.records),
            }
        )
    return found


def _cost(value: float) -> float | None:
    return round(value, 3) if math.isfinite(value) else None


def _said(route: str, value: float) -> str:
    return f"{route} costs {value:.1f}" if math.isfinite(value) else f"{route} cannot be used"


def explain_change(
    base_route: Route,
    shadow_route: Route,
    profile: MobilityProfile,
    substitutions: Mapping[str, Substitution],
    base_lookup: Mapping[str, KerbType],
    shadow_lookup: Mapping[str, KerbType],
) -> dict[str, Any]:
    """Why the chosen path moved, from the costs: each path, under each graph."""
    a_base = cost_under(base_route, base_lookup, profile)
    a_shadow = cost_under(base_route, shadow_lookup, profile)
    b_base = cost_under(shadow_route, base_lookup, profile)
    b_shadow = cost_under(shadow_route, shadow_lookup, profile)
    parts = [
        f"Baseline, in effective metres: {_said('route A', a_base)}, "
        f"{_said('route B', b_base)}; A is chosen.",
    ]
    if a_shadow - a_base < -1e-6:
        parts.append(f"City curb ramps on A's crossings lower its cost by {a_base - a_shadow:.1f}.")
    elif a_shadow - a_base > 1e-6:
        parts.append(f"A's cost rises by {a_shadow - a_base:.1f} in the shadow (unexpected).")
    b_moved = b_shadow - b_base if math.isfinite(b_shadow) and math.isfinite(b_base) else 0.0
    if b_moved < -1e-6:
        parts.append(
            f"City curb ramps on B's crossings lower its cost by {-b_moved:.1f} (an unrecorded "
            "kerb's flat penalty and its share of the missing-data penalty removed)."
        )
    elif b_moved > 1e-6:
        parts.append(f"B's cost rises by {b_moved:.1f} in the shadow (unexpected).")
    parts.append(
        f"Shadow: {_said('route A', a_shadow)}, {_said('route B', b_shadow)}; B is chosen."
    )
    kerb_a = kerb_cost_under(base_route, base_lookup, profile)
    kerb_b = kerb_cost_under(shadow_route, shadow_lookup, profile)
    kerb_b_baseline = kerb_cost_under(shadow_route, base_lookup, profile)
    return {
        "route_a_baseline": {
            "distance_m": round(base_route.distance_m, 2),
            "cost_baseline": _cost(a_base),
            "cost_shadow": _cost(a_shadow),
            "kerb_cost_m": round(kerb_a, 3),
            "unknown_kerb_crossings": base_route.unknown_kerb_crossing_count,
            "substituted_segments": _substituted_segments(base_route, substitutions, base_lookup),
        },
        "route_b_shadow": {
            "distance_m": round(shadow_route.distance_m, 2),
            "cost_baseline": _cost(b_base),
            "cost_shadow": _cost(b_shadow),
            "kerb_cost_m": round(kerb_b, 3),
            "kerb_cost_under_baseline_m": round(kerb_b_baseline, 3),
            "unknown_kerb_crossings": shadow_route.unknown_kerb_crossing_count,
            "substituted_segments": _substituted_segments(shadow_route, substitutions, base_lookup),
        },
        "distance_delta_m": round(shadow_route.distance_m - base_route.distance_m, 2),
        "cost_delta_m": _cost(b_shadow - a_base),
        "kerb_cost_delta_m": round(kerb_b - kerb_a, 3),
        "kerb_saving_on_route_b_m": round(kerb_b_baseline - kerb_b, 3),
        "cause": " ".join(parts),
        "records": sorted(
            {
                r
                for p in (base_route, shadow_route)
                for s in p.segments
                for r in (
                    substitutions[s.edge_identity].records
                    if s.edge_identity in substitutions
                    else ()
                )
            }
        ),
    }


def assess(
    journey: Journey,
    profile: MobilityProfile,
    base: KerbRouteFacts,
    other_cmp: RouteComparison,
    substitutions: Mapping[str, Substitution],
    lookups: tuple[Mapping[str, KerbType], Mapping[str, KerbType]],
    baseline_cmp: Callable[[], RouteComparison],
) -> tuple[Result, Pair | None]:
    """Compare the shadow's answer with the baseline's."""
    other = route_facts(other_cmp, profile, substitutions)
    other_route, _ = chosen_route(other_cmp, profile)
    blocked: tuple[str, ...] = ()
    base_cmp: RouteComparison | None = None
    if base.exists and base.substituted:
        base_cmp = baseline_cmp()
        base_route, _ = chosen_route(base_cmp, profile)
        if base_route is not None:
            blocked = tuple(newly_blocked(base_route, lookups[1], profile))
    category = classify(base, other, blocked=bool(blocked))
    cause = None
    if category in (Category.ROUTE_CHANGED, Category.FEASIBILITY_CHANGED) and other_route:
        base_cmp = base_cmp or baseline_cmp()
        base_route, _ = chosen_route(base_cmp, profile)
        if base_route is not None:
            cause = explain_change(
                base_route, other_route, profile, substitutions, lookups[0], lookups[1]
            )
    unexplained = category in CHANGED and not (base.substituted or other.substituted)
    kept = Pair(base_cmp, other_cmp) if cause is not None and base_cmp is not None else None
    return (
        Result(
            journey,
            profile.key,
            base,
            other,
            category,
            cause,
            blocked,
            unexplained,
            feasibility_direction(base, other),
        ),
        kept,
    )


def run_pair(
    journey: Journey,
    profile: MobilityProfile,
    baseline: RoutableGraph,
    shadow: RoutableGraph,
    substitutions: Mapping[str, Substitution],
    lookups: tuple[Mapping[str, KerbType], Mapping[str, KerbType]],
) -> tuple[Result, Pair | None]:
    """One journey for one profile on both graphs."""
    base_cmp = compare_on(baseline, journey, profile)
    return assess(
        journey,
        profile,
        route_facts(base_cmp, profile, substitutions),
        compare_on(shadow, journey, profile),
        substitutions,
        lookups,
        lambda: base_cmp,
    )


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


def _describe(values: Sequence[float]) -> dict[str, Any] | None:
    if not values:
        return None
    return {
        "n": len(values),
        "min": round(min(values), 2),
        "median": round(statistics.median(values), 2),
        "max": round(max(values), 2),
    }


def summarise_results(results: Sequence[Result]) -> dict[str, Any]:
    """Per corpus and profile: categories, exposure, kerb evidence and cost change, route changes."""
    out: dict[str, Any] = {}
    groups: dict[tuple[str, str], list[Result]] = defaultdict(list)
    for r in results:
        groups[(r.journey.corpus, r.profile_key)].append(r)
    for (corpus, profile), rows in sorted(groups.items()):
        changed = [r for r in rows if r.cause is not None]
        both = [r for r in rows if r.base.exists and r.shadow.exists]
        out.setdefault(corpus, {})[profile] = {
            "journeys": len(rows),
            "categories": dict(sorted(Counter(str(r.category) for r in rows).items())),
            "routes_on_substituted_crossings": sum(1 for r in rows if r.shadow.substituted),
            "standard_routes_on_substituted_crossings": sum(
                1 for r in rows if r.shadow.standard_substituted
            ),
            "cost_changed": sum(
                1 for r in both if abs(r.base.effective_m - r.shadow.effective_m) > 1e-6
            ),
            "path_changed": sum(1 for r in both if r.base.path != r.shadow.path),
            "feasibility_changed": sum(
                1 for r in rows if r.category is Category.FEASIBILITY_CHANGED
            ),
            "feasibility_direction": dict(
                sorted(Counter(r.feasibility for r in rows if r.feasibility).items())
            ),
            "unexplained_changes": sum(1 for r in rows if r.unexplained),
            "kerb_evidence_on_routes": {
                "baseline_unknown_kerb_crossings": sum(r.base.unknown_kerb_crossings for r in both),
                "shadow_unknown_kerb_crossings": sum(r.shadow.unknown_kerb_crossings for r in both),
                "crossings_on_routes": sum(r.shadow.crossings for r in both),
                "substituted_crossings_on_shadow_routes": sum(
                    len(r.shadow.substituted) for r in rows
                ),
            },
            "cost_deltas": {
                "effective_m": _describe(
                    [round(r.shadow.effective_m - r.base.effective_m, 3) for r in both]
                ),
                "kerb_cost_m": _describe(
                    [round(r.shadow.kerb_cost_m - r.base.kerb_cost_m, 3) for r in both]
                ),
                "physical_distance_m": _describe(
                    [round(r.shadow.distance_m - r.base.distance_m, 3) for r in both]
                ),
            },
            "changed_routes": {
                "count": len(changed),
                "distance_delta_m": _describe(
                    [c.cause["distance_delta_m"] for c in changed if c.cause]
                ),
                "cost_delta_m": _describe(
                    [
                        c.cause["cost_delta_m"]
                        for c in changed
                        if c.cause and c.cause["cost_delta_m"] is not None
                    ]
                ),
                "kerb_cost_delta_m": _describe(
                    [c.cause["kerb_cost_delta_m"] for c in changed if c.cause]
                ),
            },
        }
    return out


def results_digest(results: Iterable[Result]) -> str:
    """Every outcome of a run, without timings: two runs must match on this."""
    lines = [
        json.dumps(
            [
                r.journey.journey_id,
                r.profile_key,
                str(r.category),
                r.base.outcome(),
                r.shadow.outcome(),
                r.cause,
                list(r.blocked),
                r.unexplained,
                r.feasibility,
            ],
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        for r in sorted(results, key=lambda r: (r.journey.journey_id, r.profile_key))
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return round(ordered[index], 3)


def timing(results: Sequence[Result]) -> dict[str, Any]:
    """Per-route computation times, as the router measured them."""
    values = [facts.computation_ms for r in results for facts in (r.base, r.shadow) if facts.exists]
    return {
        "routes": len(values),
        "p50_ms": _quantile(values, 0.50),
        "p95_ms": _quantile(values, 0.95),
        "p99_ms": _quantile(values, 0.99),
        "max_ms": round(max(values), 3) if values else None,
    }


def segments_by_identity(graph: RoutableGraph) -> dict[str, RoutableEdge]:
    return {e.identity: e for e in graph.segments}
