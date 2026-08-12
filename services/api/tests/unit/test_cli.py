"""The command line's argument surface.

The parser is the contract between an operator and the ingestion pipeline. A
missing choice or a silently-accepted region name would only surface as a failed
import against a live database, which is an expensive place to find it.
"""

from __future__ import annotations

import pytest

from pathable_api.cli import build_parser
from pathable_api.geo.regions import PILOT_REGIONS
from pathable_api.routing.benchmark import build_measurement_grid, measure
from pathable_api.routing.graph import graph_from_payload
from pathable_api.routing.profiles import STANDARD, get_profile


class TestParser:
    def test_a_subcommand_is_required(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args([])

    def test_osm_ingestion_requires_a_region(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["ingest", "osm"])

    def test_only_configured_regions_are_accepted(self) -> None:
        # Catching a typo here beats discovering it after an Overpass download.
        with pytest.raises(SystemExit):
            build_parser().parse_args(["ingest", "osm", "--region", "atlantis"])

    def test_every_configured_region_is_offered(self) -> None:
        parser = build_parser()
        for definition in PILOT_REGIONS:
            args = parser.parse_args(["ingest", "osm", "--region", definition.slug])
            assert args.region == definition.slug

    def test_activation_can_be_withheld(self) -> None:
        args = build_parser().parse_args(["ingest", "osm", "--region", "waterloo", "--no-activate"])
        assert args.no_activate is True

    def test_the_overpass_endpoint_can_be_overridden(self) -> None:
        args = build_parser().parse_args(
            ["ingest", "osm", "--region", "waterloo", "--overpass-url", "https://example.org/api"]
        )
        assert args.overpass_url == "https://example.org/api"

    def test_the_synthetic_fixture_needs_no_region(self) -> None:
        args = build_parser().parse_args(["ingest", "synthetic"])
        assert args.source == "synthetic"

    def test_regions_and_datasets_have_listings(self) -> None:
        parser = build_parser()
        assert parser.parse_args(["regions", "list"]).region_command == "list"
        assert parser.parse_args(["datasets", "list"]).dataset_command == "list"

    def test_the_benchmark_takes_a_grid_or_a_region(self) -> None:
        parser = build_parser()
        assert parser.parse_args(["benchmark", "route", "--grid", "20"]).grid == 20
        assert (
            parser.parse_args(["benchmark", "route", "--region", "waterloo"]).region == "waterloo"
        )


class TestMeasurementGrid:
    def test_it_builds_a_connected_lattice(self) -> None:
        payload = build_measurement_grid(5)

        assert payload.node_count == 25
        # 2 * n * (n - 1) links in a 4-connected lattice.
        assert payload.edge_count == 2 * 5 * 4

    def test_it_is_not_uniform(self) -> None:
        # A lattice where every edge costs the same would measure a cost model
        # that never has to choose.
        payload = build_measurement_grid(6)
        classes = {edge.features.highway for edge in payload.edges}

        assert classes == {"footway", "steps"}

    def test_measuring_it_produces_real_timings(self) -> None:
        graph = graph_from_payload(build_measurement_grid(8))

        report = measure(graph, [STANDARD, get_profile("wheelchair")], samples=5)

        assert report.node_count == 64
        assert len(report.summaries) == 2
        for summary in report.summaries:
            assert summary.samples + summary.failures == 5
            assert summary.p95_ms >= summary.p50_ms

    def test_the_same_seed_measures_the_same_journeys(self) -> None:
        # Otherwise a "regression" could just be a different set of routes.
        graph = graph_from_payload(build_measurement_grid(6))

        first = measure(graph, [STANDARD], samples=8, seed=7)
        second = measure(graph, [STANDARD], samples=8, seed=7)

        assert first.summaries[0].samples == second.summaries[0].samples
        assert first.summaries[0].failures == second.summaries[0].failures

    def test_a_network_too_small_to_route_is_refused(self) -> None:
        graph = graph_from_payload(build_measurement_grid(2))
        assert graph.node_count == 4

        report = measure(graph, [STANDARD], samples=3)
        assert report.summaries[0].samples + report.summaries[0].failures == 3

    def test_the_report_serialises_for_a_record(self) -> None:
        graph = graph_from_payload(build_measurement_grid(4))
        payload = measure(graph, [STANDARD], samples=3, dataset_label="test grid").to_dict()

        assert payload["dataset"] == "test grid"
        assert payload["profiles"][0]["profile"] == "standard"
