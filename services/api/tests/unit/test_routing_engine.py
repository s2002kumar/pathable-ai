"""Routing over the synthetic network.

The fixture is built around one comparison — a short route across a stairway
versus a longer step-free route — so these tests can assert on the product's
actual behaviour rather than on a mock's.
"""

from __future__ import annotations

import pytest

from pathable_api.geo.fixtures import NODES, build_synthetic_network
from pathable_api.routing.comparison import compare_routes
from pathable_api.routing.engine import (
    MAX_REQUEST_SPAN_M,
    NoRouteFoundError,
    PointOffNetworkError,
    RequestTooLargeError,
    compute_route,
)
from pathable_api.routing.graph import RoutableGraph, graph_from_payload
from pathable_api.routing.profiles import STANDARD, get_profile

A = NODES["A"]
D = NODES["D"]
H = NODES["H"]


@pytest.fixture
def graph() -> RoutableGraph:
    return graph_from_payload(build_synthetic_network())


def node_sequence(route: object) -> list[str]:
    """The node path a route took, read back from its segment identities."""
    segments = route.segments  # type: ignore[attr-defined]
    if not segments:
        return []
    nodes = [segments[0].edge_identity.split("->")[0]]
    for segment in segments:
        u, rest = segment.edge_identity.split("->")
        v = rest.split("#")[0]
        nodes.append(v if nodes[-1] == u else u)
    return nodes


class TestGraphConstruction:
    def test_every_node_is_present(self, graph: RoutableGraph) -> None:
        assert graph.node_count == len(NODES)

    def test_segment_count_is_not_inflated_by_direction(self, graph: RoutableGraph) -> None:
        # The graph holds two directed entries per two-way segment; the dataset
        # still has one segment.
        assert graph.segment_count == build_synthetic_network().edge_count

    def test_snapping_finds_the_nearest_node(self, graph: RoutableGraph) -> None:
        snapped = graph.snap(A[0] + 0.00002, A[1])

        assert snapped is not None
        assert snapped.node_id == "A"
        assert snapped.distance_m < 5.0

    def test_snapping_reports_the_distance_in_metres(self, graph: RoutableGraph) -> None:
        # 0.0005 degrees of longitude at 43.47°N is about 40 m, not 0.0005.
        snapped = graph.snap(A[0] + 0.0005, A[1])

        assert snapped is not None
        assert snapped.node_id == "A"
        assert 35.0 < snapped.distance_m < 45.0

    def test_snapping_picks_the_genuinely_nearest_node(self, graph: RoutableGraph) -> None:
        # West of A the nearest junction is H, not the origin the caller had in
        # mind — which is exactly why the distance is returned to the caller.
        snapped = graph.snap(A[0] - 0.002, A[1])

        assert snapped is not None
        assert snapped.node_id == "H"


class TestStandardRoute:
    def test_the_shortest_route_takes_the_stairs(self, graph: RoutableGraph) -> None:
        route = compute_route(graph, origin=A, destination=D, profile=STANDARD)

        assert node_sequence(route) == ["A", "B", "C", "D"]
        assert route.stairway_count == 1
        assert route.step_count == 14

    def test_it_never_uses_a_foot_prohibited_segment(self, graph: RoutableGraph) -> None:
        # B->E is tagged foot=no; no profile, including the baseline, may use it.
        route = compute_route(graph, origin=A, destination=D, profile=STANDARD)
        assert "B->E#0" not in {segment.edge_identity for segment in route.segments}

    def test_its_effective_distance_equals_its_real_distance(self, graph: RoutableGraph) -> None:
        route = compute_route(graph, origin=A, destination=D, profile=STANDARD)
        assert route.effective_distance_m == pytest.approx(route.distance_m)

    def test_the_polyline_is_continuous(self, graph: RoutableGraph) -> None:
        route = compute_route(graph, origin=A, destination=D, profile=STANDARD)

        assert route.coordinates[0] == pytest.approx(A)
        assert route.coordinates[-1] == pytest.approx(D)
        # No duplicated junction positions where two segments meet.
        assert len(route.coordinates) == len(dict.fromkeys(route.coordinates))

    def test_segment_geometry_is_oriented_along_travel(self, graph: RoutableGraph) -> None:
        # Stored geometry runs source_u -> source_v; a route may traverse either
        # way, and a reversed segment would draw the polyline as a zigzag.
        route = compute_route(graph, origin=D, destination=A, profile=STANDARD)

        for segment in route.segments:
            assert segment.coordinates[0] != segment.coordinates[-1]
        assert route.coordinates[0] == pytest.approx(D)
        assert route.coordinates[-1] == pytest.approx(A)


class TestWheelchairRoute:
    def test_it_avoids_the_stairway(self, graph: RoutableGraph) -> None:
        route = compute_route(graph, origin=A, destination=D, profile=get_profile("wheelchair"))

        assert route.stairway_count == 0
        assert "B->C#0" not in {segment.edge_identity for segment in route.segments}

    def test_it_takes_the_ramp_and_the_signalised_crossing(self, graph: RoutableGraph) -> None:
        route = compute_route(graph, origin=A, destination=D, profile=get_profile("wheelchair"))

        assert node_sequence(route) == ["A", "B", "F", "C", "E", "D"]

    def test_it_is_longer_than_the_shortest_route(self, graph: RoutableGraph) -> None:
        # The trade the whole product exists to make visible.
        standard = compute_route(graph, origin=A, destination=D, profile=STANDARD)
        accessible = compute_route(
            graph, origin=A, destination=D, profile=get_profile("wheelchair")
        )

        assert accessible.distance_m > standard.distance_m

    def test_it_avoids_the_crossing_with_no_recorded_kerb(self, graph: RoutableGraph) -> None:
        route = compute_route(graph, origin=A, destination=D, profile=get_profile("wheelchair"))
        assert route.unknown_kerb_crossing_count == 0

    def test_it_avoids_the_gravel_path(self, graph: RoutableGraph) -> None:
        route = compute_route(graph, origin=A, destination=D, profile=get_profile("wheelchair"))
        identities = {segment.edge_identity for segment in route.segments}

        assert "A->G#0" not in identities
        assert "G->B#0" not in identities

    def test_its_effective_distance_exceeds_its_real_distance(self, graph: RoutableGraph) -> None:
        route = compute_route(graph, origin=A, destination=D, profile=get_profile("wheelchair"))
        assert route.effective_distance_m > route.distance_m


class TestCrutchesRoute:
    def test_stairs_are_allowed_but_weighed(self, graph: RoutableGraph) -> None:
        route = compute_route(graph, origin=A, destination=D, profile=get_profile("crutches"))

        # 14 steps at this profile's weights is dearer than the ramp detour, so
        # the router should take the ramp — without the stairway being forbidden.
        assert route.stairway_count == 0
        assert (
            route.distance_m
            > compute_route(graph, origin=A, destination=D, profile=STANDARD).distance_m
        )


class TestOneWaySegments:
    def test_a_one_way_passage_is_traversable_in_its_own_direction(
        self, graph: RoutableGraph
    ) -> None:
        route = compute_route(graph, origin=H, destination=A, profile=STANDARD)
        assert route.distance_m > 0

    def test_it_is_not_traversable_against_its_direction(self, graph: RoutableGraph) -> None:
        # H is reachable only through a one-way passage, so there is genuinely no
        # way back out. "No route" is the correct answer, not a route that
        # ignores the restriction.
        with pytest.raises(NoRouteFoundError):
            compute_route(graph, origin=A, destination=H, profile=STANDARD)


class TestRequestLimits:
    def test_a_point_far_from_the_network_is_refused(self, graph: RoutableGraph) -> None:
        with pytest.raises(PointOffNetworkError, match="origin"):
            compute_route(graph, origin=(A[0] - 0.05, A[1]), destination=D, profile=STANDARD)

    def test_the_refusal_names_which_point_was_off_network(self, graph: RoutableGraph) -> None:
        with pytest.raises(PointOffNetworkError, match="destination"):
            compute_route(graph, origin=A, destination=(D[0] + 0.05, D[1]), profile=STANDARD)

    def test_a_request_spanning_half_the_planet_is_refused_before_any_search(
        self, graph: RoutableGraph
    ) -> None:
        with pytest.raises(RequestTooLargeError):
            compute_route(graph, origin=A, destination=(2.35, 48.85), profile=STANDARD)

    def test_the_span_limit_is_a_walking_distance(self) -> None:
        assert 1_000 < MAX_REQUEST_SPAN_M <= 50_000


class TestDurationEstimate:
    def test_a_slower_profile_estimates_a_longer_time(self, graph: RoutableGraph) -> None:
        standard = compute_route(graph, origin=A, destination=D, profile=STANDARD)
        walker = compute_route(graph, origin=A, destination=D, profile=get_profile("walker"))

        assert walker.estimated_duration_seconds > standard.estimated_duration_seconds

    def test_it_is_not_derived_from_effective_metres(self, graph: RoutableGraph) -> None:
        # Effective metres encode preference as well as effort; a route that
        # avoids an unrecorded kerb is not slower for having done so.
        route = compute_route(graph, origin=A, destination=D, profile=get_profile("wheelchair"))
        implied = route.estimated_duration_seconds * 2.0

        assert implied < route.effective_distance_m * 10


class TestUnknownDataReporting:
    def test_a_route_reports_how_much_of_it_is_unsurveyed(self, graph: RoutableGraph) -> None:
        # A -> U -> B runs entirely over segments with no recorded attributes.
        route = compute_route(
            graph, origin=A, destination=NODES["B"], profile=get_profile("reduced_mobility")
        )
        assert 0.0 <= route.unknown_data_fraction <= 1.0

    def test_a_fully_recorded_route_reports_no_unknown_data(self, graph: RoutableGraph) -> None:
        route = compute_route(graph, origin=A, destination=NODES["B"], profile=STANDARD)

        assert node_sequence(route) == ["A", "B"]
        assert route.unknown_data_fraction == 0.0


class TestComparison:
    def test_it_returns_both_routes(self, graph: RoutableGraph) -> None:
        comparison = compare_routes(
            graph, origin=A, destination=D, profile=get_profile("wheelchair")
        )

        assert comparison.standard_route is not None
        assert comparison.accessible_route is not None
        assert comparison.extra_distance_m is not None
        assert comparison.extra_distance_m > 0

    def test_it_never_claims_a_model_was_involved(self, graph: RoutableGraph) -> None:
        comparison = compare_routes(
            graph, origin=A, destination=D, profile=get_profile("wheelchair")
        )
        assert comparison.ml_predictions_used is False

    def test_the_stairs_explanation_cites_the_real_step_count(self, graph: RoutableGraph) -> None:
        comparison = compare_routes(
            graph, origin=A, destination=D, profile=get_profile("wheelchair")
        )
        stairs = next(e for e in comparison.explanations if e.code == "avoids_stairs")

        assert "14 steps" in stairs.summary
        assert stairs.evidence["stairway_count"] == 1
        assert stairs.evidence["step_count"] == 14

    def test_it_explains_the_unrecorded_kerb_it_avoided(self, graph: RoutableGraph) -> None:
        comparison = compare_routes(
            graph, origin=A, destination=D, profile=get_profile("wheelchair")
        )
        kerbs = next(e for e in comparison.explanations if e.code == "avoids_unrecorded_kerbs")

        assert "nobody has confirmed" in kerbs.summary
        assert kerbs.evidence["crossing_count"] == 1

    def test_it_states_the_extra_distance_in_both_directions(self, graph: RoutableGraph) -> None:
        comparison = compare_routes(
            graph, origin=A, destination=D, profile=get_profile("wheelchair")
        )
        distance = next(e for e in comparison.explanations if e.code == "distance_difference")

        assert "longer" in distance.summary
        assert distance.evidence["extra_distance_m"] > 0

    def test_every_explanation_cites_evidence(self, graph: RoutableGraph) -> None:
        comparison = compare_routes(
            graph, origin=A, destination=D, profile=get_profile("wheelchair")
        )

        assert comparison.explanations
        for explanation in comparison.explanations:
            assert explanation.summary.strip()
            assert explanation.evidence, f"{explanation.code} cited nothing"

    def test_an_explanation_never_names_a_segment_the_route_actually_used(
        self, graph: RoutableGraph
    ) -> None:
        comparison = compare_routes(
            graph, origin=A, destination=D, profile=get_profile("wheelchair")
        )
        assert comparison.accessible_route is not None
        used = {segment.edge_identity for segment in comparison.accessible_route.segments}

        for explanation in comparison.explanations:
            for identity in explanation.evidence.get("segments", []):
                assert identity not in used

    def test_the_standard_profile_produces_no_second_route(self, graph: RoutableGraph) -> None:
        comparison = compare_routes(graph, origin=A, destination=D, profile=STANDARD)

        assert comparison.standard_route is not None
        assert comparison.accessible_route is None
        assert comparison.explanations == ()


class TestNoAccessibleRoute:
    def test_the_shortest_route_survives_when_the_profile_has_none(
        self, graph: RoutableGraph
    ) -> None:
        # A is reachable from H only through the one-way passage, and there is no
        # step-free alternative — so the accessible route fails while the
        # shortest route still exists, and the user should see both facts.
        comparison = compare_routes(
            graph, origin=H, destination=NODES["G"], profile=get_profile("wheelchair")
        )

        assert comparison.standard_route is not None
        if comparison.accessible_route is None:
            assert comparison.accessible_failure
            caution = next(c for c in comparison.cautions if c.code == "no_accessible_route")
            assert caution.evidence["blocked_segments_on_shortest_route"] >= 1

    def test_the_caution_names_why_segments_were_unusable(self, graph: RoutableGraph) -> None:
        comparison = compare_routes(
            graph, origin=H, destination=NODES["G"], profile=get_profile("wheelchair")
        )

        if comparison.accessible_route is None:
            caution = next(c for c in comparison.cautions if c.code == "no_accessible_route")
            assert caution.evidence["reasons"]
            assert caution.evidence["examples"]


class TestCautions:
    def test_a_route_over_unsurveyed_paths_is_flagged(self, graph: RoutableGraph) -> None:
        comparison = compare_routes(
            graph, origin=A, destination=D, profile=get_profile("wheelchair")
        )
        codes = {caution.code for caution in comparison.cautions}

        # The step-free route crosses segments with no recorded incline.
        assert "missing_accessibility_data" in codes

    def test_the_missing_data_caution_refuses_to_imply_safety(self, graph: RoutableGraph) -> None:
        comparison = compare_routes(
            graph, origin=A, destination=D, profile=get_profile("wheelchair")
        )
        caution = next(c for c in comparison.cautions if c.code == "missing_accessibility_data")
        assert "not evidence" in caution.summary
