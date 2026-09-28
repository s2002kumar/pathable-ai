"""The shadow-routing study: the same journeys, routed on the baseline and on the overlay.

Every route here is computed by PathAble's own router and explained by its own
comparison (:func:`pathable_api.routing.comparison.compare_routes`), with the
production profiles and cost model. The only difference between the two runs
of a journey is the graph: the loaded dataset, or the shadow graph with the
City's surface assertions filled in (:mod:`shadow_overlay`).

Each journey and profile is put in exactly one category, the most consequential
that applies:

- ``feasibility_changed`` — a route exists in one run and not the other, or the
  baseline route uses a segment the overlay makes unusable;
- ``route_changed_weighted_preference`` — both runs route, differently;
- ``cost_only_same_path`` — the same path at a different accessibility cost;
- ``evidence_only`` — the same path and cost, with different surface evidence;
- ``no_effect`` — the route crosses filled segments and nothing changes;
- ``not_exposed`` — neither route touches a filled segment.

A changed route is explained from the costs themselves: what each path cost in
each run, and which City assertions on which segments moved them. Nothing here
says the shadow route is better, safer or correct.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from typing import Any

from pathable_api.geo.enums import SurfaceClass
from pathable_api.geo.features import EdgeFeatures
from pathable_api.geo.geometry import geodesic_distance_m
from pathable_api.geo.kitchener.shadow_overlay import Fill
from pathable_api.routing.comparison import RouteComparison, compare_routes
from pathable_api.routing.cost import CostCode, evaluate_edge
from pathable_api.routing.engine import Route, RoutingError, compute_route
from pathable_api.routing.graph import RoutableEdge, RoutableGraph
from pathable_api.routing.profiles import (
    ROUTING_POLICY_VERSION,
    SELECTABLE_PROFILE_KEYS,
    STANDARD,
    MobilityProfile,
    build_custom_profile,
    get_profile,
)
from pathable_api.routing.search import Algorithm

BROAD_CORPUS_VERSION = "geo07-broad-corpus-v1"
TARGETED_CORPUS_VERSION = "geo07-targeted-corpus-v1"
CUSTOM_ROUGH_KEY = "custom:wheelchair+avoid_rough_surface"

#: Broad-corpus journeys: straight-line length bounds, a grid over the pilot so
#: origins spread across it, and the seed of the hash order nodes are drawn in.
BROAD_MIN_M = 800.0
BROAD_MAX_M = 3_000.0
BROAD_GRID = 6
#: Targeted journeys start and end this far either side of a filled extent.
TARGETED_HALF_SPAN_M = 250.0
#: A filled extent at least this long is "long"; anchors within this distance
#: of at least this many others are "dense".
TARGETED_LONG_M = 40.0
TARGETED_DENSE_RADIUS_M = 200.0
TARGETED_DENSE_COUNT = 3
TARGETED_PER_STRATUM = 6


class Category(StrEnum):
    FEASIBILITY_CHANGED = "feasibility_changed"
    ROUTE_CHANGED = "route_changed_weighted_preference"
    COST_ONLY = "cost_only_same_path"
    EVIDENCE_ONLY = "evidence_only"
    NO_EFFECT = "no_effect"
    NOT_EXPOSED = "not_exposed"
    NO_ROUTE_EITHER = "no_route_in_either"


def study_profiles() -> list[MobilityProfile]:
    """Every production profile, and the one custom requirement surface can make hard."""
    custom = build_custom_profile(base="wheelchair", avoid_rough_surface=True)
    return [
        STANDARD,
        *(get_profile(key) for key in SELECTABLE_PROFILE_KEYS),
        replace(custom, key=CUSTOM_ROUGH_KEY),
    ]


def surface_rules(profiles: Sequence[MobilityProfile]) -> dict[str, Any]:
    """How each profile uses surface today, read from the profiles themselves."""
    return {
        "routing_policy_version": ROUTING_POLICY_VERSION,
        "profiles": {
            p.key: {
                "surface_penalty_per_metre": {
                    str(k): v for k, v in sorted(p.surface_penalty.items(), key=lambda i: str(i[0]))
                },
                "excludes_rough_surface": p.hard_limits.exclude_rough_surface,
                "uncertainty_counts_surface": False,
            }
            for p in profiles
        },
        "mechanisms": [
            "A surface class multiplies the segment's length by the profile's penalty for it "
            "(cost.py _surface_cost); PAVED has no penalty, UNKNOWN has its own.",
            "Surface is never counted again in the missing-data uncertainty penalty "
            "(cost.py _uncertainty_cost excludes it).",
            "Only a declared hard limit excludes: exclude_rough_surface blocks a segment "
            "recorded ROUGH (cost.py _hard_constraint). No preset sets it; a custom profile can.",
            "A missing surface is never a reason to exclude.",
            "Explanations and the per-category missing-data share read surface_class "
            "(comparison.py _penalty_surfaces, engine.py Route.evidence_coverage).",
        ],
    }


# ---------------------------------------------------------------------------
# Journeys
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Journey:
    journey_id: str
    corpus: str
    origin: tuple[float, float]
    destination: tuple[float, float]
    stratum: str | None = None
    anchor_records: tuple[int, ...] = ()


def corpus_digest(journeys: Sequence[Journey]) -> str:
    payload = json.dumps([asdict(j) for j in journeys], separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _order(seed: str, key: str) -> str:
    return hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()


def broad_corpus(
    graph: RoutableGraph,
    *,
    size: int,
    seed: str,
    bounds: tuple[float, float, float, float],
    routable: Callable[[tuple[float, float], tuple[float, float]], bool] | None = None,
) -> list[Journey]:
    """Journeys across the whole pilot, chosen without looking at any City evidence.

    Origins cycle through a grid over the pilot, each cell's nodes in seeded hash
    order; each destination is the first node in another hash order at a
    walking distance. A journey is kept when the standard route exists.
    """
    west, south, east, north = bounds
    walkable: set[str] = set()
    for edge in graph.segments:
        if not (
            edge.features.foot_access.is_prohibited or edge.features.general_access.is_prohibited
        ):
            walkable.update((edge.source_u, edge.source_v))
    cells: dict[int, list[str]] = defaultdict(list)
    for node in sorted(walkable, key=lambda n: _order(seed, n)):
        lon, lat = graph.node_positions[node]
        if not (west <= lon <= east and south <= lat <= north):
            continue
        col = min(int((lon - west) / (east - west) * BROAD_GRID), BROAD_GRID - 1)
        row = min(int((lat - south) / (north - south) * BROAD_GRID), BROAD_GRID - 1)
        cells[row * BROAD_GRID + col].append(node)
    destinations = sorted(walkable, key=lambda n: _order(f"{seed}:destination", n))
    used: dict[int, int] = defaultdict(int)
    journeys: list[Journey] = []
    order = [c for c in range(BROAD_GRID * BROAD_GRID) if cells.get(c)]
    attempts = 0
    while len(journeys) < size and order and attempts < size * 50:
        cell = order[attempts % len(order)]
        attempts += 1
        if used[cell] >= len(cells[cell]):
            continue
        origin_node = cells[cell][used[cell]]
        used[cell] += 1
        origin = graph.node_positions[origin_node]
        start = int(_order(seed, origin_node)[:8], 16) % len(destinations)
        destination = None
        for offset in range(len(destinations)):
            candidate = graph.node_positions[destinations[(start + offset) % len(destinations)]]
            span = geodesic_distance_m(_point(origin), _point(candidate))
            if BROAD_MIN_M <= span <= BROAD_MAX_M:
                destination = candidate
                break
        if destination is None:
            continue
        if routable is not None and not routable(origin, destination):
            continue
        journeys.append(Journey(f"A{len(journeys):03d}", "broad", origin, destination))
    return journeys


def _point(position: tuple[float, float]) -> Any:
    from shapely.geometry import Point

    return Point(*position)


@dataclass(frozen=True, slots=True)
class Anchor:
    """One City record the overlay fills, as a place to route past."""

    record_id: int
    surface_class: SurfaceClass
    filled_m: float
    midpoint: tuple[float, float]
    #: Unit direction of the filled extent, in east/north metres.
    direction: tuple[float, float]
    neighbours: int = 0

    @property
    def stratum(self) -> str:
        length = "long" if self.filled_m >= TARGETED_LONG_M else "short"
        density = "dense" if self.neighbours >= TARGETED_DENSE_COUNT else "sparse"
        return f"{self.surface_class.value}/{length}/{density}"


_METRES_PER_DEGREE_LAT = 111_320.0


def _offset(position: tuple[float, float], east_m: float, north_m: float) -> tuple[float, float]:
    lon, lat = position
    per_lon = _METRES_PER_DEGREE_LAT * math.cos(math.radians(lat))
    return (lon + east_m / per_lon, lat + north_m / _METRES_PER_DEGREE_LAT)


def anchors(graph: RoutableGraph, fills: Mapping[str, Fill]) -> list[Anchor]:
    """Every City record the overlay fills: where its filled segments are, and which way they run."""
    by_identity = {e.identity: e for e in graph.segments}
    pieces: dict[int, list[tuple[RoutableEdge, SurfaceClass]]] = defaultdict(list)
    for fill in fills.values():
        edge = by_identity.get(fill.identity)
        if edge is None:
            continue
        for record in fill.records:
            pieces[record].append((edge, fill.surface_class))
    found: list[Anchor] = []
    for record in sorted(pieces):
        edges = pieces[record]
        classes = Counter(cls for _e, cls in edges)
        cls = min(classes, key=lambda c: (-classes[c], str(c)))
        coords = [pt for edge, _c in edges for pt in edge.geometry.coords]
        lon = sum(p[0] for p in coords) / len(coords)
        lat = sum(p[1] for p in coords) / len(coords)
        first, last = edges[0][0].geometry.coords[0], edges[-1][0].geometry.coords[-1]
        per_lon = _METRES_PER_DEGREE_LAT * math.cos(math.radians(lat))
        dx = (last[0] - first[0]) * per_lon
        dy = (last[1] - first[1]) * _METRES_PER_DEGREE_LAT
        norm = math.hypot(dx, dy) or 1.0
        found.append(
            Anchor(
                record,
                cls,
                round(sum(e.length_m for e, _c in edges), 2),
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
    """Journeys that pass the City's filled extents, a few per stratum. Targeted on purpose."""
    strata: dict[str, list[Anchor]] = defaultdict(list)
    for anchor in sorted(found, key=lambda a: _order(seed, str(a.record_id))):
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
                    (anchor.record_id,),
                )
            )
            taken += 1
    return journeys


# ---------------------------------------------------------------------------
# One route, summarised
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RouteFacts:
    exists: bool
    failure: str | None = None
    path: tuple[str, ...] = ()
    distance_m: float = 0.0
    effective_m: float = 0.0
    surface_known_m: float = 0.0
    surface_unknown_m: float = 0.0
    #: Metres of this route on segments the overlay fills.
    overlay_m: float = 0.0
    #: The same, on the standard route the explanation compares this one with:
    #: evidence there changes what the explanation says, even when this route
    #: touches none.
    standard_overlay_m: float = 0.0
    overlay_by_class: Mapping[str, float] = field(default_factory=dict)
    overlay_records: tuple[int, ...] = ()
    surface_cost_m: float = 0.0
    uncertainty_cost_m: float = 0.0
    explanation_codes: tuple[str, ...] = ()
    caution_codes: tuple[str, ...] = ()
    #: Every explanation and caution as the product states it, numbers included.
    explanation_digest: str = ""
    surface_missing_share: float | None = None
    origin: str | None = None
    destination: str | None = None
    computation_ms: float = 0.0

    def outcome(self) -> dict[str, Any]:
        """Everything but the timing: what determinism is checked on."""
        found = asdict(self)
        found.pop("computation_ms")
        return found


def chosen_route(
    comparison: RouteComparison, profile: MobilityProfile
) -> tuple[Route | None, str | None]:
    if profile.is_standard:
        return comparison.standard_route, comparison.standard_failure
    return comparison.accessible_route, comparison.accessible_failure


def route_facts(
    comparison: RouteComparison, profile: MobilityProfile, fills: Mapping[str, Fill]
) -> RouteFacts:
    route, failure = chosen_route(comparison, profile)
    explanations = tuple(sorted({e.code for e in comparison.explanations}))
    cautions = tuple(sorted({c.code for c in comparison.cautions}))
    stated = sorted(
        [("explanation", e.code, e.summary) for e in comparison.explanations]
        + [("caution", c.code, c.summary) for c in comparison.cautions]
    )
    digest = hashlib.sha256(json.dumps(stated).encode("utf-8")).hexdigest()[:16]
    standard = comparison.standard_route
    standard_overlay = (
        sum(s.length_m for s in standard.segments if s.edge_identity in fills)
        if standard is not None
        else 0.0
    )
    if route is None:
        return RouteFacts(
            False,
            failure,
            standard_overlay_m=round(standard_overlay, 3),
            explanation_codes=explanations,
            caution_codes=cautions,
            explanation_digest=digest,
        )
    overlay_m = 0.0
    by_class: dict[str, float] = defaultdict(float)
    records: set[int] = set()
    surface_cost = uncertainty = known = unknown = 0.0
    for segment in route.segments:
        if segment.surface_class is SurfaceClass.UNKNOWN:
            unknown += segment.length_m
        else:
            known += segment.length_m
        fill = fills.get(segment.edge_identity)
        if fill is not None:
            overlay_m += segment.length_m
            by_class[fill.surface_class.value] += segment.length_m
            records.update(fill.records)
        for component in segment.cost_components:
            if component.code is CostCode.SURFACE:
                surface_cost += component.effective_metres
            elif component.code is CostCode.UNCERTAINTY:
                uncertainty += component.effective_metres
    return RouteFacts(
        exists=True,
        path=tuple(s.edge_identity for s in route.segments),
        distance_m=round(route.distance_m, 3),
        effective_m=round(route.effective_distance_m, 3),
        surface_known_m=round(known, 3),
        surface_unknown_m=round(unknown, 3),
        overlay_m=round(overlay_m, 3),
        standard_overlay_m=round(standard_overlay, 3),
        overlay_by_class={k: round(v, 3) for k, v in sorted(by_class.items())},
        overlay_records=tuple(sorted(records)),
        surface_cost_m=round(surface_cost, 3),
        uncertainty_cost_m=round(uncertainty, 3),
        explanation_codes=explanations,
        caution_codes=cautions,
        explanation_digest=digest,
        surface_missing_share=round(route.evidence_coverage.get("surface", 0.0), 6),
        origin=route.origin.node_id,
        destination=route.destination.node_id,
        computation_ms=round(route.computation_ms, 3),
    )


# ---------------------------------------------------------------------------
# Baseline against shadow
# ---------------------------------------------------------------------------


def surface_lookup(graph: RoutableGraph) -> dict[str, tuple[str | None, SurfaceClass]]:
    return {e.identity: (e.features.surface, e.features.surface_class) for e in graph.segments}


def _with_surface(
    features: EdgeFeatures, lookup: Mapping[str, tuple[str | None, SurfaceClass]], identity: str
) -> EdgeFeatures:
    surface, cls = lookup.get(identity, (features.surface, features.surface_class))
    if (surface, cls) == (features.surface, features.surface_class):
        return features
    return replace(features, surface=surface, surface_class=cls)


def cost_under(
    route: Route,
    lookup: Mapping[str, tuple[str | None, SurfaceClass]],
    profile: MobilityProfile,
) -> float:
    """What this exact path costs with another graph's surfaces: segment by segment, oriented."""
    total = 0.0
    for segment in route.segments:
        features = _with_surface(segment.features, lookup, segment.edge_identity)
        total += evaluate_edge(features, segment.length_m, profile).effective_metres
    return total


def newly_blocked(
    route: Route,
    lookup: Mapping[str, tuple[str | None, SurfaceClass]],
    profile: MobilityProfile,
) -> list[str]:
    """Segments of this path the other graph's surfaces make unusable for the profile."""
    blocked = []
    for segment in route.segments:
        features = _with_surface(segment.features, lookup, segment.edge_identity)
        if features is segment.features:
            continue
        if not evaluate_edge(features, segment.length_m, profile).passable:
            blocked.append(segment.edge_identity)
    return blocked


def classify(base: RouteFacts, shadow: RouteFacts, *, blocked: bool) -> Category:
    exposed = any(f.overlay_m > 0 or f.standard_overlay_m > 0 for f in (base, shadow))
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
    evidence = ("surface_known_m", "surface_missing_share", "explanation_digest")
    if any(getattr(base, name) != getattr(shadow, name) for name in evidence):
        return Category.EVIDENCE_ONLY
    return Category.NO_EFFECT if exposed else Category.NOT_EXPOSED


@dataclass(slots=True)
class Result:
    journey: Journey
    profile_key: str
    base: RouteFacts
    shadow: RouteFacts
    category: Category
    #: For a changed path: the costs of both paths under both graphs, and why.
    cause: dict[str, Any] | None = None
    #: Segments of the baseline path the overlay makes unusable.
    blocked: tuple[str, ...] = ()


def _overlay_segments(
    route: Route, fills: Mapping[str, Fill], baseline: Mapping[str, Any]
) -> list[dict[str, Any]]:
    found = []
    for segment in route.segments:
        fill = fills.get(segment.edge_identity)
        if fill is None:
            continue
        found.append(
            {
                "segment": segment.edge_identity,
                "length_m": round(segment.length_m, 2),
                "city_surface": fill.surface,
                "city_class": fill.surface_class.value,
                "osm_class_before": str(baseline.get(segment.edge_identity, (None, "unknown"))[1]),
                "records": list(fill.records),
            }
        )
    return found


def explain_change(
    base_route: Route,
    shadow_route: Route,
    profile: MobilityProfile,
    fills: Mapping[str, Fill],
    base_lookup: Mapping[str, tuple[str | None, SurfaceClass]],
    shadow_lookup: Mapping[str, tuple[str | None, SurfaceClass]],
) -> dict[str, Any]:
    """Why the chosen path moved, from the costs: each path, under each graph."""
    a_base = cost_under(base_route, base_lookup, profile)
    a_shadow = cost_under(base_route, shadow_lookup, profile)
    b_base = cost_under(shadow_route, base_lookup, profile)
    b_shadow = cost_under(shadow_route, shadow_lookup, profile)
    a_moved = a_shadow - a_base
    b_moved = b_shadow - b_base
    parts = [
        f"Baseline: route A costs {a_base:.1f} effective m, route B {b_base:.1f}; A is chosen.",
    ]
    if a_moved > 1e-6:
        parts.append(
            f"City surfaces on A's filled segments raise its cost by {a_moved:.1f} "
            "(a known surface this profile penalises more than an unknown one)."
        )
    elif a_moved < -1e-6:
        parts.append(f"City surfaces on A's filled segments lower its cost by {-a_moved:.1f}.")
    if b_moved < -1e-6:
        parts.append(
            f"City surfaces on B's filled segments lower its cost by {-b_moved:.1f} "
            "(an unknown-surface penalty replaced by a smaller or no penalty)."
        )
    elif b_moved > 1e-6:
        parts.append(f"City surfaces on B's filled segments raise its cost by {b_moved:.1f}.")
    parts.append(f"Shadow: A costs {a_shadow:.1f}, B {b_shadow:.1f}; B is chosen.")
    return {
        "route_a_baseline": {
            "distance_m": round(base_route.distance_m, 2),
            "cost_baseline": round(a_base, 3),
            "cost_shadow": round(a_shadow, 3),
            "filled_segments": _overlay_segments(base_route, fills, base_lookup),
        },
        "route_b_shadow": {
            "distance_m": round(shadow_route.distance_m, 2),
            "cost_baseline": round(b_base, 3),
            "cost_shadow": round(b_shadow, 3),
            "filled_segments": _overlay_segments(shadow_route, fills, base_lookup),
        },
        "distance_delta_m": round(shadow_route.distance_m - base_route.distance_m, 2),
        "cost_delta_m": round(b_shadow - a_base, 3),
        "cause": " ".join(parts),
        "records": sorted(
            {
                r
                for p in (base_route, shadow_route)
                for s in p.segments
                for r in (fills[s.edge_identity].records if s.edge_identity in fills else ())
            }
        ),
    }


@dataclass(slots=True)
class Pair:
    """A journey routed for one profile on both graphs, kept whole for later analysis."""

    base: RouteComparison
    shadow: RouteComparison


def compare_on(graph: RoutableGraph, journey: Journey, profile: MobilityProfile) -> RouteComparison:
    """One journey for one profile, exactly as the routing API computes and explains it."""
    return compare_routes(
        graph, origin=journey.origin, destination=journey.destination, profile=profile
    )


def assess(
    journey: Journey,
    profile: MobilityProfile,
    base: RouteFacts,
    other_cmp: RouteComparison,
    fills: Mapping[str, Fill],
    lookups: tuple[Mapping[str, Any], Mapping[str, Any]],
    baseline_cmp: Callable[[], RouteComparison],
) -> tuple[Result, Pair | None]:
    """Compare another graph's answer with the baseline's.

    The baseline comparison is fetched again only where the path moved, to
    explain the move: routes are not kept for journeys where nothing did.
    """
    other = route_facts(other_cmp, profile, fills)
    other_route, _ = chosen_route(other_cmp, profile)
    blocked: tuple[str, ...] = ()
    base_cmp: RouteComparison | None = None
    if base.exists and base.path and any(i in fills for i in base.path):
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
            cause = explain_change(base_route, other_route, profile, fills, lookups[0], lookups[1])
    # Whole routes are kept only where the path moved: they are drawn later.
    kept = Pair(base_cmp, other_cmp) if cause is not None and base_cmp is not None else None
    return Result(journey, profile.key, base, other, category, cause, blocked), kept


def run_pair(
    journey: Journey,
    profile: MobilityProfile,
    baseline: RoutableGraph,
    shadow: RoutableGraph,
    fills: Mapping[str, Fill],
    lookups: tuple[Mapping[str, Any], Mapping[str, Any]],
) -> tuple[Result, Pair | None]:
    """One journey for one profile on both graphs."""
    base_cmp = compare_on(baseline, journey, profile)
    return assess(
        journey,
        profile,
        route_facts(base_cmp, profile, fills),
        compare_on(shadow, journey, profile),
        fills,
        lookups,
        lambda: base_cmp,
    )


def algorithms_agree(
    graph: RoutableGraph, journey: Journey, profile: MobilityProfile
) -> dict[str, Any]:
    """Dijkstra and A* on one graph: the same optimal cost, or a finding."""
    found: dict[str, Any] = {}
    for algorithm in (Algorithm.DIJKSTRA, Algorithm.ASTAR):
        try:
            route = compute_route(
                graph,
                origin=journey.origin,
                destination=journey.destination,
                profile=profile,
                algorithm=algorithm,
            )
            found[str(algorithm)] = round(route.effective_distance_m, 6)
        except RoutingError as error:
            found[str(algorithm)] = f"no route: {type(error).__name__}"
    values = list(found.values())
    agree = (
        values[0] == values[1]
        if isinstance(values[0], str) or isinstance(values[1], str)
        else abs(values[0] - values[1]) <= 1e-6 * max(1.0, abs(values[0]))
    )
    return {**found, "agree": agree}


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return round(ordered[index], 3)


def summarise_results(results: Sequence[Result]) -> dict[str, Any]:
    """Per corpus and profile: categories, evidence and cost change, route changes."""
    out: dict[str, Any] = {}
    groups: dict[tuple[str, str], list[Result]] = defaultdict(list)
    for r in results:
        groups[(r.journey.corpus, r.profile_key)].append(r)
    for (corpus, profile), rows in sorted(groups.items()):
        changed = [r for r in rows if r.cause is not None]
        both = [r for r in rows if r.base.exists and r.shadow.exists]
        overlay_class: dict[str, float] = defaultdict(float)
        for r in rows:
            for cls, metres in r.shadow.overlay_by_class.items():
                overlay_class[cls] += metres
        base_known = sum(r.base.surface_known_m for r in both)
        base_unknown = sum(r.base.surface_unknown_m for r in both)
        shadow_known = sum(r.shadow.surface_known_m for r in both)
        shadow_unknown = sum(r.shadow.surface_unknown_m for r in both)
        out.setdefault(corpus, {})[profile] = {
            "journeys": len(rows),
            "categories": dict(sorted(Counter(str(r.category) for r in rows).items())),
            "routes_on_filled_segments": sum(1 for r in rows if r.shadow.overlay_m > 0),
            "evidence_changed": sum(
                1
                for r in both
                if (r.base.surface_known_m, r.base.explanation_codes, r.base.surface_missing_share)
                != (
                    r.shadow.surface_known_m,
                    r.shadow.explanation_codes,
                    r.shadow.surface_missing_share,
                )
            ),
            "cost_changed": sum(
                1 for r in both if abs(r.base.effective_m - r.shadow.effective_m) > 1e-6
            ),
            "path_changed": sum(1 for r in both if r.base.path != r.shadow.path),
            "feasibility_changed": sum(
                1 for r in rows if r.category is Category.FEASIBILITY_CHANGED
            ),
            "surface_metres": {
                "baseline_known": round(base_known, 1),
                "baseline_unknown": round(base_unknown, 1),
                "shadow_known": round(shadow_known, 1),
                "shadow_unknown": round(shadow_unknown, 1),
                "candidate_municipal_on_shadow_routes": round(
                    sum(r.shadow.overlay_m for r in rows), 1
                ),
                "incremental_known": round(shadow_known - base_known, 1),
                "candidate_municipal_by_class": {
                    k: round(v, 1) for k, v in sorted(overlay_class.items())
                },
            },
            "changed_routes": {
                "count": len(changed),
                "distance_delta_m": _describe(
                    [c.cause["distance_delta_m"] for c in changed if c.cause]
                ),
                "cost_delta_m": _describe([c.cause["cost_delta_m"] for c in changed if c.cause]),
            },
        }
    return out


def _describe(values: Sequence[float]) -> dict[str, Any] | None:
    if not values:
        return None
    return {
        "min": round(min(values), 2),
        "median": round(statistics.median(values), 2),
        "max": round(max(values), 2),
    }


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
            ],
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        for r in sorted(results, key=lambda r: (r.journey.journey_id, r.profile_key))
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


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
