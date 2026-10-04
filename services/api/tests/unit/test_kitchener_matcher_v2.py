"""Matcher v2 on invented streets: the cases v1 got wrong, and abstention where it cannot tell.

Coordinates are metres; an identity transform stands in for the projection, so
every distance below is the distance drawn. Each test names the change from v1
it protects, and switching that change off (the policy's ablation switches)
changes the answer.
"""

from __future__ import annotations

from typing import Any

import pytest
from shapely.geometry import LineString

from pathable_api.geo.kitchener.conflation import (
    AMBIGUOUS,
    MATCHED,
    UNMATCHED,
    Record,
    RelationshipIndex,
)
from pathable_api.geo.kitchener.correspondence import KitchenerFeature, KitchenerIndex
from pathable_api.geo.kitchener.matcher_v2 import MatcherV2Policy, candidates_v2, match_v2
from tests.unit.kitchener_streets import CROSSING, CYCLEWAY, ROAD, SIDEWALK, Street

FOOTWAY = {"highway": "footway"}
STEPS = {"highway": "steps"}
KERB = {"barrier": "kerb", "kerb": "lowered"}


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
    item: Record, street: Street, policy: MatcherV2Policy | None = None, *others: Record
) -> Any:
    index = street.index()
    physical = KitchenerIndex.build(
        KitchenerFeature(
            r.activetransportid, "physical_active", r.network_role, r.subcategory, r.geometry
        )
        for r in (item, *others)
    )
    chosen = policy or MatcherV2Policy()
    return match_v2(
        candidates_v2(item, index, chosen), chosen, index, RelationshipIndex(physical, index.lines)
    )


def stair() -> Record:
    return record(10, [(0, 0.5), (10, 0.5)], family="stairs", structure="STAIRS")


class TestStairs:
    def test_a_stair_osm_draws_as_a_plain_footway_corresponds_to_it(self) -> None:
        street = Street()
        street.line(1, [(-20, 0), (30, 0)], FOOTWAY)

        decision = decide(stair(), street)

        assert decision.state == MATCHED
        assert decision.rule == "stair_on_generic_way"
        assert decision.elements == {"way/1"}
        # The stair is the City's assertion alone: OSM's way records no steps.
        assert decision.representation == "generic_way"

    def test_steps_drawn_nearby_leave_the_stair_ambiguous(self) -> None:
        street = Street()
        street.line(1, [(-20, 0), (30, 0)], FOOTWAY)
        street.line(2, [(0, 8), (10, 8)], STEPS)

        assert decide(stair(), street).rule == "stair_displaced_steps"
        assert decide(stair(), street).state == AMBIGUOUS
        assert decide(stair(), street, MatcherV2Policy(use_stair_rule=False)).state == MATCHED

    def test_a_stair_osm_splits_into_short_steps_pieces_keeps_every_piece(self) -> None:
        street = Street()
        a, b, c, d = (street.node(x, 0) for x in (0, 4, 8, 12))
        street.way(1, [a, b], STEPS)
        street.way(2, [b, c], STEPS)
        street.way(3, [c, d], STEPS)
        flight = record(10, [(0, 0.5), (12, 0.5)], family="stairs", structure="STAIRS")

        assert decide(flight, street).elements == {"way/1", "way/2", "way/3"}
        # v1's end slop drops the 4 m pieces at either end.
        without = decide(flight, street, MatcherV2Policy(use_structure_pieces=False))
        assert without.elements != {"way/1", "way/2", "way/3"}


class TestCurbCuts:
    def test_a_curb_cut_onto_a_crossing_names_its_kerb_and_both_ways_locally(self) -> None:
        street = Street()
        kerb = street.node(100, 0, KERB)
        street.way(1, [street.node(0, 0), kerb], SIDEWALK)
        street.way(2, [kerb, street.node(114, 0)], CROSSING)

        piece = record(10, [(98.5, 0.3), (101.5, 0.3)], curb_cut=True)
        decision = decide(piece, street)

        assert decision.state == MATCHED
        assert decision.elements == {f"node/{kerb}", "way/1", "way/2"}
        for target in decision.targets:
            if target.element.startswith("way/"):
                # A metre and a half of each way: never the 100 m sidewalk.
                assert target.to_m - target.from_m == pytest.approx(1.5, abs=0.3)
        # v1's class rule: a crossing never carries a sidewalk's curb cut.
        v1_rule = decide(piece, street, MatcherV2Policy(use_crossing_carriers=False))
        assert "way/2" not in v1_rule.elements

    def test_a_curb_cut_across_an_untagged_junction_with_no_kerb_abstains(self) -> None:
        street = Street()
        corner = street.node(50, 0)
        street.way(1, [street.node(0, 0), corner], SIDEWALK)
        street.way(2, [corner, street.node(50, 50)], SIDEWALK)
        street.way(3, [corner, street.node(50, -14)], CROSSING)

        # Diagonal across the corner: follows none of the three ways.
        piece = record(10, [(49.3, -0.7), (50.7, 0.7)], curb_cut=True)
        decision = decide(piece, street)

        assert decision.state == AMBIGUOUS
        assert decision.rule == "curb_cut_at_junction"
        # v1's 45-degree limit lets a way it crosses carry it.
        assert decide(piece, street, MatcherV2Policy(use_follow=False)).state == MATCHED

    def test_of_two_kerb_nodes_the_one_where_its_crossing_begins_is_named(self) -> None:
        street = Street()
        first = street.node(100, 0, KERB)
        second = street.node(101.2, 1.0, KERB)
        street.way(1, [street.node(0, 0), first], SIDEWALK)
        street.way(2, [first, street.node(114, 0)], CROSSING)
        street.way(3, [second, street.node(101.2, 15)], CROSSING)

        onto_first = record(10, [(98.5, 0.2), (101.5, 0.2)], curb_cut=True)
        assert decide(onto_first, street).elements == {f"node/{first}", "way/1", "way/2"}

        # A piece that follows no way between the two kerbs cannot be settled.
        between = record(11, [(100.1, 0.4), (100.9, 0.9)], curb_cut=True)
        assert decide(between, street).rule == "curb_cut_kerb_nodes_undecided"

    def test_a_sub_metre_piece_that_follows_no_way_is_its_kerb_node_alone(self) -> None:
        street = Street()
        kerb = street.node(50, 0.2, KERB)
        street.way(1, [street.node(0, 0), street.node(100, 0)], SIDEWALK)
        street.way(2, [kerb, street.node(50, 14)], CROSSING)

        # 0.8 m at about 30 degrees to the sidewalk and 60 to the crossing.
        piece = record(10, [(49.65, 0.0), (50.35, 0.4)], curb_cut=True)
        decision = decide(piece, street)

        assert decision.state == MATCHED
        assert decision.elements == {f"node/{kerb}"}
        assert decision.representation == "node"


class TestPiecesAndJunctions:
    def test_a_corner_piece_between_two_converging_ways_abstains(self) -> None:
        street = Street()
        corner = street.node(10, 0)
        street.way(1, [street.node(-40, 0), corner], SIDEWALK)
        # The second sidewalk leaves the corner at 20 degrees, within 2 m of the piece.
        street.way(2, [corner, street.node(-37, -17.1)], SIDEWALK)

        piece = record(10, [(5.5, -0.6), (9.5, -0.6)])
        decision = decide(piece, street)

        assert decision.state == AMBIGUOUS
        assert decision.rule == "piece_between_ways"
        assert decide(piece, street, MatcherV2Policy(use_piece_rules=False)).state == MATCHED

    def test_a_short_piece_clearly_along_one_way_is_matched(self) -> None:
        street = Street()
        street.line(1, [(0, 0), (40, 0)], SIDEWALK)
        street.line(2, [(20, 0), (20, 30)], SIDEWALK)

        decision = decide(record(10, [(5, 0.4), (8, 0.4)]), street)

        assert decision.state == MATCHED
        assert decision.elements == {"way/1"}

    def test_a_path_touching_a_spur_at_a_right_angle_is_not_a_counterpart(self) -> None:
        street = Street()
        street.line(1, [(-30, 0), (30, 0)], FOOTWAY)

        spur = record(10, [(0, 0.2), (0, 6)], family="trail")
        assert decide(spur, street).state == UNMATCHED

    def test_a_crossing_osm_draws_only_as_a_node_on_the_road(self) -> None:
        street = Street()
        crossing = street.node(50, 0, {"highway": "crossing", "crossing": "marked"})
        street.way(1, [street.node(0, 0), crossing, street.node(100, 0)], ROAD)

        decision = decide(record(10, [(50.5, -8), (50.5, 8)], family="crossing"), street)

        assert decision.state == MATCHED
        assert decision.elements == {f"node/{crossing}"}
        assert decision.representation == "node"


class TestCompetition:
    def test_a_sidewalk_between_two_parallel_sidewalks_abstains(self) -> None:
        street = Street()
        street.line(1, [(0, 0), (100, 0)], SIDEWALK)
        street.line(2, [(0, 2.2), (100, 2.2)], SIDEWALK)

        decision = decide(record(10, [(10, 1.0), (90, 1.0)]), street)

        assert decision.state == AMBIGUOUS
        assert decision.rule == "competing_way"

    def test_a_cycleway_beside_a_sidewalk_does_not_contest_it(self) -> None:
        street = Street()
        street.line(1, [(0, 0), (100, 0)], SIDEWALK)
        street.line(2, [(0, 2.2), (100, 2.2)], CYCLEWAY)

        decision = decide(record(10, [(10, 0.7), (90, 0.7)]), street)

        assert decision.state == MATCHED
        assert decision.elements == {"way/1"}

    def test_only_a_road_with_no_sidewalk_tag_is_no_counterpart(self) -> None:
        street = Street()
        street.line(1, [(0, 0), (100, 0)], ROAD)

        decision = decide(record(10, [(10, 6.0), (90, 6.0)]), street)

        assert decision.state == UNMATCHED
        assert decision.rule == "no_counterpart"

    def test_a_record_over_two_ways_that_carry_other_records_is_many_to_many(self) -> None:
        street = Street()
        middle = street.node(50, 0)
        street.way(1, [street.node(0, 0), middle], SIDEWALK)
        street.way(2, [middle, street.node(100, 0)], SIDEWALK)
        item = record(10, [(20, 0.5), (80, 0.5)])
        west = record(11, [(0, 0.5), (19, 0.5)])

        decision = decide(item, street, None, west)

        assert decision.elements == {"way/1", "way/2"}
        assert decision.relationship == "many_to_many"
        assert decide(item, street).relationship == "one_to_many"
