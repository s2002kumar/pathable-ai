"""Pedestrian source semantics.

Every rule here decides whether a real person is told a path exists. The two
failure modes are not symmetric: inventing a restriction sends somebody on a
detour or tells them there is no route at all, and inventing a permission sends
them into a barrier. These tests pin both directions.
"""

from __future__ import annotations

from typing import Any

import pytest
from shapely.geometry import LineString, Point

from pathable_api.geo.directionality import (
    TWO_WAY,
    Conveying,
    FootDirection,
    normalise_conveying,
    normalise_foot_direction,
    vehicle_oneway_is_ignored,
)
from pathable_api.geo.enums import KerbType, SmoothnessClass, SurfaceClass, TriState
from pathable_api.geo.features import all_values, is_conflicted, normalise_edge, worst_of
from pathable_api.geo.network import NetworkEdge, NetworkNode, NetworkPayload
from pathable_api.geo.node_evidence import (
    NodeEvidence,
    apply_to_crossing,
    read_node_evidence,
)
from pathable_api.routing.graph import graph_from_payload

Tags = dict[str, Any]


class TestVehicleOnewayIsNotAPedestrianRestriction:
    def test_plain_oneway_leaves_a_footway_two_way(self) -> None:
        # The single most consequential rule in this module. A person walking
        # along a one-way street walks in either direction.
        direction = normalise_foot_direction({"highway": "residential", "oneway": "yes"})

        assert direction.forward is True
        assert direction.backward is True

    def test_the_ignored_restriction_is_still_reported(self) -> None:
        # Ignoring it silently would make a surprising route unexplainable.
        assert vehicle_oneway_is_ignored({"oneway": "yes"}) is TriState.YES
        assert vehicle_oneway_is_ignored({"oneway": "no"}) is TriState.NO
        assert vehicle_oneway_is_ignored({}) is TriState.UNKNOWN

    def test_oneway_minus_one_is_also_ignored(self) -> None:
        direction = normalise_foot_direction({"highway": "service", "oneway": "-1"})
        assert (direction.forward, direction.backward) == (True, True)

    def test_the_feature_record_carries_the_fact(self) -> None:
        features = normalise_edge({"highway": "residential", "oneway": "yes"})
        assert features.vehicle_oneway_ignored is True


class TestFootSpecificDirection:
    def test_oneway_foot_yes_is_forward_only(self) -> None:
        direction = normalise_foot_direction({"highway": "footway", "oneway:foot": "yes"})
        assert (direction.forward, direction.backward) == (True, False)

    def test_oneway_foot_minus_one_is_backward_only(self) -> None:
        direction = normalise_foot_direction({"highway": "footway", "oneway:foot": "-1"})
        assert (direction.forward, direction.backward) == (False, True)

    def test_oneway_foot_no_is_explicitly_two_way(self) -> None:
        direction = normalise_foot_direction({"highway": "footway", "oneway:foot": "no"})
        assert (direction.forward, direction.backward) == (True, True)

    def test_foot_backward_no_blocks_only_that_direction(self) -> None:
        direction = normalise_foot_direction({"highway": "path", "foot:backward": "no"})
        assert (direction.forward, direction.backward) == (True, False)

    def test_the_per_direction_tag_beats_the_general_one(self) -> None:
        # `oneway:foot=yes` says forward-only; `foot:backward=yes` is a more
        # specific statement about the same direction and wins.
        direction = normalise_foot_direction(
            {"highway": "footway", "oneway:foot": "yes", "foot:backward": "yes"}
        )
        assert (direction.forward, direction.backward) == (True, True)

    def test_a_restriction_records_which_tag_caused_it(self) -> None:
        direction = normalise_foot_direction({"oneway:foot": "yes"})
        assert "oneway:foot" in direction.reason


class TestConveying:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("forward", Conveying.FORWARD),
            ("backward", Conveying.BACKWARD),
            ("-1", Conveying.BACKWARD),
            ("reversible", Conveying.REVERSIBLE),
            ("yes", Conveying.UNKNOWN_DIRECTION),
            ("no", Conveying.NONE),
        ],
    )
    def test_values(self, value: str, expected: Conveying) -> None:
        assert normalise_conveying({"conveying": value}) is expected

    def test_a_forward_escalator_cannot_be_walked_backwards(self) -> None:
        direction = normalise_foot_direction({"highway": "steps", "conveying": "forward"})
        assert (direction.forward, direction.backward) == (True, False)

    def test_an_undirected_escalator_stays_passable_and_is_flagged(self) -> None:
        # `conveying=yes` says something moves but not which way. Blocking both
        # directions would delete a real connection.
        direction = normalise_foot_direction({"highway": "steps", "conveying": "yes"})

        assert direction.forward and direction.backward
        assert direction.ambiguous is True

    def test_reversing_a_conveyor_swaps_its_direction(self) -> None:
        assert Conveying.FORWARD.reversed() is Conveying.BACKWARD
        assert Conveying.REVERSIBLE.reversed() is Conveying.REVERSIBLE


class TestAmbiguityStaysPermissive:
    def test_an_unreadable_value_does_not_create_a_barrier(self) -> None:
        direction = normalise_foot_direction({"oneway:foot": "probably"})

        assert direction.forward and direction.backward
        assert direction.ambiguous is True

    def test_denying_both_directions_is_treated_as_a_tagging_mistake(self) -> None:
        # A segment nobody may walk either way is a mapping error, not a wall.
        # Deleting the connection is how a phantom "no route" appears.
        direction = normalise_foot_direction({"foot:forward": "no", "foot:backward": "no"})

        assert direction.is_passable
        assert direction.ambiguous is True

    def test_a_plain_two_way_segment_is_not_flagged(self) -> None:
        direction = normalise_foot_direction({"highway": "footway"})

        assert direction == TWO_WAY
        assert direction.ambiguous is False


class TestDirectionReversal:
    def test_reversing_swaps_the_permitted_directions(self) -> None:
        forward_only = FootDirection(forward=True, backward=False)
        assert forward_only.reversed() == FootDirection(forward=False, backward=True)

    def test_incline_sign_flips_when_travelled_the_other_way(self) -> None:
        # A 6% climb is a 6% descent from the other end. Treating the stored
        # sign as absolute sends a wheelchair user up a ramp the router believes
        # goes down.
        uphill = normalise_edge({"highway": "footway", "incline": "6%"})

        assert uphill.incline_percent == pytest.approx(6.0)
        assert uphill.reversed().incline_percent == pytest.approx(-6.0)

    def test_reversing_twice_returns_the_original(self) -> None:
        features = normalise_edge({"highway": "footway", "incline": "-4.5%"})
        assert features.reversed().reversed().incline_percent == pytest.approx(-4.5)

    def test_an_unrecorded_incline_stays_unrecorded_when_reversed(self) -> None:
        # Reversal must not turn "nobody measured this" into a number.
        features = normalise_edge({"highway": "footway"})
        assert features.reversed().incline_percent is None

    def test_qualitative_incline_has_no_number_to_flip(self) -> None:
        features = normalise_edge({"highway": "footway", "incline": "up"})

        assert features.incline_percent is None
        assert features.reversed().incline_percent is None

    def test_derived_grade_also_flips(self) -> None:
        from dataclasses import replace

        features = replace(normalise_edge({"highway": "footway"}), derived_grade_percent=3.2)
        assert features.reversed().derived_grade_percent == pytest.approx(-3.2)


class TestConflictingAttributes:
    def test_all_values_collects_a_merged_list(self) -> None:
        assert all_values(["asphalt", "gravel", "asphalt"]) == ("asphalt", "gravel")

    def test_a_single_value_is_not_a_conflict(self) -> None:
        assert is_conflicted("asphalt") is False
        assert is_conflicted(["asphalt"]) is False

    def test_a_merged_segment_with_two_surfaces_is_a_conflict(self) -> None:
        assert is_conflicted(["asphalt", "gravel"]) is True

    def test_conflict_resolves_to_the_worse_value(self) -> None:
        # "First value wins" would make the answer depend on which way the merge
        # ran. The rough part of the segment is really there either way.
        value, conflicted = worst_of(["asphalt", "gravel"], ("asphalt", "gravel"))

        assert value == "gravel"
        assert conflicted is True

    def test_an_unrecognised_value_is_treated_as_worse_than_anything_known(self) -> None:
        value, _ = worst_of(["asphalt", "moon_dust"], ("asphalt", "gravel"))
        assert value == "moon_dust"

    def test_a_conflicting_surface_classifies_conservatively(self) -> None:
        features = normalise_edge({"highway": "path", "surface": ["asphalt", "gravel"]})

        assert features.surface_class is SurfaceClass.ROUGH
        assert "surface" in features.conflicting_attributes

    def test_a_conflicting_smoothness_classifies_conservatively(self) -> None:
        features = normalise_edge({"highway": "footway", "smoothness": ["excellent", "very_bad"]})

        assert features.smoothness_class is SmoothnessClass.BAD
        assert "smoothness" in features.conflicting_attributes

    def test_a_conflicting_kerb_takes_the_worse(self) -> None:
        features = normalise_edge(
            {"highway": "footway", "crossing": "marked", "kerb": ["lowered", "raised"]}
        )

        assert features.kerb is KerbType.RAISED
        assert "kerb" in features.conflicting_attributes

    def test_an_unconflicted_segment_reports_nothing(self) -> None:
        features = normalise_edge({"highway": "footway", "surface": "asphalt"})
        assert features.conflicting_attributes == ()


class TestNodeLevelKerbEvidence:
    def test_a_kerb_node_is_read(self) -> None:
        evidence = read_node_evidence({"barrier": "kerb", "kerb": "lowered"})

        assert evidence.kerb is KerbType.LOWERED
        assert evidence.is_informative

    def test_barrier_kerb_without_a_kind_is_unknown_not_raised(self) -> None:
        # Something is there and nobody said whether it is dropped. Calling it
        # raised invents a barrier; calling it flush invents a ramp.
        evidence = read_node_evidence({"barrier": "kerb"})

        assert evidence.kerb is KerbType.UNKNOWN
        assert evidence.is_informative  # the barrier itself is still worth knowing

    def test_an_ordinary_node_carries_nothing(self) -> None:
        assert read_node_evidence({"x": 1, "y": 2}).is_informative is False

    def test_node_evidence_reaches_the_crossing_it_belongs_to(self) -> None:
        crossing = normalise_edge({"highway": "footway", "footway": "crossing"})
        assert crossing.kerb is KerbType.UNKNOWN

        resolved = apply_to_crossing(
            crossing, NodeEvidence(kerb=KerbType.RAISED), NodeEvidence(kerb=KerbType.LOWERED)
        )

        # The worse endpoint wins: a crossing dropped at one end and raised at
        # the other is not a dropped-kerb crossing.
        assert resolved.kerb is KerbType.RAISED
        assert resolved.kerb_from_node is True

    def test_node_evidence_does_not_leak_onto_a_plain_sidewalk(self) -> None:
        # The scoping rule. A kerb node touches several ways; charging all of
        # them would penalise paths that never cross the road.
        sidewalk = normalise_edge({"highway": "footway", "surface": "asphalt"})

        resolved = apply_to_crossing(sidewalk, NodeEvidence(kerb=KerbType.RAISED), None)

        assert resolved.kerb is KerbType.UNKNOWN
        assert resolved is sidewalk

    def test_a_kerb_tagged_on_the_way_beats_the_node(self) -> None:
        # Somebody tagged the crossing itself; that is the more specific claim.
        crossing = normalise_edge({"highway": "footway", "footway": "crossing", "kerb": "flush"})

        resolved = apply_to_crossing(crossing, NodeEvidence(kerb=KerbType.RAISED), None)

        assert resolved.kerb is KerbType.FLUSH
        assert resolved.kerb_from_node is False

    def test_tactile_paving_at_only_one_end_is_not_promised(self) -> None:
        crossing = normalise_edge({"highway": "footway", "footway": "crossing"})

        resolved = apply_to_crossing(
            crossing,
            NodeEvidence(tactile_paving=TriState.YES),
            NodeEvidence(tactile_paving=TriState.NO),
        )

        assert resolved.tactile_paving is TriState.NO


class TestDirectionReachesTheRouter:
    def _graph(self, tags: Tags):
        nodes = [
            NetworkNode(source_node_id="A", geometry=Point(-80.54, 43.47)),
            NetworkNode(source_node_id="B", geometry=Point(-80.538, 43.47)),
        ]
        edges = [
            NetworkEdge(
                source_u="A",
                source_v="B",
                edge_key=0,
                geometry=LineString([(-80.54, 43.47), (-80.538, 43.47)]),
                features=normalise_edge(tags),
                direction=normalise_foot_direction(tags),
            )
        ]
        return graph_from_payload(NetworkPayload(nodes=nodes, edges=edges))

    def test_a_two_way_segment_is_traversable_both_ways(self) -> None:
        graph = self._graph({"highway": "footway"})

        assert graph.graph.has_edge("A", "B")
        assert graph.graph.has_edge("B", "A")

    def test_a_foot_oneway_segment_exists_in_one_direction_only(self) -> None:
        graph = self._graph({"highway": "footway", "oneway:foot": "yes"})

        assert graph.graph.has_edge("A", "B")
        assert not graph.graph.has_edge("B", "A")

    def test_a_vehicle_oneway_segment_still_exists_both_ways(self) -> None:
        graph = self._graph({"highway": "residential", "oneway": "yes"})

        assert graph.graph.has_edge("A", "B")
        assert graph.graph.has_edge("B", "A")

    def test_the_reverse_entry_carries_a_flipped_incline(self) -> None:
        graph = self._graph({"highway": "footway", "incline": "8%"})

        forward = graph.edge_between("A", "B", 0)
        backward = graph.edge_between("B", "A", 0)

        assert forward.features.incline_percent == pytest.approx(8.0)
        assert backward.features.incline_percent == pytest.approx(-8.0)
        assert backward.reversed is True

    def test_the_reverse_entry_reverses_its_geometry(self) -> None:
        graph = self._graph({"highway": "footway"})

        forward = graph.edge_between("A", "B", 0).coordinates()
        backward = graph.edge_between("B", "A", 0).coordinates()

        assert forward[0] == backward[-1]
        assert forward[-1] == backward[0]

    def test_both_directions_share_one_physical_segment(self) -> None:
        graph = self._graph({"highway": "footway"})

        assert graph.segment_count == 1
        assert graph.edge_between("A", "B", 0).identity == graph.edge_between("B", "A", 0).identity
