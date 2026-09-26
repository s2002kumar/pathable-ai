"""The `pathable kitchener` commands, run through `main()` as a shell would.

Snapshot and normalize need no database, so these run with DATABASE_URL unset,
and the network is replaced by the in-memory City service.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from pathable_api import cli
from tests.kitchener_fixture import LICENCE_HTML, FakeArcGIS, build_layers

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_MISCONFIGURED = 2
EXIT_REVIEW_REQUIRED = 3


def _serve(monkeypatch: pytest.MonkeyPatch, server: FakeArcGIS) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(cli, "RequestsTransport", lambda: server)


def _snapshot_folder(root: Path) -> Path:
    (folder,) = [p for p in root.iterdir() if p.is_dir()]
    return folder


class TestSnapshotAndNormalize:
    def test_snapshot_then_normalize(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _serve(monkeypatch, FakeArcGIS(build_layers()))
        manifest_copy = tmp_path / "evidence" / "snapshot.json"

        code = cli.main(
            [
                "kitchener",
                "snapshot",
                "--out",
                str(tmp_path / "snaps"),
                "--json",
                str(manifest_copy),
            ]
        )

        assert code == EXIT_OK
        folder = _snapshot_folder(tmp_path / "snaps")
        assert json.loads(manifest_copy.read_text("utf-8"))["snapshot_id"].startswith(
            folder.name.split("-")[1]
        )
        assert "licence terms as recorded: yes" in capsys.readouterr().out

        code = cli.main(
            ["kitchener", "normalize", "--snapshot", str(folder), "--out", str(tmp_path / "norm")]
        )

        assert code == EXIT_OK
        assert (tmp_path / "norm" / "kitchener-active-transport.parquet").is_file()

    def test_a_changed_licence_needs_review(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        changed = LICENCE_HTML.replace("No credit is required", "Credit is required")
        _serve(monkeypatch, FakeArcGIS(build_layers(), licence_html=changed))

        code = cli.main(["kitchener", "snapshot", "--out", str(tmp_path / "snaps")])

        assert code == EXIT_REVIEW_REQUIRED

    def test_an_incomplete_read_fails_with_the_reason(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _serve(monkeypatch, FakeArcGIS(build_layers(truncate_pages_to=1)))

        code = cli.main(["kitchener", "snapshot", "--out", str(tmp_path / "snaps")])

        assert code == EXIT_FAILED
        assert "exceededTransferLimit" in capsys.readouterr().err

    def test_a_chunk_size_below_one_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _serve(monkeypatch, FakeArcGIS(build_layers()))

        code = cli.main(["kitchener", "snapshot", "--out", str(tmp_path), "--chunk-size", "0"])

        assert code == EXIT_MISCONFIGURED

    def test_normalizing_something_that_is_not_a_snapshot_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _serve(monkeypatch, FakeArcGIS(build_layers()))

        code = cli.main(
            ["kitchener", "normalize", "--snapshot", str(tmp_path), "--out", str(tmp_path / "n")]
        )

        assert code == EXIT_FAILED


class TestConsoleEncoding:
    def test_the_commands_survive_a_cp1252_console(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Regression: `normalize` printed "→", which a Windows console piped to
        # a file (cp1252) cannot encode. The command failed after writing its
        # output but before the --json copy, and the evidence copy was missing.
        _serve(monkeypatch, FakeArcGIS(build_layers()))
        console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        monkeypatch.setattr(sys, "stdout", console)
        manifest_copy = tmp_path / "normalized.json"

        assert cli.main(["kitchener", "snapshot", "--out", str(tmp_path / "snaps")]) == EXIT_OK
        folder = _snapshot_folder(tmp_path / "snaps")
        code = cli.main(
            [
                "kitchener", "normalize", "--snapshot", str(folder),
                "--out", str(tmp_path / "norm"), "--json", str(manifest_copy),
            ]
        )  # fmt: skip

        assert code == EXIT_OK
        assert manifest_copy.is_file()


class TestAuditArguments:
    def test_the_audit_needs_every_input_and_a_known_region(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(
            [
                "kitchener", "audit", "--region", "waterloo", "--snapshot", "s",
                "--normalized", "n", "--json", "p.json", "--sample", "s.geojson",
            ]
        )  # fmt: skip

        assert args.kitchener_command == "audit"
        assert args.dataset is None
        with pytest.raises(SystemExit):
            parser.parse_args(["kitchener", "audit", "--region", "atlantis"])
