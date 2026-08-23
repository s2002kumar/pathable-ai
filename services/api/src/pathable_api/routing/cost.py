"""The cost model.

One function decides what a segment costs and why. Keeping it in one place means
the number the router optimises and the explanation the user reads come from the
same computation — an explanation that is reconstructed separately eventually
stops matching the route it describes.

Costs are in *effective metres*: a 100 m segment costing 250 means it takes about
two and a half times the effort of 100 m of clear pavement. Every contribution is
returned alongside the total, so a route can always answer "why this way?".

The two errors are not symmetric. Telling someone a blocked path is passable can
strand them; telling them a passable path is difficult costs them a detour. The
weights lean that way on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pathable_api.geo.enums import KerbType, SmoothnessClass, SurfaceClass, TriState
from pathable_api.geo.features import EdgeFeatures
from pathable_api.routing.profiles import MobilityProfile


class BlockReason(StrEnum):
    """Why a segment cannot be used at all."""

    FOOT_PROHIBITED = "foot_prohibited"
    STEPS = "steps"
    TOO_STEEP = "too_steep"
    TOO_NARROW = "too_narrow"
    SURFACE_EXCLUDED = "surface_excluded"
    SMOOTHNESS_EXCLUDED = "smoothness_excluded"


class CostCode(StrEnum):
    """What a cost contribution came from."""

    DISTANCE = "distance"
    SURFACE = "surface"
    SMOOTHNESS = "smoothness"
    INCLINE = "incline"
    STEPS = "steps"
    KERB = "kerb"
    CROSSING = "crossing"
    WIDTH = "width"
    UNCERTAINTY = "uncertainty"


@dataclass(frozen=True, slots=True)
class CostComponent:
    code: CostCode
    effective_metres: float
    detail: str


@dataclass(frozen=True, slots=True)
class EdgeCost:
    passable: bool
    effective_metres: float
    components: tuple[CostComponent, ...]
    blocked_reason: BlockReason | None = None
    blocked_detail: str = ""

    @property
    def penalty_metres(self) -> float:
        """Everything beyond the raw distance."""
        return sum(
            component.effective_metres
            for component in self.components
            if component.code is not CostCode.DISTANCE
        )


#: Returned for a segment nobody may use. Infinity rather than a large number, so
#: a blocked segment can never be outbid by a long enough detour.
BLOCKED_COST = float("inf")


def evaluate_edge(features: EdgeFeatures, length_m: float, profile: MobilityProfile) -> EdgeCost:
    """Decide whether a segment is usable and, if so, what it costs."""
    blocked = _hard_constraint(features, profile)
    if blocked is not None:
        reason, detail = blocked
        return EdgeCost(
            passable=False,
            effective_metres=BLOCKED_COST,
            components=(),
            blocked_reason=reason,
            blocked_detail=detail,
        )

    components: list[CostComponent] = [
        CostComponent(CostCode.DISTANCE, length_m, f"{length_m:.0f} m of path")
    ]
    components.extend(_surface_cost(features, length_m, profile))
    components.extend(_guidance_cost(features, length_m, profile))
    components.extend(_incline_cost(features, length_m, profile))
    components.extend(_steps_cost(features, profile))
    components.extend(_kerb_cost(features, profile))
    components.extend(_crossing_cost(features, profile))
    components.extend(_uncertainty_cost(features, length_m, profile))

    total = sum(component.effective_metres for component in components)
    return EdgeCost(passable=True, effective_metres=total, components=tuple(components))


# ---------------------------------------------------------------------------
# Hard constraints
# ---------------------------------------------------------------------------


def _hard_constraint(
    features: EdgeFeatures, profile: MobilityProfile
) -> tuple[BlockReason, str] | None:
    """Return why this segment is unusable, or None if it is usable.

    Two rules govern everything here.

    **Only declared limits exclude.** A preset saying wheelchair users generally
    prefer gradients under 8% is a preference, not a claim about the physical
    world — plenty of people using a chair get up an 11% ramp, and telling them
    their journey is impossible because a default said so is both wrong and
    disempowering. So a preset expresses itself through cost; only
    `profile.hard_limits`, which the traveller set or an explicitly documented
    preset default carries, removes anything.

    **Absence never excludes.** Every check fires on an asserted fact. A missing
    width, gradient or surface leaves the segment in the graph: excluding it
    would delete most of the network, and it would delete precisely the parts
    nobody has surveyed.
    """
    # Legal prohibition, not preference: this applies to every profile including
    # the plain shortest-distance baseline.
    if features.foot_access.is_prohibited or features.general_access.is_prohibited:
        return BlockReason.FOOT_PROHIBITED, "Pedestrian access is not permitted here."

    limits = profile.hard_limits

    if limits.exclude_steps and features.steps is TriState.YES:
        count = f" ({features.step_count} steps)" if features.step_count else ""
        return BlockReason.STEPS, f"This segment is a stairway{count}."

    if limits.max_incline_percent is not None:
        gradient = features.effective_grade_percent
        # Only the climb is disqualifying. Rolling *down* a 12% slope is a
        # different experience from hauling up it, and excluding both would
        # remove a segment in a direction that was never the problem.
        if gradient is not None and gradient > limits.max_incline_percent:
            return (
                BlockReason.TOO_STEEP,
                f"The recorded gradient is {gradient:.0f}% uphill, above the "
                f"{limits.max_incline_percent:.0f}% you set.",
            )

    if (
        limits.min_width_m is not None
        and features.width_m is not None
        and features.width_m < limits.min_width_m
    ):
        return (
            BlockReason.TOO_NARROW,
            f"The recorded width is {features.width_m:.2f} m, below the "
            f"{limits.min_width_m:.2f} m you need.",
        )

    if limits.exclude_rough_surface and features.surface_class is SurfaceClass.ROUGH:
        return (
            BlockReason.SURFACE_EXCLUDED,
            f"The surface is recorded as {features.surface or 'unpaved'}.",
        )

    return None


# ---------------------------------------------------------------------------
# Penalties
# ---------------------------------------------------------------------------


def _surface_cost(
    features: EdgeFeatures, length_m: float, profile: MobilityProfile
) -> list[CostComponent]:
    components: list[CostComponent] = []

    surface_factor = profile.surface_penalty.get(features.surface_class, 0.0)
    if surface_factor:
        described = features.surface or features.surface_class.value
        components.append(
            CostComponent(
                CostCode.SURFACE,
                length_m * surface_factor,
                f"Surface recorded as {described}."
                if features.surface_class is not SurfaceClass.UNKNOWN
                else "No surface has been recorded for this segment.",
            )
        )

    smoothness_factor = profile.smoothness_penalty.get(features.smoothness_class, 0.0)
    if smoothness_factor:
        described = features.smoothness or features.smoothness_class.value
        components.append(
            CostComponent(
                CostCode.SMOOTHNESS,
                length_m * smoothness_factor,
                f"Surface condition recorded as {described}."
                if features.smoothness_class is not SmoothnessClass.UNKNOWN
                else "No surface condition has been recorded for this segment.",
            )
        )

    return components


def _guidance_cost(
    features: EdgeFeatures, length_m: float, profile: MobilityProfile
) -> list[CostComponent]:
    """Cost for thresholds a preset cares about but does not forbid.

    Deliberately steep. A route will take almost any alternative rather than a
    segment past these thresholds — and will still offer it, with the reason
    attached, when the alternative is no route at all. That is the difference
    between advising somebody and deciding for them.
    """
    components: list[CostComponent] = []

    gradient = features.effective_grade_percent
    if profile.steep_incline_percent is not None and gradient is not None:
        excess = gradient - profile.steep_incline_percent
        if excess > 0:
            components.append(
                CostComponent(
                    CostCode.INCLINE,
                    length_m * excess * profile.guidance_penalty_factor,
                    f"{gradient:.0f}% uphill, steeper than the {profile.steep_incline_percent:.0f}% "
                    f"this profile prefers.",
                )
            )

    if (
        profile.narrow_width_m is not None
        and features.width_m is not None
        and features.width_m < profile.narrow_width_m
    ):
        shortfall_cm = (profile.narrow_width_m - features.width_m) * 100.0
        components.append(
            CostComponent(
                CostCode.WIDTH,
                length_m * shortfall_cm * 0.1 * profile.guidance_penalty_factor,
                f"{features.width_m:.2f} m wide, narrower than the "
                f"{profile.narrow_width_m:.2f} m this profile prefers.",
            )
        )

    return components


def _incline_cost(
    features: EdgeFeatures, length_m: float, profile: MobilityProfile
) -> list[CostComponent]:
    gradient = features.effective_grade_percent
    if gradient is None or not profile.incline_penalty_per_percent:
        return []

    # Only the climb is penalised heavily. Going down a 6% ramp is not the
    # same experience as going up one, and the model should not pretend it is.
    excess = abs(gradient) - profile.comfortable_incline_percent
    if excess <= 0:
        return []

    weight = profile.incline_penalty_per_percent * (1.0 if gradient > 0 else 0.4)
    direction = "uphill" if gradient > 0 else "downhill"
    return [
        CostComponent(
            CostCode.INCLINE,
            length_m * excess * weight,
            f"{abs(gradient):.0f}% {direction} gradient.",
        )
    ]


def _steps_cost(features: EdgeFeatures, profile: MobilityProfile) -> list[CostComponent]:
    if features.steps is not TriState.YES:
        return []
    if not profile.step_penalty_m and not profile.per_step_penalty_m:
        return []

    count = features.step_count
    counted = count if count is not None else profile.assumed_step_count
    detail = (
        f"Stairway with {count} steps."
        if count is not None
        else f"Stairway; the step count is not recorded, so {counted} is assumed."
    )
    return [
        CostComponent(
            CostCode.STEPS,
            profile.step_penalty_m + profile.per_step_penalty_m * counted,
            detail,
        )
    ]


def _kerb_cost(features: EdgeFeatures, profile: MobilityProfile) -> list[CostComponent]:
    # A kerb only matters where the path meets the road. Charging for an
    # unrecorded kerb on a mid-block footway would penalise a segment for
    # missing something it never had.
    if not features.is_crossing:
        return []

    penalty = profile.kerb_penalty_m.get(features.kerb, 0.0)
    if not penalty:
        return []

    detail = (
        "No kerb has been recorded at this crossing, so it may not be dropped."
        if features.kerb is KerbType.UNKNOWN
        else f"Kerb recorded as {features.kerb.value}."
    )
    return [CostComponent(CostCode.KERB, penalty, detail)]


def _crossing_cost(features: EdgeFeatures, profile: MobilityProfile) -> list[CostComponent]:
    if not features.is_crossing or not profile.crossing_penalty_m:
        return []

    described = features.crossing_type or "unspecified"
    # A signalised crossing is materially safer than an unmarked one, and the
    # cost should say so.
    factor = 0.4 if described in {"traffic_signals", "marked", "zebra"} else 1.0
    return [
        CostComponent(
            CostCode.CROSSING,
            profile.crossing_penalty_m * factor,
            f"Road crossing ({described}).",
        )
    ]


def _uncertainty_cost(
    features: EdgeFeatures, length_m: float, profile: MobilityProfile
) -> list[CostComponent]:
    """Charge for what nobody has recorded.

    Without this, the cheapest route through the network is the one with the
    least information — precisely inverting what a person needs. The penalty is
    proportional to length, because a 500 m unsurveyed path is a bigger gamble
    than a 20 m one.
    """
    if not profile.uncertainty_penalty_per_attribute:
        return []

    missing = features.unknown_attributes
    if not missing:
        return []

    # Surface and smoothness already contribute through their own unknown-class
    # penalties; counting them again here would double-charge the same gap.
    excluded = {"surface", "smoothness", *profile.ignore_unknown_attributes}
    counted = tuple(attribute for attribute in missing if attribute not in excluded)
    if not counted:
        return []

    listed = ", ".join(counted)
    return [
        CostComponent(
            CostCode.UNCERTAINTY,
            length_m * profile.uncertainty_penalty_per_attribute * len(counted),
            f"Missing accessibility data: {listed}.",
        )
    ]
