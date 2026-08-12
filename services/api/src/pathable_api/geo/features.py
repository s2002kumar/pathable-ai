"""Normalise raw OpenStreetMap tags into deterministic routing attributes.

Everything here is a *fact assertion or its absence*. Nothing is inferred,
predicted or guessed. The governing rule is that a missing tag yields
``UNKNOWN``, never ``NO`` — because OSM accessibility coverage is sparse, and the
places with the least data tend to be the least surveyed rather than the most
accessible.

There is exactly one place where absence legitimately implies ``NO``, and it is
documented at :func:`normalise_steps`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pathable_api.geo.enums import (
    AccessValue,
    KerbType,
    SmoothnessClass,
    SurfaceClass,
    TriState,
)

# --- Vocabularies -----------------------------------------------------------

_PAVED_SURFACES = {
    "paved",
    "asphalt",
    "concrete",
    "concrete:plates",
    "concrete:lanes",
    "paving_stones",
    "sett",
    "metal",
    "wood",
    "rubber",
    "tartan",
    "acrylic",
}
_COMPACTED_SURFACES = {"compacted", "fine_gravel", "gravel_turf", "chipseal"}
_ROUGH_SURFACES = {
    "unpaved",
    "gravel",
    "ground",
    "dirt",
    "earth",
    "grass",
    "sand",
    "mud",
    "cobblestone",
    "cobblestone:flattened",
    "pebblestone",
    "rock",
    "woodchips",
    "grass_paver",
}

_SMOOTHNESS_CLASSES = {
    "excellent": SmoothnessClass.EXCELLENT,
    "good": SmoothnessClass.GOOD,
    "intermediate": SmoothnessClass.INTERMEDIATE,
    "bad": SmoothnessClass.BAD,
    "very_bad": SmoothnessClass.BAD,
    "horrible": SmoothnessClass.BAD,
    "very_horrible": SmoothnessClass.BAD,
    "impassable": SmoothnessClass.BAD,
}

_ACCESS_VALUES = {
    "yes": AccessValue.YES,
    "designated": AccessValue.DESIGNATED,
    "permissive": AccessValue.PERMISSIVE,
    "destination": AccessValue.DESTINATION,
    "private": AccessValue.PRIVATE,
    "no": AccessValue.NO,
    "customers": AccessValue.DESTINATION,
    "official": AccessValue.DESIGNATED,
}

_KERB_VALUES = {
    "lowered": KerbType.LOWERED,
    "flush": KerbType.FLUSH,
    "raised": KerbType.RAISED,
    "rolled": KerbType.LOWERED,
    "no": KerbType.NONE,
}

#: `highway` values that are genuine walkable ways. Used by normalise_steps to
#: decide whether the source has said enough for "not stairs" to be a fact.
_WALKABLE_HIGHWAYS = {
    "footway",
    "path",
    "pedestrian",
    "steps",
    "living_street",
    "residential",
    "service",
    "track",
    "cycleway",
    "unclassified",
    "tertiary",
    "secondary",
    "primary",
    "corridor",
    "crossing",
    "elevator",
    "platform",
}

_INCLINE_PATTERN = re.compile(r"^(?P<sign>[-+]?)(?P<value>\d+(?:\.\d+)?)\s*%$")
_INCLINE_RATIO = re.compile(
    r"^(?P<sign>[-+]?)(?P<rise>\d+(?:\.\d+)?)\s*/\s*(?P<run>\d+(?:\.\d+)?)$"
)


def first_value(raw: Any) -> str | None:
    """Collapse an OSM tag value to a single lowercase string.

    OSMnx yields a list when several source ways were merged into one edge. A
    list means the source disagrees with itself, so the first value is taken and
    the raw tags remain available for anyone who needs the full picture.
    """
    if raw is None:
        return None
    if isinstance(raw, list):
        for item in raw:
            value = first_value(item)
            if value is not None:
                return value
        return None
    text = str(raw).strip().lower()
    return text or None


def _boolean_tag(raw: Any) -> TriState:
    """Map a yes/no-style tag to a tri-state, defaulting to unknown."""
    value = first_value(raw)
    if value is None:
        return TriState.UNKNOWN
    if value in {"yes", "true", "1"}:
        return TriState.YES
    if value in {"no", "false", "0"}:
        return TriState.NO
    # Values such as `lit=24/7` or `bridge=viaduct` assert presence.
    return TriState.YES


def normalise_access(raw: Any) -> AccessValue:
    """Normalise an access tag. Absence is unknown, not permission."""
    value = first_value(raw)
    if value is None:
        return AccessValue.UNKNOWN
    return _ACCESS_VALUES.get(value, AccessValue.UNKNOWN)


def normalise_steps(tags: dict[str, Any]) -> tuple[TriState, int | None]:
    """Decide whether a segment is a stairway, and how many steps it has.

    This is the one place where a missing tag legitimately means ``NO``, and the
    reason is OSM's own data model: stairs are not an attribute of a way, they
    are a *way type* (``highway=steps``). A mapper who classified a segment as
    ``highway=footway`` has positively asserted it is a footway and not a
    stairway. Treating that as "unknown steps" would make almost every edge in
    the network uncertain and the uncertainty signal meaningless.

    If ``highway`` is missing or unrecognised, the source has told us nothing and
    the answer stays ``UNKNOWN``.
    """
    highway = first_value(tags.get("highway"))
    step_count = _positive_int(tags.get("step_count"))

    if highway == "steps":
        return TriState.YES, step_count

    # An explicit conveying/ramp tag on a steps way is still a steps way; the
    # cost model decides what that is worth, not this function.
    if highway in _WALKABLE_HIGHWAYS:
        return TriState.NO, None

    return TriState.UNKNOWN, step_count


def normalise_surface(raw: Any) -> tuple[str | None, SurfaceClass]:
    """Return the raw surface value and its coarse class."""
    value = first_value(raw)
    if value is None:
        return None, SurfaceClass.UNKNOWN
    if value in _PAVED_SURFACES:
        return value, SurfaceClass.PAVED
    if value in _COMPACTED_SURFACES:
        return value, SurfaceClass.COMPACTED
    if value in _ROUGH_SURFACES:
        return value, SurfaceClass.ROUGH
    # A surface value we do not recognise is still not evidence of smoothness.
    return value, SurfaceClass.UNKNOWN


def normalise_smoothness(raw: Any) -> tuple[str | None, SmoothnessClass]:
    value = first_value(raw)
    if value is None:
        return None, SmoothnessClass.UNKNOWN
    return value, _SMOOTHNESS_CLASSES.get(value, SmoothnessClass.UNKNOWN)


def normalise_incline(raw: Any) -> float | None:
    """Parse an incline tag into a signed percentage.

    ``up``/``down`` carry direction but no magnitude, so they yield ``None``:
    a direction without a gradient cannot be costed, and guessing a number would
    manufacture precision the source never provided.
    """
    value = first_value(raw)
    if value is None:
        return None

    match = _INCLINE_PATTERN.match(value)
    if match:
        magnitude = float(match.group("value"))
        return -magnitude if match.group("sign") == "-" else magnitude

    ratio = _INCLINE_RATIO.match(value)
    if ratio:
        run = float(ratio.group("run"))
        if run == 0:
            return None
        magnitude = float(ratio.group("rise")) / run * 100.0
        return -magnitude if ratio.group("sign") == "-" else magnitude

    return None


def normalise_kerb(tags: dict[str, Any]) -> KerbType:
    value = first_value(tags.get("kerb")) or first_value(tags.get("curb"))
    if value is None:
        return KerbType.UNKNOWN
    return _KERB_VALUES.get(value, KerbType.UNKNOWN)


def _positive_int(raw: Any) -> int | None:
    value = first_value(raw)
    if value is None:
        return None
    try:
        parsed = int(float(value))
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _positive_float(raw: Any) -> float | None:
    value = first_value(raw)
    if value is None:
        return None
    try:
        parsed = float(re.sub(r"[^\d.\-]", "", value) or "nan")
    except ValueError:
        return None
    return parsed if parsed > 0 else None


@dataclass(frozen=True, slots=True)
class EdgeFeatures:
    """Deterministic accessibility attributes derived from source tags."""

    highway: str | None = None
    foot_access: AccessValue = AccessValue.UNKNOWN
    general_access: AccessValue = AccessValue.UNKNOWN
    steps: TriState = TriState.UNKNOWN
    step_count: int | None = None
    surface: str | None = None
    surface_class: SurfaceClass = SurfaceClass.UNKNOWN
    smoothness: str | None = None
    smoothness_class: SmoothnessClass = SmoothnessClass.UNKNOWN
    incline_percent: float | None = None
    kerb: KerbType = KerbType.UNKNOWN
    sidewalk: str | None = None
    is_crossing: bool = False
    crossing_type: str | None = None
    lit: TriState = TriState.UNKNOWN
    indoor: TriState = TriState.UNKNOWN
    bridge: TriState = TriState.UNKNOWN
    tunnel: TriState = TriState.UNKNOWN
    width_m: float | None = None
    raw_tags: dict[str, Any] = field(default_factory=dict)

    @property
    def unknown_attributes(self) -> tuple[str, ...]:
        """Routing-relevant attributes the source did not tell us about.

        Drives the uncertainty penalty and the user-facing "missing data"
        warnings. Deliberately excludes attributes that are irrelevant to
        mobility, so the warning stays meaningful.
        """
        missing: list[str] = []
        if self.surface_class is SurfaceClass.UNKNOWN:
            missing.append("surface")
        if self.smoothness_class is SmoothnessClass.UNKNOWN:
            missing.append("smoothness")
        if self.incline_percent is None:
            missing.append("incline")
        if self.is_crossing and self.kerb is KerbType.UNKNOWN:
            missing.append("kerb")
        if self.steps is TriState.UNKNOWN:
            missing.append("steps")
        return tuple(missing)


def normalise_edge(tags: dict[str, Any]) -> EdgeFeatures:
    """Derive :class:`EdgeFeatures` from one edge's raw source tags."""
    highway = first_value(tags.get("highway"))
    steps, step_count = normalise_steps(tags)
    surface, surface_class = normalise_surface(tags.get("surface"))
    smoothness, smoothness_class = normalise_smoothness(tags.get("smoothness"))
    crossing_type = first_value(tags.get("crossing"))

    return EdgeFeatures(
        highway=highway,
        foot_access=normalise_access(tags.get("foot")),
        general_access=normalise_access(tags.get("access")),
        steps=steps,
        step_count=step_count,
        surface=surface,
        surface_class=surface_class,
        smoothness=smoothness,
        smoothness_class=smoothness_class,
        incline_percent=normalise_incline(tags.get("incline")),
        kerb=normalise_kerb(tags),
        sidewalk=first_value(tags.get("sidewalk")),
        is_crossing=highway == "crossing" or crossing_type is not None,
        crossing_type=crossing_type,
        lit=_boolean_tag(tags.get("lit")),
        indoor=_boolean_tag(tags.get("indoor")),
        bridge=_boolean_tag(tags.get("bridge")),
        tunnel=_boolean_tag(tags.get("tunnel")),
        width_m=_positive_float(tags.get("width")),
        raw_tags={key: value for key, value in tags.items() if value is not None},
    )
