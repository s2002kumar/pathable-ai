"""The `pathable overture` commands, run through `main()` as a shell would.

Reading a release needs no database, so these run with DATABASE_URL unset. The
network is replaced by a fetcher that serves a fake catalog or fails, so the
failure path — no fallback, a reason, a non-zero exit — is tested for real.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pathable_api import cli
from pathable_api.geo.overture.catalog import STAC_ROOT, CatalogUnreachableError

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_MISCONFIGURED = 2

CATALOG: dict[str, dict[str, Any]] = {
    STAC_ROOT: {
        "latest": "2026-09-23.0",
        "links": [
            {"rel": "child", "href": "https://stac.overturemaps.org/2026-08-19.0/catalog.json"},
            {"rel": "child", "href": "https://stac.overturemaps.org/2026-09-23.0/catalog.json"},
        ],
    },
    "https://stac.overturemaps.org/2026-08-19.0/catalog.json": {
        "release:version": "2026-08-19.0",
        "schema:version": "1.18.0",
    },
    "https://stac.overturemaps.org/2026-09-23.0/catalog.json": {
        "release:version": "2026-09-23.0",
        "schema:version": "2.0.0",
    },
}


def _serve(
    fetch: Callable[[str], dict[str, Any]],
) -> Callable[..., Callable[[str], dict[str, Any]]]:
    return lambda **_kwargs: fetch


def _unreachable(url: str) -> dict[str, Any]:
    msg = f"Could not read {url}: connection refused"
    raise CatalogUnreachableError(msg)


def test_the_extract_command_defaults_to_latest_and_a_small_bridge_sample() -> None:
    args = cli.build_parser().parse_args(["overture", "extract", "--region", "waterloo"])

    assert args.release == "latest"
    assert args.bridge_sample_files == 2
    assert args.out == Path(".overture-data")


def test_linking_needs_an_extract_and_a_configured_region() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["overture", "link", "--region", "waterloo"])
    with pytest.raises(SystemExit):
        parser.parse_args(["overture", "link", "--region", "atlantis", "--extract", "x"])


def test_releases_are_listed_without_a_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "http_json_fetcher", _serve(CATALOG.__getitem__))

    assert cli.main(["overture", "releases"]) == EXIT_OK

    output = capsys.readouterr().out
    assert "2026-08-19.0\tschema 1.18.0" in output
    assert "2026-09-23.0\tschema 2.0.0  (latest)" in output


def test_an_unreachable_catalog_fails_with_the_reason_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "http_json_fetcher", _serve(_unreachable))

    code = cli.main(["overture", "extract", "--region", "waterloo", "--out", str(tmp_path / "o")])

    assert code == EXIT_FAILED
    assert "connection refused" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


def test_a_negative_bridge_sample_is_refused_before_any_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "http_json_fetcher", _serve(_unreachable))

    code = cli.main(["overture", "extract", "--region", "waterloo", "--bridge-sample-files", "-1"])

    assert code == EXIT_MISCONFIGURED
