"""PA-GEO-05's benchmark run: the development check, the held-out evaluation, the pilot.

One run does, in order:

1. **Development check.** Re-runs the tuning grid on the development labels
   and refuses to continue unless the declared selection rule still picks the
   frozen policy — so the policy evaluated is the one tuned, nothing later.
2. **Held-out evaluation.** Candidate recall, the four baselines, the frozen
   matcher and every declared ablation, against the frozen blind labels, per
   evidence class and per stratum. The decisions are hashed, so a later run
   (to add the failure analysis, say) can show it scored the same decisions.
3. **Analysis.** Every held-out record the matcher got wrong or abstained on;
   the repeat-label consistency; what the City's evidence and OSM's say about
   the same facility once matched.
4. **Pilot dry run.** The frozen matcher over every eligible record, written as
   the research artifact: counts, sizes and time, and no claim of correctness.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pathable_api.geo.kitchener import benchmark as bm
from pathable_api.geo.kitchener.benchmark_labels import OBVIOUS, Label, parse_labels
from pathable_api.geo.kitchener.canonical import comparisons, write_artifact
from pathable_api.geo.kitchener.conflation import (
    BASELINES,
    MATCHED,
    ConflationInputs,
    Decision,
    MatcherPolicy,
    Record,
    Target,
    baseline,
    candidate_set,
    match,
    node_kind,
)
from pathable_api.geo.kitchener.holdout import repeat_subset

#: Outcomes that are right; every other outcome is analysed as a failure.
CORRECT = frozenset({"exact", "correctly_unmatched", "correctly_abstained"})
FAILURE_ANALYSIS_VERSION = 1


class BenchmarkError(ValueError):
    """Inputs that would make the run not the benchmark it claims to be."""


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decisions_digest(decisions: Iterable[Decision]) -> str:
    """One hash over every decision, in record order: what a run decided."""
    ordered = sorted(decisions, key=lambda d: d.activetransportid)
    text = json.dumps([d.as_dict() for d in ordered], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The frozen labels
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class LabelSets:
    development: dict[int, Label]
    holdout: dict[int, Label]
    repeat: dict[int, Label]
    #: record id → its holdout stratum, and the pack that labelled it.
    strata: dict[int, str]
    packs: dict[int, str]
    identity: dict[str, Any]


def load_label_sets(evidence: Path) -> LabelSets:
    """The committed label files, checked against the sample they label."""
    files = {
        "development_labels": evidence / "kitchener-geo05-development-labels.json",
        "holdout_sample": evidence / "kitchener-geo05-holdout.geojson",
        "holdout_labels": evidence / "kitchener-geo05-holdout-labels.json",
        "repeat_labels": evidence / "kitchener-geo05-holdout-repeat-labels.json",
        "labelling_guide": evidence / "kitchener-geo05-labelling-guide.md",
    }
    missing = [str(p) for p in files.values() if not p.is_file()]
    if missing:
        raise BenchmarkError(f"missing benchmark input: {', '.join(missing)}")
    documents = {
        name: json.loads(path.read_text("utf-8"))
        for name, path in files.items()
        if path.suffix in (".json", ".geojson")
    }
    identity = {name: {"file": p.name, "sha256": sha256_of(p)} for name, p in files.items()}
    holdout_document = documents["holdout_sample"]
    labels = documents["holdout_labels"]
    for name in ("holdout_labels", "repeat_labels"):
        recorded = documents[name]["holdout"]["sha256"]
        if recorded != identity["holdout_sample"]["sha256"]:
            raise BenchmarkError(f"{name} label a different holdout sample ({recorded[:12]}).")
        if documents[name]["labelling_guide"]["sha256"] != identity["labelling_guide"]["sha256"]:
            raise BenchmarkError(f"{name} were made under a different labelling guide.")
    holdout = parse_labels(labels)
    repeat = parse_labels(documents["repeat_labels"])
    sample_ids = {f["properties"]["activetransportid"] for f in holdout_document["features"]}
    if set(holdout) != sample_ids:
        raise BenchmarkError("the holdout labels do not cover exactly the holdout sample.")
    if sorted(repeat) != sorted(repeat_subset(holdout_document)):
        raise BenchmarkError("the repeat labels do not cover exactly the repeat subset.")
    development = parse_labels(documents["development_labels"])
    if set(development) & set(holdout):
        raise BenchmarkError("a development record is in the holdout.")
    return LabelSets(
        development=development,
        holdout=holdout,
        repeat=repeat,
        strata={
            f["properties"]["activetransportid"]: f["properties"]["stratum"]
            for f in holdout_document["features"]
        },
        packs={r["activetransportid"]: r["pack"] for r in labels["records"]},
        identity=identity,
    )


# ---------------------------------------------------------------------------
# Pieces of the report
# ---------------------------------------------------------------------------


def _tuned(policy: MatcherPolicy) -> dict[str, float]:
    return {name: float(getattr(policy, name)) for name in bm.TUNING_GRID}


def _headline(summary: Mapping[str, Any]) -> dict[str, Any]:
    level = summary["records_level"]
    return {
        "exact_sets": level["exact_set_agreement"],
        "false_matches": level["false_matches"],
        "matched_where_labeller_abstained": level["matched_where_labeller_abstained"],
        "abstention_rate": level["abstention_rate"],
        "pair_precision": summary["pairs"]["precision"],
        "pair_recall": summary["pairs"]["recall"],
        "pair_f1": summary["pairs"]["f1"],
    }


def _delta(base: Mapping[str, Any], other: Mapping[str, Any]) -> dict[str, Any]:
    first, second = _headline(base), _headline(other)
    return {
        key: None
        if first[key] is None or second[key] is None
        else round(second[key] - first[key], 3)
        for key in first
    }


def failure_row(
    label: Label,
    decision: Decision,
    record: Record,
    stratum: str | None,
    pack: str | None,
) -> dict[str, Any]:
    return {
        "activetransportid": record.activetransportid,
        "outcome": bm.outcome(label, decision),
        "stratum": stratum,
        "classes": list(record.classes),
        "family": record.family,
        "length_m": round(record.length_m, 1),
        "labelled_by": pack,
        "label": label.as_dict(),
        "decision": decision.as_dict(),
    }


def _relationship_agreement(pairs: Sequence[tuple[Label, Decision]]) -> dict[str, Any]:
    exact = [(lb, d) for lb, d in pairs if bm.outcome(lb, d) == "exact"]
    agree = sum(1 for lb, d in exact if lb.relationship == d.relationship)
    confusion = Counter(f"{lb.relationship} -> {d.relationship}" for lb, d in exact)
    return {
        "exact_matches": len(exact),
        "same_relationship": agree,
        "labelled_vs_decided": dict(sorted(confusion.items())),
    }


def repeat_consistency(
    primary: Mapping[int, Label],
    repeat: Mapping[int, Label],
    decisions: Mapping[int, Decision],
) -> dict[str, Any]:
    """How often a second pass of the same procedure gave the same label."""
    ids = sorted(repeat)
    same_class = [i for i in ids if primary[i].correspondence == repeat[i].correspondence]
    both_obvious = [
        i
        for i in ids
        if primary[i].correspondence == OBVIOUS and repeat[i].correspondence == OBVIOUS
    ]
    same_set = [i for i in both_obvious if primary[i].osm == repeat[i].osm]
    confusion = Counter(f"{primary[i].correspondence} / {repeat[i].correspondence}" for i in ids)
    by_primary = [(primary[i], decisions[i]) for i in ids]
    by_repeat = [(repeat[i], decisions[i]) for i in ids]
    return {
        "what_it_is": (
            "The same records labelled again by other AI instances of the same model from the same "
            "material. Agreement is the consistency of this labelling procedure, not inter-rater "
            "reliability between independent people, and not accuracy."
        ),
        "records": len(ids),
        "same_correspondence": len(same_class),
        "correspondence_primary_vs_repeat": dict(sorted(confusion.items())),
        "both_obvious": len(both_obvious),
        "both_obvious_same_osm_set": len(same_set),
        "both_obvious_same_relationship": sum(
            1 for i in same_set if primary[i].relationship == repeat[i].relationship
        ),
        "disagreements": [
            {"primary": primary[i].as_dict(), "repeat": repeat[i].as_dict()}
            for i in ids
            if primary[i].correspondence != repeat[i].correspondence
            or primary[i].osm != repeat[i].osm
        ],
        "matcher_scored_against_primary": _headline(bm.summarise(by_primary)),
        "matcher_scored_against_repeat": _headline(bm.summarise(by_repeat)),
    }


def _label_decision(label: Label, index: Any) -> Decision:
    """The labelled correspondence as a decision, to compare attributes without matching error."""
    targets = []
    for element in sorted(label.truth):
        kind, _, number = element.partition("/")
        role = "carrier"
        if kind == "node":
            role = node_kind(index.extract.nodes[int(number)].tags) or "node"
        targets.append(Target(element, role))
    return Decision(label.activetransportid, MATCHED, "label", tuple(targets), None, "", {})


def evidence_after_matching(
    pairs: Sequence[tuple[Label, Decision]],
    records: Mapping[int, Record],
    inputs: ConflationInputs,
) -> dict[str, Any]:
    """What the City asserts beside what OSM says, per attribute, once matched.

    Counted twice: through the matcher's decisions (what an automatic pipeline
    would see), and through the labelled correspondence where the label is
    obvious (the same comparison with no matching error). Nothing is resolved.
    """
    by_matcher: dict[str, Counter[str]] = {}
    by_matcher_exact: dict[str, Counter[str]] = {}
    by_label: dict[str, Counter[str]] = {}
    for label, decision in pairs:
        record = records[label.activetransportid]
        exact = bm.outcome(label, decision) == "exact"
        for row in comparisons(record, decision, inputs.osm):
            by_matcher.setdefault(row["attribute"], Counter())[row["comparison"]] += 1
            if exact:
                by_matcher_exact.setdefault(row["attribute"], Counter())[row["comparison"]] += 1
        if label.correspondence == OBVIOUS:
            for row in comparisons(record, _label_decision(label, inputs.osm), inputs.osm):
                by_label.setdefault(row["attribute"], Counter())[row["comparison"]] += 1

    def ordered(table: Mapping[str, Counter[str]]) -> dict[str, dict[str, int]]:
        return {k: dict(sorted(v.items())) for k, v in sorted(table.items())}

    return {
        "what_it_is": (
            "The City's assertion beside OSM's on the matched elements, counted over held-out "
            "records. 'consistent' for a curb cut means OSM's kerb value agrees with a curb cut "
            "down to street level; it never means the City stated a kerb height. Kept apart, "
            "never merged or resolved: reconciliation is PA-GEO-06's question."
        ),
        "through_matcher_decisions": ordered(by_matcher),
        "through_matcher_exact_matches_only": ordered(by_matcher_exact),
        "through_labelled_correspondence": ordered(by_label),
    }


def _local_scope(
    decisions: Iterable[Decision], records: Mapping[int, Record], index: Any
) -> dict[str, Any]:
    """Whether a matched curb cut ever claims a whole long way."""
    spans: list[float] = []
    whole = []
    for decision in decisions:
        record = records[decision.activetransportid]
        if decision.state != MATCHED or not record.curb_cut:
            continue
        for target in decision.targets:
            if not target.element.startswith("way/") or target.from_m is None:
                continue
            way_length = index.lines[int(target.element.split("/")[1])].length
            span = float(target.to_m or 0.0) - float(target.from_m)
            spans.append(span)
            if way_length > 20.0 and span >= 0.9 * way_length:
                whole.append(
                    {"activetransportid": decision.activetransportid, "way": target.element}
                )
    return {
        "curb_cut_way_targets": len(spans),
        "span_m": bm.distribution([round(s) for s in spans]) if spans else {"n": 0},
        "claiming_90pct_of_a_way_over_20m": len(whole),
        "examples": whole[:10],
    }


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def run_benchmark(
    inputs: ConflationInputs,
    sets: LabelSets,
    *,
    failure_causes: Mapping[str, Any] | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], dict[str, float], dict[int, Decision]]:
    """The report, its timings (volatile, kept apart) and the held-out decisions."""
    say = progress or (lambda _message: None)
    timings: dict[str, float] = {}
    records = inputs.by_id
    frozen = MatcherPolicy()

    # 1. The development check.
    started = time.perf_counter()
    dev_ids = sorted(sets.development)
    dev_candidates = {i: candidate_set(records[i], inputs.osm) for i in dev_ids}

    def decide_development(policy: MatcherPolicy) -> list[tuple[Label, Decision]]:
        return [
            (
                sets.development[i],
                match(dev_candidates[i], policy, inputs.osm, inputs.relationships),
            )
            for i in dev_ids
        ]

    chosen, grid = bm.tune(decide_development, frozen)
    if _tuned(chosen) != _tuned(frozen):
        raise BenchmarkError(
            f"the development grid now selects {_tuned(chosen)}, not the frozen policy "
            f"{_tuned(frozen)}: the matcher changed after it was frozen."
        )
    dev_pairs = decide_development(frozen)
    dev_summary = bm.summarise(dev_pairs)
    development = {
        "records": len(dev_ids),
        "grid": {name: list(values) for name, values in bm.TUNING_GRID.items()},
        "grid_points": len(grid),
        "selection_rule": bm.SELECTION_RULE,
        "selected": _tuned(chosen),
        "reproduces_the_frozen_policy": True,
        "false_matches_across_the_grid": dict(
            sorted(Counter(row["false_matches"] for row in grid).items())
        ),
        "matcher": dev_summary,
        "baselines": {
            name: _headline(
                bm.summarise(
                    [(sets.development[i], baseline(name, dev_candidates[i])) for i in dev_ids]
                )
            )
            for name in BASELINES
        },
        "remaining_errors": [
            failure_row(lb, d, records[lb.activetransportid], None, None)
            for lb, d in dev_pairs
            if bm.outcome(lb, d) not in CORRECT
        ],
    }
    timings["development_check_s"] = round(time.perf_counter() - started, 2)
    say(f"development: grid reproduces the frozen policy; {dev_summary['records_level']}")

    # 2. The held-out evaluation.
    ids = sorted(sets.holdout)
    started = time.perf_counter()
    candidates = {i: candidate_set(records[i], inputs.osm) for i in ids}
    timings["holdout_candidates_s"] = round(time.perf_counter() - started, 2)
    started = time.perf_counter()
    decisions = {i: match(candidates[i], frozen, inputs.osm, inputs.relationships) for i in ids}
    timings["holdout_matching_s"] = round(time.perf_counter() - started, 2)
    pairs = [(sets.holdout[i], decisions[i]) for i in ids]
    digest = decisions_digest(decisions.values())

    def by_class(label: Label, _decision: Decision) -> Iterable[str]:
        return records[label.activetransportid].classes

    def by_stratum(label: Label, _decision: Decision) -> Iterable[str]:
        return (sets.strata[label.activetransportid],)

    def by_pack(label: Label, _decision: Decision) -> Iterable[str]:
        return (sets.packs[label.activetransportid],)

    matcher = bm.summarise(pairs, intervals=True)
    baselines = {}
    for name in BASELINES:
        decided = [(sets.holdout[i], baseline(name, candidates[i])) for i in ids]
        baselines[name] = {
            "ranks_ways_by": BASELINES[name],
            "summary": bm.summarise(decided, intervals=True),
            "by_class": bm.by_group(decided, by_class),
        }
    ablations = {}
    for name, switches in bm.ABLATIONS.items():
        policy = frozen.with_(**switches)
        decided = [
            (sets.holdout[i], match(candidates[i], policy, inputs.osm, inputs.relationships))
            for i in ids
        ]
        summary = bm.summarise(decided)
        ablations[name] = {
            "switched_off": sorted(switches),
            "summary": summary,
            "change_from_frozen": _delta(matcher, summary),
            "by_class": {k: _headline(v) for k, v in bm.by_group(decided, by_class).items()},
        }
    say(f"holdout: {_headline(matcher)}")

    failures = [
        failure_row(
            lb,
            d,
            records[lb.activetransportid],
            sets.strata[lb.activetransportid],
            sets.packs[lb.activetransportid],
        )
        for lb, d in pairs
        if bm.outcome(lb, d) not in CORRECT
    ]
    analysis = _attach_causes(failures, failure_causes, digest)

    rules = Counter(f"{d.rule} -> {bm.outcome(lb, d)}" for lb, d in pairs)
    holdout = {
        "records": len(ids),
        "decisions_sha256": digest,
        "labels": dict(sorted(Counter(lb.correspondence for lb in sets.holdout.values()).items())),
        "candidate_generation": bm.candidate_recall(sets.holdout, candidates),
        "matcher": matcher,
        "matcher_by_class": bm.by_group(pairs, by_class),
        "matcher_by_stratum": bm.by_group(pairs, by_stratum),
        "matcher_by_labelling_pack": {
            k: _headline(v) for k, v in bm.by_group(pairs, by_pack).items()
        },
        "matcher_rules": dict(sorted(rules.items())),
        "relationship": _relationship_agreement(pairs),
        "baselines": baselines,
        "ablations": ablations,
        "failure_analysis": analysis,
        "repeat_labels": repeat_consistency(sets.holdout, sets.repeat, decisions),
        "evidence_after_matching": evidence_after_matching(pairs, records, inputs),
    }
    report = {
        "benchmark_version": bm.BENCHMARK_VERSION,
        "policy": frozen.as_dict(),
        "ablations_declared": {k: sorted(v) for k, v in bm.ABLATIONS.items()},
        "labels": sets.identity,
        "development": development,
        "holdout": holdout,
    }
    return report, timings, decisions


def _attach_causes(
    failures: list[dict[str, Any]], causes: Mapping[str, Any] | None, digest: str
) -> dict[str, Any]:
    """Every failure, with the cause found on inspection where one has been recorded."""
    counts = Counter(f["outcome"] for f in failures)
    if causes is None:
        return {
            "failures": len(failures),
            "by_outcome": dict(sorted(counts.items())),
            "analysed": 0,
            "records": failures,
        }
    if causes.get("kitchener_geo05_failure_analysis_version") != FAILURE_ANALYSIS_VERSION:
        raise BenchmarkError("not a failure analysis of a known version.")
    if causes.get("decisions_sha256") != digest:
        raise BenchmarkError(
            "the failure analysis was written for different decisions "
            f"({str(causes.get('decisions_sha256'))[:12]}), not these ({digest[:12]})."
        )
    categories: Mapping[str, str] = causes["categories"]
    found: Mapping[str, Mapping[str, str]] = causes["records"]
    for failure in failures:
        cause = found.get(str(failure["activetransportid"]))
        if cause is not None and cause["cause"] not in categories:
            raise BenchmarkError(f"cause {cause['cause']!r} is not a defined category.")
        failure["cause"] = cause
    unexplained = sorted(f["activetransportid"] for f in failures if f.get("cause") is None)
    stale = sorted(set(found) - {str(f["activetransportid"]) for f in failures})
    if stale:
        raise BenchmarkError(f"the failure analysis names records that did not fail: {stale}")
    return {
        "failures": len(failures),
        "by_outcome": dict(sorted(counts.items())),
        "analysed": len(failures) - len(unexplained),
        "not_analysed": unexplained,
        "categories": dict(categories),
        "by_cause": dict(
            sorted(Counter(f["cause"]["cause"] for f in failures if f.get("cause")).items())
        ),
        "by_cause_and_outcome": dict(
            sorted(
                Counter(
                    f"{f['cause']['cause']} / {f['outcome']}" for f in failures if f.get("cause")
                ).items()
            )
        ),
        "records": failures,
    }


def run_pilot(
    inputs: ConflationInputs,
    folder: Path,
    *,
    check: Mapping[int, Decision] | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], dict[str, float]]:
    """The frozen matcher over every eligible record, written as the research artifact.

    Candidate sets are made and dropped one record at a time. ``check`` holds
    decisions made separately for some records; the pilot must agree with them.
    """
    say = progress or (lambda _message: None)
    frozen = MatcherPolicy()
    records = inputs.population.records
    timings: dict[str, float] = {}
    decisions: dict[int, Decision] = {}
    ways: list[int] = []
    nodes: list[int] = []
    started = time.perf_counter()
    for count, record in enumerate(records, 1):
        candidates = candidate_set(record, inputs.osm)
        ways.append(len(candidates.ways))
        nodes.append(len(candidates.nodes))
        decisions[record.activetransportid] = match(
            candidates, frozen, inputs.osm, inputs.relationships
        )
        if count % 2000 == 0:
            say(f"pilot: {count} of {len(records)} records decided")
    timings["pilot_candidates_and_matching_s"] = round(time.perf_counter() - started, 2)
    disagreements = sorted(
        i for i, d in (check or {}).items() if decisions[i].as_dict() != d.as_dict()
    )
    if disagreements:
        raise BenchmarkError(
            f"the pilot decided differently from the benchmark for {disagreements}"
        )
    by_id = {r.activetransportid: r for r in records}
    started = time.perf_counter()
    artifact = write_artifact(
        folder,
        records,
        decisions,
        inputs.osm,
        str(inputs.identity["kitchener"]["snapshot_id"]),
        frozen.version,
    )
    timings["pilot_artifact_write_s"] = round(time.perf_counter() - started, 2)
    states = Counter(d.state for d in decisions.values())
    by_class = Counter(
        f"{cls} / {d.state}"
        for d in decisions.values()
        for cls in by_id[d.activetransportid].classes
    )
    summary = {
        "what_it_is": (
            "The frozen matcher run once over every eligible record. Counts, size and time only: "
            "nothing here says the decisions are right. The held-out benchmark is the measure."
        ),
        "records": len(records),
        "decisions_sha256": decisions_digest(decisions.values()),
        "agrees_with_the_benchmark_decisions": len(check or {}),
        "states": dict(sorted(states.items())),
        "rules": dict(sorted(Counter(d.rule for d in decisions.values()).items())),
        "states_by_class": dict(sorted(by_class.items())),
        "relationships": dict(
            sorted(
                Counter(
                    str(d.relationship) for d in decisions.values() if d.state == MATCHED
                ).items()
            )
        ),
        "representations": dict(
            sorted(
                Counter(d.representation for d in decisions.values() if d.state == MATCHED).items()
            )
        ),
        "candidate_ways_per_record": bm.distribution(ways),
        "candidate_nodes_per_record": bm.distribution(nodes),
        "local_scope": _local_scope(decisions.values(), by_id, inputs.osm),
        "artifact": artifact,
        "artifact_bytes": sum(f["bytes"] for f in artifact["files"].values()),
    }
    say(f"pilot: {dict(states)}")
    return summary, timings
