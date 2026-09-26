"""The route-regression gate's pure parts: the corpus identity and the comparison.

A regression run is only evidence for the corpus, profiles and routing policy it
was run under. If the fingerprint failed to move when one of those changed, an
old run would keep approving candidates it never judged.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from pathable_api.geo.regions import WATERLOO_SLUG
from pathable_api.routing import activation
from pathable_api.routing.activation import (
    COMPARED_FIELDS,
    CORPORA,
    REGRESSION_PROFILES,
    ActivationRefusedError,
    Corpus,
    compare_outcomes,
    corpus_fingerprint,
    corpus_for,
)
from pathable_api.routing.profiles import SELECTABLE_PROFILE_KEYS, STANDARD_PROFILE_KEY


def outcome(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "routed": True,
        "failure_kind": None,
        "distance_m": 812.4,
        "effective_distance_m": 901.0,
        "duration_seconds": 640.2,
        "segments": 14,
        "path": "a" * 64,
    }
    values.update(changes)
    return values


class TestCorpus:
    def test_waterloo_is_judged_on_the_twenty_journey_corpus(self) -> None:
        corpus = corpus_for(WATERLOO_SLUG)

        assert len(corpus.cases) == 20
        assert len({case.key for case in corpus.cases}) == 20

    def test_every_profile_a_person_can_choose_is_compared(self) -> None:
        assert set(REGRESSION_PROFILES) == {STANDARD_PROFILE_KEY, *SELECTABLE_PROFILE_KEYS}

    def test_a_region_with_no_corpus_cannot_be_judged(self) -> None:
        with pytest.raises(ActivationRefusedError, match="no route-regression corpus"):
            corpus_for("atlantis")


class TestFingerprint:
    def test_moving_one_journey_changes_it(self) -> None:
        corpus = CORPORA[WATERLOO_SLUG]
        first = corpus.cases[0]
        moved = dataclasses.replace(first, origin=(first.origin[0] + 1e-6, first.origin[1]))
        changed = Corpus(name=corpus.name, cases=(moved, *corpus.cases[1:]))

        assert corpus_fingerprint(changed) != corpus_fingerprint(corpus)

    def test_dropping_a_profile_changes_it(self) -> None:
        corpus = CORPORA[WATERLOO_SLUG]

        assert corpus_fingerprint(corpus, REGRESSION_PROFILES[:-1]) != corpus_fingerprint(corpus)

    def test_a_new_routing_policy_changes_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A cost-function change is exactly when old runs stop describing routes.
        corpus = CORPORA[WATERLOO_SLUG]
        before = corpus_fingerprint(corpus)
        monkeypatch.setattr(activation, "ROUTING_POLICY_VERSION", 999)

        assert corpus_fingerprint(corpus) != before


class TestComparison:
    def test_identical_outcomes_have_no_differences(self) -> None:
        both = {("king-st", "wheelchair"): outcome()}

        results, differences = compare_outcomes(both, dict(both))

        assert len(results) == 1
        assert differences == []

    def test_each_differing_field_is_named_with_both_values(self) -> None:
        baseline = {("king-st", "wheelchair"): outcome()}
        candidate = {("king-st", "wheelchair"): outcome(distance_m=815.0, path="b" * 64)}

        _, differences = compare_outcomes(candidate, baseline)

        assert {(item["field"], item["baseline"], item["candidate"]) for item in differences} == {
            ("distance_m", 812.4, 815.0),
            ("path", "a" * 64, "b" * 64),
        }

    def test_a_route_that_stops_existing_is_a_difference(self) -> None:
        baseline = {("king-st", "wheelchair"): outcome()}
        lost = outcome(
            routed=False,
            failure_kind="NoRouteFoundError",
            distance_m=None,
            effective_distance_m=None,
            duration_seconds=None,
            segments=0,
            path=None,
        )

        _, differences = compare_outcomes({("king-st", "wheelchair"): lost}, baseline)

        assert {item["field"] for item in differences} == set(COMPARED_FIELDS)

    def test_with_no_baseline_nothing_is_called_a_difference(self) -> None:
        results, differences = compare_outcomes({("king-st", "wheelchair"): outcome()}, None)

        assert results[0]["baseline"] is None
        assert differences == []
