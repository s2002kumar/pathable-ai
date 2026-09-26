"""The command line, run for real against a real database.

Every operational task in this project happens through `pathable`: seeding
regions, importing a network, sampling elevation, reporting coverage. A parser
test proves the flags are accepted; only this proves the commands do anything.

These call `main()` exactly as a shell does, including its exit codes — an
operator scripting an import depends on a non-zero exit meaning "it did not
work".
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Iterator
from pathlib import Path

import osmium
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from pathable_api.cli import EXIT_REVIEW_REQUIRED, main
from pathable_api.core.config import get_settings

#: What the `cli` fixture hands back: argv in, exit code out.
Cli = Callable[[list[str]], int]

pytestmark = pytest.mark.integration

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_MISCONFIGURED = 2


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, migrated_database_url: str) -> Iterator[Cli]:
    """Point the CLI at a freshly migrated database."""
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    get_settings.cache_clear()
    yield main
    get_settings.cache_clear()


class TestRegions:
    def test_seeding_then_listing(self, cli: Cli, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli(["regions", "seed"]) == EXIT_OK
        assert cli(["regions", "list"]) == EXIT_OK

        assert "waterloo" in capsys.readouterr().out

    def test_seeding_twice_is_safe(self, cli: Cli) -> None:
        # Re-running an import script must not fail on the region step.
        assert cli(["regions", "seed"]) == EXIT_OK
        assert cli(["regions", "seed"]) == EXIT_OK


class TestDatasets:
    def test_the_fixture_can_be_loaded_and_listed(
        self, cli: Cli, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli(["ingest", "synthetic"]) == EXIT_OK
        assert cli(["datasets", "list"]) == EXIT_OK

        output = capsys.readouterr().out
        assert "active" in output

    def test_listing_with_no_datasets_is_not_an_error(self, cli: Cli) -> None:
        # An empty database is a state, not a failure.
        assert cli(["datasets", "list"]) == EXIT_OK


class TestCoverageCommand:
    def test_it_refuses_a_region_with_no_dataset(self, cli: Cli) -> None:
        assert cli(["regions", "seed"]) == EXIT_OK

        assert cli(["coverage", "--region", "waterloo"]) == EXIT_FAILED

    def test_the_fixture_cannot_become_the_real_region_s_answer(self, cli: Cli) -> None:
        # Loading the synthetic network must not make `coverage --region
        # waterloo` start reporting on it. The fixture lives in its own region
        # precisely so a real command can never be answered with fake data, and
        # the operational commands only accept real pilot regions.
        assert cli(["ingest", "synthetic"]) == EXIT_OK

        assert cli(["coverage", "--region", "waterloo"]) == EXIT_FAILED

    def test_a_region_nobody_configured_is_refused_before_any_work(self, cli: Cli) -> None:
        with pytest.raises(SystemExit):
            cli(["coverage", "--region", "waterloo-synthetic"])


class TestElevationCommand:
    def test_a_provider_nobody_implemented_is_refused(self, cli: Cli) -> None:
        assert cli(["elevation", "apply", "--region", "waterloo", "--provider", "guess"]) == (
            EXIT_MISCONFIGURED
        )

    def test_the_disabled_provider_is_refused_rather_than_writing_nulls(self, cli: Cli) -> None:
        # Running the sampler with elevation switched off would wipe whatever a
        # previous run had gathered.
        assert cli(["elevation", "apply", "--region", "waterloo", "--provider", "none"]) == (
            EXIT_MISCONFIGURED
        )

    def test_it_reports_when_the_region_has_nothing_to_sample(self, cli: Cli) -> None:
        assert cli(["regions", "seed"]) == EXIT_OK

        assert cli(["elevation", "apply", "--region", "waterloo"]) == EXIT_FAILED


class TestEvaluateCommand:
    def test_an_unknown_profile_is_refused(self, cli: Cli) -> None:
        assert cli(["evaluate", "--region", "waterloo", "--profile", "hovercraft"]) == (
            EXIT_MISCONFIGURED
        )


class TestBenchmarkCommand:
    def test_a_synthetic_lattice_can_be_measured_without_a_dataset(
        self, cli: Cli, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli(["benchmark", "route", "--grid", "6", "--samples", "3"]) == EXIT_OK

        output = capsys.readouterr().out
        # A lattice is not a map of anywhere, and the output has to say so.
        assert "lattice" in output.lower() or "grid" in output.lower()

    def test_asking_for_neither_a_region_nor_a_grid_is_refused(self, cli: Cli) -> None:
        assert cli(["benchmark", "route"]) == EXIT_MISCONFIGURED


def _waterloo_extract(path: Path) -> Path:
    """Two footways in the Waterloo pilot box: one with edit metadata, one without."""
    stamp = dt.datetime(2024, 3, 1, 12, 0, tzinfo=dt.UTC)
    writer = osmium.SimpleWriter(str(path))
    try:
        for node_id, longitude in ((1, -80.5400), (2, -80.5390), (3, -80.5380)):
            writer.add_node(
                osmium.osm.mutable.Node(
                    id=node_id, location=(longitude, 43.4700), version=2, timestamp=stamp
                )
            )
        writer.add_node(osmium.osm.mutable.Node(id=4, location=(-80.5370, 43.4700)))
        writer.add_way(
            osmium.osm.mutable.Way(
                id=100, nodes=[1, 2], tags={"highway": "footway"}, version=5, timestamp=stamp
            )
        )
        writer.add_way(osmium.osm.mutable.Way(id=200, nodes=[3, 4], tags={"highway": "footway"}))
    finally:
        writer.close()
    return path


def _scalar(database_url: str, query: str) -> object:
    engine = create_engine(database_url.replace("+psycopg_async", "+psycopg"), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return connection.execute(text(query)).scalar_one()
    finally:
        engine.dispose()


class TestLifecycleCommands:
    def test_an_operator_takes_a_candidate_live_and_back_on_the_waterloo_corpus(
        self,
        cli: Cli,
        migrated_database_url: str,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # The whole operator path through the real 20-journey Waterloo corpus,
        # on a network too small to route it — which is itself an outcome the
        # regression records, and one a person has to accept.
        extract = _waterloo_extract(tmp_path / "waterloo.osm.pbf")
        newest = (
            "SELECT id::text FROM dataset_versions WHERE status = 'draft' "
            "ORDER BY created_at DESC LIMIT 1"
        )
        ingest = ["ingest", "pbf", "--region", "waterloo", "--file", str(extract)]

        assert cli(["regions", "seed"]) == EXIT_OK
        assert cli([*ingest, "--no-elevation-required"]) == EXIT_OK
        first = str(_scalar(migrated_database_url, newest))
        assert _scalar(migrated_database_url, "SELECT count(osm_version) FROM graph_nodes") == 3
        assert _scalar(migrated_database_url, "SELECT count(osm_way_version) FROM graph_edges") == 1

        assert cli(["datasets", "activate", first[:8]]) == EXIT_FAILED  # not sealed
        assert cli(["datasets", "seal", first[:8]]) == EXIT_OK
        report = tmp_path / "run.json"
        assert cli(["datasets", "evaluate", first, "--json", str(report)]) == EXIT_REVIEW_REQUIRED
        run = json.loads(report.read_text(encoding="utf-8"))
        assert run["outcome"] == "no_baseline"
        assert run["comparison_count"] == 20 * 6
        assert cli(["datasets", "activate", first]) == EXIT_FAILED  # not accepted
        reason = "First Waterloo network in this database; nothing to compare against."
        assert cli(["datasets", "accept", run["run_id"][:8], "--reason", reason]) == EXIT_OK
        assert cli(["datasets", "activate", first]) == EXIT_OK

        # An import that requires elevation cannot be sealed without it.
        assert cli(ingest) == EXIT_OK
        unelevated = str(_scalar(migrated_database_url, newest))
        assert cli(["datasets", "seal", unelevated]) == EXIT_FAILED

        assert cli([*ingest, "--no-elevation-required"]) == EXIT_OK
        second = str(_scalar(migrated_database_url, newest))
        assert cli(["datasets", "seal", second]) == EXIT_OK
        assert cli(["datasets", "evaluate", second]) == EXIT_OK  # identical routes
        assert cli(["datasets", "activate", second]) == EXIT_OK

        rollback_reason = "Rehearsing the rollback path before trusting it with real data."
        assert (
            cli(["datasets", "rollback", "--region", "waterloo", "--reason", rollback_reason])
            == EXIT_OK
        )
        live = "SELECT id::text FROM dataset_versions WHERE status = 'active'"
        assert _scalar(migrated_database_url, live) == first
        assert cli(["datasets", "checksum", first]) == EXIT_OK

        capsys.readouterr()
        assert cli(["datasets", "history", "--region", "waterloo"]) == EXIT_OK
        history = capsys.readouterr().out
        assert history.count("activate ") == 2
        assert f"accepted: {reason}" in history
        assert f"reason: {rollback_reason}" in history
