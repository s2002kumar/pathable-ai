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

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from pathable_api.geo.directionality import (
    Conveying,
    normalise_conveying,
    normalise_foot_direction,
    vehicle_oneway_is_ignored,
)
from pathable_api.geo.enums import (
    AccessValue,
    InclineDirection,
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
    "rolled": KerbType.ROLLED,
    "no": KerbType.NONE,
    # "Some sort of kerb is present, but it can't or hasn't yet been determined
    # whether it is raised, lowered, flush, etc." — Key:kerb.
    "yes": KerbType.PRESENT_UNKNOWN,
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

#: Surface values ordered best-to-worst for wheeled mobility. Used to resolve a
#: merged segment that carries several surfaces: the rough part is still there.
_SURFACE_RANKING: tuple[str, ...] = (
    "asphalt",
    "concrete",
    "paved",
    "concrete:plates",
    "concrete:lanes",
    "paving_stones",
    "metal",
    "wood",
    "rubber",
    "tartan",
    "acrylic",
    "chipseal",
    "compacted",
    "fine_gravel",
    "gravel_turf",
    "sett",
    "cobblestone:flattened",
    "cobblestone",
    "pebblestone",
    "grass_paver",
    "unpaved",
    "gravel",
    "woodchips",
    "ground",
    "dirt",
    "earth",
    "grass",
    "rock",
    "sand",
    "mud",
)

#: Smoothness values ordered best-to-worst, matching the OSM scale.
_SMOOTHNESS_RANKING: tuple[str, ...] = (
    "excellent",
    "good",
    "intermediate",
    "bad",
    "very_bad",
    "horrible",
    "very_horrible",
    "impassable",
)

#: Kerb values ordered best-to-worst for a wheeled user.
#: Kerb values best-to-worst, so a merged segment resolves to the worse one.
#: `no` leads because "no kerb is present" is the best possible case — it was
#: previously ranked below `lowered`, which made an explicit "there is no kerb
#: here" lose to a kerb.
_KERB_RANKING: tuple[str, ...] = ("no", "flush", "lowered", "rolled", "yes", "raised")

#: A percentage, with the `%` optional: `incline=10` is used ~5,000 times and
#: means the same thing.
_INCLINE_PATTERN = re.compile(r"^(?P<sign>[-+]?)(?P<value>\d+(?:\.\d+)?)\s*%?$")

#: Degrees, which the wiki documents alongside percent: gradient = tan(angle).
_INCLINE_DEGREES = re.compile(r"^(?P<sign>[-+]?)(?P<value>\d+(?:\.\d+)?)\s*(?:°|deg)$")
_INCLINE_RATIO = re.compile(
    r"^(?P<sign>[-+]?)(?P<rise>\d+(?:\.\d+)?)\s*/\s*(?P<run>\d+(?:\.\d+)?)$"
)


def all_values(raw: Any) -> tuple[str, ...]:
    """Every distinct lowercase value a tag carries, in source order.

    OSMnx yields a list when several source ways were merged into one edge, which
    means the merged segment genuinely has two different answers.
    """
    if raw is None:
        return ()
    if isinstance(raw, list):
        seen: list[str] = []
        for item in raw:
            for value in all_values(item):
                if value not in seen:
                    seen.append(value)
        return tuple(seen)
    text = str(raw).strip().lower()
    return (text,) if text else ()


def is_conflicted(raw: Any) -> bool:
    """True when a merged segment carries more than one value for a tag."""
    return len(all_values(raw)) > 1


def first_value(raw: Any) -> str | None:
    """Collapse an OSM tag value to a single lowercase string.

    Only for attributes where disagreement is not route-critical. Anything that
    decides whether a person can pass must go through a conflict-aware
    normaliser instead — see `worst_of`, which resolves conservatively rather
    than letting whichever way happened to be listed first decide.
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


def worst_of(raw: Any, ranking: Sequence[str]) -> tuple[str | None, bool]:
    """Resolve a possibly-conflicting tag to its least favourable value.

    Returns ``(value, conflicted)``. When a merged segment says both ``paved``
    and ``gravel``, the honest answer for somebody deciding whether they can get
    through is ``gravel`` — the segment really does contain some. "First value
    wins" would make the answer depend on which way the merge happened to run.

    ``ranking`` runs best-to-worst; values outside it are treated as worse than
    anything known, because an unrecognised value is not evidence of quality.
    """
    values = all_values(raw)
    if not values:
        return None, False
    if len(values) == 1:
        return values[0], False

    def rank(value: str) -> int:
        try:
            return ranking.index(value)
        except ValueError:
            return len(ranking)

    return max(values, key=rank), True


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
    """Return the surface value and its coarse class, resolved conservatively."""
    value, _conflicted = worst_of(raw, _SURFACE_RANKING)
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
    value, _conflicted = worst_of(raw, _SMOOTHNESS_RANKING)
    if value is None:
        return None, SmoothnessClass.UNKNOWN
    return value, _SMOOTHNESS_CLASSES.get(value, SmoothnessClass.UNKNOWN)


def normalise_incline_direction(raw: Any) -> InclineDirection:
    """Read the direction of a slope, which most incline tags give and no more.

    ``up``/``down`` are ~85% of incline tagging. They are kept as direction and
    never converted to a number — see :func:`normalise_incline`.
    """
    value = first_value(raw)
    if value is None:
        return InclineDirection.UNKNOWN
    if value == "up":
        return InclineDirection.UP
    if value == "down":
        return InclineDirection.DOWN

    percent = normalise_incline(raw)
    if percent is None or percent == 0:
        return InclineDirection.UNKNOWN
    return InclineDirection.UP if percent > 0 else InclineDirection.DOWN


def normalise_incline(raw: Any) -> float | None:
    """Parse an incline tag into a signed percentage.

    ``up``/``down`` carry direction but no magnitude, so they yield ``None``
    here: guessing a number would manufacture precision the source never
    provided. The direction they do carry is not lost — it is read by
    :func:`normalise_incline_direction` into a separate field.
    """
    value = first_value(raw)
    if value is None:
        return None

    degrees = _INCLINE_DEGREES.match(value)
    if degrees:
        magnitude = math.tan(math.radians(float(degrees.group("value")))) * 100.0
        return -magnitude if degrees.group("sign") == "-" else magnitude

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
    """Resolve a kerb value, taking the worst when a merged segment disagrees."""
    raw = tags.get("kerb") if tags.get("kerb") is not None else tags.get("curb")
    value, _conflicted = worst_of(raw, _KERB_RANKING)
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
    #: Direction of a slope the source described without a number (`incline=up`).
    #: Carried separately because it is real evidence — most of OSM's incline
    #: tagging is exactly this — but must never be turned into a percentage.
    incline_direction: InclineDirection = InclineDirection.UNKNOWN
    kerb: KerbType = KerbType.UNKNOWN
    sidewalk: str | None = None
    is_crossing: bool = False
    crossing_type: str | None = None
    tactile_paving: TriState = TriState.UNKNOWN
    #: True when the kerb came from an OSM node rather than the crossing way.
    #: Both are real evidence; a route explanation should be able to say which.
    kerb_from_node: bool = False
    lit: TriState = TriState.UNKNOWN
    indoor: TriState = TriState.UNKNOWN
    bridge: TriState = TriState.UNKNOWN
    tunnel: TriState = TriState.UNKNOWN
    width_m: float | None = None

    # --- Direction-dependent ----------------------------------------------
    #: Grade derived from elevation, signed for the direction of travel.
    #: Kept separate from `incline_percent` so an OSM-reported incline and a
    #: value we computed never overwrite one another.
    derived_grade_percent: float | None = None
    conveying: Conveying = Conveying.NONE

    # --- Source quality ----------------------------------------------------
    #: Route-critical tags where a merged segment carried more than one value.
    #: Resolved conservatively; recorded so a surprising cost can be explained.
    conflicting_attributes: tuple[str, ...] = ()
    #: A plain `oneway` existed and was deliberately not applied to foot travel.
    vehicle_oneway_ignored: bool = False
    #: Directionality was stated in a way that could not be read. The segment
    #: stays passable and the doubt is surfaced rather than silently resolved.
    ambiguous_direction: bool = False

    raw_tags: dict[str, Any] = field(default_factory=dict)

    def reversed(self) -> EdgeFeatures:
        """The same physical segment, described for travel the other way.

        Only direction-dependent facts change. A 6% climb is a 6% descent from
        the other end, and treating the stored sign as absolute is how a router
        sends a wheelchair user up a ramp it believes goes down.
        """
        return replace(
            self,
            incline_percent=(None if self.incline_percent is None else -self.incline_percent),
            incline_direction=self.incline_direction.reversed(),
            derived_grade_percent=(
                None if self.derived_grade_percent is None else -self.derived_grade_percent
            ),
            conveying=self.conveying.reversed(),
        )

    @property
    def effective_grade_percent(self) -> float | None:
        """The grade to route on, preferring what the map actually says.

        An OSM `incline` is somebody's assertion about this specific path.
        Elevation-derived grade is our inference from a terrain model that knows
        nothing about the path — useful where the map is silent, but it should
        not overrule a surveyor.
        """
        if self.incline_percent is not None:
            return self.incline_percent
        return self.derived_grade_percent

    @property
    def grade_source(self) -> str | None:
        """Where `effective_grade_percent` came from, or None when unknown."""
        if self.incline_percent is not None:
            return "osm_incline"
        if self.derived_grade_percent is not None:
            return "derived_elevation"
        return None

    @property
    def grade_disagreement_percent(self) -> float | None:
        """How far the derived grade sits from the mapped one, when both exist.

        Surfaced as a diagnostic rather than resolved: a large disagreement
        usually means the elevation model is too coarse for the path, or the
        incline tag is wrong, and both are worth a human knowing.
        """
        if self.incline_percent is None or self.derived_grade_percent is None:
            return None
        return self.derived_grade_percent - self.incline_percent

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
        if self.effective_grade_percent is None:
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
    direction = normalise_foot_direction(tags)

    # `highway=footway` + `footway=crossing` is the standard way to map a road
    # crossing, and it is far more common than `highway=crossing`. Missing it
    # meant every kerb mapped on a crossing node had nothing to attach to.
    footway_kind = first_value(tags.get("footway"))
    cycleway_kind = first_value(tags.get("cycleway"))
    # `crossing=no` means "definitely no crossing possible/legal" and
    # `crossing=separate` means the crossing is mapped as its own element. Both
    # were being read as *evidence of* a crossing, which inverted the tag and
    # charged a crossing penalty on a segment the mapper marked as not one.
    is_crossing = (
        highway == "crossing"
        or footway_kind == "crossing"
        or cycleway_kind == "crossing"
        or crossing_type not in (None, "no", "separate")
    )

    # Route-critical tags where the source disagreed with itself. Each was
    # resolved to its least favourable value; recording which ones lets a
    # surprising cost be explained instead of merely suffered.
    conflicting = tuple(
        name
        for name in ("surface", "smoothness", "incline", "width", "kerb", "foot", "access")
        if is_conflicted(tags.get(name))
    )

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
        incline_direction=normalise_incline_direction(tags.get("incline")),
        kerb=normalise_kerb(tags),
        sidewalk=first_value(tags.get("sidewalk")),
        is_crossing=is_crossing,
        crossing_type=crossing_type,
        tactile_paving=_boolean_tag(tags.get("tactile_paving")),
        lit=_boolean_tag(tags.get("lit")),
        indoor=_boolean_tag(tags.get("indoor")),
        bridge=_boolean_tag(tags.get("bridge")),
        tunnel=_boolean_tag(tags.get("tunnel")),
        width_m=_positive_float(tags.get("width")),
        conveying=normalise_conveying(tags),
        conflicting_attributes=conflicting,
        vehicle_oneway_ignored=vehicle_oneway_is_ignored(tags) is TriState.YES,
        ambiguous_direction=direction.ambiguous,
        raw_tags={key: value for key, value in tags.items() if value is not None},
    )
