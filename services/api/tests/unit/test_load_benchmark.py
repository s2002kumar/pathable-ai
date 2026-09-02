"""The graph-load benchmark's rules, tested without loading anything.

The expensive part — reading a city out of PostGIS — is exercised by the
integration suite. What is tested here is the judgement the command applies to
its own numbers, because a benchmark that averages in a suspended laptop or
hides a dropped field behind a faster clock is worse than no benchmark.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from pathable_api.cli import build_parser
from pathable_api.geo.fixtures import build_synthetic_network
from pathable_api.routing.graph import graph_from_payload
from pathable_api.routing.load_benchmark import (
    IDLE_RATIO_LIMIT,
    LOAD_BENCHMARK_VERSION,
    LoadBenchmarkReport,
    LoadRun,
    MachineMemory,
    fingerprint,
    judge_run,
    machine_memory,
    process_memory,
    render,
)


def _run(number: int, *, elapsed: float, heap: float | None = None, valid: bool = True) -> LoadRun:
    return LoadRun(
        run=number,
        tracemalloc=heap is not None,
        started_at="2026-09-02T12:00:00+00:00",
        elapsed_seconds=elapsed,
        cpu_seconds=elapsed * 0.9,
        load_seconds_reported=elapsed * 0.95,
        peak_python_heap_mb=heap,
        rss_mb=900.0,
        peak_rss_mb=950.0,
        available_mb_before=4000.0,
        available_mb_after=3000.0,
        memory_pressure=False,
        valid=valid,
        invalid_reason=None if valid else "system suspend",
    )


def _report(runs: list[LoadRun]) -> LoadBenchmarkReport:
    graph = graph_from_payload(build_synthetic_network())
    return LoadBenchmarkReport(
        region="waterloo-synthetic",
        dataset_id="00000000-0000-0000-0000-000000000000",
        dataset_checksum="abc123" * 10,
        environment={"python": "3.13", "platform": "test", "machine": "x", "git_commit": None},
        machine_memory=MachineMemory(16000.0, 4000.0, "test"),
        process_memory_method="test",
        graph=fingerprint(graph),
        runs=runs,
    )


class TestParser:
    def test_the_load_benchmark_takes_a_configured_region(self) -> None:
        args = build_parser().parse_args(["benchmark", "load", "--region", "waterloo"])

        assert args.benchmark_command == "load"
        assert args.region == "waterloo"
        assert args.runs == 3
        assert args.heap_runs == 1
        assert args.json is None

    def test_runs_and_output_are_configurable(self) -> None:
        args = build_parser().parse_args(
            [
                "benchmark",
                "load",
                "--region",
                "waterloo",
                "--runs",
                "5",
                "--heap-runs",
                "2",
                "--json",
                "out.json",
            ]
        )

        assert (args.runs, args.heap_runs, args.json) == (5, 2, "out.json")

    def test_a_region_is_required(self) -> None:
        # A cold-start figure for no region in particular is not a figure.
        with pytest.raises(SystemExit):
            build_parser().parse_args(["benchmark", "load"])

    def test_only_configured_regions_are_accepted(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["benchmark", "load", "--region", "atlantis"])


class TestJudgingARun:
    def test_an_ordinary_run_is_valid(self) -> None:
        valid, reason, pressure = judge_run(
            elapsed_seconds=60.0, cpu_seconds=50.0, available_mb_before=4000.0, total_mb=16000.0
        )

        assert (valid, reason, pressure) == (True, None, False)

    def test_a_run_that_spanned_a_system_suspend_is_invalid_and_says_why(self) -> None:
        # Seen for real during the PA-RR-00 audit: 54,452 s of wall-clock for a
        # load that used about a minute of CPU. Averaging that in would have
        # made the optimisation look like a regression.
        valid, reason, _ = judge_run(
            elapsed_seconds=54452.0, cpu_seconds=60.0, available_mb_before=4000.0, total_mb=16000.0
        )

        assert valid is False
        assert reason is not None
        assert "suspend" in reason

    def test_the_idle_limit_is_generous_enough_for_a_busy_machine(self) -> None:
        # Paging that doubles or triples the wall-clock is still a (flagged)
        # measurement; only a run that barely executed is thrown out.
        valid, _, _ = judge_run(
            elapsed_seconds=IDLE_RATIO_LIMIT * 10.0 - 1.0,
            cpu_seconds=10.0,
            available_mb_before=None,
            total_mb=None,
        )

        assert valid is True

    def test_starting_with_little_free_memory_is_flagged_not_excluded(self) -> None:
        valid, reason, pressure = judge_run(
            elapsed_seconds=200.0, cpu_seconds=60.0, available_mb_before=800.0, total_mb=16000.0
        )

        assert (valid, reason, pressure) == (True, None, True)

    def test_unknown_memory_is_not_pressure(self) -> None:
        # A platform the probe cannot read must not be reported as starved.
        _, _, pressure = judge_run(
            elapsed_seconds=10.0, cpu_seconds=9.0, available_mb_before=None, total_mb=None
        )

        assert pressure is False


class TestSummary:
    def test_invalid_runs_are_listed_but_never_averaged(self) -> None:
        report = _report(
            [
                _run(1, elapsed=50.0),
                _run(2, elapsed=54452.0, valid=False),
                _run(3, elapsed=60.0),
                _run(4, elapsed=70.0, heap=700.0),
            ]
        )

        summary = report.summary()

        assert summary["timing_runs"] == 2
        assert summary["median_seconds"] == 55.0
        assert summary["min_seconds"] == 50.0
        assert summary["max_seconds"] == 60.0
        assert summary["spread_ratio"] == 1.2
        assert summary["invalid_runs"] == 1
        assert "54452" not in json.dumps(summary)

    def test_heap_comes_only_from_tracemalloc_runs(self) -> None:
        # A timing run has no heap figure; it must not drag the median to zero.
        report = _report([_run(1, elapsed=50.0), _run(2, elapsed=80.0, heap=701.0)])

        summary = report.summary()

        assert summary["heap_runs"] == 1
        assert summary["median_peak_python_heap_mb"] == 701.0
        # And the tracemalloc run does not count as a timing run: its clock
        # includes the tracer's overhead.
        assert summary["timing_runs"] == 1
        assert summary["median_seconds"] == 50.0

    def test_no_valid_runs_reports_none_rather_than_a_number(self) -> None:
        report = _report([_run(1, elapsed=54452.0, valid=False)])

        summary = report.summary()

        assert summary["median_seconds"] is None
        assert summary["timing_runs"] == 0
        assert "no valid timing run" in "\n".join(render(report))


class TestReportShape:
    def test_the_json_carries_provenance_and_a_version(self) -> None:
        report = _report([_run(1, elapsed=50.0), _run(2, elapsed=52.0, heap=700.0)])

        payload = report.to_dict()

        assert payload["load_benchmark_version"] == LOAD_BENCHMARK_VERSION
        assert set(payload) == {
            "load_benchmark_version",
            "region",
            "dataset_id",
            "dataset_checksum",
            "environment",
            "machine_memory",
            "process_memory_method",
            "graph",
            "summary",
            "runs",
        }
        assert set(payload["environment"]) == {"python", "platform", "machine", "git_commit"}
        assert set(payload["graph"]) == {
            "nodes",
            "segments",
            "directed_edges",
            "named_segments",
            "segments_with_raw_tags_in_memory",
            "segment_sha256",
            "node_sha256",
        }
        assert set(payload["runs"][0]) == {
            "run",
            "tracemalloc",
            "started_at",
            "elapsed_seconds",
            "cpu_seconds",
            "load_seconds_reported",
            "peak_python_heap_mb",
            "rss_mb",
            "peak_rss_mb",
            "available_mb_before",
            "available_mb_after",
            "memory_pressure",
            "valid",
            "invalid_reason",
        }
        # Round-trips as JSON: nothing in it is a dataclass or a Decimal.
        assert json.loads(json.dumps(payload)) == payload

    def test_the_rendered_summary_names_the_dataset_and_every_run(self) -> None:
        report = _report([_run(1, elapsed=50.0), _run(2, elapsed=99.0, valid=False)])

        text = "\n".join(render(report))

        assert "waterloo-synthetic" in text
        assert "INVALID: system suspend" in text
        assert "Excluded   1 invalid run(s)" in text


class TestFingerprint:
    def test_the_same_graph_fingerprints_the_same(self) -> None:
        first = fingerprint(graph_from_payload(build_synthetic_network()))
        second = fingerprint(graph_from_payload(build_synthetic_network()))

        assert first == second
        assert first["segments"] == graph_from_payload(build_synthetic_network()).segment_count
        assert first["directed_edges"] > first["segments"]

    def test_a_changed_route_relevant_field_changes_the_fingerprint(self) -> None:
        payload = build_synthetic_network()
        baseline = fingerprint(graph_from_payload(payload))

        altered = build_synthetic_network()
        first_edge = altered.edges[0]
        altered.edges[0] = replace(
            first_edge, features=replace(first_edge.features, surface="cobblestone:flattened")
        )

        assert (
            fingerprint(graph_from_payload(altered))["segment_sha256"]
            != (baseline["segment_sha256"])
        )

    def test_raw_tags_are_counted_but_not_hashed(self) -> None:
        # Whether a loader carries the OSM tag blob in memory is reported, so a
        # reader can see it; it must not move the hash, or two loaders that
        # route identically would look different.
        payload = build_synthetic_network()
        tagged = sum(1 for edge in payload.edges if edge.features.raw_tags)
        baseline = fingerprint(graph_from_payload(payload))
        assert baseline["segments_with_raw_tags_in_memory"] == tagged > 0

        annotated = build_synthetic_network()
        for index, edge in enumerate(annotated.edges):
            annotated.edges[index] = replace(
                edge,
                features=replace(
                    edge.features,
                    raw_tags={**edge.features.raw_tags, "note": "not routing evidence"},
                ),
            )
        annotated_print = fingerprint(graph_from_payload(annotated))

        assert annotated_print["segment_sha256"] == baseline["segment_sha256"]
        assert annotated_print["node_sha256"] == baseline["node_sha256"]


class TestMemoryProbes:
    def test_the_probes_never_raise_and_label_their_method(self) -> None:
        machine = machine_memory()
        process = process_memory()

        assert machine.method
        assert process.method
        for value in (machine.total_mb, machine.available_mb, process.rss_mb, process.peak_rss_mb):
            assert value is None or value >= 0.0


class TestCommandOutput:
    def test_the_json_report_is_written_with_lf_line_endings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Found on Windows: the first evidence file came out CRLF and failed the
        # repository's formatter check. The report is committed evidence, so its
        # bytes must not depend on the platform that produced it.
        from pathable_api import cli
        from pathable_api.core.config import get_settings

        report = _report([_run(1, elapsed=50.0)])

        async def fake_benchmark(*args: object, **kwargs: object) -> LoadBenchmarkReport:
            return report

        monkeypatch.setattr(cli, "run_load_benchmark", fake_benchmark)
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:y@localhost:1/none")
        get_settings.cache_clear()
        target = tmp_path / "load.json"
        try:
            exit_code = cli.main(
                ["benchmark", "load", "--region", "waterloo", "--json", str(target)]
            )
        finally:
            get_settings.cache_clear()

        assert exit_code == 0
        content = target.read_bytes()
        assert b"\r\n" not in content
        assert content.endswith(b"}\n")
        assert json.loads(content)["region"] == "waterloo-synthetic"
