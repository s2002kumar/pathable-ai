"""Evaluating routes, ablating the cost model, and reporting what happened.

These are the tools that turn "the engine runs" into "here is what it does, and
here is what that cost". They are tested on the deterministic fixture rather than
on a real extract, because the behaviour that matters is not which route comes
back — it is that every outcome is reported, including the boring ones and the
unsuccessful ones.
"""

from __future__ import annotations

import pytest

from pathable_api.geo.fixtures import NODES, build_synthetic_network
from pathable_api.routing.ablation import build_variants, run_ablation, summarise_ablation
from pathable_api.routing.evaluation import (
    RouteCase,
    as_records,
    compare_algorithms,
    evaluate,
    run_case,
)
from pathable_api.routing.graph import RoutableGraph, graph_from_payload
from pathable_api.routing.profiles import get_profile
from pathable_api.routing.waterloo_cases import WATERLOO_CASES


@pytest.fixture
def graph() -> RoutableGraph:
    return graph_from_payload(build_synthetic_network())


CROSS_THE_FIXTURE = RouteCase(
    key="a-to-d",
    description="Across the fixture, past the stairway",
    origin=NODES["A"],
    destination=NODES["D"],
)

#: Far outside the fixture's few hundred metres of network.
NOWHERE = RouteCase(
    key="off-network",
    description="A point nothing walkable is near",
    origin=(-60.0, 10.0),
    destination=(-60.001, 10.001),
)


class TestRunningOneCase:
    def test_it_records_what_the_route_ran_into(self, graph: RoutableGraph) -> None:
        outcome = run_case(graph, case=CROSS_THE_FIXTURE, profile=get_profile("standard"))

        assert outcome.routed is True
        assert outcome.distance_m is not None
        assert outcome.segments > 0
        assert outcome.origin_snap_m is not None

    def test_a_failure_is_a_result_not_an_exception(self, graph: RoutableGraph) -> None:
        # An evaluation that stopped at the first unroutable journey would only
        # ever report the journeys that worked.
        outcome = run_case(graph, case=NOWHERE, profile=get_profile("standard"))

        assert outcome.routed is False
        assert outcome.failure is not None
        assert outcome.failure_kind is not None

    def test_it_counts_the_categories_the_map_is_silent_about(self, graph: RoutableGraph) -> None:
        outcome = run_case(graph, case=CROSS_THE_FIXTURE, profile=get_profile("wheelchair"))

        assert outcome.routed is True
        # The fixture deliberately contains segments with no surface or width.
        assert set(outcome.unknown).issubset(
            {"surface", "smoothness", "gradient", "width", "kerb information"}
        )


class TestComparingProfiles:
    def test_every_case_is_reported_including_the_unchanged_ones(
        self, graph: RoutableGraph
    ) -> None:
        cases = (CROSS_THE_FIXTURE, NOWHERE)
        comparisons = evaluate(
            graph,
            cases=cases,
            baseline=get_profile("standard"),
            subject=get_profile("wheelchair"),
        )

        # Keeping only the interesting cases would turn an evaluation into a demo.
        assert len(comparisons) == len(cases)
        assert {entry.case for entry in comparisons} == {case.key for case in cases}

    def test_the_reason_is_derived_from_what_was_avoided(self, graph: RoutableGraph) -> None:
        comparison = evaluate(
            graph,
            cases=(CROSS_THE_FIXTURE,),
            baseline=get_profile("standard"),
            subject=get_profile("wheelchair"),
        )[0]

        # A hand-written reason could drift from the evidence; this one cannot.
        assert comparison.route_changed is True
        assert "avoids" in comparison.reason()

    def test_an_unroutable_case_reports_why_rather_than_a_detour(
        self, graph: RoutableGraph
    ) -> None:
        comparison = evaluate(
            graph,
            cases=(NOWHERE,),
            baseline=get_profile("standard"),
            subject=get_profile("wheelchair"),
        )[0]

        assert comparison.detour_m is None
        assert comparison.reason() != ""

    def test_records_carry_both_profiles_and_the_verdict(self, graph: RoutableGraph) -> None:
        records = as_records(
            evaluate(
                graph,
                cases=(CROSS_THE_FIXTURE,),
                baseline=get_profile("standard"),
                subject=get_profile("wheelchair"),
            )
        )

        assert records[0]["case"] == "a-to-d"
        assert "baseline" in records[0]
        assert "subject" in records[0]
        assert isinstance(records[0]["route_changed"], bool)


class TestAlgorithmComparison:
    def test_astar_and_dijkstra_agree_on_cost(self, graph: RoutableGraph) -> None:
        # The correctness claim. A* may return a different path of equal cost
        # when several are tied, but never a worse one — that would mean the
        # heuristic is not admissible.
        timings = compare_algorithms(
            graph, cases=(CROSS_THE_FIXTURE,), profile=get_profile("wheelchair"), repeats=1
        )

        assert len(timings) == 1
        assert timings[0].costs_agree is True

    def test_an_unroutable_case_is_skipped_rather_than_timed(self, graph: RoutableGraph) -> None:
        timings = compare_algorithms(
            graph, cases=(NOWHERE,), profile=get_profile("standard"), repeats=1
        )

        assert timings == []


class TestAblation:
    def test_the_variants_really_differ(self, graph: RoutableGraph) -> None:
        profile = get_profile("wheelchair")
        variants = build_variants(profile)

        assert {variant.key for variant in variants} == {
            "current",
            "no_gradient_unknown",
            "no_unknown_penalty",
        }
        assert variants[2].profile.uncertainty_penalty_per_attribute == 0.0
        assert "incline" in variants[1].profile.ignore_unknown_attributes

    def test_it_routes_every_case_under_every_variant(self, graph: RoutableGraph) -> None:
        profile = get_profile("wheelchair")
        rows = run_ablation(graph, cases=(CROSS_THE_FIXTURE,), profile=profile)

        assert len(rows) == 1
        assert set(rows[0].outcomes) == {"current", "no_gradient_unknown", "no_unknown_penalty"}
        assert all(outcome.routed for outcome in rows[0].outcomes.values())

    def test_removing_the_penalty_makes_a_route_cheaper_or_leaves_it_alone(
        self, graph: RoutableGraph
    ) -> None:
        # It can never make a route cost *more*: the penalty only ever adds.
        profile = get_profile("wheelchair")
        row = run_ablation(graph, cases=(CROSS_THE_FIXTURE,), profile=profile)[0]

        shipped = row.outcomes["current"].effective_distance_m
        without = row.outcomes["no_unknown_penalty"].effective_distance_m
        assert shipped is not None
        assert without is not None
        assert without <= shipped + 0.001

    def test_the_summary_states_what_changed_without_interpreting_it(
        self, graph: RoutableGraph
    ) -> None:
        profile = get_profile("wheelchair")
        rows = run_ablation(graph, cases=(CROSS_THE_FIXTURE,), profile=profile)
        lines = "\n".join(summarise_ablation(rows, profile))

        assert "changed" in lines
        assert "No penalty for missing data at all" in lines


class TestTheWaterlooCorpus:
    def test_it_is_a_fixed_list_of_distinct_journeys(self) -> None:
        # Fixed before any route was run, so it cannot be trimmed afterwards to
        # the cases that happened to produce a good result.
        assert len(WATERLOO_CASES) == 20
        assert len({case.key for case in WATERLOO_CASES}) == 20

    def test_every_case_sits_inside_the_pilot_region(self) -> None:
        from pathable_api.geo.regions import region_definition

        min_lon, min_lat, max_lon, max_lat = region_definition("waterloo").bounds
        for case in WATERLOO_CASES:
            for longitude, latitude in (case.origin, case.destination):
                assert min_lon <= longitude <= max_lon, case.key
                assert min_lat <= latitude <= max_lat, case.key
