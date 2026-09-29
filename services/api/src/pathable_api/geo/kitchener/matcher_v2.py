"""Matcher v2: deterministic correspondence that abstains where it cannot defend a match.

PA-GEO-05 measured matcher v1 once, on a held-out sample, and found its central
weakness: it committed where a careful reviewer would not. Every rule below
answers a failure that sample recorded (its failure analysis is development
data now), and every threshold is named with its provenance
(:data:`POLICY_PROVENANCE`). Nothing here is a probability or a confidence.

What changes from v1 (:mod:`conflation`):

- **Crossings carry curb cuts.** v1's class compatibility never let a crossing
  way carry a sidewalk-family curb cut, its commonest curb-cut failure. A
  crossing way now carries curb cuts and crossings; kind otherwise only breaks
  ties between competing ways (:func:`kind`), never removes a carrier.
- **Pieces follow ways.** A curb cut or a piece shorter than a junction's width
  is sampled every quarter metre, within the definitions' 2 m, and only a way
  the piece *follows* — within ``follow_max_deg`` where near — carries it. v1's
  45° limit let a metre-long piece be claimed by a sidewalk it crossed at 30-40°.
- **A short piece must clearly follow one way.** One way carrying most of it,
  and no rival: no second way roughly aligned with it along its whole length.
  Two ways meeting at a corner are rivals whether or not they share the corner
  node; v1 treated ways sharing a node as one facility and named the majority.
- **Curb cuts are local and settled by their kerb.** A kerb node marks the
  ramp; with two near, the one on a way the piece follows, else ambiguous.
  With no kerb node and no way followed, a piece at a junction is ambiguous.
  Targets are the kerb node and the metres of each way the piece covers.
- **Stairs.** A stair on a plain footway corresponds to it (``generic_way``)
  unless OSM steps lie nearby: then its physical identity is unclear.
- **Structures keep every carrier.** v1 kept only ways tagged as the structure
  and dropped short structure pieces as end slop. Pieces tagged as the City's
  structure now carry from a metre, and approach ways the record runs along
  carry as any way does.
- **Chained ways never compete.** Ways sharing a node are one line for the
  contest; a genuine corner is caught by the rival rule instead.
- **Partial counterparts must be aligned.** A path touching one end of a spur
  at a right angle is not a partial counterpart.

All geometry is in the City's NAD83 / UTM 17N metres. Nothing here reads or
writes PathAble's routing database, and nothing in routing reads this.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from typing import Any

import numpy as np

from pathable_api.geo.kitchener.conflation import (
    AMBIGUOUS,
    MATCHED,
    UNMATCHED,
    Decision,
    NodeCandidate,
    Record,
    RelationshipIndex,
    Target,
    WayCandidate,
    node_kind,
    samples_and_bearings,
    way_candidate,
)
from pathable_api.geo.kitchener.correspondence import OsmIndex, nearest_road, osm_class, parts
from pathable_api.geo.kitchener.matcher_v2_labels import structure_tagged

MATCHER_V2_VERSION = "kitchener-geo08-matcher-v2"
CANDIDATE_CONTRACT_V2 = "kitchener-geo08-candidates-v2"

#: v1's candidate radii, unchanged: recall first.
WAY_RADIUS_M = 25.0
NODE_RADIUS_M = 10.0
SAMPLE_SPACING_M = 1.0
#: Curb cuts and pieces shorter than a junction's width are sampled this finely:
#: at one metre, a metre-long piece has two or three samples and one decides.
FINE_SAMPLE_SPACING_M = 0.25

#: OSM classes that may carry any pedestrian record. Roads never do: a facility
#: OSM records only as a road tag is a road attribute.
CARRIER_CLASSES = frozenset({"sidewalk", "path", "steps"})

#: A record family's own kind of OSM way: used only to break ties between
#: competing ways, never to exclude a carrier.
OWN_KIND: dict[str, frozenset[str]] = {
    "sidewalk": frozenset({"sidewalk"}),
    "walkway": frozenset({"path"}),
    "trail": frozenset({"path"}),
    "crossing": frozenset({"crossing"}),
    "stairs": frozenset({"steps"}),
}
#: A curb cut lies where a sidewalk meets a crossing: both are its own kind.
CURB_CUT_KIND = frozenset({"sidewalk", "crossing", "path"})


def osm_class_v2(tags: Mapping[str, str]) -> str:
    """v1's classes, and ``construction`` for a way that is not yet a facility."""
    if tags.get("highway") == "construction":
        return "construction"
    return osm_class(tags)


def kind(record: Record, osm: str) -> int:
    """2 when an OSM class is the record's own kind of facility, 1 otherwise."""
    own = CURB_CUT_KIND if record.curb_cut else OWN_KIND.get(record.family, frozenset())
    return 2 if osm in own else 1


# ---------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------

#: Where every value of the policy came from. "Fixed" values come from the
#: label definitions, from geometry, or from v1; "tuned" ones from the declared
#: development grid (:data:`matcher_v2_benchmark.TUNING_GRID`).
POLICY_PROVENANCE: dict[str, str] = {
    "carry_m": (
        "tuned on the development set: 3 m (cost 30) against 2 m (31 or more), as v1 found; for "
        "records of a junction's width or more"
    ),
    "piece_carry_m": (
        "fixed by the label definitions: a curb cut or short piece lies along a way when most of "
        "it is within about 2 m"
    ),
    "align_max_deg": (
        "fixed, as v1: a way crossing a record at more than 45 degrees there is not along it"
    ),
    "follow_max_deg": (
        "tuned on the development set: 15 degrees (cost 30) against 10 or 20 (31 or more). The "
        "development labels cite a way for a piece at 0.9-10 degrees and not at 17 or more, with a "
        "few cited at 20-23 degrees"
    ),
    "rival_extra_deg": (
        "not identified by the development set — 10 and 15 degrees gave the same result, 5 a "
        "worse one — so the selection rule's more conservative value: a second way within 30 "
        "degrees of the piece, along all of it, makes a corner"
    ),
    "rival_share": (
        "fixed: 'along the whole piece' is 95% of its samples within piece_carry_m, allowing a "
        "sample of rounding at a quarter-metre spacing"
    ),
    "end_slop_m": "fixed by the label definitions: about a junction's width (5 m)",
    "structure_min_m": (
        "fixed: a way tagged as the City's structure carries it from a metre; OSM splits stairs "
        "and bridges into pieces shorter than the end slop"
    ),
    "cover_min": (
        "not identified by the development set — 0.6 and 0.75 gave the same result — so the "
        "selection rule's more conservative value"
    ),
    "contest_margin_m": "v1's value, never identified by a development set",
    "contest_max": "v1's value, never identified by a development set",
    "short_piece_m": "fixed by the label definitions: a junction's width",
    "piece_carrier_share": (
        "fixed: a way the piece follows for a quarter of its length carries it, rather than "
        "touching its end"
    ),
    "piece_cover_min": "fixed as v1's coverage: the one way must carry most of the piece",
    "curb_cover_min": "fixed: the ways a curb cut follows must carry at least half of it",
    "kerb_node_m": "fixed by the label definitions: a kerb node within about 2 m",
    "crossing_node_m": "v1's value",
    "near_m": "fixed by the label definitions: no counterpart within about 5 m",
    "road_attribute_m": "v1's value",
    "displaced_steps_m": (
        "fixed at the candidate radius, the most conservative value: the development set has one "
        "displaced stair (steps 7.5 m away) and cannot tell 10, 15 or 25 m apart"
    ),
}


@dataclass(frozen=True, slots=True)
class MatcherV2Policy:
    """Every threshold matcher v2 uses, named, with where it came from.

    The defaults are the frozen policy :data:`MATCHER_V2_VERSION`. The switches
    at the end each undo one change from v1, for ablation; all are on in the
    policy that is evaluated.
    """

    version: str = MATCHER_V2_VERSION
    carry_m: float = 3.0
    piece_carry_m: float = 2.0
    align_max_deg: float = 45.0
    follow_max_deg: float = 15.0
    rival_extra_deg: float = 15.0
    rival_share: float = 0.95
    end_slop_m: float = 5.0
    structure_min_m: float = 1.0
    cover_min: float = 0.75
    contest_margin_m: float = 1.5
    contest_max: float = 0.2
    short_piece_m: float = 5.0
    piece_carrier_share: float = 0.25
    piece_cover_min: float = 0.6
    curb_cover_min: float = 0.5
    kerb_node_m: float = 2.0
    crossing_node_m: float = 3.0
    near_m: float = 5.0
    road_attribute_m: float = 15.0
    displaced_steps_m: float = 25.0
    # Ablation switches: each undoes one change from v1.
    use_crossing_carriers: bool = True
    use_follow: bool = True
    use_piece_rules: bool = True
    use_kerb_topology: bool = True
    use_stair_rule: bool = True
    use_structure_pieces: bool = True
    provenance: Mapping[str, str] = field(default_factory=lambda: dict(POLICY_PROVENANCE))

    def as_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["provenance"] = dict(self.provenance)
        return values

    def with_(self, **changes: Any) -> MatcherV2Policy:
        return replace(self, **changes)


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CandidatesV2:
    record: Record
    samples: np.ndarray[Any, Any]
    spacing: float
    ways: tuple[WayCandidate, ...]
    nodes: tuple[NodeCandidate, ...]
    road_id: int | None
    road_distance_m: float | None

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    @property
    def metres_per_sample(self) -> float:
        return self.record.length_m / max(self.sample_count, 1)


def is_piece(record: Record, policy: MatcherV2Policy) -> bool:
    """A curb cut, or a record shorter than a junction's width."""
    return record.curb_cut or record.length_m < policy.short_piece_m


def candidates_v2(record: Record, index: OsmIndex, policy: MatcherV2Policy) -> CandidatesV2:
    """v1's candidate contract, with fine sampling for curb cuts and short pieces."""
    spacing = FINE_SAMPLE_SPACING_M if is_piece(record, policy) else SAMPLE_SPACING_M
    points, bearings = samples_and_bearings(record.geometry, spacing)
    hits = index.tree.query(record.geometry, predicate="dwithin", distance=WAY_RADIUS_M)
    ways = []
    for osm_id in sorted(index.way_ids[int(hit)] for hit in hits):
        tags = index.extract.ways[osm_id].tags
        candidate = way_candidate(
            osm_id, index.lines[osm_id], tags, record.family, record.geometry, points, bearings
        )
        klass = osm_class_v2(tags)
        ways.append(replace(candidate, osm_class=klass, compatibility=str(kind(record, klass))))
    nodes = []
    for hit in index.fact_tree.query(record.geometry, predicate="dwithin", distance=NODE_RADIUS_M):
        node_id = index.fact_ids[int(hit)]
        found = node_kind(index.extract.nodes[node_id].tags)
        if found is None:
            continue
        nodes.append(
            NodeCandidate(
                osm_id=node_id,
                kind=found,
                distance_m=float(index.fact_points[node_id].distance(record.geometry)),
                on_ways=tuple(sorted(index.node_ways.get(node_id, []))),
            )
        )
    nodes.sort(key=lambda n: n.osm_id)
    middle = max(parts(record.geometry), key=lambda part: part.length).interpolate(
        0.5, normalized=True
    )
    road = nearest_road(middle, index)
    return CandidatesV2(
        record=record,
        samples=points,
        spacing=spacing,
        ways=tuple(ways),
        nodes=tuple(nodes),
        road_id=road,
        road_distance_m=float(index.lines[road].distance(middle)) if road is not None else None,
    )


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Claims:
    """Which way claims each sample of a record, and which ways carry it."""

    ways: tuple[WayCandidate, ...]
    nearest: np.ndarray[Any, Any]
    claimed: np.ndarray[Any, Any]
    carriers: tuple[int, ...]
    shares: Mapping[int, float]
    coverage: float
    contested: float

    def mask(self, row: int) -> np.ndarray[Any, Any]:
        return np.asarray((self.nearest == row) & self.claimed, dtype=bool)


def eligible(way: WayCandidate, record: Record, policy: MatcherV2Policy) -> bool:
    """Whether a way may carry the record at all."""
    if way.osm_class in CARRIER_CLASSES:
        return True
    if way.osm_class == "crossing":
        # The ablation restores v1's defect: a crossing never carries a curb cut.
        return record.family == "crossing" or (record.curb_cut and policy.use_crossing_carriers)
    return way.osm_class == "service" and record.family == "trail"


def follow_angle(way: WayCandidate, within_m: float) -> float | None:
    """The median angle between a record and a way over the samples within ``within_m``."""
    near = way.distances <= within_m
    return float(np.median(way.angles[near])) if near.any() else None


def _chained(first: int, second: int, index: OsmIndex) -> bool:
    return bool(set(index.extract.ways[first].refs) & set(index.extract.ways[second].refs))


def claims(
    candidates: CandidatesV2, policy: MatcherV2Policy, index: OsmIndex, *, piece: bool
) -> Claims:
    """Nearest aligned eligible way per sample, which ways carry the record, how contested."""
    record = candidates.record
    carry = policy.piece_carry_m if piece else policy.carry_m
    ways = [w for w in candidates.ways if eligible(w, record, policy)]
    if piece and policy.use_follow:
        ways = [
            w
            for w in ways
            if (angle := follow_angle(w, carry)) is not None and angle <= policy.follow_max_deg
        ]
    n = candidates.sample_count
    if not ways or n == 0:
        empty = np.zeros(n, dtype=bool)
        return Claims((), np.zeros(n, dtype=int), empty, (), {}, 0.0, 0.0)
    distance = np.vstack([w.distances for w in ways])
    distance = np.where(
        np.vstack([w.angles for w in ways]) <= policy.align_max_deg, distance, np.inf
    )
    nearest = np.argmin(distance, axis=0)
    nearest_d = distance[nearest, np.arange(n)]
    claimed = nearest_d <= carry
    shares = {i: float(((nearest == i) & claimed).mean()) for i in range(len(ways))}
    mps = candidates.metres_per_sample
    carriers: list[int] = []
    for i, way in enumerate(ways):
        metres = shares[i] * n * mps
        if metres == 0:
            continue
        if piece:
            if shares[i] >= policy.piece_carrier_share:
                carriers.append(i)
            continue
        structural = (
            policy.use_structure_pieces
            and record.structure is not None
            and structure_tagged(record.structure, index.extract.ways[way.osm_id].tags)
        )
        if metres >= policy.end_slop_m or (structural and metres >= policy.structure_min_m):
            carriers.append(i)
    if not piece and not carriers:
        # A record barely longer than a junction: its main way, if that carries half of it.
        best = max(shares, key=lambda i: (shares[i], -ways[i].osm_id))
        if shares[best] >= 0.5:
            carriers.append(best)
    in_carrier = np.isin(nearest, carriers) & claimed
    contested = np.zeros(n, dtype=bool)
    if len(ways) > 1:
        for sample in np.flatnonzero(in_carrier):
            best = int(nearest[sample])
            for other in range(len(ways)):
                if other == best or other in carriers or not np.isfinite(distance[other, sample]):
                    continue
                if distance[other, sample] - nearest_d[sample] >= policy.contest_margin_m:
                    continue
                if int(ways[other].compatibility) < int(ways[best].compatibility):
                    continue
                if _chained(ways[best].osm_id, ways[other].osm_id, index):
                    continue
                contested[sample] = True
                break
    carried = int(in_carrier.sum())
    return Claims(
        ways=tuple(ways),
        nearest=nearest,
        claimed=claimed,
        carriers=tuple(carriers),
        shares=shares,
        coverage=float(claimed.mean()),
        contested=float(contested.sum() / carried) if carried else 0.0,
    )


def rivals(
    candidates: CandidatesV2, carrier: WayCandidate, policy: MatcherV2Policy
) -> list[WayCandidate]:
    """Other ways a short piece could equally be part of: roughly aligned, along all of it."""
    found = []
    for way in candidates.ways:
        if way.osm_id == carrier.osm_id or not eligible(way, candidates.record, policy):
            continue
        angle = follow_angle(way, policy.piece_carry_m)
        if (
            angle is not None
            and angle <= policy.follow_max_deg + policy.rival_extra_deg
            and way.share_within(policy.piece_carry_m) >= policy.rival_share
        ):
            found.append(way)
    return found


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


def _target(way: WayCandidate, mask: np.ndarray[Any, Any]) -> Target:
    positions = way.positions[mask] if mask.any() else way.positions
    return Target(f"way/{way.osm_id}", "carrier", float(positions.min()), float(positions.max()))


def _near_aligned(candidates: CandidatesV2, policy: MatcherV2Policy) -> bool:
    """Whether an eligible way lies along the record within ``near_m`` — a partial counterpart."""
    for way in candidates.ways:
        if not eligible(way, candidates.record, policy):
            continue
        near = way.distances <= policy.near_m
        if (
            near.any()
            and float(np.median(way.angles[near])) <= policy.align_max_deg
            and float(np.median(way.distances)) <= policy.near_m
        ):
            return True
    return False


def _pedestrian_near(candidates: CandidatesV2, policy: MatcherV2Policy) -> bool:
    return any(
        eligible(w, candidates.record, policy) and w.min_distance_m <= policy.near_m
        for w in candidates.ways
    )


def _road_tags_facility(candidates: CandidatesV2, index: OsmIndex, policy: MatcherV2Policy) -> bool:
    if candidates.road_id is None or candidates.road_distance_m is None:
        return False
    if candidates.road_distance_m > policy.road_attribute_m:
        return False
    tags = index.extract.ways[candidates.road_id].tags
    keys = ("sidewalk", "sidewalk:both", "sidewalk:left", "sidewalk:right", "footway")
    return bool({tags[k] for k in keys if k in tags} - {"no", "none", "separate"})


def representation(targets: tuple[Target, ...], record: Record, index: OsmIndex) -> str:
    kinds = {t.element.split("/")[0] for t in targets}
    if kinds == {"node"}:
        return "node"
    if kinds != {"way"}:
        return "multiple" if kinds else "none"
    if record.structure is not None and not any(
        structure_tagged(record.structure, index.extract.ways[int(t.element.split("/")[1])].tags)
        for t in targets
    ):
        return "generic_way"
    return "separate_way"


def match_v2(
    candidates: CandidatesV2,
    policy: MatcherV2Policy,
    index: OsmIndex,
    relationships: RelationshipIndex | None = None,
) -> Decision:
    """Matcher v2's decision for one record. Deterministic for a given policy."""
    record = candidates.record
    piece = is_piece(record, policy) and policy.use_piece_rules
    found = claims(candidates, policy, index, piece=piece)
    carriers = [found.ways[i] for i in found.carriers]
    signals: dict[str, Any] = {
        "sample_spacing_m": candidates.spacing,
        "coverage": round(found.coverage, 3),
        "contested_share": round(found.contested, 3),
        "carriers": [f"way/{w.osm_id}" for w in carriers],
        "claim_shares": {
            f"way/{found.ways[i].osm_id}": round(v, 3) for i, v in found.shares.items() if v > 0
        },
    }
    if piece:
        signals["follow_angles_deg"] = {
            f"way/{w.osm_id}": round(angle, 1)
            for w in candidates.ways
            if eligible(w, record, policy)
            and (angle := follow_angle(w, policy.piece_carry_m)) is not None
        }
    targets = tuple(
        _target(w, found.mask(i)) for i, w in zip(found.carriers, carriers, strict=True)
    )

    def decide(state: str, rule: str, chosen: tuple[Target, ...] = ()) -> Decision:
        relationship = None
        if state == MATCHED:
            relationship = (relationships or RelationshipIndex.empty()).relationship(record, chosen)
        shown = representation(chosen, record, index) if state == MATCHED else "none"
        return Decision(record.activetransportid, state, rule, chosen, relationship, shown, signals)

    if record.curb_cut and policy.use_piece_rules:
        return _curb_cut(candidates, policy, found, carriers, targets, signals, decide)

    if piece:
        ranked = sorted(found.carriers, key=lambda i: (-found.shares[i], found.ways[i].osm_id))
        covered = bool(ranked) and found.shares[ranked[0]] >= policy.piece_cover_min
        if covered:
            main = found.ways[ranked[0]]
            others = rivals(candidates, main, policy)
            if others:
                signals["rivals"] = [f"way/{w.osm_id}" for w in others]
                return decide(AMBIGUOUS, "piece_between_ways")
            targets = (_target(main, found.mask(ranked[0])),)
            carriers = [main]
        elif ranked:
            return decide(AMBIGUOUS, "piece_between_ways")
    else:
        covered = found.coverage >= policy.cover_min and bool(carriers)
    if covered and found.contested > policy.contest_max:
        return decide(AMBIGUOUS, "competing_way")
    generic_stair = (
        covered
        and record.structure == "STAIRS"
        and policy.use_stair_rule
        and not any(w.osm_class == "steps" for w in carriers)
    )
    if generic_stair:
        displaced = [
            w
            for w in candidates.ways
            if w.osm_class == "steps"
            and w.min_distance_m <= policy.displaced_steps_m
            and w not in carriers
        ]
        if displaced:
            signals["displaced_steps"] = [f"way/{w.osm_id}" for w in displaced]
            return decide(AMBIGUOUS, "stair_displaced_steps")
        return decide(MATCHED, "stair_on_generic_way", targets)
    if covered:
        return decide(MATCHED, "piece_on_one_way" if piece else "covered_by_carriers", targets)
    construction = [
        w
        for w in candidates.ways
        if w.osm_class == "construction" and w.share_within(policy.carry_m) >= policy.cover_min
    ]
    if construction:
        signals["construction"] = [f"way/{w.osm_id}" for w in construction]
        return decide(AMBIGUOUS, "osm_under_construction")
    if record.family == "crossing":
        crossing_nodes = sorted(
            (
                n
                for n in candidates.nodes
                if n.kind == "crossing" and n.distance_m <= policy.crossing_node_m
            ),
            key=lambda n: (n.distance_m, n.osm_id),
        )
        crossing_ways = [
            w
            for w in candidates.ways
            if w.osm_class == "crossing" and w.min_distance_m <= policy.near_m
        ]
        if crossing_nodes and not crossing_ways:
            return decide(
                MATCHED,
                "crossing_as_node",
                (Target(f"node/{crossing_nodes[0].osm_id}", "crossing"),),
            )
    if piece and _pedestrian_near(candidates, policy):
        return decide(AMBIGUOUS, "piece_at_junction")
    if _near_aligned(candidates, policy):
        return decide(AMBIGUOUS, "partial_or_offset_counterpart")
    if _road_tags_facility(candidates, index, policy):
        return decide(AMBIGUOUS, "road_attribute")
    return decide(UNMATCHED, "no_counterpart")


def _curb_cut(
    candidates: CandidatesV2,
    policy: MatcherV2Policy,
    found: Claims,
    carriers: list[WayCandidate],
    targets: tuple[Target, ...],
    signals: dict[str, Any],
    decide: Callable[..., Decision],
) -> Decision:
    """A curb cut: its kerb node, and the metres of each way the piece follows."""
    kerbs = sorted(
        (n for n in candidates.nodes if n.kind == "kerb" and n.distance_m <= policy.kerb_node_m),
        key=lambda n: (n.distance_m, n.osm_id),
    )
    signals["kerb_nodes"] = [[f"node/{n.osm_id}", round(n.distance_m, 2)] for n in kerbs]
    followed = sum(found.shares[i] for i in found.carriers)
    usable = followed >= policy.curb_cover_min and found.contested <= policy.contest_max
    carried = {w.osm_id for w in carriers} if usable else set()
    kerb = None
    if len(kerbs) == 1:
        kerb = kerbs[0]
    elif len(kerbs) > 1:
        if policy.use_kerb_topology:
            on_carrier = [k for k in kerbs if set(k.on_ways) & carried]
            if len(on_carrier) != 1:
                return decide(AMBIGUOUS, "curb_cut_kerb_nodes_undecided")
            kerb = on_carrier[0]
        elif kerbs[1].distance_m - kerbs[0].distance_m >= 0.5:
            kerb = kerbs[0]
        else:
            return decide(AMBIGUOUS, "curb_cut_kerb_nodes_undecided")
    node = (Target(f"node/{kerb.osm_id}", "kerb"),) if kerb is not None else ()
    ways = targets if usable else ()
    if node and ways:
        return decide(MATCHED, "curb_cut_kerb_and_ways", node + ways)
    if node:
        return decide(MATCHED, "curb_cut_kerb_node", node)
    if ways:
        return decide(MATCHED, "curb_cut_ways_followed", ways)
    if _pedestrian_near(candidates, policy):
        return decide(AMBIGUOUS, "curb_cut_at_junction")
    return decide(UNMATCHED, "curb_cut_no_counterpart")


def local_extent_m(decision: Decision) -> float | None:
    """The longest way extent a decision names, in metres: how local it is."""
    spans = [
        float(t.to_m or 0.0) - float(t.from_m)
        for t in decision.targets
        if t.element.startswith("way/") and t.from_m is not None
    ]
    return max(spans) if spans else None
