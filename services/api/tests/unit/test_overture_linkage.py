"""The linkage report, against a miniature release whose right answers are known.

Each fixture case exists to pin one behaviour: cardinality kept rather than
collapsed, versions compared only when there is evidence, ambiguity and
malformed data counted rather than dropped, and nothing matched by geometry.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from pathable_api.geo.overture.extract import EXTRACT_MANIFEST, SEGMENT_FILE
from pathable_api.geo.overture.linkage import (
    ExtractMismatchError,
    OvertureSide,
    SegmentFeature,
    Snapshots,
    SourceRow,
    VersionStatus,
    build_report,
    load_overture_side,
    source_independence,
    version_status,
)
from pathable_api.geo.overture.osm_versions import ElementState
from tests.overture_fixture import INSIDE, build_release, evidence, extract, identities


@pytest.fixture(scope="module")
def overture(tmp_path_factory: pytest.TempPathFactory) -> OvertureSide:
    root = tmp_path_factory.mktemp("overture")
    return load_overture_side(extract(build_release(root / "release"), root / "out"))


@pytest.fixture(scope="module")
def with_evidence(overture: OvertureSide) -> dict[str, Any]:
    return build_report(identities(), overture, evidence())


@pytest.fixture(scope="module")
def without_evidence(overture: OvertureSide) -> dict[str, Any]:
    return build_report(identities(), overture, None)


class TestIdentity:
    def test_ways_are_matched_by_id_or_counted_as_absent_or_not_osm(
        self, without_evidence: dict[str, Any]
    ) -> None:
        assert without_evidence["ways"]["by_match"] == {
            "linked": 9,
            "not_in_overture_sources": 1,
            "pathable_id_not_osm": 1,
        }

    def test_cardinality_is_kept_not_collapsed_to_one_gers_id(
        self, without_evidence: dict[str, Any]
    ) -> None:
        assert without_evidence["ways"]["by_cardinality"] == {
            "many_to_one": 3,  # w300, w301, w401 share a segment with another way
            "one_to_one": 3,  # w100, w500, w700
            "one_to_many": 2,  # w200 split in two; w800 cited by two segments
            "many_to_many": 1,  # w400
        }

    def test_linear_ranges_survive_into_the_report_unchanged(
        self, without_evidence: dict[str, Any]
    ) -> None:
        examples = without_evidence["ways"]["examples"]
        merged = [
            example
            for key, group in examples.items()
            if key.startswith("linked/many_to_one")
            for example in group
            if example["pathable_source_way_id"] == "300"
        ]
        assert merged[0]["segments"] == [
            {"gers_id": "seg-merge", "record_id": "w300@2", "segment_range": [0.0, 0.5]}
        ]

    def test_a_segment_outside_the_region_does_not_leak_into_cardinality(
        self, without_evidence: dict[str, Any]
    ) -> None:
        # seg-outside also cites w100; if it had been extracted, w100 would be
        # one_to_many.
        one_to_one = without_evidence["ways"]["examples"][
            "linked/one_to_one/id_match_version_unknown"
        ]
        assert "100" in {example["pathable_source_way_id"] for example in one_to_one}


class TestVersions:
    def test_without_evidence_every_match_is_version_unknown(
        self, without_evidence: dict[str, Any]
    ) -> None:
        # PathAble stores no OSM versions; an id match alone proves nothing more.
        assert without_evidence["ways"]["by_version_status"] == {
            "id_match_version_unknown": 8,
            "ambiguous_conflicting_overture_versions": 1,
        }
        assert without_evidence["pathable"]["stores_osm_versions"] is False
        assert "none" in without_evidence["version_evidence"]["method"]

    def test_with_the_source_extract_versions_and_edit_times_are_compared(
        self, with_evidence: dict[str, Any]
    ) -> None:
        assert with_evidence["ways"]["by_version_status"] == {
            "exact_version_match": 4,  # w100, w200, w301, w400
            "ambiguous_conflicting_overture_versions": 1,  # w800
            "version_match_time_unverified": 1,  # w401
            "version_mismatch_pathable_newer": 1,  # w500
            "version_mismatch_pathable_older": 1,  # w300
            "way_version_match_nodes_edited_after_pathable_snapshot": 1,  # w700
        }
        # The stored identities alone still establish no version at all.
        assert with_evidence["ways"]["by_version_status_from_stored_identities_only"] == {
            "id_match_version_unknown": 8,
            "ambiguous_conflicting_overture_versions": 1,
        }

    def test_update_time_is_tested_against_the_latest_member_edit(
        self, with_evidence: dict[str, Any]
    ) -> None:
        semantics = with_evidence["ways"]["update_time_semantics"]
        assert semantics["same_version_ways"] == 6
        assert semantics["by_relation"] == {
            "equals_way_edit_time": 3,
            "equals_latest_node_edit_time": 1,
            "later_explained_by_edits_after_pathable_snapshot": 1,
            "unverifiable": 1,
        }

    def test_connector_nodes_are_compared_the_same_way(self, with_evidence: dict[str, Any]) -> None:
        connectors = with_evidence["connectors"]
        assert connectors["connectors"] == 5
        assert connectors["source_rows_by_kind"] == {
            "malformed_record_id:missing": 1,
            "malformed_record_id:unrecognised_shape": 1,
            "malformed_record_id:version_zero": 1,
            "osm_node": 2,
        }
        assert connectors["osm_nodes_in_pathable"] == 1
        # n13@0: PathAble has node 13, but "version 0" is not a version.
        assert connectors["version_zero_nodes_in_pathable"] == 1
        assert connectors["by_version_status"] == {"exact_version_match": 1}


class TestNothingIsDroppedSilently:
    def test_every_source_row_is_accounted_for(self, without_evidence: dict[str, Any]) -> None:
        rows = without_evidence["source_rows"]
        assert rows["segment_source_rows"] == 19
        assert rows["by_kind"] == {
            "osm_way_geometry": 14,
            "duplicate_row": 1,
            "malformed_between": 1,
            "malformed_record_id": 1,
            "non_osm_dataset": 1,
            "osm_property_only": 1,
        }
        assert sum(rows["by_kind"].values()) == rows["segment_source_rows"]

    def test_unknown_values_are_reported_as_unknown(self, without_evidence: dict[str, Any]) -> None:
        rows = without_evidence["source_rows"]
        assert rows["rows_with_null_confidence"] == 19
        assert rows["rows_with_null_update_time_by_kind"] == {
            "non_osm_dataset": 1,
            "osm_property_only": 1,
        }

    def test_segments_without_an_osm_way_are_unresolved_not_guessed(
        self, without_evidence: dict[str, Any]
    ) -> None:
        segments = without_evidence["segments"]
        assert segments["by_outcome"] == {
            "all_osm_ways_in_pathable": 10,
            "osm_ways_not_in_pathable": 2,
            "unresolved_no_osm_way_source": 2,
        }
        assert segments["unresolved_by_source_datasets"] == {"OpenStreetMap": 1, "TomTom": 1}
        assert segments["not_in_pathable_by_extent"] == {
            "crosses_region_boundary": 1,
            "inside_region_bounds": 1,
        }

    def test_edges_on_a_split_way_are_ambiguous_rather_than_assigned(
        self, without_evidence: dict[str, Any]
    ) -> None:
        assert without_evidence["edges"]["by_outcome"] == {
            "way_in_single_segment": 7,
            "ambiguous_way_split_across_segments": 6,
            "way_not_in_overture_sources": 4,
            "pathable_id_not_osm": 1,
        }


class TestCrossChecks:
    def test_the_bridge_sample_is_checked_against_the_segment_sources(
        self, without_evidence: dict[str, Any]
    ) -> None:
        bridge = without_evidence["bridge_verification"]
        assert bridge["bridge_files_read"] == 1
        assert bridge["rows_for_extracted_segments"] == 3
        assert bridge["rows_matching_a_segment_source"] == 2
        # The bridge has no `property` column: a routes-only relation looks like
        # any other source there.
        assert bridge["rows_matching_only_a_property_source"] == 1
        assert bridge["rows_without_a_matching_segment_source"] == 1
        assert bridge["unmatched_examples"][0]["record_id"] == "w999@1"

    def test_changelog_changes_are_attributed_to_linked_segments(
        self, without_evidence: dict[str, Any]
    ) -> None:
        changelog = without_evidence["changelog"]
        assert changelog["segments_linked_to_pathable_by_change"] == {
            "unchanged": 8,
            "added": 1,
            "data_changed": 1,
        }
        assert changelog["segment_columns_changed"] == {"geometry": 1, "sources": 1}

    def test_the_snapshot_gap_is_computed_from_both_sides(
        self, without_evidence: dict[str, Any]
    ) -> None:
        snapshots = without_evidence["snapshots"]
        assert snapshots["overture_osm_resource_versions"] == ["2026-09-09"]
        assert snapshots["days_between_snapshots"] == 24


class TestReproducibility:
    def test_the_content_hash_ignores_run_details_only(self, overture: OvertureSide) -> None:
        first = build_report(identities(), overture, evidence(), run={"seconds": 1})
        second = build_report(identities(), overture, evidence(), run={"seconds": 99})
        different = build_report(identities(), overture, None)

        assert first["content_sha256"] == second["content_sha256"]
        assert first["content_sha256"] != different["content_sha256"]

    def test_an_extract_edited_after_it_was_written_is_refused(self, tmp_path: Path) -> None:
        folder = extract(build_release(tmp_path / "release"), tmp_path / "out")
        with (folder / SEGMENT_FILE).open("ab") as handle:
            handle.write(b"\0")

        with pytest.raises(ExtractMismatchError, match="differs from the manifest"):
            load_overture_side(folder)

    def test_a_manifest_edited_by_hand_is_refused(self, tmp_path: Path) -> None:
        folder = extract(build_release(tmp_path / "release"), tmp_path / "out")
        manifest = folder / EXTRACT_MANIFEST
        manifest.write_text(
            manifest.read_text("utf-8").replace('"fixture-region"', '"elsewhere"'), "utf-8"
        )

        with pytest.raises(ExtractMismatchError, match="edited"):
            load_overture_side(folder)


#: PathAble read the map on 2026-08-16; Overture's snapshot is either side of it.
PATHABLE_READ = "2026-08-16T23:08:23Z"
OVERTURE_LATER = Snapshots(pathable=PATHABLE_READ, overture=dt.date(2026, 9, 9))
#: As measured for 2026-08-19.0: labelled 2026-08-05, latest edit carried 2026-08-01.
OVERTURE_EARLIER = Snapshots(
    pathable=PATHABLE_READ,
    overture=dt.date(2026, 8, 5),
    overture_latest_seen="2026-08-01T22:45:54Z",
)


@pytest.mark.parametrize(
    ("overture_version", "overture_time", "state", "snapshots", "expected"),
    [
        # Same version, same latest edit.
        (3, "2024-01-01T00:00:00Z", ElementState(3, "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"), OVERTURE_LATER, VersionStatus.EXACT),
        # Overture saw a node move made after PathAble read the map.
        (3, "2026-08-20T11:49:48Z", ElementState(3, "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"), OVERTURE_LATER, VersionStatus.NODES_EDITED_AFTER_PATHABLE_SNAPSHOT),
        # ...but a later edit that predates PathAble's read is not explained by anything.
        (3, "2026-07-01T00:00:00Z", ElementState(3, "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"), OVERTURE_LATER, VersionStatus.TIME_INCONSISTENT),
        # PathAble's newer extract has a node move made after Overture's planet date.
        (3, "2024-01-01T00:00:00Z", ElementState(3, "2024-01-01T00:00:00Z", "2026-08-10T00:00:00Z"), OVERTURE_EARLIER, VersionStatus.NODES_EDITED_AFTER_OVERTURE_SNAPSHOT),
        # Between the latest edit Overture carries and its planet date, Overture's
        # real cutoff is unknown — the regression found on 2026-08-19.0.
        (3, "2024-01-01T00:00:00Z", ElementState(3, "2024-01-01T00:00:00Z", "2026-08-02T17:50:49Z"), OVERTURE_EARLIER, VersionStatus.TIME_UNVERIFIED),
        (3, "2024-01-01T00:00:00Z", ElementState(3, "2024-01-01T00:00:00Z", "2026-08-05T09:00:00Z"), OVERTURE_EARLIER, VersionStatus.TIME_UNVERIFIED),
        # PathAble holds an edit older than one Overture demonstrably saw, yet it is missing.
        (3, "2024-01-01T00:00:00Z", ElementState(3, "2024-01-01T00:00:00Z", "2026-07-01T00:00:00Z"), OVERTURE_EARLIER, VersionStatus.TIME_INCONSISTENT),
        (3, None, ElementState(3, "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"), OVERTURE_LATER, VersionStatus.TIME_UNVERIFIED),
        (4, "2024-01-01T00:00:00Z", ElementState(3, "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"), OVERTURE_LATER, VersionStatus.PATHABLE_OLDER),
        (2, "2024-01-01T00:00:00Z", ElementState(3, "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"), OVERTURE_EARLIER, VersionStatus.PATHABLE_NEWER),
    ],
)  # fmt: skip
def test_a_version_match_is_exact_only_when_the_edit_times_agree(
    overture_version: int,
    overture_time: str | None,
    state: ElementState,
    snapshots: Snapshots,
    expected: VersionStatus,
) -> None:
    status = version_status([overture_version], {overture_time}, evidence(), state, snapshots)

    assert status is expected


def test_two_overture_versions_of_one_element_are_ambiguous_whatever_the_evidence() -> None:
    state = ElementState(1, "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z")

    assert version_status([1, 2], {None}, evidence(), state, OVERTURE_LATER) is (
        VersionStatus.AMBIGUOUS
    )


class TestSourceIndependence:
    """An attribute on an OSM-only segment is OSM's evidence and must never count twice."""

    @staticmethod
    def _segment(gers_id: str, *examined: str) -> SegmentFeature:
        return SegmentFeature(gers_id, "road", "footway", None, INSIDE, frozenset(examined))

    @staticmethod
    def _row(gers_id: str, dataset: str, prop: str = "") -> SourceRow:
        record = "w1@1" if dataset == "OpenStreetMap" else None
        return SourceRow(gers_id, dataset, record, prop, None, None, None)

    def test_osm_attributes_relabelled_by_overture_add_nothing_independent(self) -> None:
        segments = {
            "a": self._segment("a", "surface", "width"),
            "t": self._segment("t"),  # TomTom geometry with no examined attribute
        }
        rows = [self._row("a", "OpenStreetMap"), self._row("t", "TomTom")]

        result = source_independence(segments, rows, ["id", "road_surface"])

        assert result["segments_by_feature_source"] == {"non_osm_only": 1, "osm_only": 1}
        assert result["examined_attributes"]["surface"]["by_feature_source"]["osm_only"] == 1
        assert result["segments_without_osm_source_carrying_examined_attributes"] == 0
        assert "adds no evidence independent of OSM" in result["conclusion"]
        assert "kerb" in result["pathable_attributes_with_no_overture_column"]

    def test_non_osm_evidence_is_counted_and_mixed_segments_are_not_attributed(self) -> None:
        segments = {
            "a": self._segment("a", "surface"),
            "t": self._segment("t", "width"),  # a TomTom segment that does carry width
            "m": self._segment("m", "surface"),  # OSM + TomTom: cannot say whose surface
        }
        rows = [
            self._row("a", "OpenStreetMap"),
            self._row("a", "TomTom", prop="/road_surface"),
            self._row("t", "TomTom"),
            self._row("m", "OpenStreetMap"),
            self._row("m", "TomTom"),
        ]

        result = source_independence(segments, rows, ["id"])

        assert result["segments_without_osm_source_carrying_examined_attributes"] == 1
        assert result["segments_without_osm_source_carrying_examined_attributes_by_dataset"] == {
            "TomTom": 1
        }
        assert result["mixed_source_segments_carrying_examined_attributes"] == 1
        assert result["non_osm_property_level_contributions"] == 1
        assert "adds no evidence" not in result["conclusion"]

    def test_the_fixture_extract_adds_nothing_independent(
        self, without_evidence: dict[str, Any]
    ) -> None:
        independence = without_evidence["source_independence"]

        assert independence["segments_by_feature_source"] == {"osm_only": 13, "non_osm_only": 1}
        assert independence["segments_by_non_osm_dataset"] == {"TomTom": 1}
        assert independence["property_level_sources"] == {"OpenStreetMap:/routes": 1}
        assert {
            name: attribute["segments"]
            for name, attribute in independence["examined_attributes"].items()
        } == {"surface": 1, "width": 1, "access": 0, "sidewalk_or_crosswalk": 1, "stairs": 0}
        assert independence["segments_without_osm_source_carrying_examined_attributes"] == 0
