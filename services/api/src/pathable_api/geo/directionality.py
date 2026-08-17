"""Which way a person may walk along a segment.

Vehicle one-way restrictions are not pedestrian restrictions. A person walking
along a one-way street walks in either direction, and a router that copies
`oneway=yes` onto foot travel invents prohibitions that do not exist — which for
this product means inventing a detour, or a "no route", for somebody who had a
perfectly good path.

So plain ``oneway`` is ignored for pedestrians. Only tags that speak about foot
travel are honoured:

* ``oneway:foot`` — the explicit statement
* ``foot:forward`` / ``foot:backward`` — per-direction access
* ``conveying`` — an escalator or moving walkway physically runs one way

"Forward" and "backward" are relative to the *way's own node order*, which is why
this has to be resolved before a segment is stored: once geometry is reversed,
the words mean the opposite thing.

Ambiguity stays permissive and is recorded. A conflicting or unparseable value
must not silently become a barrier — the two errors are not symmetric, and
refusing a passable path is the failure this module exists to avoid, while a
genuinely blocked path is caught by access tags and by the cost model.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pathable_api.geo.enums import TriState

#: Values meaning "not passable this way".
_DENY = {"no", "false", "0"}
#: Values meaning "passable".
_ALLOW = {"yes", "true", "1", "designated", "permissive", "destination", "official"}
#: `oneway`-style values that reverse the way's own direction.
_REVERSED = {"-1", "reverse", "backward"}


class Conveying(StrEnum):
    """An escalator or moving walkway, and which way it carries people."""

    NONE = "none"
    FORWARD = "forward"
    BACKWARD = "backward"
    REVERSIBLE = "reversible"
    #: Tagged as conveying, but the direction is not recorded.
    UNKNOWN_DIRECTION = "unknown_direction"

    def reversed(self) -> Conveying:
        if self is Conveying.FORWARD:
            return Conveying.BACKWARD
        if self is Conveying.BACKWARD:
            return Conveying.FORWARD
        return self


@dataclass(frozen=True, slots=True)
class FootDirection:
    """Whether a person may walk each way along a segment, and why."""

    forward: bool = True
    backward: bool = True
    #: The tag that produced a restriction, for explanation and for debugging a
    #: surprising route. Empty when the segment is ordinary two-way.
    reason: str = ""
    #: True when the source said something about direction that could not be
    #: read. The segment stays passable both ways and the flag is surfaced.
    ambiguous: bool = False

    @property
    def is_one_way(self) -> bool:
        return self.forward != self.backward

    @property
    def is_passable(self) -> bool:
        return self.forward or self.backward

    def reversed(self) -> FootDirection:
        """The same restriction seen from the other end of the segment."""
        return FootDirection(
            forward=self.backward,
            backward=self.forward,
            reason=self.reason,
            ambiguous=self.ambiguous,
        )


TWO_WAY = FootDirection()


def _value(raw: Any) -> str | None:
    """First usable lowercase value, collapsing OSMnx's merged-way lists."""
    if raw is None:
        return None
    if isinstance(raw, list):
        for item in raw:
            value = _value(item)
            if value is not None:
                return value
        return None
    text = str(raw).strip().lower()
    return text or None


def normalise_conveying(tags: dict[str, Any]) -> Conveying:
    """Read ``conveying`` — an escalator physically runs one way."""
    value = _value(tags.get("conveying"))
    if value is None:
        return Conveying.NONE
    if value in _DENY:
        return Conveying.NONE
    if value == "forward":
        return Conveying.FORWARD
    if value in _REVERSED:
        return Conveying.BACKWARD
    if value == "reversible":
        return Conveying.REVERSIBLE
    if value in _ALLOW:
        # `conveying=yes` says there is a moving surface but not which way.
        return Conveying.UNKNOWN_DIRECTION
    return Conveying.UNKNOWN_DIRECTION


def normalise_foot_direction(tags: dict[str, Any]) -> FootDirection:
    """Decide which directions a person may walk, from foot-specific tags only.

    Order matters: the most specific statement wins. ``foot:forward=no`` is a
    direct claim about one direction and beats a general ``oneway:foot``.
    """
    forward = True
    backward = True
    reasons: list[str] = []
    ambiguous = False

    # --- conveying: a physical constraint, not a legal one -----------------
    conveying = normalise_conveying(tags)
    if conveying is Conveying.FORWARD:
        backward = False
        reasons.append("conveying=forward")
    elif conveying is Conveying.BACKWARD:
        forward = False
        reasons.append("conveying=backward")
    elif conveying is Conveying.UNKNOWN_DIRECTION:
        # Something moves here and we do not know which way. Refusing both
        # directions would delete a real connection; refusing neither is the
        # permissive default, and the ambiguity is recorded.
        ambiguous = True
        reasons.append("conveying without a direction")

    # --- oneway:foot -------------------------------------------------------
    oneway_foot = _value(tags.get("oneway:foot"))
    if oneway_foot is not None:
        if oneway_foot in _DENY:
            forward = backward = True
            reasons.append("oneway:foot=no")
        elif oneway_foot in _REVERSED:
            forward, backward = False, True
            reasons.append("oneway:foot=-1")
        elif oneway_foot in _ALLOW:
            forward, backward = True, False
            reasons.append("oneway:foot=yes")
        else:
            ambiguous = True
            reasons.append(f"unreadable oneway:foot={oneway_foot!r}")

    # --- per-direction foot access, the most specific statement ------------
    for tag, sets_forward in (("foot:forward", True), ("foot:backward", False)):
        value = _value(tags.get(tag))
        if value is None:
            continue
        if value in _DENY:
            if sets_forward:
                forward = False
            else:
                backward = False
            reasons.append(f"{tag}=no")
        elif value in _ALLOW:
            if sets_forward:
                forward = True
            else:
                backward = True
            reasons.append(f"{tag}={value}")
        else:
            ambiguous = True
            reasons.append(f"unreadable {tag}={value!r}")

    # A segment nobody may walk either way is almost always a tagging mistake
    # rather than a wall. Keep it passable and flag it: access tags and the cost
    # model handle genuine prohibition, and silently deleting a connection is the
    # failure that produces a phantom "no route".
    if not forward and not backward:
        forward = backward = True
        ambiguous = True
        reasons.append("both directions denied; treated as two-way")

    return FootDirection(
        forward=forward,
        backward=backward,
        reason="; ".join(reasons),
        ambiguous=ambiguous,
    )


def vehicle_oneway_is_ignored(tags: dict[str, Any]) -> TriState:
    """Whether a plain ``oneway`` was present and deliberately not applied.

    Reported rather than acted on. Someone reading a route's evidence should be
    able to see that a vehicle restriction existed and that PathAble chose not to
    treat it as a pedestrian one.
    """
    value = _value(tags.get("oneway"))
    if value is None:
        return TriState.UNKNOWN
    return TriState.YES if value not in _DENY else TriState.NO
