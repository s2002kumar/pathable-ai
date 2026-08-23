"""The command line, run for real against a real database.

Every operational task in this project happens through `pathable`: seeding
regions, importing a network, sampling elevation, reporting coverage. A parser
test proves the flags are accepted; only this proves the commands do anything.

These call `main()` exactly as a shell does, including its exit codes — an
operator scripting an import depends on a non-zero exit meaning "it did not
work".
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from pathable_api.cli import main
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
