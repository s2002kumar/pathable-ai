"""Research reconciliation of matcher-v2 curb-ramp correspondences at a local way extent (PA-GEO-09).

PA-GEO-06 reconciled a City of Kitchener curb cut only at the OSM kerb node the
matcher named, and excluded 1,152 curb cuts that have no kerb node within 2 m.
PA-GEO-08's matcher v2 gives most of those a *local* correspondence instead:
the metres of the way or ways the City's piece follows, with no kerb node and
no kerb tag anywhere in the set. This module holds those correspondences the
way PA-GEO-06 holds everything else — the City's assertion exactly as
published, the matcher's decision exactly as made, every exclusion with its
reason, and ``not_routing_eligible`` on every row — and extends the model by
exactly one thing: a curb ramp may now sit at a local way extent, as a
**candidate** whose physical location is the matcher's, never OSM's.

What a row never says:

- that the City's ramp is real, or where along the extent it is beyond the
  matcher's sampled metres;
- that an element the matcher omitted is absent (the set is possibly
  incomplete, as PA-GEO-08 §11 requires);
- anything about routing. Whether the extent can reach the one place the
  router charges a kerb is a separate question (:mod:`curb_ramp_shadow`).

Bound to PA-GEO-08's committed evidence: the pilot decisions are re-made here
and refused unless their digest is the one that evidence records.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pathable_api.geo.kitchener.assertions import (
    NOT_ROUTING_ELIGIBLE,
    Assertion,
    Blocker,
    Topic,
)
from pathable_api.geo.kitchener.conflation import (
    AMBIGUOUS,
    MATCHED,
    UNMATCHED,
    ConflationInputs,
    Decision,
    MatcherPolicy,
    Record,
    candidate_set,
    match,
)
from pathable_api.geo.kitchener.matcher_v2 import (
    MATCHER_V2_VERSION,
    MatcherV2Policy,
    candidates_v2,
    match_v2,
)
from pathable_api.geo.kitchener.matcher_v2_benchmark import decisions_digest
from pathable_api.geo.kitchener.reconciliation import CityFields, city_assertion
from pathable_api.geo.overture.evidence import content_sha256, write_json

RECONCILIATION_VERSION = "kitchener-geo09-curb-ramp-reconciliation-v1"
ARTIFACT_VERSION = "kitchener-geo09-artifact-v1"
#: The only matcher whose curb-ramp correspondences this card accepts.
ACCEPTED_MATCHER = MATCHER_V2_VERSION
#: PA-GEO-08's committed evidence, which binds the pilot decisions by hash.
GEO08_EVIDENCE = "kitchener-geo08-matcher-v2.json"
#: PA-GEO-08 §11: a City record longer than this carrying CURBCUT = Y locates
#: no ramp — the City does not say where along it the ramp is.
MAX_RECORD_LENGTH_M = 20.0

#: The matcher-v2 rules a curb cut without a kerb node can end in.
WAYS_FOLLOWED = "curb_cut_ways_followed"
AT_JUNCTION = "curb_cut_at_junction"
NO_COUNTERPART = "curb_cut_no_counterpart"
#: Ambiguous *between* kerb nodes: those records have a kerb node, so they are
#: outside this card's class and are only counted.
KERB_NODES_UNDECIDED = "curb_cut_kerb_nodes_undecided"


class CurbRampError(RuntimeError):
    """The inputs are not the ones PA-GEO-08's committed evidence describes."""


class Stage(StrEnum):
    """What becomes of each correspondence before any routing question is asked."""

    #: A matched set of way extents, possibly incomplete, under 20 m: the
    #: routing mapping may look at it.
    CANDIDATE = "candidate_for_routing_mapping"
    #: Matcher v2 abstained: a piece at a junction it could not settle.
    ABSTAINED = "excluded_matcher_abstention"
    #: Matcher v2 found no counterpart.
    NO_COUNTERPART = "excluded_no_counterpart"
    #: The City record is longer than 20 m: it locates no ramp.
    OVER_20M = "excluded_record_over_20m"
    #: A named way carries a kerb tag: OSM already states a kerb fact there.
    OSM_WAY_KERB = "excluded_osm_way_kerb_tag"


class Completeness(StrEnum):
    #: PA-GEO-08 §11: 11 held-out sets missed the crossing the piece runs onto,
    #: so every set is treated as possibly incomplete and nothing is inferred
    #: from an element it omits.
    POSSIBLY_INCOMPLETE = "possibly_incomplete_set"
    ABSTAINED = "abstained"
    NONE = "no_counterpart"


#: PA-GEO-09's own blocker, beside PA-GEO-06's three: the correspondence set
#: names what the matcher found, not everything there is.
BLOCKED_BY_COMPLETENESS = "blocked_by_correspondence_completeness"


@dataclass(frozen=True, slots=True)
class WayExtent:
    """One way the matcher named, with the metres of it the City's piece covers, as frozen."""

    way_id: int
    from_m: float
    to_m: float
    osm_version: int | None
    osm_timestamp: str | None
    highway: str | None
    footway: str | None
    crossing: str | None
    kerb_tagged: bool

    @property
    def element(self) -> str:
        return f"way/{self.way_id}"

    @property
    def length_m(self) -> float:
        return self.to_m - self.from_m


@dataclass(frozen=True, slots=True)
class CurbRampCorrespondence:
    """One City curb cut without an OSM kerb node, as matcher v2 decided it."""

    record_id: int
    record_length_m: float
    #: The City's CURBCUT assertion, exactly as PA-GEO-06 reads it.
    city: Assertion
    matcher_version: str
    state: str
    rule: str
    relationship: str | None
    representation: str
    extents: tuple[WayExtent, ...]
    #: Kerb nodes within 2 m, from the decision's signals: empty by the rule
    #: that made it, and kept so a reader can see that it is.
    kerb_nodes_within_2m: tuple[str, ...]
    #: Among the 1,152 curb cuts PA-GEO-06 excluded as way-level only.
    in_geo06_blocked_set: bool
    completeness: Completeness
    stage: Stage

    @property
    def routing_eligibility(self) -> str:
        return NOT_ROUTING_ELIGIBLE

    @property
    def blockers(self) -> tuple[str, ...]:
        """PA-GEO-06's gates, the completeness gate, and this row's own exclusion."""
        found = {
            str(Blocker.ROUTING_POLICY),
            str(Blocker.LICENSING),
            str(Blocker.VALIDATION),
            BLOCKED_BY_COMPLETENESS,
        }
        if self.stage is not Stage.CANDIDATE:
            found.add(str(self.stage))
        return tuple(sorted(found))

    @property
    def reconciliation_state(self) -> str:
        if self.stage is Stage.CANDIDATE:
            return "source_only_kitchener_at_local_way_extent"
        return "not_reconciled"

    def as_row(self) -> dict[str, Any]:
        return {
            "reconciliation_id": f"curb_ramp/kitchener/{self.record_id}",
            "record_id": self.record_id,
            "record_length_m": round(self.record_length_m, 2),
            "city_assertion": asdict(self.city),
            "correspondence": {
                "matcher": self.matcher_version,
                "state": self.state,
                "rule": self.rule,
                "relationship": self.relationship,
                "representation": self.representation,
                "targets": [
                    {
                        "element": e.element,
                        "from_m": round(e.from_m, 2),
                        "to_m": round(e.to_m, 2),
                        "osm_version": e.osm_version,
                        "osm_timestamp": e.osm_timestamp,
                        "highway": e.highway,
                        "footway": e.footway,
                        "crossing": e.crossing,
                        "kerb_tagged": e.kerb_tagged,
                    }
                    for e in self.extents
                ],
                "kerb_nodes_within_2m": list(self.kerb_nodes_within_2m),
                "completeness": str(self.completeness),
            },
            "osm_kerb_assertion": None,
            "osm_kerb_state": "no kerb node within 2 m and no kerb tag on a named way",
            "in_geo06_blocked_set": self.in_geo06_blocked_set,
            "reconciliation_state": self.reconciliation_state,
            "stage": str(self.stage),
            "routing_eligibility": self.routing_eligibility,
            "blockers": list(self.blockers),
        }


# ---------------------------------------------------------------------------
# Binding to PA-GEO-08's committed evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Geo08Binding:
    evidence_path: Path
    content_sha256: str
    pilot_decisions_sha256: str
    pilot_records: int
    matcher_version: str
    snapshot_id: str
    extract_sha256: str
    potential_curb_ramps: int
    over_20m: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "file": self.evidence_path.name,
            "content_sha256": self.content_sha256,
            "pilot_decisions_sha256": self.pilot_decisions_sha256,
            "pilot_records": self.pilot_records,
            "matcher_version": self.matcher_version,
            "snapshot_id": self.snapshot_id,
            "extract_sha256": self.extract_sha256,
            "potential_curb_ramps_at_a_way_extent": self.potential_curb_ramps,
            "curb_ramps_whose_record_spans_over_20m": self.over_20m,
        }


def bind_geo08(evidence_dir: Path) -> Geo08Binding:
    """PA-GEO-08's committed evidence: what the pilot decisions must reproduce."""
    path = evidence_dir / GEO08_EVIDENCE
    try:
        document = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as error:
        msg = f"PA-GEO-08's evidence could not be read from {path}: {error}"
        raise CurbRampError(msg) from error
    try:
        pilot = document["full_pilot_dry_run"]
        policy = document["policy"]["version"]
        potential = pilot["potential_evidence"]
        binding = Geo08Binding(
            evidence_path=path,
            content_sha256=str(document["content_sha256"]),
            pilot_decisions_sha256=str(pilot["decisions_sha256"]),
            pilot_records=int(pilot["records"]),
            matcher_version=str(policy),
            snapshot_id=str(document["inputs"]["kitchener"]["snapshot_id"]),
            extract_sha256=str(document["inputs"]["osm_frozen"]["extract_sha256"]),
            potential_curb_ramps=int(
                potential["curb_ramps_at_a_local_way_extent_where_osm_records_no_kerb"]
            ),
            over_20m=int(potential["curb_ramps_whose_record_spans_over_20m"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        msg = f"PA-GEO-08's evidence lacks the pilot dry run this card binds to: {error!r}"
        raise CurbRampError(msg) from error
    if binding.matcher_version != ACCEPTED_MATCHER:
        msg = f"the committed evidence is for {binding.matcher_version}, not {ACCEPTED_MATCHER}."
        raise CurbRampError(msg)
    return binding


@dataclass(slots=True)
class PilotDecisions:
    v2: dict[int, Decision]
    v1: dict[int, Decision]
    timings: dict[str, float]

    @property
    def v2_digest(self) -> str:
        return decisions_digest(self.v2.values())


def decide_pilot(
    inputs: ConflationInputs, *, progress: Callable[[str], None] | None = None
) -> PilotDecisions:
    """Matcher v2 over every eligible record, and v1 over the curb cuts for PA-GEO-06's accounting."""
    say = progress or (lambda _message: None)
    frozen = MatcherV2Policy()
    v1_policy = MatcherPolicy()
    v2: dict[int, Decision] = {}
    v1: dict[int, Decision] = {}
    started = time.perf_counter()
    records = inputs.population.records
    for count, record in enumerate(records, 1):
        v2[record.activetransportid] = match_v2(
            candidates_v2(record, inputs.osm, frozen), frozen, inputs.osm, inputs.relationships
        )
        if record.curb_cut:
            v1[record.activetransportid] = match(
                candidate_set(record, inputs.osm), v1_policy, inputs.osm, inputs.relationships
            )
        if count % 2000 == 0:
            say(f"pilot: {count} of {len(records)} records decided")
    return PilotDecisions(v2, v1, {"pilot_matching_s": round(time.perf_counter() - started, 2)})


def check_binding(
    inputs: ConflationInputs, decisions: PilotDecisions, binding: Geo08Binding
) -> None:
    """Refuse inputs or decisions other than the ones the committed evidence records."""
    identity = inputs.identity
    if identity["kitchener"]["snapshot_id"] != binding.snapshot_id:
        msg = "the Kitchener snapshot is not the one PA-GEO-08's evidence records."
        raise CurbRampError(msg)
    if identity["osm_frozen"]["extract_sha256"] != binding.extract_sha256:
        msg = "the OSM study extract is not the one PA-GEO-08's evidence records."
        raise CurbRampError(msg)
    if len(decisions.v2) != binding.pilot_records:
        msg = (
            f"{len(decisions.v2)} pilot records were decided; the evidence records "
            f"{binding.pilot_records}."
        )
        raise CurbRampError(msg)
    digest = decisions.v2_digest
    if digest != binding.pilot_decisions_sha256:
        msg = (
            f"the pilot decisions ({digest[:12]}) are not the ones PA-GEO-08's evidence "
            f"records ({binding.pilot_decisions_sha256[:12]})."
        )
        raise CurbRampError(msg)


# ---------------------------------------------------------------------------
# The correspondences
# ---------------------------------------------------------------------------


def _kerb_tagged(tags: Mapping[str, str]) -> bool:
    return "kerb" in tags or tags.get("barrier") == "kerb"


def geo06_blocked_set(records: Mapping[int, Record], v1: Mapping[int, Decision]) -> set[int]:
    """The curb cuts PA-GEO-06 could not accept: matcher v1 matched them to ways only."""
    return {
        i
        for i, d in v1.items()
        if records[i].curb_cut
        and d.state == MATCHED
        and not any(t.element.startswith("node/") for t in d.targets)
    }


def _extents(inputs: ConflationInputs, decision: Decision) -> tuple[WayExtent, ...]:
    found = []
    for target in decision.targets:
        if not target.element.startswith("way/") or target.from_m is None:
            continue
        way_id = int(target.element.split("/")[1])
        way = inputs.osm.extract.ways[way_id]
        found.append(
            WayExtent(
                way_id=way_id,
                from_m=float(target.from_m),
                to_m=float(target.to_m if target.to_m is not None else target.from_m),
                osm_version=way.version,
                osm_timestamp=way.timestamp,
                highway=way.tags.get("highway"),
                footway=way.tags.get("footway"),
                crossing=way.tags.get("crossing"),
                kerb_tagged=_kerb_tagged(way.tags),
            )
        )
    return tuple(found)


def in_scope(record: Record, decision: Decision) -> bool:
    """A City curb cut whose matcher-v2 decision names no kerb node."""
    if not record.curb_cut:
        return False
    if decision.rule == KERB_NODES_UNDECIDED:
        return False
    return not any(t.element.startswith("node/") for t in decision.targets)


def build_correspondences(
    inputs: ConflationInputs,
    decisions: PilotDecisions,
    city_fields: Mapping[int, CityFields],
) -> list[CurbRampCorrespondence]:
    """Every in-scope curb cut, with its City assertion and its stage, in record order."""
    records = inputs.by_id
    blocked = geo06_blocked_set(records, decisions.v1)
    rows: list[CurbRampCorrespondence] = []
    for record_id in sorted(decisions.v2):
        record, decision = records[record_id], decisions.v2[record_id]
        if not in_scope(record, decision):
            continue
        extents = _extents(inputs, decision)
        if decision.state == AMBIGUOUS:
            stage, completeness = Stage.ABSTAINED, Completeness.ABSTAINED
        elif decision.state == UNMATCHED:
            stage, completeness = Stage.NO_COUNTERPART, Completeness.NONE
        elif record.length_m > MAX_RECORD_LENGTH_M:
            stage, completeness = Stage.OVER_20M, Completeness.POSSIBLY_INCOMPLETE
        elif any(e.kerb_tagged for e in extents):
            stage, completeness = Stage.OSM_WAY_KERB, Completeness.POSSIBLY_INCOMPLETE
        else:
            stage, completeness = Stage.CANDIDATE, Completeness.POSSIBLY_INCOMPLETE
        kerbs = tuple(str(node) for node, _distance in decision.signals.get("kerb_nodes") or [])
        rows.append(
            CurbRampCorrespondence(
                record_id=record_id,
                record_length_m=record.length_m,
                city=city_assertion(record, Topic.CURB_RAMP, city_fields.get(record_id)),
                matcher_version=ACCEPTED_MATCHER,
                state=decision.state,
                rule=decision.rule,
                relationship=decision.relationship,
                representation=decision.representation,
                extents=extents,
                kerb_nodes_within_2m=kerbs,
                in_geo06_blocked_set=record_id in blocked,
                completeness=completeness,
                stage=stage,
            )
        )
    return rows


def invariant_violations(rows: Iterable[CurbRampCorrespondence]) -> list[str]:
    """Rows whose state disagrees with what they hold. Empty when sound."""
    problems = []
    for row in rows:
        name = f"kitchener/{row.record_id}"
        if row.routing_eligibility != NOT_ROUTING_ELIGIBLE:
            problems.append(f"{name}: routing eligible")
        if not row.city.usable or row.city.normalized_value is None:
            problems.append(f"{name}: the City assertion is not a usable curb cut")
        if row.kerb_nodes_within_2m:
            problems.append(f"{name}: a kerb node within 2 m, outside this card's class")
        if row.stage is Stage.CANDIDATE:
            if row.state != MATCHED or not row.extents:
                problems.append(f"{name}: a candidate without a matched way extent")
            if row.record_length_m > MAX_RECORD_LENGTH_M:
                problems.append(f"{name}: a candidate longer than 20 m")
            if any(e.kerb_tagged for e in row.extents):
                problems.append(f"{name}: a candidate on a kerb-tagged way")
            if any(e.from_m < 0 or e.to_m < e.from_m for e in row.extents):
                problems.append(f"{name}: an extent that is not within its way")
        if row.stage is Stage.ABSTAINED and row.state != AMBIGUOUS:
            problems.append(f"{name}: an abstention that is not ambiguous")
    return problems


def pre_graph_funnel(
    inputs: ConflationInputs,
    decisions: PilotDecisions,
    rows: Sequence[CurbRampCorrespondence],
) -> dict[str, Any]:
    """The counts before any routing question, recomputed from the decisions."""
    records = inputs.by_id
    curb_cuts = [i for i, r in records.items() if r.curb_cut]
    blocked = geo06_blocked_set(records, decisions.v1)
    v2_on_blocked = Counter(decisions.v2[i].rule for i in blocked)
    in_scope_ids = {row.record_id for row in rows}
    return {
        "city_curb_cuts_in_the_pilot": len(curb_cuts),
        "curb_cuts_by_matcher_v2_rule": dict(
            sorted(Counter(decisions.v2[i].rule for i in curb_cuts).items())
        ),
        "geo06_blocked_curb_cuts": {
            "what_it_is": (
                "The curb cuts PA-GEO-06 could not accept: matcher v1 matched them to ways "
                "only, with no OSM kerb node within 2 m."
            ),
            "records": len(blocked),
            "matcher_v2_rules": dict(sorted(v2_on_blocked.items())),
        },
        "in_scope": {
            "what_it_is": "City curb cuts whose matcher-v2 decision names no kerb node.",
            "records": len(rows),
            "of_which_in_the_geo06_blocked_set": sum(1 for r in rows if r.in_geo06_blocked_set),
            "ambiguous_between_kerb_nodes_outside_scope": sum(
                1 for i in curb_cuts if decisions.v2[i].rule == KERB_NODES_UNDECIDED
            ),
            "matched_with_a_kerb_node_outside_scope": sum(
                1 for i in curb_cuts if i not in in_scope_ids and decisions.v2[i].state == MATCHED
            ),
        },
        "stages": dict(sorted(Counter(str(r.stage) for r in rows).items())),
        "candidates_by_targets_per_record": dict(
            sorted(Counter(len(r.extents) for r in rows if r.stage is Stage.CANDIDATE).items())
        ),
    }


def reconciliation_digest(rows: Iterable[CurbRampCorrespondence]) -> str:
    """The rows' identity, so two builds can be shown equal."""
    payload = json.dumps(
        [r.as_row() for r in sorted(rows, key=lambda r: r.record_id)],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_artifact(
    folder: Path,
    rows: Sequence[CurbRampCorrespondence],
    *,
    binding: Geo08Binding,
    inputs_identity: Mapping[str, Any],
    attribution: Mapping[str, str],
) -> dict[str, Any]:
    """The research artifact: every row, and a manifest that hashes it. Ignored by git."""
    folder.mkdir(parents=True, exist_ok=True)
    table = folder / "curb_ramp_correspondences.json"
    write_json(table, {"version": ARTIFACT_VERSION, "rows": [r.as_row() for r in rows]})
    manifest: dict[str, Any] = {
        "artifact_version": ARTIFACT_VERSION,
        "versions": {
            "reconciliation_policy": RECONCILIATION_VERSION,
            "accepted_matcher": ACCEPTED_MATCHER,
        },
        "bound_to": binding.as_dict(),
        "inputs": dict(inputs_identity),
        "files": {
            "curb_ramp_correspondences": {
                "file": table.name,
                "rows": len(rows),
                "bytes": table.stat().st_size,
                "sha256": hashlib.sha256(table.read_bytes()).hexdigest(),
            }
        },
        "rows_sha256": reconciliation_digest(rows),
        "stored": "the ignored data folder only; never committed and never read by routing",
        "attribution": dict(attribution),
    }
    manifest["content_sha256"] = content_sha256(manifest)
    write_json(folder / "manifest.json", manifest)
    return manifest
