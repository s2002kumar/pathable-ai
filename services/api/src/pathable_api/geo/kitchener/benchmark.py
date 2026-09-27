"""Measuring a conflation run against frozen labels.

A correspondence is a relation — one record to a set of OSM elements — so the
benchmark measures it at two levels:

- **pairs** — each (record, element) the run asserts, against each (record,
  element) the labels assert. Precision, recall and F1 over records labelled
  with an obvious correspondence or with none. Records labelled ambiguous have
  no definite answer and are reported apart.
- **records** — whether the run's decision for the record is right as a whole:
  the exact correspondence set, a partial or wrong one, a correct "no
  counterpart", an abstention.

Every figure is a count over a stratified sample, reported per class and per
stratum. Nothing here weights the sample to the City's inventory, so no figure
is a population estimate. Intervals describe sampling uncertainty conditional
on the frozen labels: not whether the labels are right, not field truth, not
any place but this pilot.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from pathable_api.geo.kitchener.benchmark_labels import (
    AMBIGUOUS,
    NONE,
    NOT_COMPARABLE,
    OBVIOUS,
    Label,
)
from pathable_api.geo.kitchener.conflation import (
    AMBIGUOUS as DECIDED_AMBIGUOUS,
)
from pathable_api.geo.kitchener.conflation import (
    MATCHED,
    UNMATCHED,
    CandidateSet,
    Decision,
    Record,
)

BENCHMARK_VERSION = "kitchener-geo05-benchmark-v1"
#: For the pair-level intervals: records are resampled, since pairs within a
#: record are not independent. Fixed, so the intervals are reproducible.
BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 20260927
Z95 = 1.959963984540054

#: Record outcomes, by what the labels say and what the run decided.
OUTCOMES = {
    OBVIOUS: {
        "exact": "the exact correspondence set",
        "partial": "matched, overlapping the labelled set but not equal to it",
        "wrong": "matched, sharing no element with the labelled set",
        "abstained": "abstained (ambiguous) on an obvious correspondence",
        "missed": "unmatched although OSM has the facility",
    },
    NONE: {
        "correctly_unmatched": "unmatched, and OSM has nothing",
        "false_match": "matched although OSM has nothing",
        "abstained": "abstained where OSM has nothing",
    },
    AMBIGUOUS: {
        "correctly_abstained": "abstained where the labeller could not name the elements",
        "matched": "matched where the labeller could not name the elements",
        "unmatched": "unmatched where the labeller could not name the elements",
    },
}


def outcome(label: Label, decision: Decision) -> str:
    if label.correspondence == OBVIOUS:
        if decision.state == MATCHED:
            predicted = decision.elements
            if predicted == label.truth:
                return "exact"
            return "partial" if predicted & label.truth else "wrong"
        return "abstained" if decision.state == DECIDED_AMBIGUOUS else "missed"
    if label.correspondence == NONE:
        if decision.state == MATCHED:
            return "false_match"
        return "correctly_unmatched" if decision.state == UNMATCHED else "abstained"
    if decision.state == MATCHED:
        return "matched"
    return "correctly_abstained" if decision.state == DECIDED_AMBIGUOUS else "unmatched"


def wilson(successes: int, trials: int) -> list[float] | None:
    """The Wilson score 95% interval for a proportion; ``None`` with no trials."""
    if trials == 0:
        return None
    p = successes / trials
    centre = (p + Z95 * Z95 / (2 * trials)) / (1 + Z95 * Z95 / trials)
    half = (
        Z95
        * math.sqrt(p * (1 - p) / trials + Z95 * Z95 / (4 * trials * trials))
        / (1 + Z95 * Z95 / trials)
    )
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


@dataclass(frozen=True, slots=True)
class PairCounts:
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float | None:
        return _ratio(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> float | None:
        return _ratio(self.tp, self.tp + self.fn)

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or p + r == 0:
            return None
        return round(2 * p * r / (p + r), 3)

    def as_dict(self) -> dict[str, Any]:
        return {
            "true_positives": self.tp,
            "false_positives": self.fp,
            "false_negatives": self.fn,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }


def pair_counts(pairs: Iterable[tuple[Label, Decision]], kind: str | None = None) -> PairCounts:
    """Pairs over records labelled obvious or none; ``kind`` limits them to ways or nodes."""

    def keep(elements: Iterable[str]) -> set[str]:
        return {e for e in elements if kind is None or e.startswith(f"{kind}/")}

    tp = fp = fn = 0
    for label, decision in pairs:
        if label.correspondence not in (OBVIOUS, NONE):
            continue
        truth = keep(label.truth)
        predicted = keep(decision.elements)
        tp += len(truth & predicted)
        fp += len(predicted - truth)
        fn += len(truth - predicted)
    return PairCounts(tp, fp, fn)


def _bootstrap(pairs: Sequence[tuple[Label, Decision]]) -> dict[str, list[float] | None]:
    """Percentile intervals for pair precision, recall and F1, resampling records."""
    rows = [
        (len(lb.truth & d.elements), len(d.elements - lb.truth), len(lb.truth - d.elements))
        for lb, d in pairs
        if lb.correspondence in (OBVIOUS, NONE)
    ]
    if not rows:
        return {"precision": None, "recall": None, "f1": None}
    counts = np.array(rows, dtype=float)
    generator = np.random.default_rng(BOOTSTRAP_SEED)
    draws = generator.integers(0, len(counts), size=(BOOTSTRAP_SAMPLES, len(counts)))
    totals = counts[draws].sum(axis=1)
    tp, fp, fn = totals[:, 0], totals[:, 1], totals[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        precision = np.where(tp + fp > 0, tp / (tp + fp), np.nan)
        recall = np.where(tp + fn > 0, tp / (tp + fn), np.nan)
        f1 = np.where(precision + recall > 0, 2 * precision * recall / (precision + recall), np.nan)

    def interval(values: np.ndarray[Any, Any]) -> list[float] | None:
        finite = values[np.isfinite(values)]
        if not len(finite):
            return None
        return [
            round(float(np.quantile(finite, 0.025)), 3),
            round(float(np.quantile(finite, 0.975)), 3),
        ]

    return {"precision": interval(precision), "recall": interval(recall), "f1": interval(f1)}


def summarise(
    pairs: Sequence[tuple[Label, Decision]], *, intervals: bool = False
) -> dict[str, Any]:
    """Every metric for one set of (label, decision) pairs."""
    judged = [(lb, d) for lb, d in pairs if lb.correspondence != NOT_COMPARABLE]
    outcomes: dict[str, Counter[str]] = {label: Counter() for label in OUTCOMES}
    for label, decision in judged:
        outcomes[label.correspondence][outcome(label, decision)] += 1
    states = Counter(d.state for _l, d in judged)
    records = len(judged)
    matched = states[MATCHED]
    automatic = matched + states[UNMATCHED]
    obvious = outcomes[OBVIOUS]
    none = outcomes[NONE]
    ambiguous = outcomes[AMBIGUOUS]
    wrong = obvious["partial"] + obvious["wrong"] + none["false_match"]
    exact = obvious["exact"]
    counts = pair_counts(judged)
    result: dict[str, Any] = {
        "records": records,
        "labels": dict(sorted(Counter(lb.correspondence for lb, _d in judged).items())),
        "decisions": dict(sorted(states.items())),
        "outcomes": {k: dict(sorted(v.items())) for k, v in outcomes.items() if v},
        "pairs": counts.as_dict(),
        "pairs_by_element": {kind: pair_counts(judged, kind).as_dict() for kind in ("way", "node")},
        "records_level": {
            "exact_set_agreement": exact,
            "correct_decisions": exact
            + none["correctly_unmatched"]
            + ambiguous["correctly_abstained"],
            "automatic_decision_coverage": _ratio(automatic, records),
            "abstention_rate": _ratio(states[DECIDED_AMBIGUOUS], records),
            "exact_precision_among_matches": _ratio(exact, matched - ambiguous["matched"]),
            "exact_precision_among_matches_strict": _ratio(exact, matched),
            "false_match_rate": _ratio(wrong, matched - ambiguous["matched"]),
            "false_matches": wrong,
            "matched_where_labeller_abstained": ambiguous["matched"],
            "ambiguous_labels_abstained": _ratio(
                ambiguous["correctly_abstained"], sum(ambiguous.values())
            ),
        },
    }
    if intervals:
        result["intervals_95"] = {
            "what_they_are": (
                "Sampling uncertainty over these records, conditional on the frozen labels. "
                "Not whether the labels are right, not field truth, not other places."
            ),
            "exact_precision_among_matches": wilson(exact, matched - ambiguous["matched"]),
            "automatic_decision_coverage": wilson(automatic, records),
            "pairs_bootstrap_over_records": _bootstrap(judged),
        }
    return result


def by_group(
    pairs: Sequence[tuple[Label, Decision]],
    group: Callable[[Label, Decision], Iterable[str]],
) -> dict[str, dict[str, Any]]:
    """The same metrics for every group a record belongs to (a record may be in several)."""
    grouped: dict[str, list[tuple[Label, Decision]]] = defaultdict(list)
    for label, decision in pairs:
        for name in group(label, decision):
            grouped[name].append((label, decision))
    return {name: summarise(items) for name, items in sorted(grouped.items())}


def candidate_recall(
    labels: Mapping[int, Label], candidates: Mapping[int, CandidateSet]
) -> dict[str, Any]:
    """Whether every labelled element is among the candidates the contract generated."""
    wanted = found = 0
    missing: list[dict[str, Any]] = []
    for record_id, label in sorted(labels.items()):
        if label.correspondence != OBVIOUS:
            continue
        candidate = candidates[record_id]
        present = {f"way/{w.osm_id}" for w in candidate.ways} | {
            f"node/{n.osm_id}" for n in candidate.nodes
        }
        for element in sorted(label.truth):
            wanted += 1
            if element in present:
                found += 1
            else:
                missing.append({"activetransportid": record_id, "element": element})
    ways = [len(c.ways) for c in candidates.values()]
    nodes = [len(c.nodes) for c in candidates.values()]
    return {
        "labelled_elements": wanted,
        "among_candidates": found,
        "recall": _ratio(found, wanted),
        "missing": missing,
        "candidate_ways_per_record": distribution(ways),
        "candidate_nodes_per_record": distribution(nodes),
    }


def distribution(values: Sequence[int]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    array = np.asarray(values, dtype=float)
    return {
        "n": len(values),
        "p50": float(np.quantile(array, 0.5)),
        "p95": float(np.quantile(array, 0.95)),
        "max": int(array.max()),
        "mean": round(float(array.mean()), 2),
    }


def classes_of(records: Mapping[int, Record]) -> Callable[[Label, Decision], Iterable[str]]:
    return lambda label, _decision: records[label.activetransportid].classes


# ---------------------------------------------------------------------------
# Tuning, on the development set only
# ---------------------------------------------------------------------------

#: The thresholds tuned, and the values tried. Everything else in the policy is
#: fixed by the label definitions (end slop, kerb distance, "about 5 m") or by
#: geometry (alignment), and says why where it is defined.
TUNING_GRID: dict[str, tuple[float, ...]] = {
    "carry_m": (1.5, 2.0, 3.0, 4.0),
    "cover_min": (0.6, 0.75, 0.9),
    "contest_margin_m": (0.5, 1.0, 1.5),
    "contest_max": (0.2, 0.3, 0.5),
}
#: Declared before the grid was run.
SELECTION_RULE = (
    "Fewest development false matches (a partial or wrong set, a match where OSM has nothing, "
    "or a match where the labeller could not name the elements); then most exact sets; then "
    "most automatic decisions; then the most conservative values: smaller carry distance, "
    "larger coverage, larger contest margin, smaller contested share."
)


def tune(
    decide: Callable[[Any], Sequence[tuple[Label, Decision]]],
    base: Any,
) -> tuple[Any, list[dict[str, Any]]]:
    """Every grid point's development result, and the policy the selection rule picks.

    ``decide`` runs the matcher with a policy over the development records.
    """
    results: list[dict[str, Any]] = []
    for carry in TUNING_GRID["carry_m"]:
        for cover in TUNING_GRID["cover_min"]:
            for margin in TUNING_GRID["contest_margin_m"]:
                for most in TUNING_GRID["contest_max"]:
                    policy = base.with_(
                        carry_m=carry, cover_min=cover, contest_margin_m=margin, contest_max=most
                    )
                    summary = summarise(decide(policy))
                    level = summary["records_level"]
                    results.append(
                        {
                            "carry_m": carry,
                            "cover_min": cover,
                            "contest_margin_m": margin,
                            "contest_max": most,
                            "false_matches": level["false_matches"]
                            + level["matched_where_labeller_abstained"],
                            "exact_sets": level["exact_set_agreement"],
                            "automatic_decision_coverage": level["automatic_decision_coverage"],
                            "pairs": summary["pairs"],
                        }
                    )

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            row["false_matches"],
            -row["exact_sets"],
            -(row["automatic_decision_coverage"] or 0.0),
            row["carry_m"],
            -row["cover_min"],
            -row["contest_margin_m"],
            row["contest_max"],
        )

    best = min(results, key=key)
    chosen = base.with_(
        carry_m=best["carry_m"],
        cover_min=best["cover_min"],
        contest_margin_m=best["contest_margin_m"],
        contest_max=best["contest_max"],
    )
    return chosen, results


#: Declared with the frozen policy, before any held-out evaluation. Each turns
#: off one kind of signal, to show why the matcher beats a spatial baseline.
ABLATIONS: dict[str, dict[str, bool]] = {
    "geometry_only": {
        "use_class": False,
        "use_contest": False,
        "use_topology": False,
        "use_nodes": False,
    },
    "no_class_compatibility": {"use_class": False},
    "no_local_alignment": {"use_alignment": False},
    "no_ambiguity_margin": {"use_contest": False},
    "no_topology": {"use_topology": False},
    "no_node_representation": {"use_nodes": False},
}
