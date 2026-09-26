"""The whole audit on the fixture: every figure it reports can be counted by hand.

The fixture's records are listed with their purposes in
``tests/kitchener_fixture.py``; the expected numbers below follow from that
table, not from running the code and copying what it printed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pathable_api.geo.kitchener.audit import AuditError, AuditResult, run_audit, write_outputs
from pathable_api.geo.kitchener.normalize import normalize_snapshot
from pathable_api.geo.overture.evidence import content_sha256
from tests.kitchener_fixture import (
    FakeArcGIS,
    build_layers,
    fixture_edges,
    fixture_region,
    snapshot,
)


def _audit(tmp_path: Path, name: str = "run") -> AuditResult:
    taken = snapshot(tmp_path / f"{name}-s")
    normalized = normalize_snapshot(taken.folder, tmp_path / f"{name}-n").folder
    region = fixture_region()
    return run_audit(taken.folder, normalized, region, fixture_edges(region))


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> AuditResult:
    """Built once: every test here only reads it."""
    return _audit(tmp_path_factory.mktemp("audit"))


def _states(profile: dict[str, Any], field: str) -> dict[str, int]:
    return {k: v for k, v in profile["fields"][field]["states"].items() if v}


class TestProfile:
    def test_states_are_counted_without_merging(self, result: AuditResult) -> None:
        profile = result.profile

        assert _states(profile, "SURFACE_MATERIAL") == {
            "template_default": 5,
            "non_default": 3,
            "null": 1,
            "blank": 1,
            "not_applicable": 3,
        }
        assert _states(profile, "CURBCUT") == {
            "template_default": 8,
            "non_default": 1,
            "unknown": 1,
            "not_published": 3,
        }
        assert _states(profile, "SURFACE_CONDITION") == {
            "template_default": 3,
            "unknown": 6,
            "non_default": 1,
            "not_published": 3,
        }

    def test_the_default_investigation(self, result: AuditResult) -> None:
        defaults = result.profile["defaults"]

        assert defaults["width_m"]["equal_to_template_default_1_5"] == 6
        assert defaults["width_m"]["equal_to_documented_default_1_8"] == 0
        assert defaults["width_m"]["zero"] == 4
        assert defaults["width_m"]["non_default_non_zero"] == 2
        assert defaults["template_signature"]["records_by_fields_at_default"] == {
            "3": 5,
            "5": 2,
            "2": 1,
            "4": 1,
            "6": 1,
        }
        assert (
            defaults["surface_condition"]["fair_poor_unusable"]["source_is_2015_trail_inventory"]
            == 1
        )

    def test_physical_and_virtual_counts(self, result: AuditResult) -> None:
        physical = result.profile["physical_virtual"]

        assert physical["physical_class"] == {
            "physical_active": 9,
            "unresolved": 2,
            "unofficial_connection": 1,
            "virtual_link": 1,
        }
        assert physical["physical_active_pedestrian"]["records"] == 8

    def test_impossible_values_are_counted(self, result: AuditResult) -> None:
        plausibility = result.profile["plausibility"]

        assert plausibility["last_inspection_year_not_a_plausible_year"]["records"] == 1
        assert plausibility["slope_max_over_100_percent"]["records"] == 1
        assert plausibility["roadsegment_side_out_of_domain"]["records"] == 1
        assert plausibility["condition_score_without_condition_date"]["records"] == 1
        assert plausibility["width_zero_on_physical_record"]["records"] == 1

    def test_derived_slope_fields_are_checked_against_each_other(self, result: AuditResult) -> None:
        slope = result.profile["derived_slope_consistency"]

        assert slope["records_with_slope_max_and_grade_category"] == 10
        assert slope["grade_category_agrees_with_slope_max"] == 9

    def test_the_bulk_update_day_is_found(self, result: AuditResult) -> None:
        update = result.profile["provenance"]["update_date"]

        assert update["bulk_update_day"] == "2026-08-24"
        assert update["share_on_bulk_update_day"] == 0.9


class TestPersonalData:
    def test_personal_sources_and_names_never_leave_the_snapshot(self, result: AuditResult) -> None:
        text = json.dumps(result.profile) + json.dumps(result.sample)

        assert "PERSONAL OBSERVATION -XY" not in text
        assert "JDOE" not in text
        assert "SOMEONE" not in text
        assert result.profile["provenance"]["source_values_withheld"] == {"personal_observation": 1}


class TestGeographyAndSample:
    def test_overlap_is_reported_with_its_label(self, result: AuditResult) -> None:
        geography = result.profile["geography"]

        assert geography["records_intersecting_study_area"] == 13
        assert geography["physical_active_pedestrian_intersecting"] == 8
        assert "not a match" in geography["label"]

    def test_the_sample_is_valid_geojson_with_its_method(self, result: AuditResult) -> None:
        sample = result.sample

        assert sample["type"] == "FeatureCollection"
        assert len(sample["features"]) == result.profile["sample"]["records"]
        strata = {feature["properties"]["stratum"] for feature in sample["features"]}
        assert {"virtual_link", "stairs", "curb_cut_coded", "unresolved_semantics"} <= strata
        for feature in sample["features"]:
            assert feature["geometry"]["type"] == "LineString"
            assert "create_by" not in feature["properties"]


class TestAdoptionAndGate:
    def test_every_field_the_card_names_has_one_disposition(self, result: AuditResult) -> None:
        adoption = result.profile["adoption"]
        subjects = {entry["subject"]: entry["disposition"] for entry in adoption["entries"]}

        assert adoption["routing_use"].startswith("none")
        for subject in (
            "identity", "source and source date", "status", "stairs and structures",
            "geometry", "width", "surface material", "surface condition", "curb cut",
            "grade", "slope", "condition score and date", "inspection year", "virtual links",
        ):  # fmt: skip
            assert subject in subjects
        assert subjects["width"] == "comparison only"
        assert subjects["grade"] == "rejected"

    def test_the_exit_questions_carry_the_runs_own_numbers(self, result: AuditResult) -> None:
        gate = result.profile["exit_gate"]

        assert gate["q2_active_physical_pedestrian_records"]["total"] == 8
        assert gate["q5_stairs_crossings_curb"]["stairs"] == 1
        assert gate["q5_stairs_crossings_curb"]["curbcut_y"] == 1
        assert gate["q6_virtual_or_non_physical"]["virtual_link"] == 1
        assert gate["q3_populated_beyond_template_defaults"]["all_records"]["GRADE_known"] == 0

    def test_evidence_counts_only_departures_from_the_template(self, result: AuditResult) -> None:
        # The eight active physical pedestrian records are 1001-1006, 1009 and
        # 1010. The crosswalk's 0 m width and every default are not evidence.
        evidence = result.profile["geography"]["evidence_on_pedestrian_records"]

        assert evidence["all"] == evidence["in_study_area"]
        assert evidence["all"] == {
            "records": 8,
            "stairs": 1,
            "other_structure": 0,
            "surface_non_default": 2,
            "width_non_default_non_zero": 2,
            "curbcut_y": 1,
            "railing_y": 1,
            "condition_fair_poor_unusable": 1,
            "with_any_of_these": 5,
            "surface_template_default": 4,
            "width_template_default": 4,
            "condition_unknown": 5,
        }


class TestReproducibility:
    def test_one_frozen_snapshot_always_produces_the_same_evidence(self, tmp_path: Path) -> None:
        # Two retrievals of an unchanged source differ in when they happened,
        # which the evidence records; the property is that one frozen snapshot,
        # normalized and audited again, reproduces every figure and hash.
        taken = snapshot(tmp_path / "s")
        region = fixture_region()
        results = [
            run_audit(
                taken.folder,
                normalize_snapshot(taken.folder, tmp_path / name).folder,
                region,
                fixture_edges(region),
            )
            for name in ("n1", "n2")
        ]

        assert results[0].profile["content_sha256"] == results[1].profile["content_sha256"]
        assert content_sha256(results[0].sample) == content_sha256(results[1].sample)

    def test_outputs_are_written_as_lf_json(self, result: AuditResult, tmp_path: Path) -> None:
        profile_path = tmp_path / "out" / "profile.json"
        sample_path = tmp_path / "out" / "sample.geojson"

        write_outputs(result, profile_path, sample_path)

        assert b"\r\n" not in profile_path.read_bytes()
        assert json.loads(sample_path.read_text("utf-8"))["type"] == "FeatureCollection"

    def test_a_normalized_file_from_another_snapshot_is_refused(self, tmp_path: Path) -> None:
        taken = snapshot(tmp_path / "s")
        other = snapshot(
            tmp_path / "o", FakeArcGIS(build_layers(walk_records=[]))
        )  # a different snapshot id
        normalized = normalize_snapshot(other.folder, tmp_path / "n").folder
        region = fixture_region()

        with pytest.raises(AuditError, match="was built from snapshot"):
            run_audit(taken.folder, normalized, region, fixture_edges(region))
