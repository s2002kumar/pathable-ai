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
from dataclasses import dataclass, field, replace
from typing import Final

from pathable_api.geo.enums import KerbType, SmoothnessClass, SurfaceClass

#: Profiles a client may request by name.
STANDARD_PROFILE_KEY: Final = "standard"
DEFAULT_ACCESSIBLE_PROFILE_KEY: Final = "wheelchair"

#: Bumped whenever a change here would move a route. Returned with every route so
#: two results can be compared, and so a stored evaluation says which policy
#: produced it.
#:
#: 2 — preset thresholds became penalties rather than exclusions. Before this,
#:     a wheelchair preset silently deleted every segment steeper than 8%,
#:     narrower than 0.90 m or rougher than paved, which stated a physical
#:     impossibility the product had no basis for.
ROUTING_POLICY_VERSION: Final = 2


@dataclass(frozen=True, slots=True)
class HardLimits:
    """Requirements a traveller **declared**, not thresholds a preset assumed.

    This distinction is the point. A hard limit deletes a segment from the graph
    and can turn a journey into "no route at all", which is a claim about the
    physical world. A preset saying "wheelchair users generally want gradients
    under 8%" is not that claim: plenty of people using a chair get up an 11%
    ramp, and telling them their journey is impossible because a default said so
    is both wrong and disempowering.

    So presets express preference through cost, and only these — set by the user
    or by an explicitly documented preset default — remove anything.
    """

    #: Stairs are impassable for this traveller. The one preset default, because
    #: "I cannot use stairs" is a genuine physical fact for a wheelchair user and
    #: the UI states it plainly.
    exclude_steps: bool = False
    #: Recorded gradients above this are excluded. Unrecorded gradient never is.
    max_incline_percent: float | None = None
    #: Recorded widths below this are excluded. Unrecorded width never is.
    min_width_m: float | None = None
    #: Recorded rough surfaces are excluded.
    exclude_rough_surface: bool = False

    @property
    def is_empty(self) -> bool:
        return not (
            self.exclude_steps
            or self.max_incline_percent is not None
            or self.min_width_m is not None
            or self.exclude_rough_surface
        )

    def describe(self) -> tuple[str, ...]:
        """Plain statements of what this traveller cannot use."""
        stated: list[str] = []
        if self.exclude_steps:
            stated.append("cannot use steps")
        if self.max_incline_percent is not None:
            stated.append(f"cannot manage gradients above {self.max_incline_percent:.0f}%")
        if self.min_width_m is not None:
            stated.append(f"needs at least {self.min_width_m:.2f} m of width")
        if self.exclude_rough_surface:
            stated.append("cannot use unpaved surfaces")
        return tuple(stated)


NO_HARD_LIMITS = HardLimits()


@dataclass(frozen=True, slots=True)
class MobilityProfile:
    """How one traveller experiences the network."""

    key: str
    display_name: str
    description: str

    # --- Hard limits: only what the traveller declared ---------------------
    hard_limits: HardLimits = NO_HARD_LIMITS

    # --- Guidance thresholds: expressed as cost, never as exclusion ---------
    #: Above this recorded gradient the cost escalates steeply. The route will
    #: avoid it wherever an alternative exists — and will still offer it, with a
    #: warning, when the alternative is no route at all.
    steep_incline_percent: float | None = None
    #: Below this recorded width the cost escalates steeply.
    narrow_width_m: float | None = None

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

    #: Multiplier applied per percentage point past `steep_incline_percent`,
    #: and per centimetre below `narrow_width_m`. Large enough that a route
    #: takes almost any alternative, small enough that "almost any" is not
    #: "none at all".
    guidance_penalty_factor: float = 6.0
    #: Attributes whose absence this profile does not charge for. Exists so the
    #: unknown-data penalty can be ablated on real data without editing the cost
    #: model — the question "is this term still doing anything" has to be
    #: answerable by measurement rather than by argument.
    ignore_unknown_attributes: tuple[str, ...] = ()

    @property
    def is_standard(self) -> bool:
        """True for the plain shortest-path baseline."""
        return self.key == STANDARD_PROFILE_KEY

    @property
    def excludes_anything(self) -> bool:
        return not self.hard_limits.is_empty


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
    # The one preset hard default, and the UI states it in words: "I cannot use
    # steps" is a genuine physical fact for a wheelchair user, not a preference
    # dressed up as one.
    hard_limits=HardLimits(exclude_steps=True),
    # Guidance, not exclusion. 8% is the steepest ramp most accessibility
    # guidance considers independently usable — but plenty of people get up
    # steeper, and a default must not declare their journey impossible.
    steep_incline_percent=8.0,
    narrow_width_m=0.90,
    surface_penalty={
        SurfaceClass.COMPACTED: 0.8,
        SurfaceClass.ROUGH: 12.0,
        SurfaceClass.UNKNOWN: 0.5,
    },
    smoothness_penalty={
        SmoothnessClass.INTERMEDIATE: 0.7,
        SmoothnessClass.BAD: 12.0,
        SmoothnessClass.UNKNOWN: 0.4,
    },
    incline_penalty_per_percent=0.55,
    comfortable_incline_percent=2.0,
    uncertainty_penalty_per_attribute=0.30,
    kerb_penalty_m={
        KerbType.RAISED: 400.0,
        KerbType.PRESENT_UNKNOWN: 160.0,
        KerbType.ROLLED: 300.0,
        KerbType.UNKNOWN: 90.0,
    },
    crossing_penalty_m=25.0,
)

WALKER = MobilityProfile(
    key="walker",
    display_name="Walker or rollator",
    description=(
        "Avoids steps, prefers even surfaces and gentle grades, and tolerates a "
        "narrower path than a wheelchair needs."
    ),
    hard_limits=HardLimits(exclude_steps=True),
    steep_incline_percent=10.0,
    narrow_width_m=0.75,
    surface_penalty={
        SurfaceClass.COMPACTED: 0.5,
        SurfaceClass.ROUGH: 4.0,
        SurfaceClass.UNKNOWN: 0.4,
    },
    smoothness_penalty={
        SmoothnessClass.INTERMEDIATE: 0.5,
        SmoothnessClass.BAD: 6.0,
        SmoothnessClass.UNKNOWN: 0.3,
    },
    incline_penalty_per_percent=0.45,
    comfortable_incline_percent=2.5,
    uncertainty_penalty_per_attribute=0.25,
    kerb_penalty_m={
        KerbType.RAISED: 200.0,
        KerbType.PRESENT_UNKNOWN: 100.0,
        KerbType.ROLLED: 140.0,
        KerbType.UNKNOWN: 60.0,
    },
    crossing_penalty_m=20.0,
)

CRUTCHES = MobilityProfile(
    key="crutches",
    display_name="Crutches or cane",
    description=(
        "Steps are possible but costly; steep grades, loose surfaces and long detours all matter."
    ),
    steep_incline_percent=15.0,
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
    kerb_penalty_m={
        KerbType.RAISED: 40.0,
        KerbType.PRESENT_UNKNOWN: 28.0,
        KerbType.ROLLED: 25.0,
        KerbType.UNKNOWN: 20.0,
    },
    crossing_penalty_m=15.0,
)

STROLLER = MobilityProfile(
    key="stroller",
    display_name="Stroller or pram",
    description="Avoids steps, prefers dropped kerbs and even surfaces.",
    hard_limits=HardLimits(exclude_steps=True),
    steep_incline_percent=12.0,
    narrow_width_m=0.70,
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
    kerb_penalty_m={
        KerbType.RAISED: 120.0,
        KerbType.PRESENT_UNKNOWN: 65.0,
        KerbType.ROLLED: 90.0,
        KerbType.UNKNOWN: 40.0,
    },
    crossing_penalty_m=15.0,
)

REDUCED_MOBILITY = MobilityProfile(
    key="reduced_mobility",
    display_name="Reduced mobility",
    description=(
        "Walks unaided but tires easily: prefers shorter, flatter, smoother "
        "routes and avoids long stairways."
    ),
    steep_incline_percent=15.0,
    surface_penalty={SurfaceClass.ROUGH: 1.0, SurfaceClass.UNKNOWN: 0.2},
    smoothness_penalty={SmoothnessClass.BAD: 1.2, SmoothnessClass.UNKNOWN: 0.2},
    incline_penalty_per_percent=0.4,
    comfortable_incline_percent=3.5,
    uncertainty_penalty_per_attribute=0.12,
    step_penalty_m=40.0,
    per_step_penalty_m=6.0,
    kerb_penalty_m={
        KerbType.RAISED: 30.0,
        KerbType.PRESENT_UNKNOWN: 20.0,
        KerbType.ROLLED: 18.0,
        KerbType.UNKNOWN: 12.0,
    },
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
    """Derive a profile from a preset, with the user's own hard requirements.

    The difference from a preset is the whole point: what a person states about
    themselves — "I cannot use steps", "I cannot manage more than 5%" — *is* a
    fact about the physical world for them, and becomes a hard limit that can
    legitimately produce "no route". A preset default cannot make that claim on
    their behalf.

    Deliberately narrow. Exposing every cost weight would let a caller build a
    model nobody has reasoned about, and the resulting route would still carry
    PathAble's name.
    """
    template = get_profile(base)

    limits = HardLimits(
        exclude_steps=(
            template.hard_limits.exclude_steps if exclude_steps is None else exclude_steps
        ),
        max_incline_percent=max_incline_percent,
        min_width_m=min_width_m,
        exclude_rough_surface=bool(avoid_rough_surface),
    )

    stated = ", ".join(limits.describe()) or "no hard requirements"
    return replace(
        template,
        key="custom",
        display_name="Custom",
        description=f"Based on {template.display_name.lower()}; {stated}.",
        hard_limits=limits,
    )
