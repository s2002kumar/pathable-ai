"""Does the unknown-data penalty still do anything on a real network?

The penalty exists for a good reason: without it, the cheapest route through the
network is the one nobody has surveyed, which exactly inverts what a person
needs. ADR 0008 records that reasoning.

But it was calibrated on a synthetic fixture where missing data was the
exception. On a real OSM extract missing data is the norm — if almost every
segment is missing almost everything, a per-attribute penalty applies roughly
uniformly, cancels out of the comparison, and stops distinguishing anything
while still inflating every effective distance. That is the failure mode this
module measures rather than assumes.

Three variants, routed over identical journeys:

* **current** — the penalties as shipped.
* **no gradient-missing penalty** — because gradient is the attribute most often
  absent, and the one most likely to be saturating.
* **no unknown penalties at all** — the floor, showing what the penalty is
  actually buying.

If the routes are identical across all three, the penalty is not changing
decisions on this data and the honest thing is to say so.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from pathable_api.routing.evaluation import run_case

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from pathable_api.routing.evaluation import RouteCase, RouteOutcome
    from pathable_api.routing.graph import RoutableGraph
    from pathable_api.routing.profiles import MobilityProfile


@dataclass(frozen=True, slots=True)
class Variant:
    """One cost policy to route under."""

    key: str
    description: str
    profile: MobilityProfile


@dataclass(slots=True)
class AblationRow:
    """One journey under every variant."""

    case: str
    outcomes: dict[str, RouteOutcome]

    def distances(self) -> dict[str, float | None]:
        return {key: outcome.distance_m for key, outcome in self.outcomes.items()}

    def differs_from_current(self, key: str) -> bool:
        """Whether this variant walked a different route from the shipped one."""
        current = self.outcomes.get("current")
        other = self.outcomes.get(key)
        if current is None or other is None:
            return False
        if current.routed != other.routed:
            return True
        if not current.routed:
            return False
        assert current.distance_m is not None  # noqa: S101
        assert other.distance_m is not None  # noqa: S101
        return abs(current.distance_m - other.distance_m) > 1.0


def build_variants(profile: MobilityProfile) -> tuple[Variant, ...]:
    """The three policies, derived from the profile actually in use."""
    return (
        Variant("current", "Penalties as shipped", profile),
        Variant(
            "no_gradient_unknown",
            "No penalty for a missing gradient",
            # Gradient is the attribute most often absent in OSM, so if any one
            # term is saturating it is this one.
            replace(profile, ignore_unknown_attributes=("incline",)),
        ),
        Variant(
            "no_unknown_penalty",
            "No penalty for missing data at all",
            replace(profile, uncertainty_penalty_per_attribute=0.0),
        ),
    )


def run_ablation(
    graph: RoutableGraph,
    *,
    cases: Sequence[RouteCase],
    profile: MobilityProfile,
) -> list[AblationRow]:
    """Route every case under every variant, keeping all of it."""
    variants = build_variants(profile)
    return [
        AblationRow(
            case=case.key,
            outcomes={
                variant.key: run_case(graph, case=case, profile=variant.profile)
                for variant in variants
            },
        )
        for case in cases
    ]


def summarise_ablation(rows: Sequence[AblationRow], profile: MobilityProfile) -> list[str]:
    """What the ablation showed, stated without interpretation."""
    variants = build_variants(profile)
    lines = [
        "Unknown-data penalty ablation",
        f"  profile {profile.display_name}, {len(rows)} journeys",
        "",
    ]
    for variant in variants:
        if variant.key == "current":
            continue
        changed = sum(1 for row in rows if row.differs_from_current(variant.key))
        lines.append(f"  {variant.description:<40} changed {changed}/{len(rows)} routes")

    routed = [row for row in rows if all(outcome.routed for outcome in row.outcomes.values())]
    if routed:
        lines.append("")
        lines.append("  Effective distance (cost) against real distance, median ratio:")
        for variant in variants:
            ratios = [
                outcome.effective_distance_m / outcome.distance_m
                for row in routed
                if (outcome := row.outcomes[variant.key]).distance_m
                and outcome.effective_distance_m is not None
                and outcome.distance_m > 0
            ]
            if ratios:
                ratios.sort()
                median = ratios[len(ratios) // 2]
                lines.append(f"    {variant.description:<40} {median:.2f}x")
    return lines
