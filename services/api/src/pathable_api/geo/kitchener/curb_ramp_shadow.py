"""Whether a curb-ramp assertion at a way extent can reach the place routing charges a kerb (PA-GEO-09).

PathAble charges a kerb in exactly one place: a **crossing segment**
(:func:`pathable_api.routing.cost._kerb_cost` returns nothing unless
``features.is_crossing``). The segment's kerb comes from the crossing way's own
``kerb`` tag, or else from the kerb node at either end of the segment
(:func:`pathable_api.geo.node_evidence.apply_to_crossing`, the worse of the two
ends). A kerb on a sidewalk is never charged, and an unrecorded kerb on a
crossing is charged as ``UNKNOWN`` plus a share of the missing-data penalty.

So a City curb ramp that matcher v2 locates at the metres of a way can change
a route only if those metres lie on a crossing segment, at the end where a
kerb node would sit. **The policy** (:data:`SHADOW_POLICY_VERSION`) maps an
assertion to a routing location only when all of this holds, and otherwise
leaves it unused and counts why:

- the extent lies on a routing segment at all;
- that segment is a crossing in the production graph — a sidewalk extent is
  never given crossing semantics, and a crossing is never inferred from one
  nearby;
- the extent lies on one segment, spilling at most one sample's rounding onto
  a neighbour, so a ramp is never spread along a way or across a junction;
- the extent reaches within :data:`SEGMENT_END_M` of one of the segment's end
  nodes, the matcher's own locality for a kerb node;
- the segment's production kerb is ``UNKNOWN``: an OSM kerb fact, from the way
  or from a node at either end, is never replaced;
- the record names exactly one such crossing segment: a piece the matcher
  attaches to two crossings has no single location.

Where it holds, the shadow graph costs the segment as the production model
costs a dropped kerb (:data:`SHADOW_KERB`): the City's "a curbcut down to
street level" is read as a kerb lowered or flush with the road, and the cost
model charges those two identically in every profile (checked by test). The
single-end behaviour is the production model's own — one kerb node fills a
crossing segment — and is recorded per segment as ``ends_asserted``.

Nothing here admits anything: the shadow graph is a copy, and every row stays
``not_routing_eligible``.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from enum import StrEnum
from typing import Any

from pathable_api.geo.enums import KerbType
from pathable_api.geo.features import EdgeFeatures
from pathable_api.geo.kitchener.curb_ramp_reconciliation import (
    CurbRampCorrespondence,
    Stage,
    WayExtent,
)
from pathable_api.geo.kitchener.matcher_v2 import FINE_SAMPLE_SPACING_M, MatcherV2Policy
from pathable_api.geo.kitchener.shadow_overlay import WaySegment, substitute_features
from pathable_api.routing.cost import MARKED_CROSSING_TYPES
from pathable_api.routing.graph import RoutableGraph
from pathable_api.routing.profiles import (
    ROUTING_POLICY_VERSION,
    SELECTABLE_PROFILE_KEYS,
    STANDARD,
    HardLimits,
    MobilityProfile,
    get_profile,
)

SHADOW_POLICY_VERSION = "curb-ramp-shadow-policy-v1"
#: How the shadow costs an eligible segment: as the production model costs a
#: dropped kerb. ``FLUSH`` would cost the same in every profile.
SHADOW_KERB = KerbType.LOWERED
#: The extent must reach this close to one of the segment's end nodes: the
#: matcher's own locality for a kerb node ("within about 2 m").
SEGMENT_END_M = MatcherV2Policy().kerb_node_m
#: An extent may spill this far onto a neighbouring segment: one sample at the
#: matcher's fine spacing, rounding only.
SPILL_M = FINE_SAMPLE_SPACING_M


class Outcome(StrEnum):
    """Why an assertion does or does not reach a routing location."""

    ELIGIBLE = "shadow_eligible"
    NO_ROUTING_SEGMENT = "no_routing_segment_on_any_extent"
    #: Every located extent is on a sidewalk or path: kerb cost is evaluated
    #: only on crossings, and no crossing is inferred.
    NO_CROSSING_EXTENT = "no_extent_on_a_crossing_segment"
    SEVERAL_CROSSING_SEGMENTS = "extents_reach_several_crossing_segments"
    EXTENT_SPANS_SEGMENTS = "crossing_extent_spans_several_segments"
    NOT_AT_SEGMENT_END = "crossing_extent_not_at_a_segment_end"
    EXISTING_OSM_KERB = "existing_osm_kerb_fact_on_the_segment"


class Placement(StrEnum):
    """What one extent lands on."""

    NO_SEGMENT = "no_routing_segment"
    NOT_CROSSING = "sidewalk_or_path_segment"
    SPANS_SEGMENTS = "spans_several_segments"
    NOT_AT_END = "not_at_a_segment_end"
    OSM_KERB = "segment_has_an_osm_kerb"
    CROSSING_AT_END = "crossing_segment_at_its_end"


@dataclass(frozen=True, slots=True)
class ExtentPlacement:
    way_id: int
    from_m: float
    to_m: float
    placement: Placement
    segment: str | None = None
    overlap_m: float = 0.0
    spill_m: float = 0.0
    is_crossing: bool = False
    segment_kerb: KerbType = KerbType.UNKNOWN
    kerb_from_node: bool = False
    crossing_type: str | None = None
    end_node: str | None = None
    distance_to_end_m: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "way": f"way/{self.way_id}",
            "from_m": round(self.from_m, 2),
            "to_m": round(self.to_m, 2),
            "placement": str(self.placement),
            "segment": self.segment,
            "overlap_m": round(self.overlap_m, 2),
            "spill_m": round(self.spill_m, 2),
            "is_crossing": self.is_crossing,
            "segment_kerb": self.segment_kerb.value,
            "kerb_from_node": self.kerb_from_node,
            "crossing_type": self.crossing_type,
            "end_node": self.end_node,
            "distance_to_end_m": (
                None if self.distance_to_end_m is None else round(self.distance_to_end_m, 2)
            ),
        }


@dataclass(frozen=True, slots=True)
class RecordMapping:
    """One candidate assertion against the routing graph."""

    record_id: int
    placements: tuple[ExtentPlacement, ...]
    outcome: Outcome
    segment: str | None = None
    end_node: str | None = None
    distance_to_end_m: float | None = None
    kerb_before: KerbType | None = None

    @property
    def unused_extents(self) -> int:
        return sum(1 for p in self.placements if p.segment != self.segment)

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "outcome": str(self.outcome),
            "segment": self.segment,
            "end_node": self.end_node,
            "distance_to_end_m": (
                None if self.distance_to_end_m is None else round(self.distance_to_end_m, 2)
            ),
            "kerb_before": None if self.kerb_before is None else self.kerb_before.value,
            "extents_not_used": self.unused_extents,
            "placements": [p.as_dict() for p in self.placements],
        }


@dataclass(frozen=True, slots=True)
class Substitution:
    """One crossing segment the shadow costs as a dropped kerb, and the assertions behind it."""

    identity: str
    way_id: int
    start_m: float
    end_m: float
    records: tuple[int, ...]
    end_nodes: tuple[str, ...]
    crossing_type: str | None
    kerb_before: KerbType
    kerb_shadow: KerbType = SHADOW_KERB

    @property
    def ends_asserted(self) -> int:
        return len(self.end_nodes)

    @property
    def marked(self) -> bool:
        return self.crossing_type in MARKED_CROSSING_TYPES

    def as_dict(self) -> dict[str, Any]:
        return {
            "segment": self.identity,
            "way": f"way/{self.way_id}",
            "way_extent_m": [round(self.start_m, 2), round(self.end_m, 2)],
            "records": list(self.records),
            "end_nodes": list(self.end_nodes),
            "ends_asserted": self.ends_asserted,
            "crossing_type": self.crossing_type,
            "kerb_before": self.kerb_before.value,
            "kerb_shadow": self.kerb_shadow.value,
        }


@dataclass(slots=True)
class CurbRampPlan:
    policy: str
    substitutions: dict[str, Substitution] = field(default_factory=dict)
    mappings: dict[int, RecordMapping] = field(default_factory=dict)

    @property
    def digest(self) -> str:
        lines = [
            json.dumps(
                [s.identity, list(s.records), s.kerb_before.value, s.kerb_shadow.value],
                separators=(",", ":"),
            )
            for s in sorted(self.substitutions.values(), key=lambda s: s.identity)
        ]
        payload = "\n".join([self.policy, *lines]).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def _nodes_of(identity: str) -> tuple[str, str]:
    source, rest = identity.split("->", 1)
    return source, rest.split("#", 1)[0]


def place_extent(
    extent: WayExtent,
    segments: Sequence[WaySegment],
    features: Mapping[str, EdgeFeatures],
) -> ExtentPlacement:
    """Which routing segment an extent lies on, and whether a kerb could be charged there."""
    a, b = min(extent.from_m, extent.to_m), max(extent.from_m, extent.to_m)
    overlaps: list[tuple[float, WaySegment]] = []
    for segment in segments:
        lo, hi = max(segment.start_m, a), min(segment.end_m, b)
        overlaps.append((max(0.0, hi - lo), segment))
    main: WaySegment | None = None
    overlap = 0.0
    if overlaps and max(o for o, _s in overlaps) > 0:
        overlap, main = max(overlaps, key=lambda item: (item[0], -item[1].start_m))
    else:
        # A point extent: the segment that contains it.
        middle = (a + b) / 2
        for segment in segments:
            if segment.start_m <= middle <= segment.end_m:
                main = segment
                break
    if main is None:
        return ExtentPlacement(extent.way_id, a, b, Placement.NO_SEGMENT)
    spill = sum(o for o, s in overlaps if s is not main)
    found = features.get(main.identity)
    if found is None:
        return ExtentPlacement(extent.way_id, a, b, Placement.NO_SEGMENT)
    source, target = _nodes_of(main.identity)
    to_start = max(0.0, a - main.start_m)
    to_end = max(0.0, main.end_m - b)
    end_node, distance = (source, to_start) if to_start <= to_end else (target, to_end)
    placement = Placement.CROSSING_AT_END
    if not found.is_crossing:
        placement = Placement.NOT_CROSSING
    elif spill > SPILL_M:
        placement = Placement.SPANS_SEGMENTS
    elif distance > SEGMENT_END_M:
        placement = Placement.NOT_AT_END
    elif found.kerb is not KerbType.UNKNOWN:
        placement = Placement.OSM_KERB
    return ExtentPlacement(
        way_id=extent.way_id,
        from_m=a,
        to_m=b,
        placement=placement,
        segment=main.identity,
        overlap_m=overlap,
        spill_m=spill,
        is_crossing=found.is_crossing,
        segment_kerb=found.kerb,
        kerb_from_node=found.kerb_from_node,
        crossing_type=found.crossing_type,
        end_node=end_node,
        distance_to_end_m=distance,
    )


_OUTCOME_OF = {
    Placement.SPANS_SEGMENTS: Outcome.EXTENT_SPANS_SEGMENTS,
    Placement.NOT_AT_END: Outcome.NOT_AT_SEGMENT_END,
    Placement.OSM_KERB: Outcome.EXISTING_OSM_KERB,
}


def map_record(
    row: CurbRampCorrespondence,
    segments_by_way: Mapping[int, Sequence[WaySegment]],
    features: Mapping[str, EdgeFeatures],
) -> RecordMapping:
    """One candidate against the graph: a single crossing segment at its end, or why not."""
    placements = tuple(
        place_extent(extent, segments_by_way.get(extent.way_id, ()), features)
        for extent in row.extents
    )
    located = [p for p in placements if p.placement is not Placement.NO_SEGMENT]
    if not located:
        return RecordMapping(row.record_id, placements, Outcome.NO_ROUTING_SEGMENT)
    on_crossings = [p for p in located if p.is_crossing]
    if not on_crossings:
        return RecordMapping(row.record_id, placements, Outcome.NO_CROSSING_EXTENT)
    if len({p.segment for p in on_crossings}) > 1:
        return RecordMapping(row.record_id, placements, Outcome.SEVERAL_CROSSING_SEGMENTS)
    chosen = on_crossings[0]
    outcome = _OUTCOME_OF.get(chosen.placement, Outcome.ELIGIBLE)
    return RecordMapping(
        row.record_id,
        placements,
        outcome,
        segment=chosen.segment,
        end_node=chosen.end_node,
        distance_to_end_m=chosen.distance_to_end_m,
        kerb_before=chosen.segment_kerb,
    )


def plan_substitutions(
    rows: Iterable[CurbRampCorrespondence],
    segments_by_way: Mapping[int, Sequence[WaySegment]],
    features: Mapping[str, EdgeFeatures],
    *,
    policy: str = SHADOW_POLICY_VERSION,
) -> CurbRampPlan:
    """Map every candidate row, and group the eligible ones by crossing segment."""
    plan = CurbRampPlan(policy)
    by_segment: dict[str, list[RecordMapping]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: r.record_id):
        if row.stage is not Stage.CANDIDATE:
            continue
        mapping = map_record(row, segments_by_way, features)
        plan.mappings[row.record_id] = mapping
        if mapping.outcome is Outcome.ELIGIBLE and mapping.segment is not None:
            by_segment[mapping.segment].append(mapping)
    extents = {s.identity: s for segments in segments_by_way.values() for s in segments}
    for identity in sorted(by_segment):
        found = by_segment[identity]
        segment = extents[identity]
        chosen = features[identity]
        plan.substitutions[identity] = Substitution(
            identity=identity,
            way_id=segment.way_id,
            start_m=segment.start_m,
            end_m=segment.end_m,
            records=tuple(sorted(m.record_id for m in found)),
            end_nodes=tuple(sorted({m.end_node for m in found if m.end_node is not None})),
            crossing_type=chosen.crossing_type,
            kerb_before=chosen.kerb,
        )
    return plan


def shadow_kerb_graph(baseline: RoutableGraph, plan: CurbRampPlan) -> RoutableGraph:
    """The baseline with only the planned crossing segments' kerbs replaced; the baseline is untouched."""
    by_identity = {e.identity: e for e in baseline.segments}
    replacements = {
        identity: replace(by_identity[identity].features, kerb=substitution.kerb_shadow)
        for identity, substitution in plan.substitutions.items()
        if identity in by_identity
    }
    return substitute_features(baseline, replacements, policy=plan.policy, digest=plan.digest)


# ---------------------------------------------------------------------------
# How kerb evidence moves a route today, read from the code
# ---------------------------------------------------------------------------


def kerb_evidence_changes_cost(profile: MobilityProfile) -> bool:
    """Whether replacing an unknown kerb with the shadow kerb changes any cost for this profile."""
    penalty = profile.kerb_penalty_m
    if penalty.get(KerbType.UNKNOWN, 0.0) != penalty.get(SHADOW_KERB, 0.0):
        return True
    return (
        profile.uncertainty_penalty_per_attribute > 0
        and "kerb" not in profile.ignore_unknown_attributes
    )


def kerb_profiles() -> list[MobilityProfile]:
    """The standard baseline, and every production profile kerb evidence can move."""
    return [
        STANDARD,
        *(
            p
            for p in (get_profile(k) for k in SELECTABLE_PROFILE_KEYS)
            if kerb_evidence_changes_cost(p)
        ),
    ]


def cost_equivalent_kerbs(profiles: Sequence[MobilityProfile]) -> list[str]:
    """Kerb kinds every profile charges exactly as it charges the shadow kerb."""
    return [
        kerb.value
        for kerb in KerbType
        if all(
            p.kerb_penalty_m.get(kerb, 0.0) == p.kerb_penalty_m.get(SHADOW_KERB, 0.0)
            for p in profiles
        )
    ]


def kerb_rules(profiles: Sequence[MobilityProfile]) -> dict[str, Any]:
    """How each profile uses kerb evidence today, read from the profiles and the cost model."""
    hard_limit_fields = [f.name for f in fields(HardLimits)]
    return {
        "routing_policy_version": ROUTING_POLICY_VERSION,
        "shadow_kerb": SHADOW_KERB.value,
        "cost_equivalent_to_shadow_kerb": cost_equivalent_kerbs(profiles),
        "hard_limit_fields": hard_limit_fields,
        "any_hard_limit_reads_kerb": any("kerb" in name for name in hard_limit_fields),
        "profiles": {
            p.key: {
                "kerb_penalty_m": {k.value: p.kerb_penalty_m.get(k, 0.0) for k in KerbType},
                "uncertainty_penalty_per_attribute": p.uncertainty_penalty_per_attribute,
                "uncertainty_counts_kerb": "kerb" not in p.ignore_unknown_attributes,
                "kerb_evidence_changes_cost": kerb_evidence_changes_cost(p),
            }
            for p in profiles
        },
        "mechanisms": [
            "A kerb is charged only on a crossing segment (cost.py _kerb_cost): a kerb on a "
            "sidewalk or path segment costs nothing, so an assertion there cannot move a route.",
            "The flat kerb penalty is the profile's rate for the segment's kerb kind; UNKNOWN "
            "has its own rate, and NONE, FLUSH and LOWERED have none (profiles.py).",
            "A crossing with an UNKNOWN kerb also counts 'kerb' among its missing attributes, "
            "charged per metre at the profile's uncertainty rate (features.py "
            "unknown_attributes, cost.py _uncertainty_cost); a known kerb removes that share.",
            "A crossing segment's kerb is the way's own kerb tag, else the worse of the kerb "
            "nodes at its two ends (node_evidence.py apply_to_crossing); one node fills the "
            "segment, which the shadow mirrors and records as ends_asserted.",
            "No hard limit reads a kerb, so kerb evidence can change cost but never feasibility.",
            "Explanations compare the chosen route with the standard one by kerb kind "
            "(comparison.py _penalty_kerbs) and count unrecorded kerbs on the route "
            "(engine.py unknown_kerb_crossing_count).",
        ],
    }


# ---------------------------------------------------------------------------
# Accounting
# ---------------------------------------------------------------------------


def _distribution(values: Sequence[float]) -> dict[str, Any] | None:
    if not values:
        return None
    ordered = sorted(values)

    def at(q: float) -> float:
        index = min(len(ordered) - 1, max(0, round(q * len(ordered)) - 1))
        return round(ordered[index], 2)

    return {"n": len(ordered), "p50": at(0.5), "p90": at(0.9), "max": round(ordered[-1], 2)}


def mapping_summary(plan: CurbRampPlan, lengths: Mapping[str, float]) -> dict[str, Any]:
    """The routing-location funnel and what the eligible segments look like."""
    mappings = list(plan.mappings.values())
    placements = Counter(str(p.placement) for m in mappings for p in m.placements)
    eligible = [m for m in mappings if m.outcome is Outcome.ELIGIBLE]
    crossing_distances = [
        p.distance_to_end_m
        for m in mappings
        for p in m.placements
        if p.is_crossing and p.distance_to_end_m is not None
    ]
    substitutions = list(plan.substitutions.values())
    return {
        "policy": plan.policy,
        "candidates": len(mappings),
        "outcomes": dict(sorted(Counter(str(m.outcome) for m in mappings).items())),
        "extent_placements": dict(sorted(placements.items())),
        "crossing_extent_distance_to_segment_end_m": _distribution(crossing_distances),
        "eligible_assertions": len(eligible),
        "eligible_distance_to_segment_end_m": _distribution(
            [m.distance_to_end_m for m in eligible if m.distance_to_end_m is not None]
        ),
        "eligible_extents_not_used": sum(m.unused_extents for m in eligible),
        "affected_crossing_segments": len(substitutions),
        "affected_crossing_metres": round(
            sum(lengths.get(s.identity, 0.0) for s in substitutions), 1
        ),
        "segments_by_ends_asserted": dict(
            sorted(Counter(s.ends_asserted for s in substitutions).items())
        ),
        "segments_by_records": dict(sorted(Counter(len(s.records) for s in substitutions).items())),
        "segments_by_crossing_type": dict(
            sorted(Counter(s.crossing_type or "unspecified" for s in substitutions).items())
        ),
        "segments_marked_or_signalised": sum(1 for s in substitutions if s.marked),
        "kerb_before": dict(sorted(Counter(s.kerb_before.value for s in substitutions).items())),
    }
