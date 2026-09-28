"""PA-GEO-07 end to end: the active graph read-only, the overlay, both corpora, the evidence.

The database is only read, inside ``READ ONLY`` transactions, and its content
checksum is computed before the study and after it. The loaded graph is
fingerprinted — its segments and the adjacency the router walks — before the
shadow graph is built and after every shadow route; a sample of baseline
journeys is routed again at the end and must come out identical.
"""

from __future__ import annotations

import functools
import hashlib
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pathable_api.geo.content_checksum import compute_content_checksum
from pathable_api.geo.enums import SurfaceClass
from pathable_api.geo.kitchener.correspondence import to_native
from pathable_api.geo.kitchener.osm_extract import StudyExtract
from pathable_api.geo.kitchener.shadow_overlay import (
    CONFLICT_SENSITIVITY,
    EDGE_COVERAGE_MIN,
    FILLED,
    OTHER_CLASS_MAX,
    SHADOW_POLICY_VERSION,
    OverlayPlan,
    SegmentSource,
    SurfaceEvidence,
    locate_segments,
    plan_overlay,
    shadow_graph,
    way_vertex_positions,
)
from pathable_api.geo.kitchener.shadow_study import (
    BROAD_CORPUS_VERSION,
    TARGETED_CORPUS_VERSION,
    Category,
    Journey,
    Pair,
    Result,
    RouteFacts,
    algorithms_agree,
    anchors,
    assess,
    broad_corpus,
    compare_on,
    corpus_digest,
    results_digest,
    route_facts,
    study_profiles,
    summarise_results,
    surface_lookup,
    surface_rules,
    targeted_corpus,
    timing,
)
from pathable_api.geo.models import DatasetVersion, GraphEdge, PilotRegion
from pathable_api.routing.comparison import RouteComparison
from pathable_api.routing.engine import RoutingError, compute_route
from pathable_api.routing.graph import RoutableGraph, load_graph
from pathable_api.routing.load_benchmark import fingerprint, process_memory
from pathable_api.routing.profiles import STANDARD

Progress = Callable[[str], None]


# ---------------------------------------------------------------------------
# Reading the active dataset, read-only
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ActiveDataset:
    dataset_id: uuid.UUID
    checksum: str
    source_name: str
    content_checksum: str
    content_checksum_version: int


async def read_only(session: AsyncSession) -> None:
    """Make this session's transaction refuse every write, at the database."""
    await session.execute(text("SET TRANSACTION READ ONLY"))


async def active_dataset(session: AsyncSession, region_slug: str) -> ActiveDataset:
    """The region's active dataset and its content checksum, computed from its rows."""
    row = (
        await session.execute(
            select(DatasetVersion.id, DatasetVersion.checksum, DatasetVersion.source_name)
            .join(PilotRegion, PilotRegion.id == DatasetVersion.pilot_region_id)
            .where(PilotRegion.slug == region_slug, DatasetVersion.status == "active")
        )
    ).one()
    content = await compute_content_checksum(session, row.id)
    return ActiveDataset(row.id, row.checksum, row.source_name, content.value, content.version)


async def load_active(
    session: AsyncSession, dataset: ActiveDataset, region_slug: str
) -> tuple[RoutableGraph, list[SegmentSource]]:
    """The routing graph exactly as the service builds it, and each segment's source way."""
    graph = await load_graph(
        session, DatasetVersion(id=dataset.dataset_id, checksum=dataset.checksum), region_slug
    )
    rows = await session.execute(
        select(
            GraphEdge.source_u, GraphEdge.source_v, GraphEdge.edge_key, GraphEdge.source_way_id
        ).where(GraphEdge.dataset_version_id == dataset.dataset_id)
    )
    sources = [SegmentSource(r.source_u, r.source_v, r.edge_key, r.source_way_id) for r in rows]
    return graph, sources


def adjacency_fingerprint(graph: RoutableGraph) -> str:
    """Every directed entry the router walks, with the surface it would cost."""
    lines = sorted(
        f"{u}|{v}|{key}|{data['edge'].identity}|{data['edge'].reversed}|"
        f"{data['edge'].features.surface}|{data['edge'].features.surface_class}"
        for u, v, key, data in graph.graph.edges(keys=True, data=True)
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def graph_identity(graph: RoutableGraph) -> dict[str, str]:
    """The loaded graph's segments, nodes and directed adjacency, each as one hash."""
    found = fingerprint(graph)
    return {
        "segment_sha256": str(found["segment_sha256"]),
        "node_sha256": str(found["node_sha256"]),
        "adjacency_sha256": adjacency_fingerprint(graph),
    }


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class StudyOutput:
    plan: OverlayPlan
    conflict_plan: OverlayPlan
    locate_problems: Counter[str]
    corpora: dict[str, list[Journey]]
    results: list[Result]
    sensitivity: list[Result]
    pairs: dict[tuple[str, str], Pair]
    agreement: list[dict[str, Any]]
    isolation: dict[str, Any]
    network: dict[str, Any]
    timings: dict[str, float]
    memory: dict[str, float | None]
    shadow_identity: dict[str, str] = field(default_factory=dict)


def _given(comparison: RouteComparison) -> RouteComparison:
    return comparison


def _memory() -> float | None:
    return process_memory().rss_mb


def network_evidence(graph: RoutableGraph, plan: OverlayPlan) -> dict[str, Any]:
    """Across the whole routing graph: surface known before, and what the overlay adds."""
    known = unknown = 0.0
    for edge in graph.segments:
        if edge.features.surface_class is SurfaceClass.UNKNOWN:
            unknown += edge.length_m
        else:
            known += edge.length_m
    lengths = {e.identity: e.length_m for e in graph.segments}
    filled: dict[str, list[float]] = defaultdict(list)
    for fill in plan.fills.values():
        filled[fill.surface_class.value].append(lengths.get(fill.identity, 0.0))
    added = sum(sum(v) for v in filled.values())
    return {
        "segments": graph.segment_count,
        "surface_known_m": round(known, 1),
        "surface_unknown_m": round(unknown, 1),
        "candidate_municipal_segments": len(plan.fills),
        "candidate_municipal_m": round(added, 1),
        "candidate_municipal_by_class": {
            k: {"segments": len(v), "metres": round(sum(v), 1)} for k, v in sorted(filled.items())
        },
        "counterfactual_known_m": round(known + added, 1),
        "segments_touched_by_city_extents": len(plan.touched),
        "segments_not_filled": dict(sorted(plan.skipped.items())),
        "touched_coverage_distribution": _coverage_bins(plan.touched.values()),
    }


def _coverage_bins(values: Any) -> dict[str, int]:
    bins = Counter[str]()
    for value in values:
        if value >= EDGE_COVERAGE_MIN:
            bins[f">= {EDGE_COVERAGE_MIN}"] += 1
        elif value >= 0.5:
            bins[f"0.5 to {EDGE_COVERAGE_MIN}"] += 1
        else:
            bins["< 0.5"] += 1
    return dict(sorted(bins.items()))


def run_study(
    graph: RoutableGraph,
    sources: Sequence[SegmentSource],
    evidence: SurfaceEvidence,
    extract: StudyExtract,
    *,
    bounds: tuple[float, float, float, float],
    broad_size: int,
    seed: str,
    per_stratum: int,
    recheck: int = 12,
    progress: Progress | None = None,
) -> StudyOutput:
    say = progress or (lambda _message: None)
    timings: dict[str, float] = {}
    memory: dict[str, float | None] = {"after_load_mb": _memory()}

    started = time.perf_counter()
    positions = way_vertex_positions(extract, to_native())
    by_way, problems = locate_segments(sources, extract, positions)
    features = {e.identity: e.features for e in graph.segments}
    plan = plan_overlay(evidence.eligible, by_way, features)
    conflict_plan = plan_overlay(evidence.conflicts, by_way, features, policy=CONFLICT_SENSITIVITY)
    timings["overlay_plan_s"] = round(time.perf_counter() - started, 2)
    say(f"overlay: {len(plan.fills)} segments filled; conflicts: {len(conflict_plan.fills)}")

    before = graph_identity(graph)
    started = time.perf_counter()
    shadow = shadow_graph(graph, plan)
    timings["shadow_graph_build_s"] = round(time.perf_counter() - started, 2)
    memory["after_shadow_graph_mb"] = _memory()
    lookups = (surface_lookup(graph), surface_lookup(shadow))
    profiles = study_profiles()

    def routable(origin: tuple[float, float], destination: tuple[float, float]) -> bool:
        try:
            compute_route(graph, origin=origin, destination=destination, profile=STANDARD)
        except RoutingError:
            return False
        return True

    started = time.perf_counter()
    broad = broad_corpus(graph, size=broad_size, seed=seed, bounds=bounds, routable=routable)
    targeted = targeted_corpus(
        anchors(shadow, plan.fills), seed=seed, per_stratum=per_stratum, routable=routable
    )
    timings["corpus_build_s"] = round(time.perf_counter() - started, 2)
    say(f"corpora: {len(broad)} broad, {len(targeted)} targeted journeys")

    results: list[Result] = []
    pairs: dict[tuple[str, str], Pair] = {}
    # Each baseline route is computed once and summarised twice: against the
    # overlay's segments and against the conflict segments the sensitivity uses.
    conflict_base: dict[tuple[str, str], RouteFacts] = {}
    for name, journeys in (("broad", broad), ("targeted", targeted)):
        started = time.perf_counter()
        for count, journey in enumerate(journeys, 1):
            for profile in profiles:
                base_cmp = compare_on(graph, journey, profile)
                conflict_base[(journey.journey_id, profile.key)] = route_facts(
                    base_cmp, profile, conflict_plan.fills
                )
                result, pair = assess(
                    journey,
                    profile,
                    route_facts(base_cmp, profile, plan.fills),
                    compare_on(shadow, journey, profile),
                    plan.fills,
                    lookups,
                    functools.partial(_given, base_cmp),
                )
                results.append(result)
                if pair is not None:
                    pairs[(journey.journey_id, profile.key)] = pair
            if count % 25 == 0:
                say(f"{name}: {count} of {len(journeys)} journeys")
        timings[f"{name}_corpus_s"] = round(time.perf_counter() - started, 2)
    memory["after_corpora_mb"] = _memory()

    # Dijkstra against A*, on the shadow graph, for every changed route and a
    # fixed sample of broad journeys.
    by_key = {p.key: p for p in profiles}
    checks = sorted(pairs) + [(j.journey_id, "wheelchair") for j in broad[:10]]
    journeys_by_id = {j.journey_id: j for j in (*broad, *targeted)}
    agreement = [
        {
            "journey": jid,
            "profile": key,
            **algorithms_agree(shadow, journeys_by_id[jid], by_key[key]),
        }
        for jid, key in dict.fromkeys(checks)
    ]

    after_shadow = graph_identity(graph)
    shadow_identity = graph_identity(shadow)
    del shadow

    # The conflict sensitivity: the City's side on conflict extents, measured
    # against the same baseline. A sensitivity, never a policy.
    started = time.perf_counter()
    flipped = shadow_graph(graph, conflict_plan)
    flip_lookups = (lookups[0], surface_lookup(flipped))
    sensitivity = [
        assess(
            journey,
            profile,
            conflict_base[(journey.journey_id, profile.key)],
            compare_on(flipped, journey, profile),
            conflict_plan.fills,
            flip_lookups,
            functools.partial(compare_on, graph, journey, profile),
        )[0]
        for journey in (*broad, *targeted)
        for profile in profiles
    ]
    timings["conflict_sensitivity_s"] = round(time.perf_counter() - started, 2)
    del flipped

    # The overlay removed: the baseline graph routes exactly as it did.
    first = {(r.journey.journey_id, r.profile_key): r for r in results}
    rechecked = []
    for journey in broad[:recheck]:
        for profile in profiles:
            again = route_facts(compare_on(graph, journey, profile), profile, plan.fills)
            rechecked.append(
                again.outcome() == first[(journey.journey_id, profile.key)].base.outcome()
            )
    isolation = {
        "baseline_graph_before_shadow": before,
        "baseline_graph_after_every_run": graph_identity(graph),
        "baseline_graph_unchanged": before == after_shadow == graph_identity(graph),
        "baseline_rerouted_after_study": {
            "routes": len(rechecked),
            "identical": sum(rechecked),
        },
    }
    memory["peak_mb"] = process_memory().peak_rss_mb
    return StudyOutput(
        plan=plan,
        conflict_plan=conflict_plan,
        locate_problems=problems,
        corpora={"broad": broad, "targeted": targeted},
        results=results,
        sensitivity=sensitivity,
        pairs=pairs,
        agreement=agreement,
        isolation=isolation,
        network=network_evidence(graph, plan),
        timings=timings,
        memory=memory,
        shadow_identity=shadow_identity,
    )


# ---------------------------------------------------------------------------
# What the evidence says
# ---------------------------------------------------------------------------


def eligible_outcomes(evidence: SurfaceEvidence, plan: OverlayPlan) -> dict[str, Any]:
    """Every City-only assertion: does it describe a routing segment, and if not, why not."""
    outcome = Counter(plan.assertion_outcomes[i.reconciliation_id] for i in evidence.eligible)
    by_value: dict[str, Counter[str]] = defaultdict(Counter)
    freshness = Counter[str]()
    years = Counter[str]()
    for item in evidence.eligible:
        state = plan.assertion_outcomes[item.reconciliation_id]
        by_value[item.raw_value][state] += 1
        if state == FILLED:
            freshness[item.freshness] += 1
            years[(item.source_capture_date or "none")[:4]] += 1
    return {
        "assertions": len(evidence.eligible),
        "outcome": dict(sorted(outcome.items())),
        "by_city_value": {k: dict(sorted(v.items())) for k, v in sorted(by_value.items())},
        "filled_assertions_freshness": dict(sorted(freshness.items())),
        "filled_assertions_capture_year": dict(sorted(years.items())),
    }


def _fill_records(plan: OverlayPlan) -> dict[int, list[str]]:
    found: dict[int, list[str]] = defaultdict(list)
    for fill in plan.fills.values():
        for record in fill.records:
            found[record].append(fill.identity)
    return found


def changed_routes(results: Sequence[Result]) -> list[dict[str, Any]]:
    return [
        {
            "journey": r.journey.journey_id,
            "corpus": r.journey.corpus,
            "profile": r.profile_key,
            "category": str(r.category),
            "blocked_segments": list(r.blocked),
            **(r.cause or {}),
        }
        for r in sorted(results, key=lambda r: (r.journey.journey_id, r.profile_key))
        if r.cause is not None or r.category is Category.FEASIBILITY_CHANGED
    ]


def conflict_analysis(
    evidence: SurfaceEvidence,
    plan: OverlayPlan,
    results: Sequence[Result],
    sensitivity: Sequence[Result],
) -> dict[str, Any]:
    """Conflicts on evaluated routes, described; and what taking the City's side would do."""
    by_id = {c.reconciliation_id: c for c in evidence.conflicts}
    touched: dict[str, set[str]] = defaultdict(set)
    for r in results:
        for identity in r.base.path:
            fill = plan.fills.get(identity)
            if fill is None:
                continue
            for rid in fill.reconciliations:
                touched[rid].add(f"{r.journey.journey_id}/{r.profile_key}")
    pairs = Counter[str]()
    class_changes = Counter[str]()
    for rid in touched:
        item = by_id[rid]
        pairs[f"{item.raw_value} | {item.osm_value}"] += 1
        class_changes[
            "same_class" if item.osm_class is item.surface_class else "class_differs"
        ] += 1
    routes_touching = Counter[str]()
    for r in results:
        if any(i in plan.fills for i in r.base.path):
            routes_touching[f"{r.journey.corpus}/{r.profile_key}"] += 1
    return {
        "what_it_is": (
            "Descriptive only. Conflicts are never used by the shadow policy. The sensitivity "
            "routes every journey again with the City's value on conflict extents, to see whether "
            "choosing that side would matter; it resolves nothing."
        ),
        "conflict_assertions": len(evidence.conflicts),
        "conflict_segments_in_graph": len(plan.fills),
        "conflict_segments_where_the_class_differs": sum(
            1 for f in plan.fills.values() if f.replaces is not f.surface_class
        ),
        "baseline_routes_touching_conflicts": dict(sorted(routes_touching.items())),
        "conflict_assertions_on_evaluated_routes": len(touched),
        "surface_pairs_on_evaluated_routes": dict(pairs.most_common()),
        "routing_class_on_evaluated_routes": dict(sorted(class_changes.items())),
        "provenance_on_evaluated_routes": [
            {
                "reconciliation_id": rid,
                "city": by_id[rid].raw_value,
                "city_capture_date": by_id[rid].source_capture_date,
                "osm": by_id[rid].osm_value,
                "osm_observation_date": by_id[rid].osm_observation_date,
                "osm_value_since": by_id[rid].osm_value_since,
                "lineage": by_id[rid].lineage,
                "routes": len(touched[rid]),
            }
            for rid in sorted(touched)
        ],
        "if_the_city_side_were_taken": summarise_results(sensitivity),
    }


VALIDATION_STRATA = (
    ("feasibility_change", "A hard requirement changed whether a route exists or may use it."),
    ("route_change", "The chosen path moved in at least one journey."),
    ("repeated_exposure", "Filled segments on the chosen route of three or more journeys."),
    ("rough_or_compacted", "A City surface the cost model penalises, on a route."),
    ("long_extent", "The longest filled extents that any route used."),
    ("conflict_that_matters", "A conflict where the City's side would move a route."),
)
VALIDATION_PER_STRATUM = 8
VALIDATION_MAX = 40


def validation_queue(
    evidence: SurfaceEvidence,
    output: StudyOutput,
    graph: RoutableGraph,
) -> list[dict[str, Any]]:
    """A small, explicit set of City records worth checking in the field, and why each."""
    plan = output.plan
    items = {i.record_id: i for i in evidence.eligible}
    conflicts = {i.record_id: i for i in evidence.conflicts}
    segments = _fill_records(plan)
    lengths = {e.identity: e for e in graph.segments}
    uses: dict[int, list[Result]] = defaultdict(list)
    for r in output.results:
        for record in set(r.shadow.overlay_records) | set(r.base.overlay_records):
            uses[record].append(r)

    def filled_m(record: int) -> float:
        return sum(lengths[s].length_m for s in segments.get(record, ()) if s in lengths)

    candidates: dict[str, list[int]] = {}
    feasibility: Counter[int] = Counter()
    moved: Counter[int] = Counter()
    for r in output.results:
        records = set(r.cause["records"]) if r.cause else set()
        if r.category is Category.FEASIBILITY_CHANGED:
            for identity in r.blocked:
                records.update(plan.fills[identity].records if identity in plan.fills else ())
            feasibility.update(records)
        elif r.category is Category.ROUTE_CHANGED:
            moved.update(records)
    candidates["feasibility_change"] = [
        k for k, _ in sorted(feasibility.items(), key=lambda i: (-i[1], i[0]))
    ]
    candidates["route_change"] = [k for k, _ in sorted(moved.items(), key=lambda i: (-i[1], i[0]))]
    journeys_on = {k: len({r.journey.journey_id for r in v}) for k, v in uses.items()}
    candidates["repeated_exposure"] = sorted(
        (k for k, n in journeys_on.items() if n >= 3), key=lambda k: (-journeys_on[k], k)
    )
    candidates["rough_or_compacted"] = sorted(
        (
            k
            for k in uses
            if k in items and items[k].surface_class in (SurfaceClass.ROUGH, SurfaceClass.COMPACTED)
        ),
        key=lambda k: (-filled_m(k), k),
    )
    candidates["long_extent"] = sorted(uses, key=lambda k: (-filled_m(k), k))
    flips: Counter[int] = Counter()
    for r in output.sensitivity:
        if r.category in (Category.ROUTE_CHANGED, Category.FEASIBILITY_CHANGED) and r.cause:
            flips.update(r.cause["records"])
    candidates["conflict_that_matters"] = [
        k for k, _ in sorted(flips.items(), key=lambda i: (-i[1], i[0]))
    ]

    chosen: dict[int, list[str]] = {}
    for stratum, _why in VALIDATION_STRATA:
        taken = 0
        for record in candidates.get(stratum, ()):
            if len(chosen) >= VALIDATION_MAX or taken >= VALIDATION_PER_STRATUM:
                break
            if record in chosen:
                chosen[record].append(stratum)
                continue
            chosen[record] = [stratum]
            taken += 1
    queue = []
    for record, strata in chosen.items():
        item = items.get(record) or conflicts.get(record)
        if item is None:
            continue
        fills = [plan.fills[s] for s in segments.get(record, ()) if s in plan.fills]
        coords = [
            pt
            for s in segments.get(record, ())
            if s in lengths
            for pt in lengths[s].geometry.coords
        ]
        examples = [
            {
                "journey": r.journey.journey_id,
                "profile": r.profile_key,
                "category": str(r.category),
                "distance_delta_m": (r.cause or {}).get("distance_delta_m"),
                "cost_delta_m": (r.cause or {}).get("cost_delta_m"),
            }
            for r in sorted(
                uses.get(record, []),
                key=lambda r: (
                    r.category is Category.NOT_EXPOSED,
                    str(r.category),
                    r.journey.journey_id,
                    r.profile_key,
                ),
            )[:3]
        ]
        queue.append(
            {
                "record_id": record,
                "selected_for": strata,
                "municipal_assertion": {
                    "field": "SURFACE_MATERIAL",
                    "raw_value": item.raw_value,
                    "normalized_value": item.normalized_value,
                    "routing_class": item.surface_class.value,
                },
                "osm_state": (
                    {
                        "way": f"way/{item.way_id}",
                        "surface": None,
                        "meaning": "OSM records no surface",
                    }
                    if item.relationship == "source_only_kitchener"
                    else {
                        "way": f"way/{item.way_id}",
                        "surface": item.osm_value,
                        "meaning": "conflict",
                    }
                ),
                "local_extent": {
                    "way": f"way/{item.way_id}",
                    "from_m": round(item.from_m, 2),
                    "to_m": round(item.to_m, 2),
                    "graph_segments": sorted({f.identity for f in fills}),
                    "graph_metres": round(filled_m(record), 1),
                    "midpoint_lon_lat": (
                        [
                            round(sum(p[0] for p in coords) / len(coords), 6),
                            round(sum(p[1] for p in coords) / len(coords), 6),
                        ]
                        if coords
                        else None
                    ),
                },
                "provenance": {
                    "capture_source": item.capture_source,
                    "source_capture_date": item.source_capture_date,
                    "inspection_year": item.inspection_year,
                    "freshness": item.freshness,
                    "routing_eligibility": "not_routing_eligible",
                },
                "route_impact_examples": examples,
            }
        )
    return queue


LIMITATIONS = (
    "A counterfactual: the City's surfaces are treated as accepted only to measure what "
    "admitting them would change. They are not validated, and nothing here is a route anyone "
    "should follow.",
    "The correspondences are PA-GEO-05's frozen matcher's decisions, measured once on a "
    "held-out sample against AI labels, and unverified row by row.",
    "The City supplies no observation date for any surface: every filled assertion is dated "
    "only by when its record was captured, or not at all.",
    "The cost weights are engineering judgement, never validated with the people they model; "
    "a route change says what this cost model does, not what a traveller would prefer.",
    "The broad corpus is an engineering sample of journeys across the pilot, not a sample of "
    "real trips; its change rates are not prevalence. The targeted corpus is chosen to pass "
    "City evidence and its rates describe nothing but itself.",
    "One dataset, one City snapshot, one laptop.",
)


def shadow_evidence(
    *,
    evidence: SurfaceEvidence,
    output: StudyOutput,
    dataset_before: ActiveDataset,
    dataset_after: ActiveDataset,
    extract_sha256: str,
    seed: str,
    queue: list[dict[str, Any]],
    attribution: Mapping[str, str],
) -> dict[str, Any]:
    """The committed summary of one study run."""
    profiles = study_profiles()
    broad = output.corpora["broad"]
    targeted = output.corpora["targeted"]
    by_corpus: dict[str, list[Result]] = defaultdict(list)
    for r in output.results:
        by_corpus[r.journey.corpus].append(r)
    disagreements = [a for a in output.agreement if not a["agree"]]
    return {
        "kitchener_geo07_shadow_routing_version": 1,
        "label": "Research counterfactual — not production routing",
        "what_it_is": (
            "PA-GEO-07: an offline shadow-routing study. The same journeys are routed by "
            "PathAble's own router on the active OSM-only graph and on a shadow copy in which "
            "City-only Kitchener surface assertions fill surfaces OSM does not record. It "
            "measures what admitting that evidence would change. It admits nothing: every "
            "Kitchener assertion stays not_routing_eligible, and the production graph, database "
            "and API are untouched."
        ),
        "policy": {
            "version": SHADOW_POLICY_VERSION,
            "rule": [
                "If OSM records a surface on a segment, keep OSM's.",
                "Else, if accepted City-only non-default surface assertions of one routing "
                f"class cover at least {EDGE_COVERAGE_MIN:.0%} of the segment, and no other City "
                f"class covers more than {OTHER_CLASS_MAX:.0%}, take the City's surface.",
                "Else the surface stays unknown.",
            ],
            "never_used": [
                "agreements, as extra evidence",
                "conflicts (studied separately as a sensitivity)",
                "City template defaults, including CONCRETE",
                "ambiguous or unmatched PA-GEO-05 decisions",
                "curb ramps, structures, stairs, width, grade, slope and condition",
            ],
            "conflict_sensitivity": CONFLICT_SENSITIVITY,
        },
        "inputs": {
            "geo06": evidence.identity,
            "dataset": {
                "dataset_id": str(dataset_before.dataset_id),
                "source_name": dataset_before.source_name,
                "ingest_checksum": dataset_before.checksum,
                "content_checksum_version": dataset_before.content_checksum_version,
                "content_checksum": dataset_before.content_checksum,
            },
            "osm_study_extract_sha256": extract_sha256,
            "seed": seed,
        },
        "surface_in_routing_today": surface_rules(profiles),
        "surface_evidence": {
            "geo06_surface_rows_by_relationship": evidence.relationships,
            "city_only": eligible_outcomes(evidence, output.plan),
            "segments_that_could_not_be_located": dict(sorted(output.locate_problems.items())),
            "network": output.network,
        },
        "corpora": {
            "broad": {
                "version": BROAD_CORPUS_VERSION,
                "journeys": len(broad),
                "sha256": corpus_digest(broad),
                "definition": (
                    "Origins cycle through a 6 x 6 grid over the pilot, each cell's walkable "
                    "nodes in seeded hash order; each destination is the first node in another "
                    "hash order 800 m to 3 km away in a straight line; kept when the standard "
                    "route exists. No City evidence is read."
                ),
                "list": [_journey(j) for j in broad],
            },
            "targeted": {
                "version": TARGETED_CORPUS_VERSION,
                "journeys": len(targeted),
                "sha256": corpus_digest(targeted),
                "definition": (
                    "For City records the overlay fills, stratified by routing class, filled "
                    "length and how many others lie within 200 m: journeys from 250 m before to "
                    "250 m after the filled extent, a few per stratum in seeded hash order. "
                    "Chosen to pass City evidence; its rates are not prevalence."
                ),
                "strata": dict(sorted(Counter(j.stratum or "" for j in targeted).items())),
                "list": [_journey(j) for j in targeted],
            },
            "profiles": [p.key for p in profiles],
        },
        "results": summarise_results(output.results),
        "route_changes": changed_routes(output.results),
        "per_journey": {
            "columns": [
                "journey",
                "profile",
                "category",
                "baseline_exists",
                "shadow_exists",
                "baseline_distance_m",
                "shadow_distance_m",
                "baseline_cost_m",
                "shadow_cost_m",
                "shadow_filled_m",
            ],
            "rows": [
                [
                    r.journey.journey_id,
                    r.profile_key,
                    str(r.category),
                    r.base.exists,
                    r.shadow.exists,
                    r.base.distance_m,
                    r.shadow.distance_m,
                    r.base.effective_m,
                    r.shadow.effective_m,
                    r.shadow.overlay_m,
                ]
                for r in sorted(output.results, key=lambda r: (r.journey.journey_id, r.profile_key))
            ],
        },
        "algorithm_agreement": {
            "graph": "shadow",
            "checked": len(output.agreement),
            "agree": len(output.agreement) - len(disagreements),
            "disagreements": disagreements,
        },
        "conflicts": conflict_analysis(
            evidence, output.conflict_plan, output.results, output.sensitivity
        ),
        "validation_queue": {
            "what_it_is": (
                "City records to check in the field or with an external party first, chosen by "
                "explicit strata from measured impact; no field validation happened here."
            ),
            "strata": dict(VALIDATION_STRATA),
            "entries": queue,
        },
        "production_isolation": {
            "database": {
                "transactions": "READ ONLY, enforced by PostgreSQL",
                "content_checksum_before": dataset_before.content_checksum,
                "content_checksum_after": dataset_after.content_checksum,
                "unchanged": dataset_before.content_checksum == dataset_after.content_checksum
                and dataset_before.checksum == dataset_after.checksum,
            },
            **output.isolation,
            "shadow_graph": output.shadow_identity,
            "serving_code": (
                "no module that serves a route imports this study (test_kitchener_isolation.py)"
            ),
        },
        # Timings and memory vary between runs, so they sit under "run", which the
        # content hash leaves out: two runs of the same inputs must match on the rest.
        "run": {
            "timings_s": output.timings,
            "memory_mb": output.memory,
            "per_route": {corpus: timing(rows) for corpus, rows in sorted(by_corpus.items())},
            "context": "One laptop. Shadow-routing timings are not production latency.",
        },
        "results_sha256": results_digest(output.results),
        "limitations": list(LIMITATIONS),
        "licensing": (
            "The founder licensing gate stays closed. Kitchener assertions are used only in this "
            "offline research computation; none reaches the active graph, the routing API, the "
            "application or a published combined database."
        ),
        "attribution": dict(attribution),
    }


def _journey(journey: Journey) -> dict[str, Any]:
    found: dict[str, Any] = {
        "id": journey.journey_id,
        "origin": [round(journey.origin[0], 7), round(journey.origin[1], 7)],
        "destination": [round(journey.destination[0], 7), round(journey.destination[1], 7)],
    }
    if journey.stratum:
        found["stratum"] = journey.stratum
        found["anchor_records"] = list(journey.anchor_records)
    return found
