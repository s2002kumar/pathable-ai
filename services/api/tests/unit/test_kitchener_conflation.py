"""The matcher on invented streets: the difficult cases the benchmark is about.

Coordinates are metres; an identity transform stands in for the projection, so
every distance below is the distance drawn.
"""

from __future__ import annotations

from typing import Any

import pytest
from shapely.geometry import LineString

from pathable_api.geo.kitchener.conflation import (
    AMBIGUOUS,
    MATCHED,
    MATCHER_VERSION,
    POLICY_PROVENANCE,
    UNMATCHED,
    MatcherPolicy,
    Record,
    RelationshipIndex,
    baseline,
    candidate_set,
    match,
)
from pathable_api.geo.kitchener.correspondence import KitchenerFeature, KitchenerIndex, OsmIndex
from tests.unit.kitchener_streets import CROSSING, CYCLEWAY, ROAD, SIDEWALK, Street


def record(
    record_id: int,
    points: list[tuple[float, float]],
    *,
    family: str = "sidewalk",
    curb_cut: bool = False,
    structure: str | None = None,
) -> Record:
    geometry = LineString(points)
    return Record(
        activetransportid=record_id,
        network_role="pedestrian_crossing" if family == "crossing" else "pedestrian_way",
        family=family,
        subcategory="CROSSWALK" if family == "crossing" else "SIDEWALK",
        structure=structure,
        curb_cut=curb_cut,
        surface_material=None,
        length_m=float(geometry.length),
        street="FIXTURE ST",
        geometry=geometry,
    )


def decide(
    item: Record, index: OsmIndex, policy: MatcherPolicy | None = None, *others: Record
) -> Any:
    physical = KitchenerIndex.build(
        KitchenerFeature(
            r.activetransportid, "physical_active", r.network_role, r.subcategory, r.geometry
        )
        for r in (item, *others)
    )
    relationships = RelationshipIndex(physical, index.lines)
    return match(candidate_set(item, index), policy or MatcherPolicy(), index, relationships)


class TestLines:
    def test_a_sidewalk_beside_its_osm_twin_matches_it_with_its_local_scope(self) -> None:
        street = Street()
        street.line(1, [(0, 1), (100, 1)], SIDEWALK)
        street.line(2, [(0, 10), (100, 10)], ROAD)

        decision = decide(record(10, [(20, 0), (60, 0)]), street.index())

        assert decision.state == MATCHED
        assert decision.elements == {"way/1"}
        (target,) = decision.targets
        assert (target.from_m, target.to_m) == pytest.approx((20.0, 60.0), abs=0.01)
        assert decision.relationship == "one_to_one"

    def test_two_equal_parallel_sidewalks_abstain(self) -> None:
        street = Street()
        street.line(1, [(0, 1), (100, 1)], SIDEWALK)
        street.line(2, [(0, -1), (100, -1)], SIDEWALK)

        decision = decide(record(10, [(10, 0), (90, 0)]), street.index())

        assert decision.state == AMBIGUOUS
        assert decision.rule == "competing_way"

    def test_a_cycleway_beside_the_sidewalk_does_not_compete_with_it(self) -> None:
        # PA-GEO-04's 14357: closeness alone would not tell them apart; class does.
        street = Street()
        street.line(1, [(0, 0.7), (100, 0.7)], SIDEWALK)
        street.line(2, [(0, -1.7), (100, -1.7)], CYCLEWAY)

        decision = decide(record(10, [(10, 0), (90, 0)]), street.index())

        assert decision.state == MATCHED
        assert decision.elements == {"way/1"}
        without_class = decide(
            record(10, [(10, 0), (90, 0)]), street.index(), MatcherPolicy(use_class=False)
        )
        assert without_class.state == AMBIGUOUS

    def test_the_city_splits_what_osm_merges(self) -> None:
        street = Street()
        street.line(1, [(0, 1), (100, 1)], SIDEWALK)
        west, east = record(10, [(0, 0), (40, 0)]), record(11, [(40, 0), (100, 0)])

        decision = decide(west, street.index(), None, east)

        assert decision.elements == {"way/1"}
        assert decision.relationship == "many_to_one"
        (target,) = decision.targets
        # The record's evidence belongs to its own 40 m, not to the 100 m way.
        assert (target.from_m, target.to_m) == pytest.approx((0.0, 40.0), abs=0.01)

    def test_osm_splits_what_the_city_merges(self) -> None:
        street = Street()
        middle = street.node(50, 1)
        street.way(1, [street.node(0, 1), middle], SIDEWALK)
        street.way(2, [middle, street.node(100, 1)], SIDEWALK)

        decision = decide(record(10, [(0, 0), (100, 0)]), street.index())

        assert decision.state == MATCHED
        assert decision.elements == {"way/1", "way/2"}
        assert decision.relationship == "one_to_many"

    def test_a_few_metres_onto_the_next_way_is_end_slop_not_a_second_carrier(self) -> None:
        street = Street()
        corner = street.node(30, 1)
        street.way(1, [street.node(0, 1), corner], SIDEWALK)
        street.way(2, [corner, street.node(30, 40)], SIDEWALK)

        decision = decide(record(10, [(0, 0), (30, 0), (30, 3)]), street.index())

        assert decision.elements == {"way/1"}

    def test_nothing_near_is_unmatched_and_the_baseline_still_matches(self) -> None:
        street = Street()
        street.line(1, [(0, 20), (100, 20)], SIDEWALK)
        street.line(2, [(0, 12), (100, 12)], ROAD)
        item = record(10, [(10, 0), (90, 0)])

        assert decide(item, street.index()).state == UNMATCHED
        nearest = baseline("A_nearest_geometry", candidate_set(item, street.index()))
        assert nearest.state == MATCHED
        assert nearest.elements == {"way/2"}  # the road: nearest, and wrong

    def test_no_candidate_at_all(self) -> None:
        street = Street()
        street.line(1, [(0, 500), (100, 500)], SIDEWALK)
        item = record(10, [(10, 0), (90, 0)])

        assert decide(item, street.index()).state == UNMATCHED
        assert baseline("B_median_offset", candidate_set(item, street.index())).state == UNMATCHED

    def test_a_sidewalk_osm_records_only_as_a_road_tag_abstains(self) -> None:
        street = Street()
        street.line(1, [(0, 6), (100, 6)], {**ROAD, "sidewalk": "both"})

        decision = decide(record(10, [(10, 0), (90, 0)]), street.index())

        assert decision.state == AMBIGUOUS
        assert decision.rule == "road_attribute"

    def test_stairs_keep_the_steps_not_the_approaches_they_run_onto(self) -> None:
        street = Street()
        top, bottom = street.node(10, 0.5), street.node(20, 0.5)
        street.way(1, [street.node(0, 0.5), top], {"highway": "footway"})
        street.way(2, [top, bottom], {"highway": "steps"})
        street.way(3, [bottom, street.node(30, 0.5)], {"highway": "footway"})

        stairs = record(10, [(4, 0), (26, 0)], family="stairs", structure="STAIRS")
        decision = decide(stairs, street.index())

        assert decision.elements == {"way/2"}


class TestNodes:
    def test_a_curb_cut_is_its_kerb_node_and_two_metres_of_the_sidewalk(self) -> None:
        street = Street()
        kerb = street.node(100, 0.3, {"barrier": "kerb", "kerb": "lowered"})
        street.way(1, [street.node(0, 0.3), kerb], SIDEWALK)
        street.way(2, [kerb, street.node(100, 12)], CROSSING)

        stub = record(10, [(98, 0), (100, 0)], curb_cut=True)
        decision = decide(stub, street.index())

        assert decision.state == MATCHED
        assert decision.elements == {"node/" + str(kerb), "way/1"}
        assert decision.representation == "multiple"
        carrier = next(t for t in decision.targets if t.element == "way/1")
        # Two metres of a 100-metre sidewalk: never the whole way.
        assert carrier.to_m - carrier.from_m == pytest.approx(2.0, abs=0.01)

    def test_two_kerb_nodes_that_cannot_be_told_apart_abstain(self) -> None:
        street = Street()
        first = street.node(99, 1.0, {"kerb": "lowered"})
        second = street.node(101, 1.0, {"kerb": "lowered"})
        street.way(1, [street.node(0, 1), first, second], SIDEWALK)

        decision = decide(record(10, [(99, 0), (101, 0)], curb_cut=True), street.index())

        assert decision.state == AMBIGUOUS
        assert decision.rule == "curb_cut_two_kerb_nodes"

    def test_a_curb_cut_osm_draws_only_as_a_kerb_node(self) -> None:
        street = Street()
        kerb = street.node(50, 0.2, {"barrier": "kerb", "kerb": "flush"})
        street.way(1, [street.node(50, 0.2), street.node(50, 40)], CROSSING)

        # The piece runs across the crossing's start, aligned with nothing.
        decision = decide(record(10, [(49, 0), (51, 0)], curb_cut=True), street.index())

        assert decision.state == MATCHED
        assert decision.elements == {f"node/{kerb}"}
        assert decision.representation == "node"

    def test_a_crossing_osm_draws_only_as_a_node_on_the_road(self) -> None:
        street = Street()
        crossing = street.node(50, 0, {"highway": "crossing", "crossing": "marked"})
        street.way(1, [street.node(0, 0), crossing, street.node(100, 0)], ROAD)

        crosswalk = record(10, [(50.5, -8), (50.5, 8)], family="crossing")
        decision = decide(crosswalk, street.index())

        assert decision.state == MATCHED
        assert decision.elements == {f"node/{crossing}"}
        assert decide(crosswalk, street.index(), MatcherPolicy(use_nodes=False)).state != MATCHED


class TestPolicy:
    def test_the_frozen_policy_names_its_version_and_every_values_provenance(self) -> None:
        policy = MatcherPolicy()

        assert policy.version == MATCHER_VERSION
        thresholds = {name for name, value in policy.as_dict().items() if isinstance(value, float)}
        assert thresholds == set(POLICY_PROVENANCE)
        assert policy.as_dict()["provenance"]["carry_m"].startswith("tuned")

    def test_the_same_inputs_give_the_same_decisions(self) -> None:
        street = Street()
        street.line(1, [(0, 1), (100, 1)], SIDEWALK)
        street.line(2, [(0, -3), (100, -3)], CYCLEWAY)
        item = record(10, [(10, 0), (90, 0)])

        first = decide(item, street.index()).as_dict()
        second = decide(item, street.index()).as_dict()

        assert first == second
