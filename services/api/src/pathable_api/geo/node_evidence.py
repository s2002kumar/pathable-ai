"""Accessibility facts that live on OSM nodes rather than ways.

A kerb is mapped where a path meets the road — on the node — not along the
footway. A router that reads only way tags therefore never sees a single kerb,
which for a wheelchair user is the difference between a usable crossing and a
120 mm step.

The hard part is not reading the tags, it is **scope**. A kerb node sits between
a sidewalk and a crossing, and several ways touch it. Charging every one of them
would penalise paths that never cross the road at all. So node evidence is
applied only to the segment it is genuinely a property of: the crossing.

Absence is handled the same way it is everywhere else. ``barrier=kerb`` with no
``kerb=*`` says something is there and does *not* say whether it is dropped;
that is ``UNKNOWN``, and calling it ``RAISED`` would invent a barrier just as
surely as calling it ``FLUSH`` would invent a ramp.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from pathable_api.geo.enums import KerbType, TriState
from pathable_api.geo.features import EdgeFeatures, first_value, worst_of

#: How bad each kerb kind is for a wheeled user. Used to pick the worse of two
#: endpoints: a crossing dropped at one end and raised at the other is not a
#: dropped-kerb crossing.
#:
#: `PRESENT_UNKNOWN` sits above `ROLLED` deliberately: "there is a kerb here of
#: unrecorded height" could be a 15 cm step, so it must not be cheaper than a
#: known-traversable one, and it must be worse than the `UNKNOWN` of a node that
#: says nothing at all.
_KERB_SEVERITY: dict[KerbType, int] = {
    KerbType.NONE: 0,
    KerbType.FLUSH: 1,
    KerbType.LOWERED: 2,
    KerbType.UNKNOWN: 3,
    KerbType.ROLLED: 4,
    KerbType.PRESENT_UNKNOWN: 5,
    KerbType.RAISED: 6,
}

_NODE_KERB_VALUES: dict[str, KerbType] = {
    "flush": KerbType.FLUSH,
    "lowered": KerbType.LOWERED,
    "rolled": KerbType.ROLLED,
    "raised": KerbType.RAISED,
    "no": KerbType.NONE,
    "yes": KerbType.PRESENT_UNKNOWN,
}

#: Node kerb values, best-to-worst, derived from the severity table above so the
#: two orderings cannot drift apart.
NODE_KERB_RANKING: tuple[str, ...] = tuple(
    sorted(_NODE_KERB_VALUES, key=lambda value: _KERB_SEVERITY[_NODE_KERB_VALUES[value]])
)


@dataclass(frozen=True, slots=True)
class NodeEvidence:
    """What one OSM node says about accessibility."""

    kerb: KerbType = KerbType.UNKNOWN
    is_crossing_node: bool = False
    crossing_type: str | None = None
    tactile_paving: TriState = TriState.UNKNOWN
    barrier: str | None = None

    @property
    def is_informative(self) -> bool:
        """Whether this node is worth carrying at all."""
        return (
            self.kerb is not KerbType.UNKNOWN
            or self.is_crossing_node
            or self.tactile_paving is not TriState.UNKNOWN
            or self.barrier is not None
        )


def read_node_evidence(tags: dict[str, Any]) -> NodeEvidence:
    """Interpret one node's tags."""
    highway = first_value(tags.get("highway"))
    barrier = first_value(tags.get("barrier"))
    kerb_value, _conflicted = worst_of(tags.get("kerb"), NODE_KERB_RANKING)

    kerb = KerbType.UNKNOWN
    if kerb_value is not None:
        kerb = _NODE_KERB_VALUES.get(kerb_value, KerbType.UNKNOWN)
    elif barrier == "kerb":
        # `barrier=kerb` asserts a kerb exists; `kerb=*` is what states its
        # height. Calling this RAISED would invent a barrier and calling it
        # FLUSH would invent a ramp — but calling it UNKNOWN threw away the one
        # thing the mapper did tell us, which is that something is there.
        kerb = KerbType.PRESENT_UNKNOWN

    return NodeEvidence(
        kerb=kerb,
        is_crossing_node=highway == "crossing",
        crossing_type=first_value(tags.get("crossing")),
        tactile_paving=_tristate(tags.get("tactile_paving")),
        barrier=barrier,
    )


def apply_to_crossing(
    features: EdgeFeatures,
    start: NodeEvidence | None,
    end: NodeEvidence | None,
) -> EdgeFeatures:
    """Fold endpoint evidence into a crossing segment.

    Way tags win where they exist — somebody tagged the crossing itself and that
    is the more specific statement. Node evidence fills gaps only.

    Returns the features unchanged for anything that is not a crossing, which is
    what keeps a kerb from leaking onto every sidewalk that happens to touch it.
    """
    if not features.is_crossing:
        return features

    present = [node for node in (start, end) if node is not None]
    if not present:
        return features

    kerb = features.kerb
    kerb_from_node = False
    if kerb is KerbType.UNKNOWN:
        stated = [node.kerb for node in present if node.kerb is not KerbType.UNKNOWN]
        if stated:
            kerb = max(stated, key=_KERB_SEVERITY.__getitem__)
            kerb_from_node = True

    tactile = features.tactile_paving
    if tactile is TriState.UNKNOWN:
        stated_tactile = [
            node.tactile_paving for node in present if node.tactile_paving is not TriState.UNKNOWN
        ]
        if stated_tactile:
            # Tactile paving at one end only is not tactile paving at the
            # crossing; the conservative reading is the one that does not
            # promise a guide somebody may not find.
            tactile = (
                TriState.YES
                if all(value is TriState.YES for value in stated_tactile)
                else TriState.NO
            )

    crossing_type = features.crossing_type
    if crossing_type is None:
        for node in present:
            if node.crossing_type is not None:
                crossing_type = node.crossing_type
                break

    return replace(
        features,
        kerb=kerb,
        kerb_from_node=kerb_from_node,
        tactile_paving=tactile,
        crossing_type=crossing_type,
    )


def _tristate(raw: Any) -> TriState:
    value = first_value(raw)
    if value is None:
        return TriState.UNKNOWN
    if value in {"no", "false", "0"}:
        return TriState.NO
    return TriState.YES
