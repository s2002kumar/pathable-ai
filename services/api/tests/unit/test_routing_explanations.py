"""Explanation and caution paths that the fixture does not naturally reach.

The synthetic network produces one particular comparison. These cover the
statements it never triggers — a recorded raised kerb, a steeper gradient
avoided, the routes coming out the same length, and the case where the shortest
route itself cannot be computed. Each is a sentence a user will read, so each is
worth a test that fails if the wording stops matching the evidence.
"""

from __future__ import annotations

from typing import Any

import pytest
from shapely.geometry import LineString, Point

from pathable_api.geo.enums import KerbType, SurfaceClass, TriState
from pathable_api.geo.features import normalise_edge
from pathable_api.geo.network import NetworkEdge, NetworkNode, NetworkPayload
from pathable_api.routing.comparison import compare_routes
from pathable_api.routing.graph import RoutableGraph, graph_from_payload
from pathable_api.routing.profiles import STANDARD, get_profile

# A corridor with two parallel middle links, so a profile can pick either.
#   A ---- B ==== C ---- D
# where B..C exists twice: one "direct" link and one "alternative".
WEST = (-80.5400, 43.4700)
MID_WEST = (-80.5380, 43.4700)
MID_EAST = (-80.5360, 43.4700)
EAST = (-80.5340, 43.4700)
DETOUR = (-80.5370, 43.4690)


Tags = dict[str, Any]


def build(direct_tags: Tags, detour_tags: Tags) -> RoutableGraph:
    """A network where the direct middle link competes with a longer detour."""
    coordinates = {
        "A": WEST,
        "B": MID_WEST,
        "C": MID_EAST,
        "D": EAST,
        "X": DETOUR,
    }
    nodes = [
        NetworkNode(source_node_id=name, geometry=Point(*position))
        for name, position in coordinates.items()
    ]

    clear: Tags = {
        "highway": "footway",
        "surface": "asphalt",
        "smoothness": "good",
        "incline": "0%",
    }
    links: list[tuple[str, str, Tags]] = [
        ("A", "B", clear),
        ("B", "C", direct_tags),
        ("B", "X", detour_tags),
        ("X", "C", detour_tags),
        ("C", "D", clear),
    ]

    edges = [
        NetworkEdge(
            source_u=u,
            source_v=v,
            edge_key=0,
            geometry=LineString([coordinates[u], coordinates[v]]),
            features=normalise_edge(tags),
            source_way_id=f"{u}{v}",
        )
        for u, v, tags in links
    ]
    return graph_from_payload(NetworkPayload(nodes=nodes, edges=edges))


CLEAR: Tags = {"highway": "footway", "surface": "asphalt", "smoothness": "good", "incline": "0%"}


class TestKerbExplanations:
    def test_a_recorded_raised_kerb_is_named_as_recorded(self) -> None:
        graph = build(
            direct_tags={
                "highway": "footway",
                "crossing": "marked",
                "kerb": "raised",
                "surface": "asphalt",
                "smoothness": "good",
                "incline": "0%",
            },
            detour_tags=CLEAR,
        )

        comparison = compare_routes(
            graph, origin=WEST, destination=EAST, profile=get_profile("wheelchair")
        )
        codes = {item.code for item in comparison.explanations}

        assert "avoids_raised_kerbs" in codes
        raised = next(e for e in comparison.explanations if e.code == "avoids_raised_kerbs")
        assert "recorded raised kerb" in raised.summary


class TestGradientExplanations:
    def test_a_steeper_avoided_gradient_is_stated_against_the_one_taken(self) -> None:
        graph = build(
            direct_tags={
                "highway": "footway",
                "incline": "7%",
                "surface": "asphalt",
                "smoothness": "good",
            },
            detour_tags={
                "highway": "footway",
                "incline": "1%",
                "surface": "asphalt",
                "smoothness": "good",
            },
        )

        comparison = compare_routes(
            graph, origin=WEST, destination=EAST, profile=get_profile("wheelchair")
        )
        gradient = next(
            (e for e in comparison.explanations if e.code == "avoids_steep_gradient"), None
        )

        assert gradient is not None
        assert gradient.evidence["avoided_max_incline_percent"] == pytest.approx(7.0)
        assert gradient.evidence["route_max_incline_percent"] == pytest.approx(1.0)

    def test_no_gradient_claim_when_the_route_taken_is_steeper(self) -> None:
        # Claiming to have avoided a gradient while climbing a worse one would be
        # a false statement, not merely an unhelpful one.
        graph = build(
            direct_tags={
                "highway": "footway",
                "incline": "3%",
                "surface": "gravel",
            },
            detour_tags={
                "highway": "footway",
                "incline": "6%",
                "surface": "asphalt",
                "smoothness": "good",
            },
        )

        comparison = compare_routes(
            graph, origin=WEST, destination=EAST, profile=get_profile("wheelchair")
        )

        assert not any(e.code == "avoids_steep_gradient" for e in comparison.explanations)


class TestSurfaceExplanations:
    def test_it_names_the_recorded_surface_it_avoided(self) -> None:
        graph = build(
            direct_tags={"highway": "path", "surface": "gravel"},
            detour_tags=CLEAR,
        )

        comparison = compare_routes(
            graph, origin=WEST, destination=EAST, profile=get_profile("wheelchair")
        )
        surface = next(e for e in comparison.explanations if e.code == "avoids_rough_surface")

        assert "gravel" in surface.summary
        assert surface.evidence["length_m"] > 0


class TestEquivalentRoutes:
    def test_it_says_so_when_the_routes_are_the_same(self) -> None:
        # "3 m longer" is noise dressed up as information.
        graph = build(direct_tags=CLEAR, detour_tags=CLEAR)

        comparison = compare_routes(
            graph, origin=WEST, destination=EAST, profile=get_profile("wheelchair")
        )

        assert comparison.routes_are_equivalent
        assert any(e.code == "same_distance" for e in comparison.explanations)


class TestNoStandardRoute:
    def test_a_point_off_the_network_fails_with_that_reason(self) -> None:
        graph = build(direct_tags=CLEAR, detour_tags=CLEAR)

        # Inside the span limit, but nowhere near a mapped path.
        comparison = compare_routes(
            graph,
            origin=(-80.60, 43.44),
            destination=EAST,
            profile=get_profile("wheelchair"),
        )

        assert comparison.standard_route is None
        assert comparison.standard_failure is not None
        assert "mapped path" in comparison.standard_failure
        assert comparison.explanations == ()

    def test_a_journey_too_long_to_walk_fails_with_that_reason(self) -> None:
        # A different refusal from the one above, and the message has to say
        # which — they lead a user to do different things.
        graph = build(direct_tags=CLEAR, detour_tags=CLEAR)

        comparison = compare_routes(
            graph, origin=(-80.70, 43.30), destination=EAST, profile=get_profile("wheelchair")
        )

        assert comparison.standard_failure is not None
        assert "km apart" in comparison.standard_failure

    def test_extra_distance_is_absent_rather_than_zero_when_a_route_is_missing(self) -> None:
        graph = build(direct_tags=CLEAR, detour_tags=CLEAR)

        comparison = compare_routes(
            graph, origin=(-80.60, 43.44), destination=EAST, profile=STANDARD
        )

        # Zero would read as "the same length", which is a claim about two routes
        # that do not both exist.
        assert comparison.extra_distance_m is None
        assert comparison.extra_distance_fraction is None
        assert comparison.routes_are_equivalent is False


class TestSnapCaution:
    def test_a_route_starting_far_from_the_request_says_so(self) -> None:
        graph = build(direct_tags=CLEAR, detour_tags=CLEAR)

        # ~120 m north of A: within the refusal threshold, past the caution one.
        comparison = compare_routes(
            graph,
            origin=(WEST[0], WEST[1] + 0.0011),
            destination=EAST,
            profile=get_profile("wheelchair"),
        )
        codes = {caution.code for caution in comparison.cautions}

        assert "snapped_far_from_request" in codes


class TestFeatureRoundTrip:
    def test_a_segment_carries_the_attributes_its_explanation_relies_on(self) -> None:
        graph = build(
            direct_tags={"highway": "steps", "step_count": "9"},
            detour_tags=CLEAR,
        )

        comparison = compare_routes(
            graph, origin=WEST, destination=EAST, profile=get_profile("wheelchair")
        )
        assert comparison.standard_route is not None

        stairs = next(
            segment
            for segment in comparison.standard_route.segments
            if segment.steps is TriState.YES
        )
        assert stairs.step_count == 9
        assert stairs.kerb is KerbType.UNKNOWN
        assert stairs.surface_class is SurfaceClass.UNKNOWN
