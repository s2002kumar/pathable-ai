"""Bounded extraction, run for real against a miniature release on disk.

No network: the fixture's catalog points at local files, and a local run turns
DuckDB's extension autoloading off, so a test that reached for the network
would fail rather than quietly succeed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from pathable_api.geo.overture.contract import (
    VARCHAR,
    IncompatibleSchemaError,
    ObservedType,
    check_schema,
    observe,
)
from pathable_api.geo.overture.extract import (
    CHANGELOG_FILE,
    EXTRACT_MANIFEST,
    SEGMENT_FILE,
    ExtractionError,
    ExtractionPlan,
    run_extraction,
)
from tests.overture_fixture import (
    CHANGELOG,
    EXTRACTED_SEGMENTS,
    REGION,
    RELEASE,
    SEGMENT_DDL,
    build_release,
    extract,
)


def _ids(path: Path) -> list[str]:
    with duckdb.connect() as connection:
        rows = connection.execute("SELECT id FROM read_parquet(?)", [path.as_posix()]).fetchall()
    return [str(row[0]) for row in rows]


def _manifest(folder: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((folder / EXTRACT_MANIFEST).read_text("utf-8"))
    return document


class TestBounding:
    def test_only_features_whose_box_meets_the_region_are_kept(self, tmp_path: Path) -> None:
        folder = extract(build_release(tmp_path / "release"), tmp_path / "out")

        assert _ids(folder / SEGMENT_FILE) == sorted(EXTRACTED_SEGMENTS)
        assert "seg-outside" not in _ids(folder / SEGMENT_FILE)
        # The boundary-crossing segment is kept whole: a box test, not a clip.
        assert "seg-boundary" in _ids(folder / SEGMENT_FILE)

    def test_a_file_whose_catalog_box_misses_the_region_is_never_opened(
        self, tmp_path: Path
    ) -> None:
        # The fixture's second segment file is not Parquet at all. Reaching it
        # would fail the run, so success is the proof it was skipped.
        folder = extract(build_release(tmp_path / "release"), tmp_path / "out")

        segment = _manifest(folder)["artifacts"]["segment"]
        assert segment["files_available"] == 2
        assert segment["files_opened"] == 1

    def test_the_output_folder_is_named_for_the_observed_release(self, tmp_path: Path) -> None:
        folder = extract(build_release(tmp_path / "release"), tmp_path / "out")

        assert folder == tmp_path / "out" / RELEASE / "fixture-region"
        release = _manifest(folder)["release"]
        assert release["requested"] == RELEASE
        assert release["observed"] == RELEASE


class TestReproducibility:
    def test_two_runs_produce_the_same_files_and_the_same_content_hash(
        self, tmp_path: Path
    ) -> None:
        fixture = build_release(tmp_path / "release")
        first = _manifest(extract(fixture, tmp_path / "one"))
        second = _manifest(extract(fixture, tmp_path / "two"))

        assert first["content_sha256"] == second["content_sha256"]
        for name, artifact in first["artifacts"].items():
            other = second["artifacts"][name]
            assert artifact["output"]["sha256"] == other["output"]["sha256"]

    def test_the_manifest_records_the_query_and_parameters_but_no_local_path(
        self, tmp_path: Path
    ) -> None:
        folder = extract(build_release(tmp_path / "release"), tmp_path / "out")
        bridge = _manifest(folder)["artifacts"]["bridge_sample"]

        assert "read_parquet(?" in bridge["query"]
        assert bridge["parameters"][1] == "<extract>/segment.parquet"
        assert str(tmp_path / "out") not in json.dumps(bridge["parameters"])

    def test_a_local_run_reports_no_network_traffic_rather_than_zero(self, tmp_path: Path) -> None:
        folder = extract(build_release(tmp_path / "release"), tmp_path / "out")
        segment = _manifest(folder)["artifacts"]["segment"]

        assert segment["measurement"]["http"] is None


class TestSchemaContract:
    def test_a_file_missing_a_required_column_stops_the_run_before_writing(
        self, tmp_path: Path
    ) -> None:
        without_sources = SEGMENT_DDL.replace(
            SEGMENT_DDL[
                SEGMENT_DDL.index("sources STRUCT") : SEGMENT_DDL.index("geometry GEOMETRY")
            ],
            "",
        )
        fixture = build_release(tmp_path / "release", segment_ddl=without_sources)

        with pytest.raises(IncompatibleSchemaError, match="missing sources"):
            extract(fixture, tmp_path / "out")
        assert not (tmp_path / "out" / RELEASE / "fixture-region" / SEGMENT_FILE).exists()

    def test_nested_fields_and_types_are_checked_not_just_column_names(self) -> None:
        with duckdb.connect() as connection:
            relation = connection.sql(
                "SELECT [{'record_id': 'w1@1', 'between': '0,1'}] AS sources, 'x' AS id"
            )
            columns, types = relation.columns, [observe(t) for t in relation.types]

        check = check_schema("segment", columns, types)

        assert "sources[].property" in check.missing
        assert any(
            problem.startswith("sources[].between is VARCHAR") for problem in check.mismatched
        )
        assert not check.compatible

    def test_added_columns_are_recorded_not_refused(self) -> None:
        text = ObservedType("varchar", "VARCHAR")
        check = check_schema("bridge", ["id", "novel"], [text, text], {"id": VARCHAR})

        assert check.compatible
        assert check.additional == ("novel",)


class TestChangelog:
    def test_changelog_rows_are_bounded_like_features(self, tmp_path: Path) -> None:
        folder = extract(build_release(tmp_path / "release"), tmp_path / "out")

        assert "seg-outside" not in _ids(folder / CHANGELOG_FILE)
        assert "seg-gone" in _ids(folder / CHANGELOG_FILE)
        assert _manifest(folder)["warnings"] == []

    def test_a_feature_missing_from_the_changelog_is_reported(self, tmp_path: Path) -> None:
        incomplete = [row for row in CHANGELOG if row[2] != "seg-dup"]
        folder = extract(build_release(tmp_path / "release", changelog=incomplete), tmp_path / "o")

        warnings = _manifest(folder)["warnings"]
        assert warnings == [
            "changelog/segment: 1 current feature(s) absent from the changelog, "
            "0 changelog feature(s) absent from the release extract."
        ]


def test_a_negative_sample_size_is_refused(tmp_path: Path) -> None:
    fixture = build_release(tmp_path / "release")
    plan = ExtractionPlan("fixture-region", REGION, "test", RELEASE, bridge_sample_files=-1)

    with pytest.raises(ExtractionError):
        run_extraction(plan, tmp_path / "out", fetch_json=fixture.fetch_json)
