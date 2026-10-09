"""PA-GEO-09 on invented streets and PathAble's own router.

What these protect:

- the reconciliation keeps only what PA-GEO-08's conditions allow: no
  abstention, no record over 20 m, no kerb node, no kerb-tagged way, every set
  possibly incomplete, every row not_routing_eligible;
- an assertion reaches a routing location only on one crossing segment, at
  its end, where the production kerb is unknown — never on a sidewalk, never
  spread along a way, never over an OSM kerb fact, never inferred from an
  element the matcher omitted;
- the shadow changes costs through the production cost model and leaves the
  baseline graph exactly as it was; the standard route never moves;
- Dijkstra and A* agree on the shadow graph; two builds give one digest.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import LineString, Point

from pathable_api.geo.enums import KerbType
from pathable_api.geo.features import EdgeFeatures, normalise_edge
from pathable_api.geo.kitchener.assertions import NOT_ROUTING_ELIGIBLE, Assertion, Dates, Topic
from pathable_api.geo.kitchener.conflation import (
    AMBIGUOUS,
    MATCHED,
    ConflationInputs,
    Population,
    Record,
    RelationshipIndex,
)
from pathable_api.geo.kitchener.correspondence import KitchenerFeature, KitchenerIndex, OsmIndex
from pathable_api.geo.kitchener.curb_ramp_page import WATERMARK, render_page
from pathable_api.geo.kitchener.curb_ramp_reconciliation import (
    ACCEPTED_MATCHER,
    BLOCKED_BY_COMPLETENESS,
    Completeness,
    CurbRampCorrespondence,
    CurbRampError,
    Geo08Binding,
    Stage,
    WayExtent,
    bind_geo08,
    build_correspondences,
    check_binding,
    decide_pilot,
    invariant_violations,
    pre_graph_funnel,
    reconciliation_digest,
    write_artifact,
)
from pathable_api.geo.kitchener.curb_ramp_run import (
    Reconciled,
    extent_coordinates,
    rejected_examples,
    run_study,
    shadow_evidence,
)
from pathable_api.geo.kitchener.curb_ramp_shadow import (
    SEGMENT_END_M,
    SHADOW_KERB,
    SHADOW_POLICY_VERSION,
    Outcome,
    Placement,
    cost_equivalent_kerbs,
    kerb_evidence_changes_cost,
    kerb_profiles,
    kerb_rules,
    map_record,
    plan_substitutions,
    shadow_kerb_graph,
)
from pathable_api.geo.kitchener.curb_ramp_study import (
    KerbRouteFacts,
    anchors,
    classify,
    kerb_lookup,
    results_digest,
    run_pair,
    targeted_corpus,
)
from pathable_api.geo.kitchener.osm_extract import OsmNode, OsmWay, StudyExtract
from pathable_api.geo.kitchener.reconciliation import CityFields
from pathable_api.geo.kitchener.shadow_overlay import (
    SegmentSource,
    WaySegment,
    locate_segments,
    way_vertex_positions,
)
from pathable_api.geo.kitchener.shadow_run import ActiveDataset
from pathable_api.geo.kitchener.shadow_study import Category, Journey, algorithms_agree
from pathable_api.geo.network import NetworkEdge, NetworkNode, NetworkPayload
from pathable_api.routing.graph import RoutableGraph, graph_from_payload
from pathable_api.routing.load_benchmark import fingerprint
from pathable_api.routing.profiles import PROFILES, STANDARD, get_profile
from tests.unit.kitchener_streets import CROSSING, SIDEWALK, Identity

LON, LAT = -80.49, 43.45
WHEELCHAIR = get_profile("wheelchair")


def at(east_m: float, north_m: float) -> tuple[float, float]:
    per_lon = 111_320.0 * math.cos(math.radians(LAT))
    return (LON + east_m / per_lon, LAT + north_m / 111_320.0)


class Streets:
    """Invented OSM ways in metres, cut at every node as the PBF import cuts them.

    Node names are integers written as strings, so the extract's refs and the
    graph's node ids agree the way they do for a real import.
    """

    def __init__(self) -> None:
        self.nodes: dict[int, tuple[float, float]] = {}
        self.edges: list[NetworkEdge] = []
        self.ways: dict[int, tuple[tuple[int, ...], dict[str, str]]] = {}
        self._next = 1

    def node(self, east: float, north: float) -> int:
        node_id = self._next
        self._next += 1
        self.nodes[node_id] = (east, north)
        return node_id

    def way(
        self,
        way_id: int,
        refs: list[int],
        tags: dict[str, str],
        features: EdgeFeatures | None = None,
    ) -> None:
        self.ways[way_id] = (tuple(refs), dict(tags))
        found = features or normalise_edge(dict(tags))
        for key, (u, v) in enumerate(pairwise(refs)):
            (x1, y1), (x2, y2) = self.nodes[u], self.nodes[v]
            self.edges.append(
                NetworkEdge(
                    source_u=str(u),
                    source_v=str(v),
                    edge_key=key,
                    geometry=LineString([at(x1, y1), at(x2, y2)]),
                    features=found,
                    source_way_id=str(way_id),
                )
            )

    def graph(self) -> RoutableGraph:
        nodes = [NetworkNode(str(n), Point(*at(*xy))) for n, xy in sorted(self.nodes.items())]
        return graph_from_payload(NetworkPayload(nodes=nodes, edges=self.edges))

    def sources(self) -> list[SegmentSource]:
        return [
            SegmentSource(e.source_u, e.source_v, e.edge_key, e.source_way_id) for e in self.edges
        ]

    def extract(self) -> StudyExtract:
        """The same ways in native metres, with an identity transform standing in for the projection."""
        return StudyExtract(
            nodes={
                i: OsmNode(i, xy[0], xy[1], 1, "2024-01-01T00:00:00Z", {})
                for i, xy in self.nodes.items()
            },
            ways={
                w: OsmWay(w, 1, "2024-01-01T00:00:00Z", tags, refs)
                for w, (refs, tags) in self.ways.items()
            },
        )

    def segments(self) -> dict[int, list[WaySegment]]:
        extract = self.extract()
        by_way, problems = locate_segments(
            self.sources(), extract, way_vertex_positions(extract, Identity())
        )
        assert not problems
        return by_way

    def bounds(self) -> tuple[float, float, float, float]:
        lons = [at(*xy)[0] for xy in self.nodes.values()]
        lats = [at(*xy)[1] for xy in self.nodes.values()]
        return (min(lons) - 0.001, min(lats) - 0.001, max(lons) + 0.001, max(lats) + 0.001)


def features_of(graph: RoutableGraph) -> dict[str, EdgeFeatures]:
    return {e.identity: e.features for e in graph.segments}


def city_assertion(record_id: int) -> Assertion:
    return Assertion(
        assertion_id=f"kitchener/{record_id}#curb_ramp",
        source_id="kitchener-active-transportation",
        source_record=f"kitchener/{record_id}",
        source_record_version=None,
        topic=Topic.CURB_RAMP,
        prop="curb_ramp",
        raw_attribute="CURBCUT",
        raw_value="Y",
        normalized_value="curb_ramp_present",
        value_state="non_default",
        usable=True,
        evidence_origin="administrative_assertion",
        scope="kitchener_record",
        capture_source="orthoimagery",
        dates=Dates(source_capture_date="2012-05-01"),
    )


def extent(way: int, start: float, end: float, tags: dict[str, str] | None = None) -> WayExtent:
    found = tags if tags is not None else CROSSING
    return WayExtent(
        way, start, end, 1, None, found.get("highway"), found.get("footway"), found.get("crossing"),
        "kerb" in found or found.get("barrier") == "kerb",
    )  # fmt: skip


def row(
    record_id: int,
    extents: list[WayExtent],
    *,
    length_m: float = 1.5,
    stage: Stage = Stage.CANDIDATE,
    state: str = MATCHED,
    rule: str = "curb_cut_ways_followed",
) -> CurbRampCorrespondence:
    return CurbRampCorrespondence(
        record_id=record_id,
        record_length_m=length_m,
        city=city_assertion(record_id),
        matcher_version=ACCEPTED_MATCHER,
        state=state,
        rule=rule,
        relationship="many_to_one",
        representation="separate_way" if state == MATCHED else "none",
        extents=tuple(extents),
        kerb_nodes_within_2m=(),
        in_geo06_blocked_set=True,
        completeness=row_completeness(stage),
        stage=stage,
    )


def row_completeness(stage: Stage) -> Completeness:
    if stage is Stage.ABSTAINED:
        return Completeness.ABSTAINED
    if stage is Stage.NO_COUNTERPART:
        return Completeness.NONE
    return Completeness.POSSIBLY_INCOMPLETE


# ---------------------------------------------------------------------------
# The street everything routes on
# ---------------------------------------------------------------------------


def two_crossings(
    *,
    long_crossing_tags: dict[str, str] | None = None,
    long_crossing_features: EdgeFeatures | None = None,
) -> tuple[Streets, dict[str, int]]:
    """Two sidewalks joined by two crossings, the western one 4 m longer.

    A wheelchair route from the south-west corner to the north-east one can
    cross at either end; the shorter eastern crossing wins unless kerb evidence
    makes the western one cheaper. Each crossing has a mid-road node, so each
    of its two halves is a crossing segment of its own, as a real three-node
    crossing way is. Sidewalks run 300 m south and north of the western
    crossing, so a targeted journey across it can snap to the network.
    """
    s = Streets()
    a0, a1, a2 = s.node(0, 0), s.node(100, 0), s.node(200, 0)
    b0, b1, b2 = s.node(0, 18), s.node(100, 14), s.node(200, 14)
    m1 = s.node(0, 9)
    e_mid = s.node(200, 7)
    south, north = s.node(0, -300), s.node(0, 318)
    s.way(1, [a0, a1, a2], SIDEWALK)
    s.way(2, [b0, b1, b2], SIDEWALK)
    # The western crossing: 18 m in two segments.
    s.way(3, [a0, m1, b0], long_crossing_tags or CROSSING, long_crossing_features)
    # The eastern crossing: 14 m in two segments.
    s.way(4, [a2, e_mid, b2], CROSSING)
    s.way(5, [south, a0], SIDEWALK)
    s.way(6, [b0, north], SIDEWALK)
    return s, {"a0": a0, "a1": a1, "a2": a2, "b0": b0, "b1": b1, "b2": b2, "m1": m1, "e_mid": e_mid}


def corner_journey(streets: Streets, nodes: dict[str, int]) -> Journey:
    origin = at(*streets.nodes[nodes["a0"]])
    destination = at(*streets.nodes[nodes["b2"]])
    return Journey("T000", "targeted", origin, destination)


# ---------------------------------------------------------------------------
# What the cost model does with a kerb, pinned
# ---------------------------------------------------------------------------


def test_the_shadow_kerb_costs_what_a_flush_kerb_or_no_kerb_costs_in_every_profile() -> None:
    profiles = list(PROFILES.values())
    assert set(cost_equivalent_kerbs(profiles)) >= {"lowered", "flush", "none"}
    assert "unknown" not in cost_equivalent_kerbs(profiles)
    assert SHADOW_KERB is KerbType.LOWERED


def test_every_selectable_profile_but_the_standard_one_is_moved_by_kerb_evidence() -> None:
    chosen = kerb_profiles()
    assert chosen[0] is STANDARD
    assert [p.key for p in chosen[1:]] == [
        "wheelchair", "walker", "crutches", "stroller", "reduced_mobility"
    ]  # fmt: skip
    assert not kerb_evidence_changes_cost(STANDARD)
    rules = kerb_rules(chosen)
    assert rules["any_hard_limit_reads_kerb"] is False
    assert rules["profiles"]["wheelchair"]["kerb_penalty_m"]["unknown"] == 90.0
    assert rules["profiles"]["wheelchair"]["kerb_penalty_m"]["lowered"] == 0.0


# ---------------------------------------------------------------------------
# Mapping to a routing location
# ---------------------------------------------------------------------------


def test_a_crossing_extent_at_the_segment_end_is_eligible_and_names_the_end_node() -> None:
    streets, nodes = two_crossings()
    found = map_record(
        row(1, [extent(3, 0.0, 1.5)]), streets.segments(), features_of(streets.graph())
    )

    assert found.outcome is Outcome.ELIGIBLE
    assert found.segment == f"{nodes['a0']}->{nodes['m1']}#0"
    assert found.end_node == str(nodes["a0"])
    assert found.distance_to_end_m == 0.0
    assert found.kerb_before is KerbType.UNKNOWN


def test_a_sidewalk_extent_is_never_given_crossing_kerb_semantics() -> None:
    streets, _nodes = two_crossings()
    found = map_record(
        row(1, [extent(1, 0.0, 1.5, SIDEWALK)]), streets.segments(), features_of(streets.graph())
    )

    assert found.outcome is Outcome.NO_CROSSING_EXTENT
    assert found.placements[0].placement is Placement.NOT_CROSSING
    assert found.segment is None


def test_an_incomplete_set_that_omits_the_crossing_infers_nothing_from_the_crossing_nearby() -> (
    None
):
    # The piece runs from the sidewalk's end onto crossing 3, but the matcher
    # named only the sidewalk (PA-GEO-08's commonest failure). Nothing maps.
    streets, _nodes = two_crossings()
    found = map_record(
        row(1, [extent(1, 0.0, 1.5, SIDEWALK)]), streets.segments(), features_of(streets.graph())
    )
    plan = plan_substitutions(
        [row(1, [extent(1, 0.0, 1.5, SIDEWALK)])], streets.segments(), features_of(streets.graph())
    )

    assert found.outcome is Outcome.NO_CROSSING_EXTENT
    assert plan.substitutions == {}


def test_a_set_naming_the_sidewalk_and_the_crossing_uses_only_the_crossing_extent() -> None:
    streets, nodes = two_crossings()
    found = map_record(
        row(1, [extent(1, 0.0, 1.0, SIDEWALK), extent(3, 0.0, 1.5)]),
        streets.segments(),
        features_of(streets.graph()),
    )

    assert found.outcome is Outcome.ELIGIBLE
    assert found.segment == f"{nodes['a0']}->{nodes['m1']}#0"
    assert found.unused_extents == 1


def test_a_curb_ramp_is_never_spread_along_a_whole_crossing_way() -> None:
    streets, nodes = two_crossings()
    plan = plan_substitutions(
        [row(1, [extent(3, 0.0, 1.5)])], streets.segments(), features_of(streets.graph())
    )

    # Way 3 has two segments; only the one the extent lies on is substituted.
    assert list(plan.substitutions) == [f"{nodes['a0']}->{nodes['m1']}#0"]
    assert plan.substitutions[f"{nodes['a0']}->{nodes['m1']}#0"].ends_asserted == 1


def test_an_extent_spilling_across_a_segment_boundary_is_not_placed() -> None:
    streets, _nodes = two_crossings()
    found = map_record(
        row(1, [extent(3, 8.0, 11.0)]), streets.segments(), features_of(streets.graph())
    )

    assert found.outcome is Outcome.EXTENT_SPANS_SEGMENTS


def test_an_extent_in_the_middle_of_a_crossing_segment_is_not_at_a_kerb() -> None:
    streets, _nodes = two_crossings()
    found = map_record(
        row(1, [extent(3, SEGMENT_END_M + 1.0, SEGMENT_END_M + 2.0)]),
        streets.segments(),
        features_of(streets.graph()),
    )

    assert found.outcome is Outcome.NOT_AT_SEGMENT_END
    assert found.distance_to_end_m == pytest.approx(SEGMENT_END_M + 1.0)


@pytest.mark.parametrize(
    ("tags", "features"),
    [
        ({**CROSSING, "kerb": "raised"}, None),
        (
            CROSSING,
            replace(normalise_edge(dict(CROSSING)), kerb=KerbType.LOWERED, kerb_from_node=True),
        ),
    ],
)
def test_an_existing_osm_kerb_fact_is_never_replaced(
    tags: dict[str, str], features: EdgeFeatures | None
) -> None:
    streets, _nodes = two_crossings(long_crossing_tags=tags, long_crossing_features=features)
    found = map_record(
        row(1, [extent(3, 0.0, 1.5)]), streets.segments(), features_of(streets.graph())
    )
    plan = plan_substitutions(
        [row(1, [extent(3, 0.0, 1.5)])], streets.segments(), features_of(streets.graph())
    )

    assert found.outcome is Outcome.EXISTING_OSM_KERB
    assert found.kerb_before is not KerbType.UNKNOWN
    assert plan.substitutions == {}


def test_a_record_reaching_two_crossing_segments_has_no_single_location() -> None:
    streets, _nodes = two_crossings()
    found = map_record(
        row(1, [extent(3, 0.0, 1.0), extent(4, 0.0, 1.0)]),
        streets.segments(),
        features_of(streets.graph()),
    )

    assert found.outcome is Outcome.SEVERAL_CROSSING_SEGMENTS


def test_an_extent_on_a_way_the_graph_leaves_out_reaches_nothing() -> None:
    streets, _nodes = two_crossings()
    found = map_record(
        row(1, [extent(99, 0.0, 1.5)]), streets.segments(), features_of(streets.graph())
    )

    assert found.outcome is Outcome.NO_ROUTING_SEGMENT


def test_only_candidates_are_mapped_and_two_ramps_on_one_segment_count_both_ends() -> None:
    streets, nodes = two_crossings()
    rows = [
        row(1, [extent(3, 0.0, 1.5)]),
        row(2, [extent(3, 8.0, 9.2)]),
        row(
            3,
            [extent(3, 0.0, 1.5)],
            stage=Stage.ABSTAINED,
            state=AMBIGUOUS,
            rule="curb_cut_at_junction",
        ),
        row(4, [extent(3, 0.0, 1.5)], length_m=30.0, stage=Stage.OVER_20M),
    ]
    plan = plan_substitutions(rows, streets.segments(), features_of(streets.graph()))

    assert sorted(plan.mappings) == [1, 2]
    segment = plan.substitutions[f"{nodes['a0']}->{nodes['m1']}#0"]
    assert segment.records == (1, 2)
    assert segment.ends_asserted == 2


def test_the_plan_digest_is_the_same_for_the_same_rows() -> None:
    streets, _nodes = two_crossings()
    rows = [row(1, [extent(3, 0.0, 1.5)])]
    first = plan_substitutions(rows, streets.segments(), features_of(streets.graph()))
    second = plan_substitutions(
        list(reversed(rows)), streets.segments(), features_of(streets.graph())
    )

    assert first.digest == second.digest
    assert first.policy == SHADOW_POLICY_VERSION


# ---------------------------------------------------------------------------
# Routing on the shadow
# ---------------------------------------------------------------------------


def shadow_pair(
    streets: Streets, rows: list[CurbRampCorrespondence]
) -> tuple[RoutableGraph, RoutableGraph, Any]:
    graph = streets.graph()
    plan = plan_substitutions(rows, streets.segments(), features_of(graph))
    return graph, shadow_kerb_graph(graph, plan), plan


def test_a_municipal_curb_ramp_on_the_longer_crossing_moves_the_wheelchair_route() -> None:
    streets, nodes = two_crossings()
    graph, shadow, plan = shadow_pair(streets, [row(1, [extent(3, 0.0, 1.5)])])
    journey = corner_journey(streets, nodes)

    result, pair = run_pair(
        journey,
        WHEELCHAIR,
        graph,
        shadow,
        plan.substitutions,
        (kerb_lookup(graph), kerb_lookup(shadow)),
    )

    assert result.category is Category.ROUTE_CHANGED
    assert pair is not None
    assert result.cause is not None
    assert result.cause["cost_delta_m"] < 0
    assert result.cause["kerb_cost_delta_m"] == pytest.approx(-90.0)
    assert result.cause["records"] == [1]
    assert f"{nodes['a0']}->{nodes['m1']}#0" in result.shadow.path
    assert result.shadow.unknown_kerb_crossings == result.base.unknown_kerb_crossings - 1
    assert not result.unexplained
    assert result.feasibility is None


def test_the_shortest_distance_route_never_moves() -> None:
    streets, nodes = two_crossings()
    graph, shadow, plan = shadow_pair(streets, [row(1, [extent(3, 0.0, 1.5)])])

    result, _ = run_pair(
        corner_journey(streets, nodes),
        STANDARD,
        graph,
        shadow,
        plan.substitutions,
        (kerb_lookup(graph), kerb_lookup(shadow)),
    )

    assert result.category is Category.NOT_EXPOSED
    assert result.base.path == result.shadow.path


def test_a_ramp_on_the_chosen_crossing_changes_only_its_cost() -> None:
    streets, nodes = two_crossings()
    # The eastern crossing is the baseline's choice; a ramp there lowers its cost only.
    graph, shadow, plan = shadow_pair(streets, [row(1, [extent(4, 0.0, 1.5)])])

    result, _ = run_pair(
        corner_journey(streets, nodes),
        WHEELCHAIR,
        graph,
        shadow,
        plan.substitutions,
        (kerb_lookup(graph), kerb_lookup(shadow)),
    )

    assert result.category is Category.COST_ONLY
    assert result.shadow.effective_m < result.base.effective_m
    assert result.base.path == result.shadow.path


def test_the_baseline_graph_is_untouched_and_routes_as_before() -> None:
    streets, nodes = two_crossings()
    graph = streets.graph()
    before = fingerprint(graph)
    before_kerbs = kerb_lookup(graph)
    plan = plan_substitutions(
        [row(1, [extent(3, 0.0, 1.5)])], streets.segments(), features_of(graph)
    )
    journey = corner_journey(streets, nodes)
    first, _ = run_pair(journey, WHEELCHAIR, graph, graph, {}, (before_kerbs, before_kerbs))

    shadow = shadow_kerb_graph(graph, plan)
    run_pair(
        journey, WHEELCHAIR, graph, shadow, plan.substitutions, (before_kerbs, kerb_lookup(shadow))
    )

    assert fingerprint(graph) == before
    assert kerb_lookup(graph) == before_kerbs
    assert shadow.graph is not graph.graph
    assert kerb_lookup(shadow)[f"{nodes['a0']}->{nodes['m1']}#0"] is SHADOW_KERB
    again, _ = run_pair(journey, WHEELCHAIR, graph, graph, {}, (before_kerbs, before_kerbs))
    assert again.base.outcome() == first.base.outcome()


def test_dijkstra_and_a_star_agree_on_the_shadow_graph() -> None:
    streets, nodes = two_crossings()
    graph, shadow, _plan = shadow_pair(streets, [row(1, [extent(3, 0.0, 1.5)])])
    journey = corner_journey(streets, nodes)

    for found in (
        algorithms_agree(shadow, journey, WHEELCHAIR),
        algorithms_agree(graph, journey, WHEELCHAIR),
    ):
        assert found["agree"], found


def test_each_change_lands_in_one_category() -> None:
    exists = KerbRouteFacts(True, path=("a",), effective_m=100.0, unknown_kerb_crossings=1)
    assert (
        classify(exists, replace(exists, exists=False), blocked=False)
        is Category.FEASIBILITY_CHANGED
    )
    assert classify(exists, replace(exists, path=("b",)), blocked=False) is Category.ROUTE_CHANGED
    assert classify(exists, replace(exists, effective_m=90.0), blocked=False) is Category.COST_ONLY
    assert (
        classify(exists, replace(exists, unknown_kerb_crossings=0), blocked=False)
        is Category.EVIDENCE_ONLY
    )
    assert (
        classify(exists, replace(exists, substituted=("a",)), blocked=False) is Category.NO_EFFECT
    )
    assert classify(exists, exists, blocked=False) is Category.NOT_EXPOSED
    gone = replace(exists, exists=False)
    assert classify(gone, gone, blocked=False) is Category.NO_ROUTE_EITHER


# ---------------------------------------------------------------------------
# Corpora
# ---------------------------------------------------------------------------


def test_the_targeted_corpus_is_the_same_for_the_same_seed_and_crosses_the_segment() -> None:
    streets, _nodes = two_crossings()
    _graph, shadow, plan = shadow_pair(streets, [row(1, [extent(3, 0.0, 1.5)])])
    found = anchors(shadow, plan.substitutions)

    first = targeted_corpus(found, seed="test", per_stratum=2)
    second = targeted_corpus(found, seed="test", per_stratum=2)

    assert first == second
    assert len(first) == 1
    assert first[0].stratum == "one_end/unmarked/sparse"
    assert first[0].anchor_records == (1,)
    # 250 m either side of the crossing, along it: north and south of the street.
    assert first[0].origin[1] < at(0, 0)[1] < at(0, 18)[1] < first[0].destination[1]


# ---------------------------------------------------------------------------
# The reconciliation, from matcher decisions
# ---------------------------------------------------------------------------


def record(record_id: int, points: list[tuple[float, float]], *, curb_cut: bool = True) -> Record:
    geometry = LineString(points)
    return Record(
        activetransportid=record_id,
        network_role="pedestrian_way",
        family="sidewalk",
        subcategory="SIDEWALK",
        structure=None,
        curb_cut=curb_cut,
        surface_material=None,
        length_m=float(geometry.length),
        street="FIXTURE ST",
        geometry=geometry,
        attributes={
            "curbcut": "Y" if curb_cut else "N",
            "state_curbcut": "non_default",
            "origin_curbcut": "administrative_assertion",
            "source_class": "orthoimagery",
            "last_inspection_year": 2021,
        },
    )


def conflation_inputs(records: list[Record], extract: StudyExtract) -> ConflationInputs:
    index = OsmIndex.build(extract, Identity())
    physical = KitchenerIndex.build(
        KitchenerFeature(
            r.activetransportid, "physical_active", r.network_role, r.subcategory, r.geometry
        )
        for r in records
    )
    return ConflationInputs(
        osm=index,
        population=Population(records, {}, physical),
        eligible=physical,
        relationships=RelationshipIndex(physical, index.lines),
        parquet=Path("fixture.parquet"),
        identity={
            "kitchener": {"snapshot_id": "fixture"},
            "osm_frozen": {"extract_sha256": "e" * 64},
        },
    )


def scene() -> tuple[Streets, ConflationInputs, dict[str, int]]:
    """Two crossings and four City curb cuts: one onto crossing 3, one abstaining at a
    diagonal corner, one along the sidewalk, one 30 m long."""
    streets, nodes = two_crossings()
    corner = streets.node(300, 0)
    streets.way(6, [nodes["a2"], corner], SIDEWALK)
    streets.way(7, [corner, streets.node(300, 50)], SIDEWALK)
    streets.way(8, [corner, streets.node(300, -14)], CROSSING)
    records = [
        record(1, [(0.3, -1.0), (0.3, 1.5)]),
        record(2, [(299.3, -0.7), (300.7, 0.7)]),
        record(3, [(40, 0.3), (43, 0.3)]),
        record(4, [(50, 0.3), (80, 0.3)]),
    ]
    return streets, conflation_inputs(records, streets.extract()), nodes


def city_fields() -> dict[int, CityFields]:
    return {
        i: CityFields("2015-01-01T00:00:00Z", "2020-01-01T00:00:00Z", None, "2012-05-01")
        for i in range(1, 5)
    }


def test_the_reconciliation_keeps_matches_and_names_every_exclusion() -> None:
    _streets, inputs, _nodes = scene()
    decisions = decide_pilot(inputs)
    rows = {r.record_id: r for r in build_correspondences(inputs, decisions, city_fields())}

    assert rows[1].stage is Stage.CANDIDATE
    assert rows[1].rule == "curb_cut_ways_followed"
    # The piece follows the south-approach sidewalk and the crossing: a two-way set,
    # of which only the crossing extent can reach a routing location.
    assert {e.way_id for e in rows[1].extents} == {3, 5}
    assert {e.footway for e in rows[1].extents} == {"crossing", "sidewalk"}
    assert rows[2].stage is Stage.ABSTAINED
    assert rows[3].stage is Stage.CANDIDATE
    assert [e.way_id for e in rows[3].extents] == [1]
    assert rows[4].stage is Stage.OVER_20M
    assert all(r.routing_eligibility == NOT_ROUTING_ELIGIBLE for r in rows.values())
    assert BLOCKED_BY_COMPLETENESS in rows[1].blockers
    assert "blocked_by_licensing" in rows[1].blockers
    assert str(Stage.OVER_20M) in rows[4].blockers
    assert rows[1].city.raw_value == "Y"
    assert rows[1].city.dates.source_capture_date == "2012-05-01"
    assert invariant_violations(rows.values()) == []


def test_a_curb_cut_with_a_kerb_node_is_outside_this_card() -> None:
    streets, nodes = two_crossings()
    extract = streets.extract()
    extract.nodes[nodes["a0"]].tags.update({"barrier": "kerb", "kerb": "lowered"})
    inputs = conflation_inputs([record(1, [(0.3, -1.0), (0.3, 1.5)])], extract)
    decisions = decide_pilot(inputs)

    assert decisions.v2[1].rule == "curb_cut_kerb_and_ways"
    assert build_correspondences(inputs, decisions, city_fields()) == []


def test_two_builds_give_one_digest_and_the_artifact_hashes_it(tmp_path: Path) -> None:
    _streets, inputs, _nodes = scene()
    decisions = decide_pilot(inputs)
    first = build_correspondences(inputs, decisions, city_fields())
    second = build_correspondences(inputs, decide_pilot(inputs), city_fields())
    binding = Geo08Binding(
        tmp_path / "x.json",
        "c" * 64,
        decisions.v2_digest,
        4,
        ACCEPTED_MATCHER,
        "fixture",
        "e" * 64,
        2,
        1,
    )

    manifest = write_artifact(
        tmp_path / "artifact",
        first,
        binding=binding,
        inputs_identity=inputs.identity,
        attribution={"k": "v"},
    )

    assert reconciliation_digest(first) == reconciliation_digest(second) == manifest["rows_sha256"]
    rows = json.loads(
        (tmp_path / "artifact" / "curb_ramp_correspondences.json").read_text("utf-8")
    )["rows"]
    assert {r["routing_eligibility"] for r in rows} == {NOT_ROUTING_ELIGIBLE}
    assert manifest["files"]["curb_ramp_correspondences"]["rows"] == 4


def test_the_funnel_is_recomputed_from_the_decisions() -> None:
    _streets, inputs, _nodes = scene()
    decisions = decide_pilot(inputs)
    rows = build_correspondences(inputs, decisions, city_fields())

    funnel = pre_graph_funnel(inputs, decisions, rows)

    assert funnel["city_curb_cuts_in_the_pilot"] == 4
    assert funnel["in_scope"]["records"] == 4
    assert funnel["stages"] == {
        str(Stage.ABSTAINED): 1,
        str(Stage.CANDIDATE): 2,
        str(Stage.OVER_20M): 1,
    }


def geo08_evidence(path: Path, digest: str, *, records: int = 4) -> None:
    path.write_text(
        json.dumps(
            {
                "content_sha256": "c" * 64,
                "policy": {"version": ACCEPTED_MATCHER},
                "inputs": {
                    "kitchener": {"snapshot_id": "fixture"},
                    "osm_frozen": {"extract_sha256": "e" * 64},
                },
                "full_pilot_dry_run": {
                    "records": records,
                    "decisions_sha256": digest,
                    "potential_evidence": {
                        "curb_ramps_at_a_local_way_extent_where_osm_records_no_kerb": 2,
                        "curb_ramps_whose_record_spans_over_20m": 1,
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def test_pilot_decisions_that_do_not_reproduce_the_committed_evidence_are_refused(
    tmp_path: Path,
) -> None:
    _streets, inputs, _nodes = scene()
    decisions = decide_pilot(inputs)
    geo08_evidence(tmp_path / "kitchener-geo08-matcher-v2.json", decisions.v2_digest)
    binding = bind_geo08(tmp_path)
    check_binding(inputs, decisions, binding)

    geo08_evidence(tmp_path / "kitchener-geo08-matcher-v2.json", "0" * 64)
    with pytest.raises(CurbRampError, match="not the ones PA-GEO-08's evidence records"):
        check_binding(inputs, decisions, bind_geo08(tmp_path))
    geo08_evidence(tmp_path / "kitchener-geo08-matcher-v2.json", decisions.v2_digest, records=5)
    with pytest.raises(CurbRampError, match="evidence records 5"):
        check_binding(inputs, decisions, bind_geo08(tmp_path))


# ---------------------------------------------------------------------------
# The whole study, offline
# ---------------------------------------------------------------------------


def test_the_whole_study_runs_and_writes_evidence_that_admits_nothing(tmp_path: Path) -> None:
    streets, inputs, nodes = scene()
    decisions = decide_pilot(inputs)
    rows = build_correspondences(inputs, decisions, city_fields())
    binding = Geo08Binding(
        tmp_path / "x.json",
        "c" * 64,
        decisions.v2_digest,
        4,
        ACCEPTED_MATCHER,
        "fixture",
        "e" * 64,
        2,
        1,
    )
    manifest = write_artifact(
        tmp_path / "artifact",
        rows,
        binding=binding,
        inputs_identity=inputs.identity,
        attribution={"k": "v"},
    )
    extract = streets.extract()
    reconciled = Reconciled(
        binding=binding,
        inputs_identity=inputs.identity,
        rows=rows,
        funnel=pre_graph_funnel(inputs, decisions, rows),
        pilot_decisions_sha256=decisions.v2_digest,
        rows_sha256=reconciliation_digest(rows),
        artifact_manifest=manifest,
        extract=extract,
        positions=way_vertex_positions(extract, Identity()),
        timings={"reconciliation_build_s": 0.1},
        memory_mb=None,
    )
    graph = streets.graph()
    before = fingerprint(graph)

    output = run_study(
        graph,
        streets.sources(),
        reconciled,
        bounds=streets.bounds(),
        broad_size=3,
        seed="test",
        per_stratum=2,
        recheck=2,
    )

    assert output.mapping["outcomes"] == {
        str(Outcome.ELIGIBLE): 1,
        str(Outcome.NO_CROSSING_EXTENT): 1,
    }
    assert list(output.plan.substitutions) == [f"{nodes['a0']}->{nodes['m1']}#0"]
    assert fingerprint(graph) == before
    assert output.isolation["baseline_graph_unchanged"]
    rerouted = output.isolation["baseline_rerouted_after_study"]
    assert rerouted["identical"] == rerouted["routes"] > 0
    assert len(output.results) == len(output.profiles) * (
        len(output.corpora["broad"]) + len(output.corpora["targeted"])
    )
    assert all(a["agree"] for a in output.agreement)
    assert not any(r.unexplained for r in output.results)
    assert not any(r.category is Category.FEASIBILITY_CHANGED for r in output.results)
    standard = [r for r in output.results if r.profile_key == "standard"]
    assert all(r.base.path == r.shadow.path for r in standard)

    dataset = ActiveDataset(uuid.uuid4(), "i" * 64, "fixture", "c" * 64, 2)
    document = shadow_evidence(
        reconciled=reconciled,
        output=output,
        dataset_before=dataset,
        dataset_after=dataset,
        extract_sha256="x" * 64,
        seed="test",
        attribution={"k": "v"},
    )
    page = render_page(
        output.results, output.pairs, {p.key: p for p in output.profiles}, output.plan.substitutions,
        rejected_examples(reconciled, output.plan, graph), {"k": "v"},
    )  # fmt: skip

    serialised = json.loads(json.dumps(document))
    assert serialised["production_isolation"]["database"]["unchanged"]
    assert serialised["input_funnel"]["final_shadow_eligible_assertions"] == 1
    assert serialised["input_funnel"]["final_affected_crossing_segments"] == 1
    assert serialised["input_funnel"]["exact_routing_location_mapping_failures"] == {
        str(Outcome.NO_CROSSING_EXTENT): 1
    }
    rows_by_id = {r["record_id"]: r for r in serialised["routing_mapping"]["records"]}
    assert rows_by_id[1]["outcome"] == str(Outcome.ELIGIBLE)
    assert rows_by_id[3]["outcome"] == str(Outcome.NO_CROSSING_EXTENT)
    assert rows_by_id[3]["placements"][0]["placement"] == "sidewalk_or_path_segment"
    assert serialised["defects"] == {
        "unexplained_changes": 0,
        "feasibility_changes": 0,
        "cost_rises_on_a_changed_route": 0,
    }
    assert (
        serialised["reconciliation"]["routing_eligibility"] == "not_routing_eligible on every row"
    )
    assert serialised["kerb_in_routing_today"]["shadow_kerb"] == "lowered"
    assert serialised["results_sha256"] == results_digest(output.results)
    assert WATERMARK in page
    assert "Candidates the mapping refused" in page
    assert "City record 3" in page


def test_an_extent_is_drawn_along_its_way_between_the_nodes() -> None:
    streets, nodes = two_crossings()
    extract = streets.extract()
    positions = way_vertex_positions(extract, Identity())

    coords = extent_coordinates(extract, positions, 3, 0.0, 5.0)

    assert coords[0] == (0.0, 0.0)
    assert coords[-1] == (0.0, 5.0)
    assert extent_coordinates(extract, positions, 99, 0.0, 1.0) == ()
    assert nodes["m1"] in extract.ways[3].refs
