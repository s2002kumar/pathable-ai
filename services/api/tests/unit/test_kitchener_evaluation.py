"""The run's safeguards: frozen labels, frozen decisions, and honest repeat agreement."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from pathable_api.geo.kitchener.benchmark_labels import parse_label
from pathable_api.geo.kitchener.conflation import AMBIGUOUS, MATCHED, Decision, Target
from pathable_api.geo.kitchener.evaluation import (
    FAILURE_ANALYSIS_VERSION,
    BenchmarkError,
    _attach_causes,
    decisions_digest,
    load_label_sets,
    repeat_consistency,
)


def _decision(record_id: int, state: str = MATCHED, element: str = "way/1") -> Decision:
    targets = (Target(element, "carrier"),) if state == MATCHED else ()
    return Decision(record_id, state, "fixture", targets, None, "separate_way", {})


def _obvious(record_id: int, element: str = "way/1") -> dict[str, Any]:
    return {
        "activetransportid": record_id,
        "correspondence": "obvious_correspondence",
        "osm": [element],
        "representation": "separate_way",
        "relationship": "one_to_one",
    }


def _write(path: Path, document: Any) -> str:
    path.write_bytes(json.dumps(document).encode("utf-8"))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(tmp_path: Path, *, holdout_sha: str | None = None) -> Path:
    features = [{"properties": {"activetransportid": i, "stratum": f"s{i}"}} for i in (1, 2, 3)]
    sample = _write(
        tmp_path / "kitchener-geo05-holdout.geojson",
        {"metadata": {"seed": "fixture"}, "features": features},
    )
    (tmp_path / "kitchener-geo05-labelling-guide.md").write_bytes(b"guide\n")
    guide = hashlib.sha256(b"guide\n").hexdigest()
    for name, ids in (("labels", (1, 2, 3)), ("repeat-labels", (1, 2, 3))):
        _write(
            tmp_path / f"kitchener-geo05-holdout-{name}.json",
            {
                "kitchener_geo05_labels_version": 1,
                "holdout": {"sha256": holdout_sha or sample},
                "labelling_guide": {"sha256": guide},
                "records": [{**_obvious(i), "pack": "primary-1"} for i in ids],
            },
        )
    _write(
        tmp_path / "kitchener-geo05-development-labels.json",
        {"kitchener_geo05_labels_version": 1, "records": [_obvious(9)]},
    )
    return tmp_path


def test_the_labels_load_with_their_identity(tmp_path: Path) -> None:
    sets = load_label_sets(_evidence(tmp_path))

    assert sorted(sets.holdout) == [1, 2, 3]
    assert sets.strata[2] == "s2"
    assert set(sets.identity) >= {"holdout_sample", "holdout_labels", "labelling_guide"}


def test_labels_for_another_holdout_sample_are_refused(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkError, match="different holdout sample"):
        load_label_sets(_evidence(tmp_path, holdout_sha="0" * 64))


def test_the_decision_digest_ignores_order_and_sees_any_change() -> None:
    first = [_decision(1), _decision(2, AMBIGUOUS)]

    assert decisions_digest(first) == decisions_digest(list(reversed(first)))
    assert decisions_digest(first) != decisions_digest([_decision(1), _decision(2)])


FAILURES: list[dict[str, Any]] = [{"activetransportid": 5, "outcome": "partial"}]


class TestFailureAnalysis:
    def _causes(self, **overrides: Any) -> dict[str, Any]:
        return {
            "kitchener_geo05_failure_analysis_version": FAILURE_ANALYSIS_VERSION,
            "decisions_sha256": "abc",
            "categories": {"end_slop": "a few metres onto the next way"},
            "records": {"5": {"cause": "end_slop", "explanation": "fixture"}},
            **overrides,
        }

    def test_causes_attach_to_the_decisions_they_were_written_for(self) -> None:
        analysis = _attach_causes([dict(f) for f in FAILURES], self._causes(), "abc")

        assert analysis["analysed"] == 1
        assert analysis["by_cause"] == {"end_slop": 1}

    def test_an_analysis_of_other_decisions_is_refused(self) -> None:
        with pytest.raises(BenchmarkError, match="different decisions"):
            _attach_causes([dict(f) for f in FAILURES], self._causes(), "def")

    def test_a_record_that_did_not_fail_is_refused(self) -> None:
        causes = self._causes(records={"6": {"cause": "end_slop", "explanation": "fixture"}})

        with pytest.raises(BenchmarkError, match="did not fail"):
            _attach_causes([dict(f) for f in FAILURES], causes, "abc")


def test_repeat_agreement_counts_sets_not_just_classes() -> None:
    primary = {i: parse_label(_obvious(i)) for i in (1, 2)}
    repeat = {1: parse_label(_obvious(1)), 2: parse_label(_obvious(2, "way/7"))}

    result = repeat_consistency(primary, repeat, {1: _decision(1), 2: _decision(2)})

    assert result["same_correspondence"] == 2
    assert result["both_obvious_same_osm_set"] == 1
    assert [d["primary"]["activetransportid"] for d in result["disagreements"]] == [2]
    assert "not inter-rater reliability" in result["what_it_is"]
