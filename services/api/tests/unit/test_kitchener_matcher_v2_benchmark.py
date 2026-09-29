"""PA-GEO-08's benchmark machinery: the declared tuning rule and the failure analysis binding."""

from __future__ import annotations

from typing import Any

import pytest

from pathable_api.geo.kitchener.matcher_v2 import MatcherV2Policy
from pathable_api.geo.kitchener.matcher_v2_benchmark import (
    FAILURE_ANALYSIS_VERSION,
    BenchmarkV2Error,
    attach_causes,
    cost,
    tune,
    tuned,
)


def _summary(
    *, partial: int = 0, abstained_ambiguous: int = 0, matched_ambiguous: int = 0, missed: int = 0
) -> dict[str, Any]:
    return {
        "records_level": {
            "false_matches": partial,
            "matched_where_labeller_abstained": matched_ambiguous,
            "exact_set_agreement": 10,
            "abstention_rate": 0.1,
        },
        "outcomes": {
            "obvious_correspondence": {"abstained": abstained_ambiguous, "missed": missed}
        },
        "pairs": {},
    }


def test_a_false_attachment_costs_twice_an_abstention() -> None:
    assert cost(_summary(partial=1)) == 2
    assert cost(_summary(matched_ambiguous=1)) == 2
    assert cost(_summary(abstained_ambiguous=1, missed=1)) == 2
    # One false attachment is worse than one abstention on an obvious correspondence.
    assert cost(_summary(partial=1)) > cost(_summary(abstained_ambiguous=1))


def test_a_tie_on_the_grid_goes_to_the_most_conservative_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Every grid point scores the same: the selection rule alone decides.
    monkeypatch.setattr(
        "pathable_api.geo.kitchener.matcher_v2_benchmark.bm.summarise",
        lambda _pairs: _summary(),
    )

    chosen, rows = tune(lambda _policy: [], MatcherV2Policy())

    assert tuned(chosen) == {
        "follow_max_deg": 10.0,
        "rival_extra_deg": 15.0,
        "carry_m": 2.0,
        "cover_min": 0.75,
    }
    assert len(rows) == 36


def test_a_failure_analysis_for_other_decisions_is_refused() -> None:
    failures = [{"activetransportid": 1, "outcome": "partial"}]
    causes = {
        "kitchener_geo08_failure_analysis_version": FAILURE_ANALYSIS_VERSION,
        "decisions_sha256": "a" * 64,
        "categories": {"kerb": "meaning"},
        "records": {"1": {"cause": "kerb", "explanation": "…"}},
    }

    with pytest.raises(BenchmarkV2Error, match="different decisions"):
        attach_causes(failures, causes, "b" * 64)
    attached = attach_causes([dict(f) for f in failures], causes, "a" * 64)
    assert attached["by_cause"] == {"kerb": 1}

    with pytest.raises(BenchmarkV2Error, match="did not fail"):
        attach_causes([], causes, "a" * 64)
