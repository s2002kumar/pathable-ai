"""PA-GEO-08's benchmark: tuning on development data, the held-out evaluation, the pilot.

One run does, in order:

1. **Development check.** Re-runs the declared tuning grid on the development
   labels (definitions version 2) and refuses to continue unless the declared
   selection rule still picks the frozen policy.
2. **Held-out evaluation.** Candidate recall; baselines A (nearest), B (median
   offset) and D (overlap); matcher v1's frozen policy, unchanged; matcher v2
   and every declared ablation — against the frozen blind labels, overall, per
   class and per stratum. The decisions are hashed, so a later run (to attach
   the failure analysis) can show it scored the same decisions.
3. **Analysis.** Every held-out record v2 got wrong or abstained on, repeat-label
   consistency, and v1 against v2 on the classes v2 was built for.
4. **Pilot dry run.** Matcher v2 over every eligible record: counts only, with
   no claim of correctness; and the evidence it would make available to a later
   reconciliation, which is research, not routing.
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
from pathable_api.geo.kitchener.benchmark_labels import AMBIGUOUS, NONE, OBVIOUS, Label
from pathable_api.geo.kitchener.conflation import (
    BASELINES,
    MATCHED,
    ConflationInputs,
    Decision,
    MatcherPolicy,
    Record,
    baseline,
    candidate_set,
    match,
)
from pathable_api.geo.kitchener.matcher_v2 import (
    CANDIDATE_CONTRACT_V2,
    FINE_SAMPLE_SPACING_M,
    NODE_RADIUS_M,
    WAY_RADIUS_M,
    CandidatesV2,
    MatcherV2Policy,
    candidates_v2,
    local_extent_m,
    match_v2,
)
from pathable_api.geo.kitchener.matcher_v2_holdout import repeat_subset
from pathable_api.geo.kitchener.matcher_v2_labels import parse_labels

BENCHMARK_VERSION = "kitchener-geo08-benchmark-v1"
FAILURE_ANALYSIS_VERSION = 1
CORRECT = frozenset({"exact", "correctly_unmatched", "correctly_abstained"})
#: The v1 baselines the card asks for; C (worst point) adds nothing B does not.
BASELINES_RUN = ("A_nearest_geometry", "B_median_offset", "D_overlap_2m")

#: The thresholds tuned, and the values tried. Everything else in the policy is
#: fixed and says why in :data:`matcher_v2.POLICY_PROVENANCE`.
TUNING_GRID: dict[str, tuple[float, ...]] = {
    "follow_max_deg": (10.0, 15.0, 20.0),
    "rival_extra_deg": (5.0, 10.0, 15.0),
    "carry_m": (2.0, 3.0),
    "cover_min": (0.6, 0.75),
}
#: Declared before the grid was run.
SELECTION_RULE = (
    "Lowest development cost, where a false attachment — a partial or wrong set, a match where "
    "OSM has nothing, or a match where the labeller could not name the elements — costs 2 and an "
    "abstention or a miss on an obvious correspondence costs 1; then most exact sets; then the "
    "most conservative values: smaller follow angle, larger rival allowance, smaller carry "
    "distance, larger coverage."
)

#: Declared with the frozen policy, before any held-out evaluation. Each undoes
#: one change from v1, to show what it is worth.
ABLATIONS: dict[str, dict[str, bool]] = {
    "crossings_never_carry_curb_cuts": {"use_crossing_carriers": False},
    "no_follow_rule": {"use_follow": False},
    "no_piece_rules": {"use_piece_rules": False},
    "no_kerb_topology": {"use_kerb_topology": False},
    "no_stair_rule": {"use_stair_rule": False},
    "no_structure_pieces": {"use_structure_pieces": False},
}


class BenchmarkV2Error(ValueError):
    """Inputs that would make the run not the benchmark it claims to be."""


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decisions_digest(decisions: Iterable[Decision]) -> str:
    ordered = sorted(decisions, key=lambda d: d.activetransportid)
    text = json.dumps([d.as_dict() for d in ordered], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Tuning, on the development set only
# ---------------------------------------------------------------------------


def cost(summary: Mapping[str, Any]) -> int:
    """The declared development cost: a false attachment counts twice an abstention."""
    level = summary["records_level"]
    obvious = summary["outcomes"].get(OBVIOUS, {})
    false = level["false_matches"] + level["matched_where_labeller_abstained"]
    return int(2 * false + obvious.get("abstained", 0) + obvious.get("missed", 0))


def tune(
    decide: Callable[[MatcherV2Policy], Sequence[tuple[Label, Decision]]],
    base: MatcherV2Policy,
) -> tuple[MatcherV2Policy, list[dict[str, Any]]]:
    """Every grid point's development result, and the policy the selection rule picks."""
    rows: list[dict[str, Any]] = []
    for follow in TUNING_GRID["follow_max_deg"]:
        for rival in TUNING_GRID["rival_extra_deg"]:
            for carry in TUNING_GRID["carry_m"]:
                for cover in TUNING_GRID["cover_min"]:
                    policy = base.with_(
                        follow_max_deg=follow,
                        rival_extra_deg=rival,
                        carry_m=carry,
                        cover_min=cover,
                    )
                    summary = bm.summarise(decide(policy))
                    level = summary["records_level"]
                    rows.append(
                        {
                            "follow_max_deg": follow,
                            "rival_extra_deg": rival,
                            "carry_m": carry,
                            "cover_min": cover,
                            "cost": cost(summary),
                            "false_attachments": level["false_matches"]
                            + level["matched_where_labeller_abstained"],
                            "exact_sets": level["exact_set_agreement"],
                            "abstention_rate": level["abstention_rate"],
                            "pairs": summary["pairs"],
                        }
                    )

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            row["cost"],
            -row["exact_sets"],
            row["follow_max_deg"],
            -row["rival_extra_deg"],
            row["carry_m"],
            -row["cover_min"],
        )

    best = min(rows, key=key)
    chosen = base.with_(**{name: best[name] for name in TUNING_GRID})
    return chosen, rows


def tuned(policy: MatcherV2Policy) -> dict[str, float]:
    return {name: float(getattr(policy, name)) for name in TUNING_GRID}


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class LabelSets:
    development: dict[int, Label]
    holdout: dict[int, Label]
    repeat: dict[int, Label]
    strata: dict[int, str]
    packs: dict[int, str]
    identity: dict[str, Any]


def load_label_sets(evidence: Path) -> LabelSets:
    """The committed label files, checked against the sample and guide they belong to."""
    files = {
        "development_labels": evidence / "kitchener-geo08-development-labels.json",
        "holdout_sample": evidence / "kitchener-geo08-holdout.geojson",
        "holdout_labels": evidence / "kitchener-geo08-holdout-labels.json",
        "repeat_labels": evidence / "kitchener-geo08-holdout-repeat-labels.json",
        "labelling_guide": evidence / "kitchener-geo08-labelling-guide.md",
    }
    missing = [str(p) for p in files.values() if not p.is_file()]
    if missing:
        raise BenchmarkV2Error(f"missing benchmark input: {', '.join(missing)}")
    documents = {
        name: json.loads(path.read_text("utf-8"))
        for name, path in files.items()
        if path.suffix in (".json", ".geojson")
    }
    identity = {name: {"file": p.name, "sha256": sha256_of(p)} for name, p in files.items()}
    for name in ("holdout_labels", "repeat_labels"):
        if documents[name]["holdout"]["sha256"] != identity["holdout_sample"]["sha256"]:
            raise BenchmarkV2Error(f"{name} label a different held-out sample.")
        if documents[name]["labelling_guide"]["sha256"] != identity["labelling_guide"]["sha256"]:
            raise BenchmarkV2Error(f"{name} were made under a different labelling guide.")
    sample = documents["holdout_sample"]
    holdout = parse_labels(documents["holdout_labels"])
    repeat = parse_labels(documents["repeat_labels"])
    ids = {int(f["properties"]["activetransportid"]) for f in sample["features"]}
    if set(holdout) != ids:
        raise BenchmarkV2Error("the held-out labels do not cover exactly the held-out sample.")
    if sorted(repeat) != sorted(repeat_subset(sample)):
        raise BenchmarkV2Error("the repeat labels do not cover exactly the repeat subset.")
    development = parse_labels(documents["development_labels"])
    if set(development) & set(holdout):
        raise BenchmarkV2Error("a development record is in the held-out sample.")
    return LabelSets(
        development=development,
        holdout=holdout,
        repeat=repeat,
        strata={
            int(f["properties"]["activetransportid"]): f["properties"]["stratum"]
            for f in sample["features"]
        },
        packs={
            int(r["activetransportid"]): r["pack"] for r in documents["holdout_labels"]["records"]
        },
        identity=identity,
    )


# ---------------------------------------------------------------------------
# Pieces of the report
# ---------------------------------------------------------------------------


def headline(summary: Mapping[str, Any]) -> dict[str, Any]:
    level = summary["records_level"]
    obvious = summary["outcomes"].get(OBVIOUS, {})
    return {
        "exact_sets": level["exact_set_agreement"],
        "false_attachments": level["false_matches"],
        "over_commitments_on_ambiguous_labels": level["matched_where_labeller_abstained"],
        "abstained_or_missed_on_obvious": obvious.get("abstained", 0) + obvious.get("missed", 0),
        "correct_decisions": level["correct_decisions"],
        "abstention_rate": level["abstention_rate"],
        "automatic_decision_coverage": level["automatic_decision_coverage"],
        "pair_precision": summary["pairs"]["precision"],
        "pair_recall": summary["pairs"]["recall"],
        "pair_f1": summary["pairs"]["f1"],
    }


def candidate_recall(
    labels: Mapping[int, Label], candidates: Mapping[int, CandidatesV2]
) -> dict[str, Any]:
    """Whether every element a label names is among v2's candidates for that record."""
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
    return {
        "what_it_is": (
            "Every element an obvious label names, checked against v2's candidates for the "
            "record. An element no labeller named cannot be missed, so this is recall of the "
            "labelled correspondence, not of every possible one."
        ),
        "labelled_elements": wanted,
        "among_candidates": found,
        "recall": bm._ratio(found, wanted),
        "missing": missing,
        "candidate_ways_per_record": bm.distribution([len(c.ways) for c in candidates.values()]),
        "candidate_nodes_per_record": bm.distribution([len(c.nodes) for c in candidates.values()]),
    }


def groups_of(
    records: Mapping[int, Record], strata: Mapping[int, str]
) -> Callable[[Label, Decision], Iterable[str]]:
    """The classes the card reports separately. A record may be in several."""

    def group(label: Label, _decision: Decision) -> Iterable[str]:
        record = records[label.activetransportid]
        stratum = strata.get(label.activetransportid, "")
        found = []
        if record.curb_cut:
            found.append("curb_cuts")
            if stratum.startswith("curb_cut_no_kerb"):
                found.append("curb_cuts_without_osm_kerb_node")
        if record.structure == "STAIRS":
            found.append("stairs")
            found.append(
                "stairs_explicit_osm_steps"
                if stratum == "stairs_explicit_steps"
                else "stairs_generic_footway_or_displaced_steps"
            )
        elif record.structure is not None:
            found.append("other_structures")
        if not record.curb_cut and record.length_m < 5.0:
            found.append("short_and_junction_pieces")
        return found or ["other"]

    return group


def failure_row(
    label: Label, decision: Decision, record: Record, stratum: str | None, pack: str | None
) -> dict[str, Any]:
    return {
        "activetransportid": record.activetransportid,
        "outcome": bm.outcome(label, decision),
        "stratum": stratum,
        "classes": list(record.classes),
        "family": record.family,
        "structure": record.structure,
        "length_m": round(record.length_m, 1),
        "labelled_by": pack,
        "label": label.as_dict(),
        "decision": decision.as_dict(),
    }


def v1_against_v2(
    v1: Sequence[tuple[Label, Decision]],
    v2: Sequence[tuple[Label, Decision]],
    group: Callable[[Label, Decision], Iterable[str]],
) -> dict[str, Any]:
    """Per class: v1 and v2 side by side, and the records one got right and the other not."""
    first = bm.by_group(v1, group)
    second = bm.by_group(v2, group)
    outcomes: dict[str, Counter[str]] = {}
    for (label, a), (_l, b) in zip(v1, v2, strict=True):
        was, now = bm.outcome(label, a), bm.outcome(label, b)
        if (was in CORRECT) == (now in CORRECT):
            continue
        change = "fixed_by_v2" if now in CORRECT else "broken_by_v2"
        for name in group(label, b):
            outcomes.setdefault(name, Counter())[change] += 1
    return {
        name: {
            "v1": headline(first[name]),
            "v2": headline(second[name]),
            "records_changed": dict(sorted(outcomes.get(name, Counter()).items())),
        }
        for name in sorted(second)
    }


def repeat_consistency(
    primary: Mapping[int, Label], repeat: Mapping[int, Label], decisions: Mapping[int, Decision]
) -> dict[str, Any]:
    """How often a second blind pass of the same procedure gave the same label."""
    ids = sorted(repeat)
    same = [i for i in ids if primary[i].correspondence == repeat[i].correspondence]
    both = [
        i
        for i in ids
        if primary[i].correspondence == OBVIOUS and repeat[i].correspondence == OBVIOUS
    ]
    same_set = [i for i in both if primary[i].osm == repeat[i].osm]
    return {
        "what_it_is": (
            "The same records labelled again by other AI instances of the same model from the same "
            "material: the consistency of this labelling procedure, not inter-rater reliability "
            "between independent people, and not accuracy."
        ),
        "records": len(ids),
        "same_correspondence": len(same),
        "correspondence_primary_vs_repeat": dict(
            sorted(
                Counter(
                    f"{primary[i].correspondence} / {repeat[i].correspondence}" for i in ids
                ).items()
            )
        ),
        "both_obvious": len(both),
        "both_obvious_same_osm_set": len(same_set),
        "disagreements": [
            {"primary": primary[i].as_dict(), "repeat": repeat[i].as_dict()}
            for i in ids
            if primary[i].correspondence != repeat[i].correspondence
            or primary[i].osm != repeat[i].osm
        ],
        "v2_scored_against_primary": headline(
            bm.summarise([(primary[i], decisions[i]) for i in ids])
        ),
        "v2_scored_against_repeat": headline(
            bm.summarise([(repeat[i], decisions[i]) for i in ids])
        ),
    }


def attach_causes(
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
    if causes.get("kitchener_geo08_failure_analysis_version") != FAILURE_ANALYSIS_VERSION:
        raise BenchmarkV2Error("not a PA-GEO-08 failure analysis of a known version.")
    if causes.get("decisions_sha256") != digest:
        raise BenchmarkV2Error(
            "the failure analysis was written for different decisions "
            f"({str(causes.get('decisions_sha256'))[:12]}), not these ({digest[:12]})."
        )
    categories: Mapping[str, str] = causes["categories"]
    found: Mapping[str, Mapping[str, str]] = causes["records"]
    for failure in failures:
        cause = found.get(str(failure["activetransportid"]))
        if cause is not None and cause["cause"] not in categories:
            raise BenchmarkV2Error(f"cause {cause['cause']!r} is not a defined category.")
        failure["cause"] = cause
    stale = sorted(set(found) - {str(f["activetransportid"]) for f in failures})
    if stale:
        raise BenchmarkV2Error(f"the failure analysis names records that did not fail: {stale}")
    return {
        "failures": len(failures),
        "by_outcome": dict(sorted(counts.items())),
        "analysed": sum(1 for f in failures if f.get("cause")),
        "not_analysed": sorted(f["activetransportid"] for f in failures if not f.get("cause")),
        "categories": dict(categories),
        "by_cause": dict(
            sorted(Counter(f["cause"]["cause"] for f in failures if f.get("cause")).items())
        ),
        "records": failures,
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
    """The report, its timings (volatile, kept apart) and v2's held-out decisions."""
    say = progress or (lambda _message: None)
    timings: dict[str, float] = {}
    records = inputs.by_id
    frozen = MatcherV2Policy()

    # 1. The development check.
    started = time.perf_counter()
    dev_ids = sorted(i for i in sets.development if i in records)
    dev_candidates = {i: candidates_v2(records[i], inputs.osm, frozen) for i in dev_ids}

    def decide_development(policy: MatcherV2Policy) -> list[tuple[Label, Decision]]:
        return [
            (
                sets.development[i],
                match_v2(dev_candidates[i], policy, inputs.osm, inputs.relationships),
            )
            for i in dev_ids
        ]

    chosen, grid = tune(decide_development, frozen)
    if tuned(chosen) != tuned(frozen):
        raise BenchmarkV2Error(
            f"the development grid now selects {tuned(chosen)}, not the frozen policy "
            f"{tuned(frozen)}: matcher v2 changed after it was frozen."
        )
    dev_pairs = decide_development(frozen)
    dev_v1 = [
        (
            sets.development[i],
            match(
                candidate_set(records[i], inputs.osm),
                MatcherPolicy(),
                inputs.osm,
                inputs.relationships,
            ),
        )
        for i in dev_ids
    ]
    development = {
        "records": len(dev_ids),
        "not_eligible": sorted(set(sets.development) - set(dev_ids)),
        "grid": {name: list(values) for name, values in TUNING_GRID.items()},
        "grid_points": len(grid),
        "selection_rule": SELECTION_RULE,
        "selected": tuned(chosen),
        "reproduces_the_frozen_policy": True,
        "cost_across_the_grid": dict(sorted(Counter(row["cost"] for row in grid).items())),
        "grid_results": grid,
        "matcher_v2": bm.summarise(dev_pairs),
        "matcher_v1": headline(bm.summarise(dev_v1)),
        "what_it_is": (
            "Where matcher v2 was designed and tuned, including the PA-GEO-05 held-out records "
            "whose failures shaped it. Not a result."
        ),
    }
    timings["development_check_s"] = round(time.perf_counter() - started, 2)
    say(f"development: grid reproduces the frozen policy {tuned(frozen)}")

    # 2. The held-out evaluation.
    ids = sorted(sets.holdout)
    started = time.perf_counter()
    candidates = {i: candidates_v2(records[i], inputs.osm, frozen) for i in ids}
    v1_candidates = {i: candidate_set(records[i], inputs.osm) for i in ids}
    timings["holdout_candidates_s"] = round(time.perf_counter() - started, 2)
    started = time.perf_counter()
    decisions = {i: match_v2(candidates[i], frozen, inputs.osm, inputs.relationships) for i in ids}
    timings["holdout_matching_s"] = round(time.perf_counter() - started, 2)
    pairs = [(sets.holdout[i], decisions[i]) for i in ids]
    digest = decisions_digest(decisions.values())
    group = groups_of(records, sets.strata)

    def by_stratum(label: Label, _decision: Decision) -> Iterable[str]:
        return (sets.strata[label.activetransportid],)

    def by_pack(label: Label, _decision: Decision) -> Iterable[str]:
        return (sets.packs[label.activetransportid],)

    v1_pairs = [
        (
            sets.holdout[i],
            match(v1_candidates[i], MatcherPolicy(), inputs.osm, inputs.relationships),
        )
        for i in ids
    ]
    matcher = bm.summarise(pairs, intervals=True)
    compared = {
        "baselines": {
            name: {
                "ranks_ways_by": BASELINES[name],
                "summary": headline(
                    bm.summarise([(sets.holdout[i], baseline(name, v1_candidates[i])) for i in ids])
                ),
            }
            for name in BASELINES_RUN
        },
        "matcher_v1_frozen": {
            "policy": MatcherPolicy().version,
            "summary": bm.summarise(v1_pairs, intervals=True),
        },
        "matcher_v2": headline(matcher),
    }
    ablations = {}
    for name, switches in ABLATIONS.items():
        policy = frozen.with_(**switches)
        decided = [
            (sets.holdout[i], match_v2(candidates[i], policy, inputs.osm, inputs.relationships))
            for i in ids
        ]
        summary = bm.summarise(decided)
        ablations[name] = {
            "switched_off": sorted(switches),
            "summary": headline(summary),
            "by_class": {k: headline(v) for k, v in bm.by_group(decided, group).items()},
        }
    say(f"holdout: {headline(matcher)}")

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
    rules = Counter(f"{d.rule} -> {bm.outcome(lb, d)}" for lb, d in pairs)
    extents = [e for d in decisions.values() if (e := local_extent_m(d)) is not None]
    holdout = {
        "records": len(ids),
        "decisions_sha256": digest,
        "labels": dict(sorted(Counter(lb.correspondence for lb in sets.holdout.values()).items())),
        "candidate_generation": candidate_recall(sets.holdout, candidates),
        "matcher_v2": matcher,
        "matcher_v2_by_class": bm.by_group(pairs, group),
        "matcher_v2_by_stratum": bm.by_group(pairs, by_stratum),
        "matcher_v2_by_labelling_pack": {
            k: headline(v) for k, v in bm.by_group(pairs, by_pack).items()
        },
        "matcher_v2_rules": dict(sorted(rules.items())),
        "compared": compared,
        "v1_against_v2_by_class": v1_against_v2(v1_pairs, pairs, group),
        "ablations": ablations,
        "local_scope": {
            "curb_cut_way_extent_m": bm.distribution(
                [
                    round(e)
                    for d in decisions.values()
                    if records[d.activetransportid].curb_cut
                    and (e := local_extent_m(d)) is not None
                ]
            ),
            "every_way_extent_m": bm.distribution([round(e) for e in extents]),
        },
        "failure_analysis": attach_causes(failures, failure_causes, digest),
        "repeat_labels": repeat_consistency(sets.holdout, sets.repeat, decisions),
    }
    report = {
        "benchmark_version": BENCHMARK_VERSION,
        "policy": frozen.as_dict(),
        "candidate_contract": {
            "version": CANDIDATE_CONTRACT_V2,
            "way_radius_m": WAY_RADIUS_M,
            "node_radius_m": NODE_RADIUS_M,
            "fine_sample_spacing_m": FINE_SAMPLE_SPACING_M,
            "fine_for": "curb cuts and records shorter than a junction's width",
        },
        "ablations_declared": {k: sorted(v) for k, v in ABLATIONS.items()},
        "labels": sets.identity,
        "development": development,
        "holdout": holdout,
    }
    return report, timings, decisions


# ---------------------------------------------------------------------------
# The pilot dry run
# ---------------------------------------------------------------------------


def _kerb_tagged(tags: Mapping[str, str]) -> bool:
    return "kerb" in tags or tags.get("barrier") == "kerb"


def run_pilot(
    inputs: ConflationInputs,
    *,
    check: Mapping[int, Decision] | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], dict[str, float]]:
    """Matcher v1 and v2 over every eligible record: counts and potential evidence only."""
    say = progress or (lambda _message: None)
    frozen = MatcherV2Policy()
    records = inputs.population.records
    timings: dict[str, float] = {}
    started = time.perf_counter()
    v2: dict[int, Decision] = {}
    v1: dict[int, Decision] = {}
    for count, record in enumerate(records, 1):
        v2[record.activetransportid] = match_v2(
            candidates_v2(record, inputs.osm, frozen), frozen, inputs.osm, inputs.relationships
        )
        v1[record.activetransportid] = match(
            candidate_set(record, inputs.osm), MatcherPolicy(), inputs.osm, inputs.relationships
        )
        if count % 2000 == 0:
            say(f"pilot: {count} of {len(records)} records decided")
    timings["pilot_v1_and_v2_s"] = round(time.perf_counter() - started, 2)
    disagreements = sorted(i for i, d in (check or {}).items() if v2[i].as_dict() != d.as_dict())
    if disagreements:
        raise BenchmarkV2Error(
            f"the pilot decided differently from the benchmark for {disagreements}"
        )
    by_id = {r.activetransportid: r for r in records}

    def tally(ids: Iterable[int]) -> dict[str, Any]:
        chosen = [v2[i] for i in ids]
        return {
            "records": len(chosen),
            "states": dict(sorted(Counter(d.state for d in chosen).items())),
            "rules": dict(sorted(Counter(d.rule for d in chosen).items())),
        }

    # PA-GEO-06's blocked curb cuts: v1 matched them to ways only, with no kerb node.
    blocked = [
        i
        for i, d in v1.items()
        if by_id[i].curb_cut
        and d.state == MATCHED
        and not any(t.element.startswith("node/") for t in d.targets)
    ]
    stairs = [i for i, r in by_id.items() if r.structure == "STAIRS"]
    short = [i for i, r in by_id.items() if not r.curb_cut and r.length_m < 5.0]
    curb_cuts = [i for i, r in by_id.items() if r.curb_cut]

    # Research only: what a later reconciliation could compare. Nothing is routed.
    new_ramps = []
    for i in curb_cuts:
        d = v2[i]
        if d.state != MATCHED or any(t.element.startswith("node/") for t in d.targets):
            continue
        ways = [int(t.element.split("/")[1]) for t in d.targets if t.element.startswith("way/")]
        if any(_kerb_tagged(inputs.osm.extract.ways[w].tags) for w in ways):
            continue
        new_ramps.append(i)
    generic_stairs = [
        i for i in stairs if v2[i].state == MATCHED and v2[i].representation == "generic_way"
    ]
    summary = {
        "what_it_is": (
            "Matcher v2 run once over every eligible record, with matcher v1 beside it for the "
            "same records. Counts, sizes and time only: nothing here says a decision is right. "
            "The held-out benchmark is the measure."
        ),
        "records": len(records),
        "decisions_sha256": decisions_digest(v2.values()),
        "agrees_with_the_benchmark_decisions": len(check or {}),
        "v2_states": dict(sorted(Counter(d.state for d in v2.values()).items())),
        "v1_states": dict(sorted(Counter(d.state for d in v1.values()).items())),
        "v2_rules": dict(sorted(Counter(d.rule for d in v2.values()).items())),
        "v2_relationships": dict(
            sorted(Counter(str(d.relationship) for d in v2.values() if d.state == MATCHED).items())
        ),
        "v2_representations": dict(
            sorted(Counter(d.representation for d in v2.values() if d.state == MATCHED).items())
        ),
        "curb_cuts": tally(curb_cuts),
        "curb_cuts_v1_matched_to_ways_only": {
            "what_it_is": (
                "The curb cuts PA-GEO-06 could not accept: matched by v1 to ways only, with no "
                "OSM kerb node. How v2 decides the same records."
            ),
            **tally(blocked),
        },
        "stairs": tally(stairs),
        "short_non_curb_pieces": tally(short),
        "potential_evidence": {
            "what_it_is": (
                "Research only. What a later, licensed reconciliation could compare: never routed, "
                "never called verified, and resting on correspondences the benchmark measured "
                "only on a sample."
            ),
            "curb_ramps_at_a_local_way_extent_where_osm_records_no_kerb": len(new_ramps),
            "city_stairs_on_an_osm_way_that_records_no_steps": len(generic_stairs),
            "curb_ramp_way_extent_m": bm.distribution(
                [round(e) for i in new_ramps if (e := local_extent_m(v2[i])) is not None]
            ),
        },
    }
    say(f"pilot: {summary['v2_states']}")
    return summary, timings


#: Labels outside obvious, ambiguous and none are not judged.
JUDGED = (OBVIOUS, AMBIGUOUS, NONE)
