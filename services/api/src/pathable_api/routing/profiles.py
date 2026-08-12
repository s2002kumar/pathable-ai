"""Mobility profiles.

A profile is a statement about what a person needs, expressed in two parts that
must stay separate:

* **Hard constraints** exclude a segment outright. Use them only where using the
  segment is genuinely not possible — a stairway in a wheelchair, a path too
  narrow for the chair to fit. A hard constraint can make a journey unroutable,
  which is sometimes the honest answer and is always better than routing someone
  into a barrier.
* **Penalties** make a segment cost more without forbidding it. Everything that
  is "harder" rather than "impossible" belongs here: rough surface, a steep but
  passable grade, an unrecorded kerb.

The numbers are *effective metres* — how far a segment feels, not how far it is.
That keeps the model explainable: a 100 m gravel path costing 250 effective
metres means "this feels like two and a half times the distance", which is
something a person can evaluate and disagree with.

These values are engineering judgement, not measurements. They have not been
validated against how real people with these mobility aids actually travel, and
nothing in the product may present them as if they had been.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from pathable_api.geo.enums import KerbType, SmoothnessClass, SurfaceClass

#: Profiles a client may request by name.
STANDARD_PROFILE_KEY: Final = "standard"
DEFAULT_ACCESSIBLE_PROFILE_KEY: Final = "wheelchair"


@dataclass(frozen=True, slots=True)
class MobilityProfile:
    """How one traveller experiences the network."""

    key: str
    display_name: str
    description: str

    # --- Hard constraints -------------------------------------------------
    #: Stairs are impassable, not merely unpleasant.
    exclude_steps: bool = False
    #: Gradients above this are excluded. Only applied where the gradient is
    #: *known*; an unrecorded slope is handled as uncertainty, not as flat.
    max_incline_percent: float | None = None
    #: Excluded when the recorded width is below this. A missing width never
    #: excludes anything.
    min_width_m: float | None = None
    excluded_surface_classes: frozenset[SurfaceClass] = frozenset()
    excluded_smoothness_classes: frozenset[SmoothnessClass] = frozenset()

    # --- Penalties, as multiples of the segment's own length --------------
    surface_penalty: Mapping[SurfaceClass, float] = field(default_factory=dict)
    smoothness_penalty: Mapping[SmoothnessClass, float] = field(default_factory=dict)
    #: Extra cost per percentage point of gradient above `comfortable_incline_percent`.
    incline_penalty_per_percent: float = 0.0
    comfortable_incline_percent: float = 3.0
    #: Cost added for each routing-relevant attribute the source never recorded.
    #: This is what stops "no data" from being the cheapest way through.
    uncertainty_penalty_per_attribute: float = 0.0

    # --- Penalties, in flat effective metres ------------------------------
    step_penalty_m: float = 0.0
    per_step_penalty_m: float = 0.0
    #: Applied when a step count is unknown but the segment is known to be stairs.
    assumed_step_count: int = 10
    kerb_penalty_m: Mapping[KerbType, float] = field(default_factory=dict)
    crossing_penalty_m: float = 0.0
    unlit_penalty_m: float = 0.0

    @property
    def is_standard(self) -> bool:
        """True for the plain shortest-path baseline."""
        return self.key == STANDARD_PROFILE_KEY


#: The baseline everything is compared against: shortest walking distance, with
#: no accessibility preferences at all. It still refuses segments where foot
#: access is prohibited, because that is a legal fact about the way rather than
#: a preference.
STANDARD = MobilityProfile(
    key=STANDARD_PROFILE_KEY,
    display_name="Standard walking",
    description="Shortest walking route, ignoring accessibility characteristics.",
)

WHEELCHAIR = MobilityProfile(
    key="wheelchair",
    display_name="Wheelchair",
    description=(
        "Avoids steps entirely, prefers paved and smooth surfaces, and treats "
        "unrecorded kerbs and surfaces as risks rather than as clear paths."
    ),
    exclude_steps=True,
    # 8% is the steepest ramp gradient most accessibility guidance considers
    # independently usable; beyond it a route is not a route.
    max_incline_percent=8.0,
    min_width_m=0.90,
    excluded_surface_classes=frozenset({SurfaceClass.ROUGH}),
    excluded_smoothness_classes=frozenset({SmoothnessClass.BAD}),
    surface_penalty={SurfaceClass.COMPACTED: 0.8, SurfaceClass.UNKNOWN: 0.5},
    smoothness_penalty={SmoothnessClass.INTERMEDIATE: 0.7, SmoothnessClass.UNKNOWN: 0.4},
    incline_penalty_per_percent=0.55,
    comfortable_incline_percent=2.0,
    uncertainty_penalty_per_attribute=0.30,
    kerb_penalty_m={KerbType.RAISED: 400.0, KerbType.UNKNOWN: 90.0},
    crossing_penalty_m=25.0,
)

WALKER = MobilityProfile(
    key="walker",
    display_name="Walker or rollator",
    description=(
        "Avoids steps, prefers even surfaces and gentle grades, and tolerates a "
        "narrower path than a wheelchair needs."
    ),
    exclude_steps=True,
    max_incline_percent=10.0,
    min_width_m=0.75,
    excluded_smoothness_classes=frozenset({SmoothnessClass.BAD}),
    surface_penalty={
        SurfaceClass.COMPACTED: 0.5,
        SurfaceClass.ROUGH: 2.0,
        SurfaceClass.UNKNOWN: 0.4,
    },
    smoothness_penalty={SmoothnessClass.INTERMEDIATE: 0.5, SmoothnessClass.UNKNOWN: 0.3},
    incline_penalty_per_percent=0.45,
    comfortable_incline_percent=2.5,
    uncertainty_penalty_per_attribute=0.25,
    kerb_penalty_m={KerbType.RAISED: 200.0, KerbType.UNKNOWN: 60.0},
    crossing_penalty_m=20.0,
)

CRUTCHES = MobilityProfile(
    key="crutches",
    display_name="Crutches or cane",
    description=(
        "Steps are possible but costly; steep grades, loose surfaces and long detours all matter."
    ),
    max_incline_percent=15.0,
    surface_penalty={
        SurfaceClass.COMPACTED: 0.4,
        SurfaceClass.ROUGH: 1.6,
        SurfaceClass.UNKNOWN: 0.35,
    },
    smoothness_penalty={
        SmoothnessClass.INTERMEDIATE: 0.4,
        SmoothnessClass.BAD: 1.8,
        SmoothnessClass.UNKNOWN: 0.3,
    },
    incline_penalty_per_percent=0.5,
    comfortable_incline_percent=3.0,
    uncertainty_penalty_per_attribute=0.2,
    # Stairs are usable on crutches, and pretending otherwise would send someone
    # on a needless detour — but each step is real effort.
    step_penalty_m=60.0,
    per_step_penalty_m=12.0,
    kerb_penalty_m={KerbType.RAISED: 40.0, KerbType.UNKNOWN: 20.0},
    crossing_penalty_m=15.0,
)

STROLLER = MobilityProfile(
    key="stroller",
    display_name="Stroller or pram",
    description="Avoids steps, prefers dropped kerbs and even surfaces.",
    exclude_steps=True,
    max_incline_percent=12.0,
    min_width_m=0.70,
    surface_penalty={
        SurfaceClass.COMPACTED: 0.4,
        SurfaceClass.ROUGH: 1.5,
        SurfaceClass.UNKNOWN: 0.3,
    },
    smoothness_penalty={
        SmoothnessClass.INTERMEDIATE: 0.35,
        SmoothnessClass.BAD: 1.5,
        SmoothnessClass.UNKNOWN: 0.25,
    },
    incline_penalty_per_percent=0.3,
    comfortable_incline_percent=4.0,
    uncertainty_penalty_per_attribute=0.15,
    kerb_penalty_m={KerbType.RAISED: 120.0, KerbType.UNKNOWN: 40.0},
    crossing_penalty_m=15.0,
)

REDUCED_MOBILITY = MobilityProfile(
    key="reduced_mobility",
    display_name="Reduced mobility",
    description=(
        "Walks unaided but tires easily: prefers shorter, flatter, smoother "
        "routes and avoids long stairways."
    ),
    max_incline_percent=15.0,
    surface_penalty={SurfaceClass.ROUGH: 1.0, SurfaceClass.UNKNOWN: 0.2},
    smoothness_penalty={SmoothnessClass.BAD: 1.2, SmoothnessClass.UNKNOWN: 0.2},
    incline_penalty_per_percent=0.4,
    comfortable_incline_percent=3.5,
    uncertainty_penalty_per_attribute=0.12,
    step_penalty_m=40.0,
    per_step_penalty_m=6.0,
    kerb_penalty_m={KerbType.RAISED: 30.0, KerbType.UNKNOWN: 12.0},
    crossing_penalty_m=10.0,
)

PROFILES: Final[Mapping[str, MobilityProfile]] = {
    profile.key: profile
    for profile in (STANDARD, WHEELCHAIR, WALKER, CRUTCHES, STROLLER, REDUCED_MOBILITY)
}

#: Profiles a person can pick in the UI — the standard baseline is not a mobility
#: profile, it is the thing the others are compared against.
SELECTABLE_PROFILE_KEYS: Final[tuple[str, ...]] = (
    "wheelchair",
    "walker",
    "crutches",
    "stroller",
    "reduced_mobility",
)


class UnknownProfileError(KeyError):
    """Raised when a caller names a profile that does not exist."""


def get_profile(key: str) -> MobilityProfile:
    try:
        return PROFILES[key]
    except KeyError as error:
        known = ", ".join(sorted(PROFILES))
        msg = f"Unknown mobility profile {key!r}. Known profiles: {known}"
        raise UnknownProfileError(msg) from error


def build_custom_profile(
    *,
    base: str = DEFAULT_ACCESSIBLE_PROFILE_KEY,
    exclude_steps: bool | None = None,
    max_incline_percent: float | None = None,
    min_width_m: float | None = None,
    avoid_rough_surface: bool | None = None,
) -> MobilityProfile:
    """Derive a profile from a preset with a few overrides.

    Deliberately narrow. Exposing every weight would let a caller construct a
    cost model nobody has thought about, and the resulting route would still be
    presented with PathAble's name on it.
    """
    template = get_profile(base)
    excluded_surfaces = template.excluded_surface_classes
    if avoid_rough_surface is not None:
        excluded_surfaces = frozenset({SurfaceClass.ROUGH}) if avoid_rough_surface else frozenset()

    return MobilityProfile(
        key="custom",
        display_name="Custom",
        description=f"Custom preferences based on the {template.display_name.lower()} profile.",
        exclude_steps=(template.exclude_steps if exclude_steps is None else exclude_steps),
        max_incline_percent=(
            template.max_incline_percent if max_incline_percent is None else max_incline_percent
        ),
        min_width_m=template.min_width_m if min_width_m is None else min_width_m,
        excluded_surface_classes=excluded_surfaces,
        excluded_smoothness_classes=template.excluded_smoothness_classes,
        surface_penalty=template.surface_penalty,
        smoothness_penalty=template.smoothness_penalty,
        incline_penalty_per_percent=template.incline_penalty_per_percent,
        comfortable_incline_percent=template.comfortable_incline_percent,
        uncertainty_penalty_per_attribute=template.uncertainty_penalty_per_attribute,
        step_penalty_m=template.step_penalty_m,
        per_step_penalty_m=template.per_step_penalty_m,
        kerb_penalty_m=template.kerb_penalty_m,
        crossing_penalty_m=template.crossing_penalty_m,
        unlit_penalty_m=template.unlit_penalty_m,
    )
