"""Labels and the metrics that score a run against them."""

from __future__ import annotations

from typing import Any

import pytest

from pathable_api.geo.kitchener import benchmark as bm
from pathable_api.geo.kitchener.benchmark_labels import (
    DEVELOPMENT_CONVERSIONS,
    Label,
    LabelError,
    development_labels,
    parse_label,
)
from pathable_api.geo.kitchener.conflation import AMBIGUOUS, MATCHED, UNMATCHED, Decision, Target


def _label(record_id: int, correspondence: str, osm: list[str], **extra: Any) -> Label:
    representation = extra.pop(
        "representation",
        "none" if correspondence == "no_correspondence" else "separate_way",
    )
    relationship = extra.pop(
        "relationship", "one_to_one" if correspondence == "obvious_correspondence" else None
    )
    return parse_label(
        {
            "activetransportid": record_id,
            "correspondence": correspondence,
            "osm": osm,
            "representation": representation,
            "relationship": relationship,
        }
    )


def _decision(record_id: int, state: str, elements: list[str] = ()) -> Decision:  # type: ignore[assignment]
    targets = tuple(Target(e, "carrier") for e in elements)
    return Decision(record_id, state, "fixture", targets, None, "separate_way", {})


class TestLabels:
    @pytest.mark.parametrize(
        ("item", "message"),
        [
            ({"correspondence": "obvious_correspondence", "osm": []}, "names its OSM elements"),
            (
                {
                    "correspondence": "obvious_correspondence",
                    "osm": ["node/1"],
                    "representation": "separate_way",
                },
                "does not describe",
            ),
            (
                {"correspondence": "ambiguous_correspondence", "relationship": "one_to_one"},
                "only an obvious",
            ),
            ({"correspondence": "no_correspondence", "osm": ["way/1"]}, "names no elements"),
            ({"correspondence": "obvious_correspondence", "osm": ["relation/1"]}, "not a way/ID"),
            ({"correspondence": "maybe"}, "is not defined"),
        ],
    )
    def test_a_label_that_breaks_a_definition_is_refused(
        self, item: dict[str, Any], message: str
    ) -> None:
        base = {
            "activetransportid": 1,
            "osm": [],
            "representation": "none",
            "relationship": "one_to_one"
            if item.get("correspondence") == "obvious_correspondence"
            else None,
        }
        with pytest.raises(LabelError, match=message):
            parse_label({**base, **item})

    def test_the_development_conversion_records_every_change(self) -> None:
        geo04 = {
            "labeller": "fixture",
            "records": [
                {
                    "activetransportid": 403539,
                    "correspondence": "obvious_correspondence",
                    "osm": ["way/962754860"],
                    "representation": "separate_way",
                    "relationship": "many_to_one",
                },
                {
                    "activetransportid": 1,
                    "correspondence": "obvious_correspondence",
                    "osm": ["way/5"],
                    "representation": "separate_way",
                    "relationship": "one_to_one",
                },
            ],
        }

        document = development_labels(geo04, [403539, 1, 2])

        converted = next(r for r in document["records"] if r["activetransportid"] == 403539)
        assert converted["osm"] == ["node/8905696991", "way/962754860"]
        assert converted["representation"] == "multiple"
        (change,) = document["conversions"]
        assert change["reason"] == DEVELOPMENT_CONVERSIONS[403539]["reason"]
        assert change["before"]["osm"] == ["way/962754860"]


class TestOutcomes:
    def test_every_label_and_decision_has_one_outcome(self) -> None:
        obvious = _label(1, "obvious_correspondence", ["way/1", "way/2"])
        none = _label(2, "no_correspondence", [])
        ambiguous = _label(3, "ambiguous_correspondence", ["way/9"])

        assert bm.outcome(obvious, _decision(1, MATCHED, ["way/1", "way/2"])) == "exact"
        assert bm.outcome(obvious, _decision(1, MATCHED, ["way/1"])) == "partial"
        assert bm.outcome(obvious, _decision(1, MATCHED, ["way/7"])) == "wrong"
        assert bm.outcome(obvious, _decision(1, AMBIGUOUS)) == "abstained"
        assert bm.outcome(obvious, _decision(1, UNMATCHED)) == "missed"
        assert bm.outcome(none, _decision(2, MATCHED, ["way/1"])) == "false_match"
        assert bm.outcome(none, _decision(2, UNMATCHED)) == "correctly_unmatched"
        assert bm.outcome(ambiguous, _decision(3, AMBIGUOUS)) == "correctly_abstained"
        assert bm.outcome(ambiguous, _decision(3, MATCHED, ["way/9"])) == "matched"

    def test_pairs_count_ways_and_nodes_and_leave_ambiguous_labels_out(self) -> None:
        pairs = [
            (
                _label(1, "obvious_correspondence", ["way/1", "node/5"], representation="multiple"),
                _decision(1, MATCHED, ["way/1"]),
            ),
            (_label(2, "no_correspondence", []), _decision(2, MATCHED, ["way/3"])),
            (_label(3, "ambiguous_correspondence", ["way/9"]), _decision(3, MATCHED, ["way/8"])),
            (_label(4, "obvious_correspondence", ["way/4"]), _decision(4, AMBIGUOUS)),
        ]

        summary = bm.summarise(pairs, intervals=True)

        assert summary["pairs"] == {
            "true_positives": 1,
            "false_positives": 1,
            "false_negatives": 2,
            "precision": 0.5,
            "recall": 0.333,
            "f1": 0.4,
        }
        assert summary["pairs_by_element"]["node"]["false_negatives"] == 1
        level = summary["records_level"]
        assert level["matched_where_labeller_abstained"] == 1
        assert level["false_matches"] == 2  # a partial set and a match where OSM has nothing
        assert level["automatic_decision_coverage"] == 0.75
        assert level["abstention_rate"] == 0.25
        assert (
            summary["intervals_95"]["pairs_bootstrap_over_records"]
            == bm.summarise(pairs, intervals=True)["intervals_95"]["pairs_bootstrap_over_records"]
        )

    def test_the_wilson_interval(self) -> None:
        assert bm.wilson(0, 0) is None
        assert bm.wilson(8, 10) == [0.49, 0.943]


class TestTuning:
    def test_the_selection_rule_prefers_fewer_false_matches_then_exact_sets(self) -> None:
        class Policy:
            def __init__(self, **values: float) -> None:
                self.values = values

            def with_(self, **values: float) -> Policy:
                return Policy(**values)

        obvious = _label(1, "obvious_correspondence", ["way/1"])
        none = _label(2, "no_correspondence", [])

        def decide(policy: Policy) -> list[tuple[Label, Decision]]:
            carry = policy.values["carry_m"]
            first = _decision(1, MATCHED, ["way/1"]) if carry >= 2.0 else _decision(1, AMBIGUOUS)
            second = _decision(2, MATCHED, ["way/2"]) if carry >= 3.0 else _decision(2, UNMATCHED)
            return [(obvious, first), (none, second)]

        chosen, rows = bm.tune(decide, Policy())

        assert len(rows) == 108
        assert chosen.values["carry_m"] == 2.0  # 3.0 and 4.0 add a false match
