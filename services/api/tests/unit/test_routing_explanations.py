"""Explanation and caution paths that the fixture does not naturally reach.

The synthetic network produces one particular comparison. These cover the
statements it never triggers — a recorded raised kerb, a steeper gradient
avoided, the routes coming out the same length, and the case where the shortest
route itself cannot be computed. Each is a sentence a user will read, so each is
worth a test that fails if the wording stops matching the evidence.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from shapely.geometry import LineString, Point

from pathable_api.geo.enums import KerbType, SurfaceClass, TriState
from pathable_api.geo.features import normalise_edge
from pathable_api.geo.network import NetworkEdge, NetworkNode, NetworkPayload
from pathable_api.routing.comparison import compare_routes
from pathable_api.routing.graph import RoutableGraph, graph_from_payload
from pathable_api.routing.profiles import (
    STANDARD,
    MobilityProfile,
    build_custom_profile,
    get_profile,
)

# A corridor with two parallel middle links, so a profile can pick either.
#   A ---- B ==== C ---- D
# where B..C exists twice: one "direct" link and one "alternative".
WEST = (-80.5400, 43.4700)
MID_WEST = (-80.5380, 43.4700)
MID_EAST = (-80.5360, 43.4700)
EAST = (-80.5340, 43.4700)
DETOUR = (-80.5370, 43.4690)


Tags = dict[str, Any]


def build(
    direct_tags: Tags,
    detour_tags: Tags,
    *,
    direct_grade: float | None = None,
    detour_grade: float | None = None,
) -> RoutableGraph:
    """A network where the direct middle link competes with a longer detour.

    ``direct_grade`` and ``detour_grade`` stand in for what the elevation model
    would derive for those links, signed west to east. They sit beside any
    `incline` tag rather than replacing it, exactly as a sampling pass stores them.
    """
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
    links: list[tuple[str, str, Tags, float | None]] = [
        ("A", "B", clear, None),
        ("B", "C", direct_tags, direct_grade),
        ("B", "X", detour_tags, detour_grade),
        ("X", "C", detour_tags, detour_grade),
        ("C", "D", clear, None),
    ]

    edges = [
        NetworkEdge(
            source_u=u,
            source_v=v,
            edge_key=0,
            geometry=LineString([coordinates[u], coordinates[v]]),
            features=replace(normalise_edge(tags), derived_grade_percent=grade),
            source_way_id=f"{u}{v}",
        )
        for u, v, tags, grade in links
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
        assert raised.basis == "recorded"


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
        # Direction-aware: both links climb west to east, the way this route runs.
        assert gradient.evidence["shortest_route_steepest_uphill_percent"] == pytest.approx(7.0)
        assert gradient.evidence["route_steepest_uphill_percent"] == pytest.approx(1.0)
        assert gradient.basis == "recorded"
        assert "7.0% (recorded)" in gradient.summary

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


class TestBlockingDiagnostics:
    def test_a_width_that_blocked_the_profile_is_named(self) -> None:
        # The diagnostic rebuilds features from route segments. Width used not to
        # travel with them, so a route blocked by narrow paths reported every
        # reason except the real one.
        graph = build(
            direct_tags={
                "highway": "footway",
                "width": "0.5",
                "surface": "asphalt",
                "smoothness": "good",
                "incline": "0%",
            },
            detour_tags={
                "highway": "footway",
                "width": "0.5",
                "surface": "asphalt",
                "smoothness": "good",
                "incline": "0%",
            },
        )

        # A *declared* minimum width, not a preset threshold: only what the
        # traveller states about themselves may make a journey impossible.
        profile = build_custom_profile(base="wheelchair", min_width_m=0.9)
        comparison = compare_routes(graph, origin=WEST, destination=EAST, profile=profile)

        assert comparison.accessible_route is None
        caution = next(c for c in comparison.cautions if c.code == "no_accessible_route")
        assert "too_narrow" in caution.evidence["reasons"]
        assert caution.evidence["blocked_segments_on_shortest_route"] >= 1

    def test_the_caution_gives_a_concrete_example(self) -> None:
        graph = build(
            direct_tags={"highway": "steps", "step_count": "20"},
            detour_tags={"highway": "steps", "step_count": "20"},
        )

        comparison = compare_routes(
            graph, origin=WEST, destination=EAST, profile=get_profile("wheelchair")
        )

        assert comparison.accessible_route is None
        caution = next(c for c in comparison.cautions if c.code == "no_accessible_route")
        assert any("stairway" in example for example in caution.evidence["examples"])

    def test_a_slope_limit_on_estimated_gradients_is_named(self) -> None:
        # Regression (D8): the diagnostic rebuilt each segment from a handful of
        # copied fields and dropped the derived grade, so a limit that blocked
        # only estimated gradients — nearly all of Waterloo's — reported no
        # reason at all for "no route".
        # CLEAR records `incline=0%`; drop it so the estimate is what routing uses.
        graph = build(
            direct_tags={**CLEAR, "incline": None},
            detour_tags={**CLEAR, "incline": None},
            direct_grade=9.0,
            detour_grade=9.0,
        )
        profile = build_custom_profile(base="wheelchair", max_incline_percent=5.0)

        comparison = compare_routes(graph, origin=WEST, destination=EAST, profile=profile)

        assert comparison.accessible_route is None
        caution = next(c for c in comparison.cautions if c.code == "no_accessible_route")
        assert caution.evidence["reasons"] == {"too_steep": 1}
        assert any("estimated gradient" in example for example in caution.evidence["examples"])


class TestEveryConstraintIsNamed:
    """Why the routes differ, read from the profile's own costs.

    Regression (D7): the interface said the detour was "to avoid N stairways",
    and the engine had no statement at all for several of the constraints the
    profile weighs. A detour is the sum of every constraint that differs.
    """

    def test_a_detour_without_stairs_is_not_attributed_to_stairs(self) -> None:
        graph = build(
            direct_tags={
                "highway": "footway",
                "footway": "crossing",
                "crossing": "unmarked",
                "surface": "gravel",
            },
            detour_tags=CLEAR,
        )

        comparison = compare_routes(
            graph, origin=WEST, destination=EAST, profile=get_profile("wheelchair")
        )
        codes = [e.code for e in comparison.explanations]

        assert "avoids_stairs" not in codes
        assert {"avoids_unrecorded_kerbs", "avoids_rough_surface"} <= set(codes)
        assert "fewer_unmarked_crossings" in codes

    def test_stairs_and_every_other_difference_are_named_together(self) -> None:
        graph = build(
            direct_tags={"highway": "steps", "step_count": "9", "surface": "gravel"},
            detour_tags={**CLEAR, "footway": "crossing", "crossing": "marked", "kerb": "raised"},
        )

        comparison = compare_routes(
            graph, origin=WEST, destination=EAST, profile=get_profile("crutches")
        )
        codes = [e.code for e in comparison.explanations]

        # Crutches allow stairs at a cost, so the stairs are one reason among
        # others — here, the recorded gravel — and each is stated. The detour's
        # own raised kerbs are a cost it took on, so no kerb statement appears.
        assert {"avoids_stairs", "avoids_rough_surface"} <= set(codes)
        assert not any("kerb" in code for code in codes)
        for explanation in comparison.explanations:
            difference = explanation.evidence.get("cost_difference_effective_m")
            if difference is not None:
                assert difference > 0, explanation.code
        assert codes[-1] in {"distance_difference", "same_distance"}

    def test_a_constraint_the_profile_does_not_charge_is_never_claimed(self) -> None:
        # This profile weighs one thing — an unrecorded kerb — so the detour it
        # takes must be explained by that alone, even though the direct link is
        # also recorded as compacted.
        kerbs_only = MobilityProfile(
            key="kerbs_only",
            display_name="Kerbs only",
            description="Charges for an unrecorded kerb and nothing else.",
            kerb_penalty_m={KerbType.UNKNOWN: 500.0},
        )
        graph = build(
            direct_tags={
                "highway": "footway",
                "footway": "crossing",
                "crossing": "unmarked",
                "surface": "compacted",
            },
            detour_tags=CLEAR,
        )

        comparison = compare_routes(graph, origin=WEST, destination=EAST, profile=kerbs_only)
        codes = [e.code for e in comparison.explanations]

        assert codes == ["avoids_unrecorded_kerbs", "distance_difference"]

    def test_hard_limits_come_before_penalties(self) -> None:
        graph = build(
            direct_tags={"highway": "steps", "step_count": "9", "surface": "gravel"},
            detour_tags=CLEAR,
        )

        comparison = compare_routes(
            graph, origin=WEST, destination=EAST, profile=get_profile("wheelchair")
        )

        first = comparison.explanations[0]
        assert first.code == "avoids_stairs"
        assert first.evidence["hard_limit"] is True
        assert "which this profile excludes" in first.summary


class TestEvidenceBasis:
    """Each statement names the kind of evidence it rests on."""

    def test_an_unrecorded_kerb_is_never_labelled_as_recorded(self) -> None:
        # Regression (D6): the interface tagged "avoids crossings where no kerb
        # has been recorded" as "Recorded in OpenStreetMap" — an absence of data
        # presented as an observation.
        graph = build(
            direct_tags={"highway": "footway", "footway": "crossing", "crossing": "unmarked"},
            detour_tags=CLEAR,
        )

        comparison = compare_routes(
            graph, origin=WEST, destination=EAST, profile=get_profile("wheelchair")
        )
        kerbs = next(e for e in comparison.explanations if e.code == "avoids_unrecorded_kerbs")

        assert kerbs.basis == "not_recorded"

    def test_an_estimated_gradient_is_labelled_estimated(self) -> None:
        graph = build(
            direct_tags={**CLEAR, "incline": None},
            detour_tags={**CLEAR, "incline": None},
            direct_grade=7.0,
            detour_grade=1.0,
        )

        comparison = compare_routes(
            graph, origin=WEST, destination=EAST, profile=get_profile("wheelchair")
        )
        gradient = next(e for e in comparison.explanations if e.code == "avoids_steep_gradient")

        assert gradient.basis == "estimated"
        assert "(estimated)" in gradient.summary
        assert gradient.evidence["shortest_route_steepest_uphill_source"] == "derived_elevation"

    def test_recorded_and_estimated_gradients_together_are_labelled_mixed(self) -> None:
        # The direct link's incline is recorded; the detour's comes from terrain.
        graph = build(
            direct_tags={**CLEAR, "incline": "7%"},
            detour_tags={**CLEAR, "incline": None},
            detour_grade=3.0,
        )

        comparison = compare_routes(
            graph, origin=WEST, destination=EAST, profile=get_profile("wheelchair")
        )
        gradient = next(e for e in comparison.explanations if e.code == "avoids_steep_gradient")

        assert gradient.basis == "mixed"

    def test_the_distance_statement_is_a_profile_rule(self) -> None:
        graph = build(direct_tags={"highway": "steps"}, detour_tags=CLEAR)

        comparison = compare_routes(
            graph, origin=WEST, destination=EAST, profile=get_profile("wheelchair")
        )
        distance = next(e for e in comparison.explanations if e.code == "distance_difference")

        assert distance.basis == "profile_rule"


class TestSlopeLimitStatements:
    def test_a_declared_limit_is_repeated_exactly(self) -> None:
        # Regression (D4): limits were rounded to whole percent for display, so
        # somebody who set 4.5% was told they had set 4%.
        graph = build(
            direct_tags={**CLEAR, "incline": None},
            detour_tags={**CLEAR, "incline": None},
            direct_grade=4.7,
            detour_grade=1.0,
        )
        profile = build_custom_profile(base="wheelchair", max_incline_percent=4.5)

        comparison = compare_routes(graph, origin=WEST, destination=EAST, profile=profile)
        limit = next(e for e in comparison.explanations if e.code == "avoids_gradient_above_limit")

        assert "the 4.5% you set" in limit.summary
        assert "4.7% uphill, estimated" in limit.summary
        assert limit.basis == "estimated"
        assert "cannot manage uphill gradients above 4.5%" in profile.description

    def test_only_the_climb_is_excluded(self) -> None:
        # The limit is uphill in the direction of travel: the same link walked
        # downhill is not a reason to avoid it.
        graph = build(
            direct_tags={**CLEAR, "incline": None},
            detour_tags={**CLEAR, "incline": None},
            direct_grade=-9.0,
        )
        profile = build_custom_profile(base="wheelchair", max_incline_percent=5.0)

        comparison = compare_routes(graph, origin=WEST, destination=EAST, profile=profile)

        assert comparison.accessible_route is not None
        assert not any(e.code == "avoids_gradient_above_limit" for e in comparison.explanations)
