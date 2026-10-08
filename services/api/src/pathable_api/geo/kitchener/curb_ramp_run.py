"""PA-GEO-09 end to end: reconcile offline, read the active graph read-only, route both corpora, write the evidence.

Two stages. The first needs no database: PA-GEO-08's committed evidence is
bound, the pilot decisions are re-made and refused unless they reproduce it,
and every in-scope curb cut becomes a reconciliation row in the ignored data
folder. The second reads the active dataset inside ``READ ONLY`` transactions,
maps each candidate to the one routing segment where a kerb could be charged,
builds the shadow copy, routes both corpora on both graphs, and proves the
loaded graph and the database are as they were.
"""

from __future__ import annotations

import functools
import hashlib
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from pathable_api.geo.enums import KerbType
from pathable_api.geo.kitchener.conflation import load_inputs
from pathable_api.geo.kitchener.correspondence import to_native
from pathable_api.geo.kitchener.curb_ramp_page import DrawnSegment, RejectedExample
from pathable_api.geo.kitchener.curb_ramp_reconciliation import (
    MAX_RECORD_LENGTH_M,
    RECONCILIATION_VERSION,
    CurbRampCorrespondence,
    CurbRampError,
    Geo08Binding,
    Stage,
    bind_geo08,
    build_correspondences,
    check_binding,
    decide_pilot,
    invariant_violations,
    pre_graph_funnel,
    reconciliation_digest,
    write_artifact,
)
from pathable_api.geo.kitchener.curb_ramp_shadow import (
    SEGMENT_END_M,
    SHADOW_KERB,
    SHADOW_POLICY_VERSION,
    SPILL_M,
    CurbRampPlan,
    Outcome,
    kerb_profiles,
    kerb_rules,
    mapping_summary,
    plan_substitutions,
    shadow_kerb_graph,
)
from pathable_api.geo.kitchener.curb_ramp_study import (
    BROAD_CORPUS_VERSION,
    TARGETED_CORPUS_VERSION,
    Result,
    anchors,
    assess,
    kerb_lookup,
    results_digest,
    route_facts,
    summarise_results,
    targeted_corpus,
    timing,
)
from pathable_api.geo.kitchener.osm_extract import StudyExtract
from pathable_api.geo.kitchener.reconciliation_run import city_record_fields
from pathable_api.geo.kitchener.shadow_overlay import (
    SegmentSource,
    locate_segments,
    way_vertex_positions,
)
from pathable_api.geo.kitchener.shadow_run import ActiveDataset
from pathable_api.geo.kitchener.shadow_study import (
    Category,
    Journey,
    Pair,
    algorithms_agree,
    broad_corpus,
    compare_on,
    corpus_digest,
)
from pathable_api.routing.comparison import RouteComparison
from pathable_api.routing.engine import RoutingError, compute_route
from pathable_api.routing.graph import RoutableGraph
from pathable_api.routing.load_benchmark import fingerprint, process_memory
from pathable_api.routing.profiles import STANDARD, MobilityProfile

Progress = Callable[[str], None]
Positions = dict[int, np.ndarray[Any, Any]]


# ---------------------------------------------------------------------------
# Stage one: reconcile, offline
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Reconciled:
    binding: Geo08Binding
    inputs_identity: dict[str, Any]
    rows: list[CurbRampCorrespondence]
    funnel: dict[str, Any]
    pilot_decisions_sha256: str
    rows_sha256: str
    artifact_manifest: dict[str, Any]
    extract: StudyExtract
    positions: Positions
    timings: dict[str, float]
    memory_mb: float | None


def reconcile(
    *,
    normalized: Path,
    extract_path: Path,
    extract_manifest: Path,
    evidence_dir: Path,
    artifact_dir: Path,
    attribution: Mapping[str, str],
    progress: Progress | None = None,
) -> Reconciled:
    """Bind, decide, build and write the rows. Needs neither the database nor the network."""
    say = progress or (lambda _message: None)
    timings: dict[str, float] = {}
    started = time.perf_counter()
    binding = bind_geo08(evidence_dir)
    inputs = load_inputs(normalized, extract_path, extract_manifest, progress=say)
    timings["load_inputs_s"] = round(time.perf_counter() - started, 2)
    decisions = decide_pilot(inputs, progress=say)
    timings.update(decisions.timings)
    check_binding(inputs, decisions, binding)
    say(f"pilot decisions reproduce PA-GEO-08's evidence ({decisions.v2_digest[:12]})")
    started = time.perf_counter()
    city_fields, _curb_cuts = city_record_fields(inputs.parquet)
    rows = build_correspondences(inputs, decisions, city_fields)
    problems = invariant_violations(rows)
    if problems:
        msg = "the reconciliation refuses its own rows: " + "; ".join(problems[:5])
        raise CurbRampError(msg)
    funnel = pre_graph_funnel(inputs, decisions, rows)
    manifest = write_artifact(
        artifact_dir,
        rows,
        binding=binding,
        inputs_identity=inputs.identity,
        attribution=attribution,
    )
    timings["reconciliation_build_s"] = round(time.perf_counter() - started, 2)
    say(f"reconciled {len(rows)} in-scope curb cuts: {funnel['stages']}")
    positions = way_vertex_positions(inputs.osm.extract, to_native())
    return Reconciled(
        binding=binding,
        inputs_identity=inputs.identity,
        rows=rows,
        funnel=funnel,
        pilot_decisions_sha256=decisions.v2_digest,
        rows_sha256=reconciliation_digest(rows),
        artifact_manifest=manifest,
        extract=inputs.osm.extract,
        positions=positions,
        timings=timings,
        memory_mb=process_memory().rss_mb,
    )


# ---------------------------------------------------------------------------
# Stage two: the study, on the loaded graph
# ---------------------------------------------------------------------------


def adjacency_fingerprint(graph: RoutableGraph) -> str:
    """Every directed entry the router walks, with the kerb, crossing and surface it would cost."""
    lines = sorted(
        f"{u}|{v}|{key}|{data['edge'].identity}|{data['edge'].reversed}|"
        f"{data['edge'].features.kerb}|{data['edge'].features.is_crossing}|"
        f"{data['edge'].features.surface_class}"
        for u, v, key, data in graph.graph.edges(keys=True, data=True)
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def graph_identity(graph: RoutableGraph) -> dict[str, str]:
    found = fingerprint(graph)
    return {
        "segment_sha256": str(found["segment_sha256"]),
        "node_sha256": str(found["node_sha256"]),
        "adjacency_sha256": adjacency_fingerprint(graph),
    }


def _memory() -> float | None:
    return process_memory().rss_mb


def network_evidence(graph: RoutableGraph, plan: CurbRampPlan) -> dict[str, Any]:
    """Across the whole routing graph: crossings and their kerbs before, and what the shadow changes."""
    crossings = [e for e in graph.segments if e.features.is_crossing]
    kerbs = Counter(e.features.kerb.value for e in crossings)
    unknown = [e for e in crossings if e.features.kerb is KerbType.UNKNOWN]
    substituted_m = sum(e.length_m for e in crossings if e.identity in plan.substitutions)
    return {
        "segments": graph.segment_count,
        "crossing_segments": len(crossings),
        "crossing_kerb_before": dict(sorted(kerbs.items())),
        "crossing_segments_with_unknown_kerb": len(unknown),
        "crossing_metres_with_unknown_kerb": round(sum(e.length_m for e in unknown), 1),
        "candidate_municipal_crossing_segments": len(plan.substitutions),
        "candidate_municipal_crossing_metres": round(substituted_m, 1),
        "counterfactual_unknown_kerb_crossings": len(unknown) - len(plan.substitutions),
        "share_of_unknown_kerb_crossings_described": (
            round(len(plan.substitutions) / len(unknown), 4) if unknown else None
        ),
    }


@dataclass(slots=True)
class StudyOutput:
    plan: CurbRampPlan
    mapping: dict[str, Any]
    locate_problems: Counter[str]
    corpora: dict[str, list[Journey]]
    results: list[Result]
    pairs: dict[tuple[str, str], Pair]
    agreement: list[dict[str, Any]]
    isolation: dict[str, Any]
    network: dict[str, Any]
    timings: dict[str, float]
    memory: dict[str, float | None]
    shadow_identity: dict[str, str] = field(default_factory=dict)
    profiles: list[MobilityProfile] = field(default_factory=list)


def _given(comparison: RouteComparison) -> RouteComparison:
    return comparison


def run_study(
    graph: RoutableGraph,
    sources: Sequence[SegmentSource],
    reconciled: Reconciled,
    *,
    bounds: tuple[float, float, float, float],
    broad_size: int,
    seed: str,
    per_stratum: int,
    recheck: int = 12,
    agreement_sample: int = 20,
    progress: Progress | None = None,
) -> StudyOutput:
    say = progress or (lambda _message: None)
    timings: dict[str, float] = {}
    memory: dict[str, float | None] = {"after_load_mb": _memory()}

    started = time.perf_counter()
    by_way, problems = locate_segments(sources, reconciled.extract, reconciled.positions)
    features = {e.identity: e.features for e in graph.segments}
    lengths = {e.identity: e.length_m for e in graph.segments}
    plan = plan_substitutions(reconciled.rows, by_way, features)
    mapping = mapping_summary(plan, lengths)
    timings["routing_mapping_s"] = round(time.perf_counter() - started, 2)
    say(f"mapping: {mapping['outcomes']}; {len(plan.substitutions)} crossing segments")

    before = graph_identity(graph)
    started = time.perf_counter()
    shadow = shadow_kerb_graph(graph, plan)
    timings["shadow_graph_build_s"] = round(time.perf_counter() - started, 2)
    memory["after_shadow_graph_mb"] = _memory()
    lookups = (kerb_lookup(graph), kerb_lookup(shadow))
    profiles = kerb_profiles()

    def routable(origin: tuple[float, float], destination: tuple[float, float]) -> bool:
        try:
            compute_route(graph, origin=origin, destination=destination, profile=STANDARD)
        except RoutingError:
            return False
        return True

    started = time.perf_counter()
    broad = broad_corpus(graph, size=broad_size, seed=seed, bounds=bounds, routable=routable)
    targeted = targeted_corpus(
        anchors(shadow, plan.substitutions), seed=seed, per_stratum=per_stratum, routable=routable
    )
    timings["corpus_build_s"] = round(time.perf_counter() - started, 2)
    say(f"corpora: {len(broad)} broad, {len(targeted)} targeted journeys")

    results: list[Result] = []
    pairs: dict[tuple[str, str], Pair] = {}
    for name, journeys in (("broad", broad), ("targeted", targeted)):
        started = time.perf_counter()
        for count, journey in enumerate(journeys, 1):
            for profile in profiles:
                base_cmp = compare_on(graph, journey, profile)
                result, pair = assess(
                    journey,
                    profile,
                    route_facts(base_cmp, profile, plan.substitutions),
                    compare_on(shadow, journey, profile),
                    plan.substitutions,
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

    # Dijkstra against A*: every changed route on both graphs, and a fixed
    # sample of each corpus on the shadow graph for every accessible profile.
    started = time.perf_counter()
    by_key = {p.key: p for p in profiles}
    journeys_by_id = {j.journey_id: j for j in (*broad, *targeted)}
    accessible = [p.key for p in profiles if not p.is_standard]
    sample = [
        (j.journey_id, key)
        for j in (*broad[:agreement_sample], *targeted[:agreement_sample])
        for key in accessible
    ]
    agreement = []
    for jid, key in dict.fromkeys([*sorted(pairs), *sample]):
        entry: dict[str, Any] = {"journey": jid, "profile": key, "changed": (jid, key) in pairs}
        entry["shadow"] = algorithms_agree(shadow, journeys_by_id[jid], by_key[key])
        if (jid, key) in pairs:
            entry["baseline"] = algorithms_agree(graph, journeys_by_id[jid], by_key[key])
        entry["agree"] = all(
            bool(entry[graph_name]["agree"])
            for graph_name in ("shadow", "baseline")
            if graph_name in entry
        )
        agreement.append(entry)
    timings["algorithm_agreement_s"] = round(time.perf_counter() - started, 2)

    after_shadow = graph_identity(graph)
    shadow_identity = graph_identity(shadow)
    del shadow

    first = {(r.journey.journey_id, r.profile_key): r for r in results}
    rechecked = []
    for journey in (*broad[:recheck], *targeted[:recheck]):
        for profile in profiles:
            again = route_facts(compare_on(graph, journey, profile), profile, plan.substitutions)
            rechecked.append(
                again.outcome() == first[(journey.journey_id, profile.key)].base.outcome()
            )
    isolation = {
        "baseline_graph_before_shadow": before,
        "baseline_graph_after_every_run": graph_identity(graph),
        "baseline_graph_unchanged": before == after_shadow == graph_identity(graph),
        "baseline_rerouted_after_study": {"routes": len(rechecked), "identical": sum(rechecked)},
    }
    memory["peak_mb"] = process_memory().peak_rss_mb
    return StudyOutput(
        plan=plan,
        mapping=mapping,
        locate_problems=problems,
        corpora={"broad": broad, "targeted": targeted},
        results=results,
        pairs=pairs,
        agreement=agreement,
        isolation=isolation,
        network=network_evidence(graph, plan),
        timings=timings,
        memory=memory,
        shadow_identity=shadow_identity,
        profiles=profiles,
    )


# ---------------------------------------------------------------------------
# Rejected mappings, drawn
# ---------------------------------------------------------------------------


def extent_coordinates(
    extract: StudyExtract, positions: Positions, way_id: int, from_m: float, to_m: float
) -> tuple[tuple[float, float], ...]:
    """The lon/lat of the metres ``from_m``..``to_m`` along a way, interpolated between its nodes."""
    way = extract.ways.get(way_id)
    cumulative = positions.get(way_id)
    if way is None or cumulative is None or len(way.refs) < 2:
        return ()
    lo, hi = min(from_m, to_m), max(from_m, to_m)
    points: list[tuple[float, float]] = []
    for i in range(len(way.refs) - 1):
        start, end = float(cumulative[i]), float(cumulative[i + 1])
        if end < lo or start > hi or end <= start:
            continue
        a, b = extract.nodes[way.refs[i]], extract.nodes[way.refs[i + 1]]
        for metres in (max(lo, start), min(hi, end)):
            t = (metres - start) / (end - start)
            point = (a.lon + (b.lon - a.lon) * t, a.lat + (b.lat - a.lat) * t)
            if not points or points[-1] != point:
                points.append(point)
    return tuple(points)


_CELL_DEG = 0.002


def _cells(coords: Sequence[tuple[float, float]]) -> set[tuple[int, int]]:
    lons = [p[0] for p in coords]
    lats = [p[1] for p in coords]
    found = set()
    for cx in range(int(min(lons) // _CELL_DEG), int(max(lons) // _CELL_DEG) + 1):
        for cy in range(int(min(lats) // _CELL_DEG), int(max(lats) // _CELL_DEG) + 1):
            found.add((cx, cy))
    return found


_REJECTION_NOTES = {
    Outcome.NO_CROSSING_EXTENT: (
        "Every named extent lies on a sidewalk or path segment. The router charges a kerb only "
        "on a crossing, and no crossing is inferred from the one nearby: the set may be "
        "incomplete, and nothing may be read from what it omits."
    ),
    Outcome.SEVERAL_CROSSING_SEGMENTS: (
        "The named extents reach two crossing segments, so the assertion has no single "
        "routing location."
    ),
    Outcome.EXTENT_SPANS_SEGMENTS: (
        "The crossing extent spills across a segment boundary by more than one sample, so it "
        "cannot be placed on one segment without spreading it."
    ),
    Outcome.NOT_AT_SEGMENT_END: (
        f"The crossing extent lies more than {SEGMENT_END_M:g} m from either end of its "
        "segment, where a kerb would sit."
    ),
    Outcome.EXISTING_OSM_KERB: (
        "The crossing segment already carries an OSM kerb fact, from the way or from a node at "
        "one of its ends; it is never replaced."
    ),
    Outcome.NO_ROUTING_SEGMENT: "No routing segment lies on any named extent.",
}


def rejected_examples(
    reconciled: Reconciled,
    plan: CurbRampPlan,
    graph: RoutableGraph,
    *,
    per_outcome: int = 1,
    padding_deg: float = 0.0004,
) -> list[RejectedExample]:
    """A deterministic handful of refused candidates, one or two per reason, with geometry to draw."""
    rows = {r.record_id: r for r in reconciled.rows}
    chosen: list[tuple[Outcome, int]] = []
    taken: Counter[str] = Counter()
    for record_id in sorted(plan.mappings):
        outcome = plan.mappings[record_id].outcome
        if outcome is Outcome.ELIGIBLE or taken[str(outcome)] >= per_outcome:
            continue
        taken[str(outcome)] += 1
        chosen.append((outcome, record_id))
    if not chosen:
        return []
    grid: dict[tuple[int, int], list[str]] = defaultdict(list)
    by_identity = {e.identity: e for e in graph.segments}
    for edge in graph.segments:
        for cell in _cells([(float(x), float(y)) for x, y, *_ in edge.geometry.coords]):
            grid[cell].append(edge.identity)
    examples = []
    for outcome, record_id in chosen:
        row = rows[record_id]
        extents = []
        for extent in row.extents:
            coords = extent_coordinates(
                reconciled.extract, reconciled.positions, extent.way_id, extent.from_m, extent.to_m
            )
            if coords:
                extents.append((extent.element, coords))
        if not extents:
            continue
        points = [p for _way, coords in extents for p in coords]
        west = min(p[0] for p in points) - padding_deg
        east = max(p[0] for p in points) + padding_deg
        south = min(p[1] for p in points) - padding_deg
        north = max(p[1] for p in points) + padding_deg
        near: list[DrawnSegment] = []
        seen: set[str] = set()
        for cell in _cells([(west, south), (east, north)]):
            for identity in grid.get(cell, ()):
                if identity in seen:
                    continue
                seen.add(identity)
                edge = by_identity[identity]
                coords_e = tuple((float(x), float(y)) for x, y, *_ in edge.geometry.coords)
                if all(not (west <= x <= east and south <= y <= north) for x, y in coords_e):
                    continue
                near.append(
                    DrawnSegment(
                        identity,
                        coords_e,
                        edge.features.is_crossing,
                        identity in plan.substitutions,
                    )
                )
        near.sort(key=lambda s: s.identity)
        examples.append(
            RejectedExample(
                record_id=record_id,
                outcome=str(outcome),
                rule=row.rule,
                record_length_m=row.record_length_m,
                extents=tuple(extents),
                segments=tuple(near),
                note=_REJECTION_NOTES.get(outcome, ""),
            )
        )
    return examples


# ---------------------------------------------------------------------------
# What the evidence says
# ---------------------------------------------------------------------------


def input_funnel(reconciled: Reconciled, output: StudyOutput) -> dict[str, Any]:
    """From the City's curb cuts to the crossing segments the shadow costs differently."""
    funnel = reconciled.funnel
    stages = funnel["stages"]
    mapping = output.mapping
    outcomes = mapping["outcomes"]
    failures = {k: v for k, v in outcomes.items() if k != str(Outcome.ELIGIBLE)}
    return {
        "city_curb_cuts_in_the_pilot": funnel["city_curb_cuts_in_the_pilot"],
        "geo06_blocked_curb_cuts": funnel["geo06_blocked_curb_cuts"],
        "curb_cuts_without_a_kerb_node_in_scope": funnel["in_scope"],
        "matcher_v2_corresponded_at_way_extents": stages.get(str(Stage.CANDIDATE), 0)
        + stages.get(str(Stage.OVER_20M), 0)
        + stages.get(str(Stage.OSM_WAY_KERB), 0),
        "matcher_abstentions": stages.get(str(Stage.ABSTAINED), 0),
        "no_counterpart": stages.get(str(Stage.NO_COUNTERPART), 0),
        "records_over_20m_excluded": stages.get(str(Stage.OVER_20M), 0),
        "existing_osm_fact_exclusions": {
            "kerb_tag_on_a_named_way": stages.get(str(Stage.OSM_WAY_KERB), 0),
            "kerb_on_the_crossing_segment": outcomes.get(str(Outcome.EXISTING_OSM_KERB), 0),
        },
        "candidates_for_routing_mapping": mapping["candidates"],
        "exact_routing_location_mapping_failures": failures,
        "final_shadow_eligible_assertions": mapping["eligible_assertions"],
        "final_affected_crossing_segments": mapping["affected_crossing_segments"],
        "final_affected_crossing_metres": mapping["affected_crossing_metres"],
    }


def changed_routes(
    results: Sequence[Result], plan: CurbRampPlan, rows: Mapping[int, CurbRampCorrespondence]
) -> list[dict[str, Any]]:
    """Every journey whose path or feasibility moved, with the City assertions behind it."""
    found = []
    for r in sorted(results, key=lambda r: (r.journey.journey_id, r.profile_key)):
        if r.cause is None and r.category is not Category.FEASIBILITY_CHANGED:
            continue
        records = sorted(set((r.cause or {}).get("records", [])))
        assertions = [
            {
                "record_id": record,
                "raw_value": rows[record].city.raw_value,
                "value_state": rows[record].city.value_state,
                "evidence_origin": rows[record].city.evidence_origin,
                "capture_source": rows[record].city.capture_source,
                "source_capture_date": rows[record].city.dates.source_capture_date,
                "freshness": rows[record].city.dates.freshness_basis,
                "segment": plan.mappings[record].segment,
                "distance_to_segment_end_m": plan.mappings[record].distance_to_end_m,
            }
            for record in records
            if record in rows and record in plan.mappings
        ]
        found.append(
            {
                "journey": r.journey.journey_id,
                "corpus": r.journey.corpus,
                "profile": r.profile_key,
                "category": str(r.category),
                "feasibility": r.feasibility,
                "unexplained": r.unexplained,
                "algorithm": r.shadow.algorithm,
                **(r.cause or {}),
                "city_assertions": assertions,
            }
        )
    return found


def records_that_moved_routes(results: Sequence[Result]) -> list[dict[str, Any]]:
    moved: Counter[int] = Counter()
    journeys: dict[int, set[str]] = defaultdict(set)
    for r in results:
        if r.cause is not None:
            for record in r.cause["records"]:
                moved[record] += 1
                journeys[record].add(r.journey.journey_id)
    return [
        {"record_id": record, "journey_profile_pairs": count, "journeys": len(journeys[record])}
        for record, count in sorted(moved.items(), key=lambda i: (-i[1], i[0]))
    ]


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


LIMITATIONS = (
    "A counterfactual: the City's curb ramps are treated as accepted only to measure what "
    "admitting them would change. None is validated, and nothing here is a route anyone "
    "should follow.",
    "The correspondences are matcher v2's decisions, measured once on a held-out sample "
    "against AI labels and unverified row by row; every set is treated as possibly incomplete.",
    "The routing location is the matcher's, not OSM's: a crossing segment the extent reaches "
    "at its end. One City ramp fills the segment the way one OSM kerb node does in production; "
    "the other end of the crossing is not asserted by it.",
    "CURBCUT = Y is read as a dropped kerb for costing only; the City states no kerb height, "
    "and the cost model charges lowered and flush kerbs identically.",
    "The City supplies no observation date for any curb cut: every assertion is dated only by "
    "when its record was captured, or not at all.",
    "The cost weights are engineering judgement, never validated with the people they model; "
    "a route change says what this cost model does, not what a traveller would choose.",
    "The broad corpus is an engineering sample of journeys across the pilot, not a sample of "
    "real trips; its change rates are not prevalence. The targeted corpus is chosen to cross "
    "the substituted segments and its rates describe nothing but itself.",
    "One dataset, one City snapshot, one laptop.",
)


def shadow_evidence(
    *,
    reconciled: Reconciled,
    output: StudyOutput,
    dataset_before: ActiveDataset,
    dataset_after: ActiveDataset,
    extract_sha256: str,
    seed: str,
    attribution: Mapping[str, str],
) -> dict[str, Any]:
    """The committed summary of one study run."""
    profiles = output.profiles
    broad = output.corpora["broad"]
    targeted = output.corpora["targeted"]
    by_corpus: dict[str, list[Result]] = defaultdict(list)
    for r in output.results:
        by_corpus[r.journey.corpus].append(r)
    disagreements = [a for a in output.agreement if not a["agree"]]
    rows = {r.record_id: r for r in reconciled.rows}
    eligible_rows = [
        rows[i] for i, m in output.plan.mappings.items() if m.outcome is Outcome.ELIGIBLE
    ]
    capture_years = Counter((r.city.dates.source_capture_date or "none")[:4] for r in eligible_rows)
    return {
        "kitchener_geo09_curb_ramp_shadow_routing_version": 1,
        "label": "Research counterfactual — not production routing; unvalidated municipal assertions",
        "what_it_is": (
            "PA-GEO-09: an offline shadow-routing study. City of Kitchener curb ramps that "
            "matcher v2 locates at the metres of an OSM way with no kerb node are reconciled as "
            "research rows, mapped to the one routing segment where PathAble charges a kerb — "
            "a crossing, at its end — and, where that mapping holds, substituted for an unknown "
            "kerb in a shadow copy of the active graph. The same journeys are routed on both "
            "graphs by PathAble's own router. It admits nothing: every row stays "
            "not_routing_eligible, and the production graph, database and API are untouched."
        ),
        "policy": {
            "reconciliation": RECONCILIATION_VERSION,
            "shadow": SHADOW_POLICY_VERSION,
            "shadow_kerb": SHADOW_KERB.value,
            "rule": [
                "Only a City curb cut matcher v2 matched to way extents, with no kerb node "
                "within 2 m and no kerb tag on a named way, is a candidate; abstentions, "
                f"records with no counterpart and records over {MAX_RECORD_LENGTH_M:g} m are "
                "excluded.",
                "A candidate reaches a routing location only if one named extent lies on one "
                "crossing segment of the production graph, spilling at most "
                f"{SPILL_M:g} m onto a neighbour, within {SEGMENT_END_M:g} m of one of that "
                "segment's end nodes, and that segment's production kerb is unknown.",
                "A sidewalk or path extent is never given crossing semantics, no crossing is "
                "inferred from one nearby, and a record naming two crossing segments has no "
                "single location.",
                "Where it holds, the shadow replaces the segment's unknown kerb with the kerb "
                "kind the cost model charges as dropped; nothing else changes.",
            ],
            "never_used": [
                "matcher v2 abstentions, including the junction cases",
                "curb cuts with an OSM kerb node (PA-GEO-06's class)",
                "any OSM kerb fact, from a way tag or a node at either end of the segment",
                "elements the matcher omitted from a set",
                "stairs, surfaces, structures, width, grade and condition",
            ],
        },
        "inputs": {
            "geo08": reconciled.binding.as_dict(),
            "pilot_decisions_sha256_reproduced": reconciled.pilot_decisions_sha256,
            "kitchener": reconciled.inputs_identity["kitchener"],
            "osm_study_extract_sha256": extract_sha256,
            "dataset": {
                "dataset_id": str(dataset_before.dataset_id),
                "source_name": dataset_before.source_name,
                "ingest_checksum": dataset_before.checksum,
                "content_checksum_version": dataset_before.content_checksum_version,
                "content_checksum": dataset_before.content_checksum,
            },
            "seed": seed,
        },
        "kerb_in_routing_today": kerb_rules(profiles),
        "reconciliation": {
            "artifact": {
                k: v
                for k, v in reconciled.artifact_manifest.items()
                if k in ("artifact_version", "versions", "files", "rows_sha256", "stored")
            },
            "rows": len(reconciled.rows),
            "stages": reconciled.funnel["stages"],
            "completeness": "every matched set is possibly_incomplete_set; nothing is inferred from an omitted element",
            "routing_eligibility": "not_routing_eligible on every row",
            "blockers_on_every_row": sorted(
                {b for r in reconciled.rows for b in r.blockers if not b.startswith("excluded_")}
            ),
        },
        "input_funnel": input_funnel(reconciled, output),
        "routing_mapping": {
            **output.mapping,
            "segments_that_could_not_be_located": dict(sorted(output.locate_problems.items())),
            "eligible_assertions_capture_year": dict(sorted(capture_years.items())),
            "eligible_assertions_evidence_origin": dict(
                sorted(Counter(r.city.evidence_origin for r in eligible_rows).items())
            ),
            "substitutions": [
                s.as_dict()
                for s in sorted(output.plan.substitutions.values(), key=lambda s: s.identity)
            ],
        },
        "network": output.network,
        "corpora": {
            "broad": {
                "version": BROAD_CORPUS_VERSION,
                "journeys": len(broad),
                "sha256": corpus_digest(broad),
                "first_200_sha256": corpus_digest(broad[:200]),
                "definition": (
                    "PA-GEO-07's broad corpus, unchanged: origins cycle through a 6 x 6 grid "
                    "over the pilot, each cell's walkable nodes in seeded hash order; each "
                    "destination is the first node in another hash order 800 m to 3 km away "
                    "in a straight line; kept when the standard route exists. No City "
                    "evidence is read, and the seed is PA-GEO-07's."
                ),
                "list": [_journey(j) for j in broad],
            },
            "targeted": {
                "version": TARGETED_CORPUS_VERSION,
                "journeys": len(targeted),
                "sha256": corpus_digest(targeted),
                "definition": (
                    "For each crossing segment the shadow substitutes, stratified by whether "
                    "one or both of its ends carry a City ramp, whether the crossing is marked "
                    "or signalised, and how many other substituted crossings lie within 200 m: "
                    "journeys from 250 m before to 250 m after the crossing along its own "
                    "direction, a few per stratum in seeded hash order. Chosen to cross City "
                    "evidence; its rates are not prevalence."
                ),
                "strata": dict(sorted(Counter(j.stratum or "" for j in targeted).items())),
                "list": [_journey(j) for j in targeted],
            },
            "profiles": [p.key for p in profiles],
        },
        "results": summarise_results(output.results),
        "route_changes": changed_routes(output.results, output.plan, rows),
        "records_that_moved_routes": records_that_moved_routes(output.results),
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
                "baseline_kerb_cost_m",
                "shadow_kerb_cost_m",
                "shadow_substituted_crossings",
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
                    r.base.kerb_cost_m,
                    r.shadow.kerb_cost_m,
                    len(r.shadow.substituted),
                ]
                for r in sorted(output.results, key=lambda r: (r.journey.journey_id, r.profile_key))
            ],
        },
        "algorithm_agreement": {
            "graphs": "shadow for every checked pair; baseline too for every changed pair",
            "checked": len(output.agreement),
            "agree": len(output.agreement) - len(disagreements),
            "disagreements": disagreements,
            "tolerance": "1e-6 relative on the optimal effective cost; feasibility must match",
        },
        "defects": {
            "unexplained_changes": sum(1 for r in output.results if r.unexplained),
            "feasibility_changes": sum(
                1 for r in output.results if r.category is Category.FEASIBILITY_CHANGED
            ),
            "cost_rises_on_a_changed_route": sum(
                1
                for r in output.results
                if r.cause is not None
                and r.cause["cost_delta_m"] is not None
                and r.cause["cost_delta_m"] > 1e-6
            ),
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
        "run": {
            "timings_s": {**reconciled.timings, **output.timings},
            "memory_mb": {"after_reconciliation_mb": reconciled.memory_mb, **output.memory},
            "per_route": {corpus: timing(rows_) for corpus, rows_ in sorted(by_corpus.items())},
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
