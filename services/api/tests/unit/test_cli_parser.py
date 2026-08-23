"""The command line's argument surface.

A CLI is an operational tool: if it accepts a flag it does not honour, or
silently accepts a region that does not exist, the failure shows up in the
middle of a twenty-minute import rather than at the prompt. These tests pin the
parser, which is the part that can reject bad input before any work starts.

Nothing here touches a database, a network, or an extract.
"""

from __future__ import annotations

import argparse

import pytest

from pathable_api.cli import build_parser


def parse(*argv: str) -> argparse.Namespace:
    return build_parser().parse_args(list(argv))


class TestIngest:
    def test_pbf_needs_a_region_and_a_file(self) -> None:
        args = parse("ingest", "pbf", "--region", "waterloo", "--file", "ontario.osm.pbf")

        assert args.command == "ingest"
        assert args.source == "pbf"
        assert args.region == "waterloo"
        assert str(args.file) == "ontario.osm.pbf"

    def test_a_region_nobody_configured_is_refused(self) -> None:
        # Better here than after reading a 925 MB extract.
        with pytest.raises(SystemExit):
            parse("ingest", "pbf", "--region", "atlantis", "--file", "x.osm.pbf")

    def test_provenance_can_be_supplied_at_import_time(self) -> None:
        args = parse(
            "ingest",
            "pbf",
            "--region",
            "waterloo",
            "--file",
            "x.osm.pbf",
            "--provider",
            "geofabrik",
            "--source-timestamp",
            "2026-08-16T23:08:23+00:00",
        )

        assert args.provider == "geofabrik"
        assert args.source_timestamp == "2026-08-16T23:08:23+00:00"

    def test_a_dataset_can_be_stored_without_going_live(self) -> None:
        args = parse("ingest", "pbf", "--region", "waterloo", "--file", "x", "--no-activate")

        assert args.no_activate is True

    def test_the_synthetic_fixture_is_a_separate_source(self) -> None:
        # It must never be reachable by accident from a real-import command.
        assert parse("ingest", "synthetic").source == "synthetic"


class TestElevation:
    def test_it_defaults_to_the_lidar_source(self) -> None:
        args = parse("elevation", "apply", "--region", "waterloo")

        assert args.elevation_command == "apply"
        assert args.provider == "hrdem"

    def test_a_different_provider_can_be_named(self) -> None:
        args = parse("elevation", "apply", "--region", "waterloo", "--provider", "opentopodata")

        assert args.provider == "opentopodata"

    def test_it_can_target_a_dataset_that_is_not_live(self) -> None:
        args = parse("elevation", "apply", "--region", "waterloo", "--dataset", "abc-123")

        assert args.dataset == "abc-123"


class TestReporting:
    def test_coverage_can_write_its_report_to_a_file(self) -> None:
        args = parse("coverage", "--region", "waterloo", "--json", "out.json")

        assert args.command == "coverage"
        assert args.json == "out.json"

    def test_evaluate_defaults_to_comparing_against_the_wheelchair_profile(self) -> None:
        args = parse("evaluate", "--region", "waterloo")

        assert args.profile == "wheelchair"
        assert args.algorithms is False
        assert args.ablate is False

    def test_the_expensive_analyses_are_opt_in(self) -> None:
        # Timing both searches and routing every case three more times should
        # not happen because somebody wanted the route table.
        args = parse("evaluate", "--region", "waterloo", "--algorithms", "--ablate")

        assert args.algorithms is True
        assert args.ablate is True


class TestBenchmark:
    def test_a_synthetic_grid_is_distinguishable_from_a_real_region(self) -> None:
        # A lattice is not a map of anywhere, and a benchmark that confused the
        # two would produce a number about nothing.
        grid = parse("benchmark", "route", "--grid", "40")
        region = parse("benchmark", "route", "--region", "waterloo")

        assert grid.grid == 40
        assert grid.region is None
        assert region.region == "waterloo"
        assert region.grid is None


class TestNoDefaultCommand:
    def test_running_it_with_nothing_is_an_error(self) -> None:
        # Never guess at an operation that writes to a database.
        with pytest.raises(SystemExit):
            parse()
