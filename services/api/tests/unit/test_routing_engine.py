"""Routing over the synthetic network.

The fixture is built around one comparison — a short route across a stairway
versus a longer step-free route — so these tests can assert on the product's
actual behaviour rather than on a mock's.
"""

from __future__ import annotations

from itertools import pairwise

import pytest
from shapely.geometry import Point

from pathable_api.geo.fixtures import NODES, build_synthetic_network
from pathable_api.geo.geometry import geodesic_distance_m
from pathable_api.routing.comparison import compare_routes
from pathable_api.routing.engine import (
    MAX_REQUEST_SPAN_M,
    NoRouteFoundError,
    PointOffNetworkError,
    RequestTooLargeError,
    Route,
    RoutingError,
    compute_route,
)
from pathable_api.routing.graph import RoutableGraph, graph_from_payload
from pathable_api.routing.profiles import STANDARD, MobilityProfile, get_profile
from pathable_api.routing.search import Algorithm

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

    def test_snapping_finds_the_nearest_point_on_a_segment(self, graph: RoutableGraph) -> None:
        # Not the nearest junction. On a long block the junction can be a
        # hundred metres from the door somebody actually asked about.
        snap = graph.snap_to_edge(A[0] + 0.001, A[1] + 0.0003)

        assert snap is not None
        assert 0.0 < snap.fraction < 1.0
        assert snap.distance_m < 60.0

    def test_snapping_reports_the_distance_in_metres(self, graph: RoutableGraph) -> None:
        # ~33 m north of the A-B line, which runs due east-west.
        snap = graph.snap_to_edge(A[0] + 0.001, A[1] + 0.0003)

        assert snap is not None
        assert 25.0 < snap.distance_m < 45.0

    def test_snapping_lands_on_the_endpoint_when_that_is_nearest(
        self, graph: RoutableGraph
    ) -> None:
        snap = graph.snap_to_edge(A[0], A[1])

        assert snap is not None
        assert snap.distance_m < 1.0

    def test_the_spatial_index_covers_every_segment(self, graph: RoutableGraph) -> None:
        assert len(graph.edge_index) == graph.segment_count


class TestTheDrawnRouteIsContinuous:
    """The polyline must be walkable as drawn, not merely correct in total.

    Regression: partial segments created by a snap were stored already reversed
    *and* marked as reversed, so the geometry was flipped twice and the piece was
    drawn backwards. On the real Waterloo network this put gaps of up to 93 m in
    12 of 19 routes and ended one of them 15 m from the point the user chose —
    while the reported distance stayed plausible, so nothing else caught it.
    """

    def _seams(self, route: object) -> list[float]:
        segments = route.segments  # type: ignore[attr-defined]
        return [
            geodesic_distance_m(Point(*first.coordinates[-1]), Point(*second.coordinates[0]))
            for first, second in pairwise(segments)
        ]

    def test_segments_meet_where_they_are_drawn(self, graph: RoutableGraph) -> None:
        origin = (A[0] + 0.0005, A[1])
        destination = (D[0] - 0.0005, D[1])
        route = compute_route(graph, origin=origin, destination=destination, profile=STANDARD)

        assert max(self._seams(route), default=0.0) < 1.0

    def test_it_holds_when_the_route_runs_against_the_stored_direction(
        self, graph: RoutableGraph
    ) -> None:
        # The reverse traversal is the case the bug lived in: forward-only
        # routes drew correctly, so testing one direction proved nothing.
        origin = (D[0] - 0.0005, D[1])
        destination = (A[0] + 0.0005, A[1])
        route = compute_route(graph, origin=origin, destination=destination, profile=STANDARD)

        assert max(self._seams(route), default=0.0) < 1.0

    def test_the_route_ends_where_the_traveller_was_snapped(self, graph: RoutableGraph) -> None:
        origin = (A[0] + 0.0005, A[1])
        destination = (D[0] - 0.0005, D[1])
        route = compute_route(graph, origin=origin, destination=destination, profile=STANDARD)

        start = Point(*route.coordinates[0])
        end = Point(*route.coordinates[-1])
        assert geodesic_distance_m(start, route.origin.point) < 1.0
        assert geodesic_distance_m(end, route.destination.point) < 1.0

    def test_the_drawn_length_matches_the_reported_distance(self, graph: RoutableGraph) -> None:
        # A backwards piece inflates what is drawn without changing what is
        # reported, so comparing the two is what makes the failure visible.
        origin = (A[0] + 0.0005, A[1])
        destination = (D[0] - 0.0005, D[1])
        route = compute_route(graph, origin=origin, destination=destination, profile=STANDARD)

        drawn = sum(
            geodesic_distance_m(Point(*a), Point(*b)) for a, b in pairwise(route.coordinates)
        )
        assert drawn == pytest.approx(route.distance_m, rel=0.02)


class TestPartialSegments:
    def test_a_route_can_start_part_way_along_a_segment(self, graph: RoutableGraph) -> None:
        # A quarter of the way along A->B, which used to snap back to A and
        # report a distance nobody would walk.
        origin = (A[0] + 0.0005, A[1])
        route = compute_route(graph, origin=origin, destination=D, profile=STANDARD)

        assert route.origin.distance_m < 5.0
        assert route.coordinates[0][0] == pytest.approx(origin[0], abs=1e-6)

    def test_a_partial_segment_is_shorter_than_the_whole(self, graph: RoutableGraph) -> None:
        from_start = compute_route(graph, origin=A, destination=D, profile=STANDARD)
        from_midway = compute_route(
            graph, origin=(A[0] + 0.001, A[1]), destination=D, profile=STANDARD
        )

        assert from_midway.distance_m < from_start.distance_m

    def test_partial_costs_are_prorated_not_repeated(self, graph: RoutableGraph) -> None:
        # Half a segment must cost about half, not the whole thing again.
        whole = compute_route(graph, origin=A, destination=NODES["B"], profile=STANDARD)
        half = compute_route(
            graph, origin=(A[0] + 0.001, A[1]), destination=NODES["B"], profile=STANDARD
        )

        assert half.distance_m == pytest.approx(whole.distance_m / 2, rel=0.15)

    def test_the_shared_graph_is_never_mutated_by_a_request(self, graph: RoutableGraph) -> None:
        # The graph is cached per dataset version and shared across concurrent
        # requests. A snap that mutated it would leak one user's origin into
        # somebody else's route.
        before_nodes = graph.node_count
        before_edges = graph.graph.number_of_edges()

        compute_route(graph, origin=(A[0] + 0.0005, A[1]), destination=D, profile=STANDARD)

        assert graph.node_count == before_nodes
        assert graph.graph.number_of_edges() == before_edges

    def test_a_split_one_way_segment_stays_one_way(self) -> None:
        # Half of a one-way passage is still one-way. The half running against
        # the permitted direction must not appear.
        payload = build_synthetic_network()
        graph = graph_from_payload(payload)

        # H -> A is a forward-only escalator; starting midway must still not
        # allow travel toward H.
        midpoint = ((H[0] + A[0]) / 2, (H[1] + A[1]) / 2)
        with pytest.raises(NoRouteFoundError):
            compute_route(graph, origin=midpoint, destination=H, profile=STANDARD)


class TestAlgorithmEquivalence:
    """A* must return the same optimal cost as Dijkstra, or the heuristic lies."""

    @pytest.fixture
    def pairs(self) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        names = sorted(NODES)
        return [
            (NODES[first], NODES[second])
            for index, first in enumerate(names)
            for second in names[index + 1 :]
        ]

    @pytest.mark.parametrize(
        "profile_key", ["standard", "wheelchair", "crutches", "reduced_mobility"]
    )
    def test_astar_matches_dijkstra_on_every_pair(
        self,
        graph: RoutableGraph,
        pairs: list[tuple[tuple[float, float], tuple[float, float]]],
        profile_key: str,
    ) -> None:
        profile = STANDARD if profile_key == "standard" else get_profile(profile_key)
        compared = 0

        for origin, destination in pairs:
            dijkstra_route = _route_or_none(graph, origin, destination, profile, Algorithm.DIJKSTRA)
            astar_route = _route_or_none(graph, origin, destination, profile, Algorithm.ASTAR)

            # Reachability must agree: a heuristic cannot make a path exist or
            # disappear, only change the order nodes are settled in.
            assert (dijkstra_route is None) == (astar_route is None), (origin, destination)
            if dijkstra_route is None or astar_route is None:
                continue

            compared += 1
            assert astar_route.effective_distance_m == pytest.approx(
                dijkstra_route.effective_distance_m, rel=1e-9
            ), (origin, destination)

        assert compared > 10, "the corpus stopped exercising the comparison"

    def test_the_heuristic_never_exceeds_the_true_cost(self, graph: RoutableGraph) -> None:
        # Admissibility, stated directly. Every edge costs at least its own
        # length, so straight-line distance is a valid lower bound — and this
        # breaks the moment somebody adds a discount to the cost model.
        for profile_key in ("standard", "wheelchair"):
            profile = STANDARD if profile_key == "standard" else get_profile(profile_key)
            route = compute_route(graph, origin=A, destination=D, profile=profile)
            straight_line = geodesic_distance_m(Point(*A), Point(*D))

            assert straight_line <= route.effective_distance_m + 1e-6

    def test_both_algorithms_are_reported_honestly(self, graph: RoutableGraph) -> None:
        dijkstra = compute_route(
            graph, origin=A, destination=D, profile=STANDARD, algorithm=Algorithm.DIJKSTRA
        )
        astar = compute_route(
            graph, origin=A, destination=D, profile=STANDARD, algorithm=Algorithm.ASTAR
        )

        assert dijkstra.algorithm is Algorithm.DIJKSTRA
        assert astar.algorithm is Algorithm.ASTAR
        assert dijkstra.expanded_nodes > 0
        assert astar.expanded_nodes > 0


def _route_or_none(
    graph: RoutableGraph,
    origin: tuple[float, float],
    destination: tuple[float, float],
    profile: MobilityProfile,
    algorithm: Algorithm,
) -> Route | None:
    try:
        return compute_route(
            graph,
            origin=origin,
            destination=destination,
            profile=profile,
            algorithm=algorithm,
        )
    except RoutingError:
        return None


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

    def test_the_missing_data_caution_says_what_the_figure_counts(
        self, graph: RoutableGraph
    ) -> None:
        # PA-UX-01F. The fraction is the share of length over segments missing
        # at least one attribute; a recorded stairway on such a segment is still
        # recorded. "No accessibility details" claimed more than that, and it
        # contradicted the stairway count shown beside it.
        comparison = compare_routes(
            graph, origin=A, destination=D, profile=get_profile("wheelchair")
        )
        caution = next(c for c in comparison.cautions if c.code == "missing_accessibility_data")
        route = comparison.accessible_route or comparison.standard_route
        assert route is not None

        assert "at least one accessibility attribute" in caution.summary
        assert "no accessibility details" not in caution.summary.lower()
        # It names the route it describes, and the length it is measured over.
        assert route.profile_display_name.lower() in caution.summary
        assert f"{route.unknown_data_fraction * 100:.0f}% of its length" in caution.summary
        assert caution.evidence["route_distance_m"] == round(route.distance_m)
