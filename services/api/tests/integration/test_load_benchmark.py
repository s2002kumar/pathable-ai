"""The graph-load benchmark, run for real against PostGIS.

The synthetic fixture is tiny, so nothing here is a performance number worth
quoting. What it proves is that the command loads what is actually stored,
reports every run, and refuses to invent a figure for a region with nothing in
it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pathable_api.cli import main
from pathable_api.core.config import get_settings
from pathable_api.geo.fixtures import (
    SYNTHETIC_REGION_SLUG,
    build_synthetic_network,
    load_synthetic_dataset,
)
from pathable_api.geo.regions import seed_pilot_regions
from pathable_api.routing.graph import NoActiveDatasetError, graph_from_payload
from pathable_api.routing.load_benchmark import LOAD_BENCHMARK_VERSION, run_load_benchmark

from .test_cli_commands import EXIT_FAILED, EXIT_OK, Cli

pytestmark = pytest.mark.integration


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, migrated_database_url: str) -> Iterator[Cli]:
    """Point the CLI at a freshly migrated database, as `test_cli_commands` does."""
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    get_settings.cache_clear()
    yield main
    get_settings.cache_clear()


class TestRunLoadBenchmark:
    async def test_it_measures_the_stored_network_and_fingerprints_it(
        self, db_session: AsyncSession
    ) -> None:
        await load_synthetic_dataset(db_session)
        await db_session.commit()

        report = await run_load_benchmark(db_session, SYNTHETIC_REGION_SLUG, runs=2, heap_runs=1)

        expected = graph_from_payload(build_synthetic_network())
        assert report.graph["nodes"] == expected.node_count == 9
        assert report.graph["segments"] == expected.segment_count == 13
        # Fewer than two per segment: the fixture has a one-way segment.
        assert report.graph["directed_edges"] == expected.graph.number_of_edges()
        assert len(report.graph["segment_sha256"]) == 64
        assert [run.tracemalloc for run in report.runs] == [False, False, True]
        assert all(run.valid for run in report.runs)
        assert all(run.elapsed_seconds > 0 for run in report.runs)
        assert report.runs[-1].peak_python_heap_mb is not None

        summary = report.summary()
        assert summary["timing_runs"] == 2
        assert summary["heap_runs"] == 1

    async def test_the_same_dataset_fingerprints_the_same_twice(
        self, db_session: AsyncSession
    ) -> None:
        # Loading is deterministic; if two loads of one dataset disagreed, the
        # before/after comparison this exists for would be meaningless.
        await load_synthetic_dataset(db_session)
        await db_session.commit()

        first = await run_load_benchmark(db_session, SYNTHETIC_REGION_SLUG, runs=1, heap_runs=0)
        second = await run_load_benchmark(db_session, SYNTHETIC_REGION_SLUG, runs=1, heap_runs=0)

        assert first.graph == second.graph

    async def test_a_region_with_no_dataset_is_refused(self, db_session: AsyncSession) -> None:
        await seed_pilot_regions(db_session)
        await db_session.commit()

        with pytest.raises(NoActiveDatasetError):
            await run_load_benchmark(db_session, "waterloo")

    async def test_a_region_nobody_configured_is_refused(self, db_session: AsyncSession) -> None:
        with pytest.raises(NoActiveDatasetError):
            await run_load_benchmark(db_session, "atlantis")


class TestBenchmarkLoadCommand:
    def test_it_fails_cleanly_when_the_region_has_nothing_to_load(
        self, cli: Cli, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli(["regions", "seed"]) == EXIT_OK

        assert cli(["benchmark", "load", "--region", "waterloo"]) == EXIT_FAILED
        assert "no active network dataset" in capsys.readouterr().err

    def test_asking_for_zero_runs_is_refused(self, cli: Cli) -> None:
        assert (
            cli(["benchmark", "load", "--region", "waterloo", "--runs", "0", "--heap-runs", "0"])
            == 2
        )

    def test_the_fixture_cannot_be_measured_as_the_real_region(self, cli: Cli) -> None:
        # Same rule as `coverage`: a number about the nine-node fixture must
        # never be printed under a real city's name.
        assert cli(["ingest", "synthetic"]) == EXIT_OK

        assert cli(["benchmark", "load", "--region", "waterloo"]) == EXIT_FAILED

    def test_the_json_report_is_written_where_asked(
        self, cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The CLI only accepts real pilot regions, so this goes through the
        # function with the fixture's region and checks the same serialisation
        # the command writes.
        import asyncio

        from pathable_api.core.event_loop import selector_loop_factory
        from pathable_api.db.session import build_database

        assert cli(["ingest", "synthetic"]) == EXIT_OK

        async def produce() -> dict[str, object]:
            database = build_database(get_settings())
            try:
                async with database.session() as session:
                    report = await run_load_benchmark(
                        session, SYNTHETIC_REGION_SLUG, runs=1, heap_runs=0
                    )
            finally:
                await database.dispose()
            return report.to_dict()

        payload = asyncio.run(produce(), loop_factory=selector_loop_factory())
        target = tmp_path / "load.json"
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        stored = json.loads(target.read_text(encoding="utf-8"))
        assert stored["load_benchmark_version"] == LOAD_BENCHMARK_VERSION
        assert stored["region"] == SYNTHETIC_REGION_SLUG
        assert stored["summary"]["timing_runs"] == 1
        assert stored["runs"][0]["valid"] is True
