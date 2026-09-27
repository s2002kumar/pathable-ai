"""The lineage study end to end on invented data: inputs, labels, history, report.

The Kitchener side is the audit fixture, normalized for real; the OSM side is
placed beside it in ``tests.kitchener_lineage_fixture``. No network, no database.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pathable_api import cli
from pathable_api.geo.kitchener.lineage import ElementHistory, Lineage
from pathable_api.geo.kitchener.normalize import normalize_snapshot
from pathable_api.geo.kitchener.osm_history import Changeset, Contribution
from pathable_api.geo.kitchener.review import render_review
from pathable_api.geo.kitchener.study import (
    History,
    SampleFeature,
    StudyError,
    StudyInputs,
    attribute_comparisons,
    compare_surface,
    completeness,
    history_document,
    history_elements,
    load_history,
    load_inputs,
    municipal_since,
    repeat_subset,
    run_study,
    slim,
)
from tests import kitchener_lineage_fixture as osm_fixture
from tests.kitchener_fixture import snapshot


@pytest.fixture(scope="module")
def files(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path | str]:
    root = tmp_path_factory.mktemp("lineage")
    taken = snapshot(root / "snapshots")
    normalized = normalize_snapshot(taken.folder, root / "normalized")
    extract, manifest = osm_fixture.write_extract(root / "osm")
    sample, sample_sha = osm_fixture.write_sample(root / "sample.geojson", taken.snapshot_id)
    return {
        "normalized": normalized.folder,
        "extract": extract,
        "manifest": manifest,
        "sample": sample,
        "sample_sha": sample_sha,
        "root": root,
    }


@pytest.fixture(scope="module")
def inputs(files: dict[str, Any]) -> StudyInputs:
    return load_inputs(
        files["sample"],
        files["normalized"],
        files["extract"],
        files["manifest"],
        expected_sample_sha256=files["sample_sha"],
    )


def _record(document: dict[str, Any], record_id: int) -> dict[str, Any]:
    return next(r for r in document["records"] if r["activetransportid"] == record_id)


class TestInputs:
    def test_the_sample_is_studied_as_drawn(self, inputs: StudyInputs) -> None:
        assert [f.activetransportid for f in inputs.sample] == [r for r, _ in osm_fixture.SAMPLE]
        assert inputs.identity["kitchener"]["sample"]["records"] == len(osm_fixture.SAMPLE)

    def test_a_changed_sample_is_refused(self, files: dict[str, Any]) -> None:
        with pytest.raises(StudyError, match="not the recorded"):
            load_inputs(
                files["sample"],
                files["normalized"],
                files["extract"],
                files["manifest"],
                expected_sample_sha256="0" * 64,
            )

    def test_a_sample_from_another_snapshot_is_refused(
        self, files: dict[str, Any], tmp_path: Path
    ) -> None:
        other, _sha = osm_fixture.write_sample(tmp_path / "other.geojson", "f" * 64)

        with pytest.raises(StudyError, match="drawn from snapshot"):
            load_inputs(other, files["normalized"], files["extract"], files["manifest"])


class TestCandidates:
    def test_the_same_inputs_give_the_same_document(self, inputs: StudyInputs) -> None:
        first = run_study(inputs)
        second = run_study(inputs)

        assert first["content_sha256"] == second["content_sha256"]
        assert "summary" not in first  # nothing to summarise without labels

    def test_the_sidewalk_beside_a_record_comes_first(self, inputs: StudyInputs) -> None:
        document = run_study(inputs)

        sidewalk = _record(document, 1001)
        assert sidewalk["candidates"][0]["osm"] == "way/501"
        assert sidewalk["candidates"][0]["metrics"]["max_offset_m"] == pytest.approx(1.0, abs=0.05)
        assert sidewalk["road"]["name"] == "Fixture Street"
        assert sidewalk["road"]["street_matches_kitchener_street"] is True

    def test_history_is_read_for_near_candidates_and_nodes(self, inputs: StudyInputs) -> None:
        wanted = history_elements(run_study(inputs))

        assert "node/9001" in wanted
        assert "way/501" in wanted
        assert wanted == sorted(wanted, key=lambda e: (e.split("/")[0], int(e.split("/")[1])))


class TestLabelled:
    def test_counts_keep_virtual_and_physical_apart(self, inputs: StudyInputs) -> None:
        document = run_study(inputs, labels=osm_fixture.labels())

        summary = document["summary"]
        assert summary["all"]["correspondence"] == {
            "ambiguous_correspondence": 1,
            "no_correspondence": 1,
            "not_comparable": 1,
            "obvious_correspondence": 5,
        }
        assert summary["virtual_or_connection"]["records"] == 1
        assert summary["physical_or_unresolved"]["correspondence"]["obvious_correspondence"] == 4

    def test_attributes_are_compared_on_what_the_city_actually_asserts(
        self, inputs: StudyInputs
    ) -> None:
        document = run_study(inputs, labels=osm_fixture.labels())

        # CURBCUT = Y is never restated as a kerb value: a lowered kerb is
        # consistent with the City's "curbcut down to street level", not the same.
        curb = _record(document, 1002)["attributes"]["curb_cut"]
        assert curb["comparison"] == "consistent"
        assert curb["osm_kerb_values"] == ["lowered"]
        stairs = _record(document, 1004)["attributes"]
        assert stairs["structure"]["comparison"] == "same"
        assert stairs["railing"]["comparison"] == "consistent"
        trail = _record(document, 1005)["attributes"]
        assert trail["surface"]["comparison"] == "conflict"  # STONEDUST against gravel
        assert trail["condition"]["comparison"] == "both_present"
        assert "2015" in trail["condition"]["kitchener"]
        # A template-default CONCRETE is not evidence, so it is not compared.
        assert "surface" not in _record(document, 1001)["attributes"]
        assert "virtual_link" in _record(document, 2001)["attributes"]

    def test_topology_facts_come_from_the_labelled_ways(self, inputs: StudyInputs) -> None:
        document = run_study(inputs, labels=osm_fixture.labels())

        facts = _record(document, 1001)["topology_facts"]
        assert facts is not None
        assert [end["distance_m"] for end in facts["record_ends"]] == pytest.approx(
            [1.0, 1.0], abs=0.05
        )
        assert _record(document, 1010)["topology_facts"] is None

    def test_the_signals_are_described_not_scored(self, inputs: StudyInputs) -> None:
        signals = run_study(inputs, labels=osm_fixture.labels())["matcher_signals"]

        assert signals["records_with_obvious_way_correspondence"] == 5
        assert signals["labelled_way_ranks_first"]["overlap_5m"]["first"] == 5
        assert "weights" not in json.dumps(signals)

    def test_repeat_labels_are_compared_as_consistency(self, inputs: StudyInputs) -> None:
        primary = osm_fixture.labels()
        repeat = osm_fixture.labels()
        repeat["records"][4] = osm_fixture.label(1003, "ambiguous_correspondence", ["way/503"])

        review = run_study(inputs, labels=primary, repeat=repeat)["repeat_review"]

        as_labelled = review["as_labelled"]
        assert as_labelled["correspondence"]["records"] == 8
        assert as_labelled["correspondence"]["agree"] == 7
        assert as_labelled["relationship_where_both_obvious"]["records"] == 4
        assert "not inter-rater reliability" in as_labelled["kind"]
        assert review["after_refinement"] is None

    def test_consistency_is_measured_on_the_passes_as_labelled(self, inputs: StudyInputs) -> None:
        # Adjudication changes the labels the results use, never the measurement
        # of how consistent the two passes were.
        first = osm_fixture.labels()
        repeat = osm_fixture.labels()
        repeat["records"][4] = osm_fixture.label(1003, "ambiguous_correspondence", ["way/503"])
        adjudicated = osm_fixture.labels()
        adjudicated["records"][4] = repeat["records"][4]

        document = run_study(
            inputs,
            labels=adjudicated,
            first_pass=first,
            repeat=repeat,
            repeat_refined=repeat,
        )

        review = document["repeat_review"]
        assert review["as_labelled"]["correspondence"]["agree"] == 7
        assert review["after_refinement"]["correspondence"]["agree"] == 8
        assert document["summary"]["all"]["correspondence"]["ambiguous_correspondence"] == 2


def _contribution(
    element: str, changeset: int, timestamp: str, tags: dict[str, str], **flags: bool
) -> Contribution:
    return Contribution(
        element=element,
        timestamp=timestamp,
        version=2,
        changeset=changeset,
        creation=flags.get("creation", False),
        deletion=False,
        geometry_change=flags.get("geometry", False),
        tag_change=flags.get("tag_change", False),
        tags=tags,
    )


class TestHistory:
    def _history(self) -> History:
        way_501 = osm_fixture.WAYS[501][1]
        way_503 = osm_fixture.WAYS[503][1]
        return History(
            elements={
                "way/501": ElementHistory(
                    "way/501",
                    (_contribution("way/501", 10, "2015-01-01T00:00:00Z", way_501, creation=True),),
                    True,
                ),
                "way/503": ElementHistory(
                    "way/503",
                    (_contribution("way/503", 20, "2019-01-01T00:00:00Z", way_503, creation=True),),
                    True,
                ),
                "node/9001": ElementHistory(
                    "node/9001",
                    (
                        _contribution("node/9001", 20, "2019-01-01T00:00:00Z", {}, creation=True),
                        _contribution(
                            "node/9001",
                            30,
                            "2022-01-01T00:00:00Z",
                            {"kerb": "lowered"},
                            tag_change=True,
                        ),
                    ),
                    True,
                ),
            },
            changesets={
                10: Changeset(10, None, None, 5, None, {"source": "Bing"}),
                20: Changeset(20, None, None, 5, None, {"source": "City of Kitchener open data"}),
                30: Changeset(30, None, None, 1, None, {"created_by": "StreetComplete 45.0"}),
            },
            identity={"fixture": True},
        )

    def test_lineage_follows_the_stated_sources(self, inputs: StudyInputs) -> None:
        document = run_study(inputs, history=self._history(), labels=osm_fixture.labels())

        assert _record(document, 1001)["lineage"]["geometry"] == str(Lineage.INDEPENDENT)
        assert _record(document, 1003)["lineage"]["geometry"] == str(Lineage.KNOWN)
        kerb = _record(document, 1002)["attributes"]["curb_cut"]["osm_kerb_nodes"][0]["lineage"]
        assert kerb["label"] == str(Lineage.INDEPENDENT)  # set by a survey app, not the import
        assert _record(document, 1004)["lineage"]["ways"]["way/504"]["label"] == str(
            Lineage.UNKNOWN
        )

    def test_lineage_is_traced_only_for_an_obvious_correspondence(
        self, inputs: StudyInputs
    ) -> None:
        # Bug: an ambiguous label's cited ways — a road carrying a bicycle lane only
        # as a tag — had their own lineage counted as the City record's.
        labels = osm_fixture.labels()
        labels["records"][4] = osm_fixture.label(
            1003, "ambiguous_correspondence", ["way/503"], representation="road_attribute"
        )

        document = run_study(inputs, history=self._history(), labels=labels)

        assert _record(document, 1003)["lineage"] is None
        assert str(Lineage.KNOWN) not in document["summary"]["all"]["geometry_lineage"]

    def test_a_value_with_no_history_is_unknown_not_dropped(self, inputs: StudyInputs) -> None:
        # Bug: an OSM value the history could not trace left no finding at all,
        # so the attribute summary counted only the values it could trace.
        document = run_study(inputs, history=self._history(), labels=osm_fixture.labels())

        surface = _record(document, 1005)["attributes"]["surface"]
        assert surface["lineage"]["way/505"]["label"] == str(Lineage.UNKNOWN)
        assert surface["lineage"]["way/505"]["reasons"] == ["no history was read for this element"]
        assert document["attribute_results"]["surface"]["osm_value_lineage"] == {
            str(Lineage.UNKNOWN): 1
        }

    def test_a_history_file_round_trips(self, tmp_path: Path, inputs: StudyInputs) -> None:
        history = self._history()
        contributions = [c for element in history.elements.values() for c in element.contributions]
        document = history_document(contributions, history.changesets, inputs.osm.extract, {"x": 1})
        path = tmp_path / "history.json"
        path.write_text(json.dumps(document), "utf-8")

        loaded = load_history(path)

        assert sorted(loaded.elements) == ["node/9001", "way/501", "way/503"]
        assert loaded.changesets[20].tags["source"] == "City of Kitchener open data"

    def test_completeness_compares_against_the_frozen_state(self, inputs: StudyInputs) -> None:
        extract = inputs.osm.extract
        way = extract.ways[501]
        coordinates = tuple((extract.nodes[r].lon, extract.nodes[r].lat) for r in way.refs)

        def contribution(version: int, points: tuple[tuple[float, float], ...]) -> Contribution:
            return Contribution(
                "way/501", "2020-01-01T00:00:00Z", version, 1, True, False, False, False, {}, points
            )

        assert completeness("way/501", [contribution(2, coordinates)], extract) == (True, None)
        behind = completeness("way/501", [contribution(1, coordinates)], extract)
        assert behind[0] is False
        assert "version 2" in str(behind[1])
        moved = ((coordinates[0][0] + 0.001, coordinates[0][1]), coordinates[1])
        assert completeness("way/501", [contribution(2, moved)], extract)[0] is False


class TestAttributeResults:
    def test_results_per_attribute_and_what_only_osm_says(self, inputs: StudyInputs) -> None:
        results = run_study(inputs, labels=osm_fixture.labels())["attribute_results"]

        assert results["curb_cut"]["comparison"] == {"consistent": 1}
        assert results["structure"]["comparison"] == {"same": 1}
        # Trail 1005's STONEDUST against gravel; crosswalk 1003's painted asphalt
        # beside an OSM crossing with no surface tag.
        assert results["surface"]["comparison"] == {"conflict": 1, "kitchener_only": 1}
        assert results["condition"]["comparison"] == {"both_present": 1}
        # Sidewalk 1001's CONCRETE is a template default: OSM's surface is OSM's alone.
        assert 1001 in results["osm_only"]["surface"]["examples"]

    def test_way_tags_are_compared_only_on_an_obvious_correspondence(
        self, inputs: StudyInputs
    ) -> None:
        # Bug: a bicycle lane OSM records only as a tag on the road was compared
        # with the road's own surface, and counted as the same.
        labels = osm_fixture.labels()
        labels["records"][5] = osm_fixture.label(
            1005, "ambiguous_correspondence", ["way/505"], representation="road_attribute"
        )

        document = run_study(inputs, labels=labels)

        trail = _record(document, 1005)["attributes"]
        assert trail["surface"]["comparison"] == "not_comparable"
        assert trail["condition"]["comparison"] == "not_comparable"
        assert "osm_only" not in trail
        surface = document["attribute_results"]["surface"]
        assert surface["correspondence"] == {
            "ambiguous_correspondence": 1,
            "obvious_correspondence": 1,
        }

    def test_a_virtual_links_outcome_is_the_reviewers_not_proximity(
        self, inputs: StudyInputs
    ) -> None:
        # Bug: a crossing of another leg of the junction, within 5 m, counted as
        # OSM having the crossing the City's link makes.
        labels = osm_fixture.labels()
        labels["records"][0] = osm_fixture.label(
            2001, "no_correspondence", [], representation="none"
        )

        document = run_study(inputs, labels=labels)

        link = _record(document, 2001)["attributes"]["virtual_link"]
        assert link["osm_crossing_ways_within_5m"] == ["way/506"]
        assert link["comparison"] == "osm_lacks_the_connection"
        assert document["attribute_results"]["virtual_link"]["comparison"] == {
            "osm_lacks_the_connection": 1
        }

    def test_a_record_sourced_from_street_level_imagery_is_never_compared(
        self, inputs: StudyInputs
    ) -> None:
        document = run_study(inputs, labels=osm_fixture.labels())
        record = dict(_record(document, 1002))
        record["kitchener"] = {
            **record["kitchener"],
            "restricted_lineage": "restricted_or_unresolved_lineage",
        }

        compared = attribute_comparisons(record, None, document["osm_elements"], None)

        assert compared == {"restricted": "restricted_or_unresolved_lineage"}

    def test_population_context_is_proximity_over_every_record(self, inputs: StudyInputs) -> None:
        context = run_study(inputs, labels=osm_fixture.labels())["population_context"]

        assert context["curb_cut"] == {"lowered_or_flush": 1}
        assert context["stairs"] == {"osm_steps_within_3m": 1}
        assert "not correspondence" in context["what_this_is"]

    def test_the_evidence_keeps_far_candidates_as_identity_and_distance(
        self, inputs: StudyInputs
    ) -> None:
        evidence = slim(run_study(inputs, labels=osm_fixture.labels()))

        far = [c for r in evidence["records"] for c in r["candidates"] if "metrics" not in c]
        assert far
        assert all(c["min_distance_m"] > 10 for c in far)
        near = {c["osm"] for r in evidence["records"] for c in r["candidates"] if "metrics" in c}
        assert near <= set(evidence["osm_elements"])


class TestPieces:
    @pytest.mark.parametrize(
        ("material", "osm", "expected"),
        [
            ("ASPHALT", "asphalt", "same"),
            ("ASPHALT (PAINTED)", "asphalt", "same"),
            ("STONEDUST", "fine_gravel", "same"),
            ("STONEDUST", "gravel", "conflict"),
            ("ASPHALT", "paved", "same_coarser"),
            ("NATURAL", "paved", "conflict"),
            ("WOOD", None, "kitchener_only"),
        ],
    )
    def test_surfaces_compare_by_material(
        self, material: str, osm: str | None, expected: str
    ) -> None:
        assert compare_surface(material, osm) == expected

    def test_the_citys_earliest_date(self) -> None:
        assert (
            municipal_since({"create_date": "2014-06-30", "source_date": "2012-03-31"})
            == "2012-03-31"
        )
        assert municipal_since({"create_date": None, "source_date": None}) is None

    def test_the_repeat_subset_covers_every_stratum_then_fills_by_hash(self) -> None:
        sample = [SampleFeature(i, f"s{i % 5}", 1, {}) for i in range(1, 61)]

        chosen = repeat_subset(sample, target=12)

        assert len(chosen) == 12
        assert {f"s{i % 5}" for i in chosen} == {f"s{k}" for k in range(5)}
        assert chosen == repeat_subset(list(reversed(sample)), target=12)


class TestReviewAndCommand:
    def test_the_review_page_embeds_maps_and_the_blind_page_hides_labels(
        self, inputs: StudyInputs
    ) -> None:
        document = run_study(inputs, labels=osm_fixture.labels())

        page = render_review(document, inputs.kitchener, inputs.osm)
        blind = render_review(document, inputs.kitchener, inputs.osm, blind=True, only=[1001])

        assert page.count("<svg") == len(osm_fixture.SAMPLE)
        assert "<h3>Labels</h3>" in page
        assert blind.count("<svg") == 1
        assert "<h3>Labels</h3>" not in blind
        assert "obvious_correspondence</td>" not in blind.split("<main")[1]
        assert "src=" not in page  # nothing fetched: no basemap, no imagery
        assert "What this does not show" in page

    def test_the_command_writes_the_document_and_the_page(
        self, files: dict[str, Any], tmp_path: Path
    ) -> None:
        labels = tmp_path / "labels.json"
        labels.write_text(json.dumps(osm_fixture.labels()), "utf-8")
        out, page = tmp_path / "study.json", tmp_path / "review.html"

        code = cli.main(
            [
                "kitchener", "lineage-study",
                "--sample", str(files["sample"]), "--sample-sha256", str(files["sample_sha"]),
                "--normalized", str(files["normalized"]),
                "--extract", str(files["extract"]), "--extract-manifest", str(files["manifest"]),
                "--labels", str(labels), "--json", str(out), "--html", str(page),
            ]
        )  # fmt: skip

        assert code == 0
        assert json.loads(out.read_text("utf-8"))["summary"]["all"]["records"] == 8
        assert page.read_text("utf-8").startswith("<!doctype html>")

    def test_a_label_that_breaks_a_definition_fails_the_command(
        self, files: dict[str, Any], tmp_path: Path
    ) -> None:
        broken = osm_fixture.labels()
        broken["records"][0]["relationship"] = None
        labels = tmp_path / "labels.json"
        labels.write_text(json.dumps(broken), "utf-8")

        code = cli.main(
            [
                "kitchener", "lineage-study",
                "--sample", str(files["sample"]), "--normalized", str(files["normalized"]),
                "--extract", str(files["extract"]), "--extract-manifest", str(files["manifest"]),
                "--labels", str(labels), "--json", str(tmp_path / "study.json"),
            ]
        )  # fmt: skip

        assert code == 1
        assert not (tmp_path / "study.json").exists()
