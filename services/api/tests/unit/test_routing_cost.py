"""The cost model and its hard constraints.

These tests protect the two properties that make a route trustworthy: a hard
constraint fires only on evidence, and missing data always costs something.
"""

from __future__ import annotations

import pytest

from pathable_api.geo.enums import KerbType, SmoothnessClass, SurfaceClass, TriState
from pathable_api.geo.features import EdgeFeatures, normalise_edge
from pathable_api.routing.cost import BlockReason, CostCode, EdgeCost, evaluate_edge
from pathable_api.routing.profiles import (
    PROFILES,
    SELECTABLE_PROFILE_KEYS,
    STANDARD,
    WHEELCHAIR,
    UnknownProfileError,
    build_custom_profile,
    get_profile,
)

LENGTH = 100.0


def cost_of(
    tags: dict[str, object], profile_key: str = "wheelchair", length: float = LENGTH
) -> EdgeCost:
    return evaluate_edge(normalise_edge(tags), length, get_profile(profile_key))


class TestStandardProfile:
    def test_the_baseline_costs_exactly_the_distance(self) -> None:
        cost = evaluate_edge(normalise_edge({"highway": "footway"}), 250.0, STANDARD)

        assert cost.passable
        assert cost.effective_metres == pytest.approx(250.0)
        assert cost.penalty_metres == pytest.approx(0.0)

    def test_the_baseline_ignores_accessibility_entirely(self) -> None:
        stairs = evaluate_edge(
            normalise_edge({"highway": "steps", "step_count": "30"}), 40.0, STANDARD
        )
        gravel = evaluate_edge(
            normalise_edge({"highway": "path", "surface": "gravel", "smoothness": "very_bad"}),
            40.0,
            STANDARD,
        )

        assert stairs.passable
        assert gravel.passable
        assert stairs.effective_metres == gravel.effective_metres == pytest.approx(40.0)

    def test_the_baseline_still_refuses_prohibited_access(self) -> None:
        # Not a preference: a way tagged foot=no is one people are not permitted
        # to walk on, whatever their mobility.
        cost = evaluate_edge(normalise_edge({"highway": "service", "foot": "no"}), 40.0, STANDARD)

        assert not cost.passable
        assert cost.blocked_reason is BlockReason.FOOT_PROHIBITED


class TestHardConstraints:
    def test_stairs_block_a_wheelchair(self) -> None:
        cost = cost_of({"highway": "steps", "step_count": "12"})

        assert not cost.passable
        assert cost.blocked_reason is BlockReason.STEPS
        assert "12 steps" in cost.blocked_detail

    def test_stairs_do_not_block_crutches(self) -> None:
        cost = cost_of({"highway": "steps", "step_count": "12"}, "crutches")

        assert cost.passable
        assert cost.effective_metres > LENGTH

    def test_a_recorded_gradient_above_the_limit_blocks(self) -> None:
        cost = cost_of({"highway": "footway", "incline": "12%"})

        assert not cost.passable
        assert cost.blocked_reason is BlockReason.TOO_STEEP

    def test_an_unrecorded_gradient_never_blocks(self) -> None:
        # The alternative would exclude most of the network on the basis of
        # nobody having surveyed it.
        cost = cost_of({"highway": "footway"})
        assert cost.passable

    def test_incline_up_carries_no_magnitude_and_so_cannot_block(self) -> None:
        cost = cost_of({"highway": "footway", "incline": "up"})
        assert cost.passable

    def test_a_recorded_narrow_width_blocks(self) -> None:
        cost = cost_of({"highway": "footway", "width": "0.6"})

        assert not cost.passable
        assert cost.blocked_reason is BlockReason.TOO_NARROW

    def test_an_unrecorded_width_never_blocks(self) -> None:
        assert cost_of({"highway": "footway"}).passable

    def test_a_recorded_rough_surface_blocks_a_wheelchair(self) -> None:
        cost = cost_of({"highway": "path", "surface": "gravel"})

        assert not cost.passable
        assert cost.blocked_reason is BlockReason.SURFACE_EXCLUDED

    def test_an_unrecorded_surface_never_blocks(self) -> None:
        assert cost_of({"highway": "footway"}).passable

    def test_bad_smoothness_blocks_a_wheelchair(self) -> None:
        cost = cost_of({"highway": "footway", "surface": "asphalt", "smoothness": "very_bad"})

        assert not cost.passable
        assert cost.blocked_reason is BlockReason.SMOOTHNESS_EXCLUDED

    def test_a_blocked_edge_costs_infinity(self) -> None:
        # A large finite number could be outbid by a long enough detour; infinity
        # cannot.
        assert cost_of({"highway": "steps"}).effective_metres == float("inf")

    @pytest.mark.parametrize("profile_key", SELECTABLE_PROFILE_KEYS)
    def test_no_profile_blocks_a_plain_untagged_path(self, profile_key: str) -> None:
        # The single most important cross-profile property: unknown must never be
        # treated as impassable, or the product deletes every unsurveyed street.
        cost = evaluate_edge(EdgeFeatures(), LENGTH, get_profile(profile_key))
        assert cost.passable, f"{profile_key} blocked an edge with no recorded attributes"


class TestUncertaintyCosts:
    def test_missing_data_costs_more_than_recorded_good_data(self) -> None:
        known = cost_of(
            {"highway": "footway", "surface": "asphalt", "smoothness": "good", "incline": "0%"}
        )
        unknown = evaluate_edge(EdgeFeatures(), LENGTH, WHEELCHAIR)

        assert unknown.effective_metres > known.effective_metres

    def test_a_fully_recorded_clear_path_costs_only_its_distance(self) -> None:
        cost = cost_of(
            {"highway": "footway", "surface": "asphalt", "smoothness": "good", "incline": "0%"}
        )
        assert cost.effective_metres == pytest.approx(LENGTH)

    def test_the_uncertainty_penalty_scales_with_length(self) -> None:
        # A 500 m unsurveyed path is a bigger gamble than a 20 m one.
        short = evaluate_edge(EdgeFeatures(), 20.0, WHEELCHAIR)
        long = evaluate_edge(EdgeFeatures(), 500.0, WHEELCHAIR)

        assert long.penalty_metres > short.penalty_metres * 20

    def test_surface_is_not_charged_twice(self) -> None:
        # `surface` drives its own unknown-class penalty; counting it again in
        # the uncertainty term would double the cost of the same gap.
        cost = evaluate_edge(EdgeFeatures(), LENGTH, WHEELCHAIR)
        uncertainty = next(
            component for component in cost.components if component.code is CostCode.UNCERTAINTY
        )
        assert "surface" not in uncertainty.detail

    def test_the_standard_profile_charges_nothing_for_uncertainty(self) -> None:
        cost = evaluate_edge(EdgeFeatures(), LENGTH, STANDARD)
        assert cost.effective_metres == pytest.approx(LENGTH)


class TestKerbCosts:
    def test_an_unrecorded_kerb_on_a_crossing_is_charged(self) -> None:
        crossing = cost_of({"highway": "footway", "crossing": "unmarked", "surface": "asphalt"})
        kerb = [c for c in crossing.components if c.code is CostCode.KERB]

        assert kerb
        assert "may not be dropped" in kerb[0].detail

    def test_a_lowered_kerb_is_not_charged(self) -> None:
        crossing = cost_of({"highway": "footway", "crossing": "traffic_signals", "kerb": "lowered"})
        assert not [c for c in crossing.components if c.code is CostCode.KERB]

    def test_a_raised_kerb_costs_far_more_than_an_unrecorded_one(self) -> None:
        # A recorded barrier is worse news than an unrecorded one, and the model
        # should not flatten the two.
        raised = cost_of({"highway": "footway", "crossing": "marked", "kerb": "raised"})
        unknown = cost_of({"highway": "footway", "crossing": "marked"})

        assert raised.effective_metres > unknown.effective_metres

    def test_a_mid_block_path_is_not_charged_for_a_missing_kerb(self) -> None:
        path = cost_of({"highway": "footway", "surface": "asphalt", "smoothness": "good"})
        assert not [c for c in path.components if c.code is CostCode.KERB]

    def test_a_signalised_crossing_costs_less_than_an_unmarked_one(self) -> None:
        signalled = cost_of(
            {"highway": "footway", "crossing": "traffic_signals", "kerb": "lowered"}
        )
        unmarked = cost_of({"highway": "footway", "crossing": "unmarked", "kerb": "lowered"})

        assert signalled.effective_metres < unmarked.effective_metres


class TestInclineCosts:
    def test_a_gentle_slope_within_tolerance_is_free(self) -> None:
        gentle = cost_of(
            {"highway": "footway", "surface": "asphalt", "smoothness": "good", "incline": "1%"}
        )
        assert gentle.effective_metres == pytest.approx(LENGTH)

    def test_uphill_costs_more_than_downhill_at_the_same_gradient(self) -> None:
        uphill = cost_of(
            {"highway": "footway", "surface": "asphalt", "smoothness": "good", "incline": "6%"}
        )
        downhill = cost_of(
            {"highway": "footway", "surface": "asphalt", "smoothness": "good", "incline": "-6%"}
        )

        assert uphill.effective_metres > downhill.effective_metres

    def test_a_steeper_slope_costs_more(self) -> None:
        shallow = cost_of(
            {"highway": "footway", "surface": "asphalt", "smoothness": "good", "incline": "4%"},
            "crutches",
        )
        steep = cost_of(
            {"highway": "footway", "surface": "asphalt", "smoothness": "good", "incline": "9%"},
            "crutches",
        )

        assert steep.effective_metres > shallow.effective_metres


class TestExplainability:
    def test_every_cost_carries_a_reason(self) -> None:
        cost = cost_of({"highway": "footway", "crossing": "unmarked"})

        assert cost.components
        for component in cost.components:
            assert component.detail.strip(), f"{component.code} produced no explanation"

    def test_the_components_sum_to_the_total(self) -> None:
        # The number the router optimises must be the number the explanation adds
        # up to, or the two will drift.
        cost = cost_of({"highway": "path", "crossing": "unmarked", "incline": "5%"})
        assert cost.effective_metres == pytest.approx(
            sum(component.effective_metres for component in cost.components)
        )

    def test_distance_is_always_the_first_component(self) -> None:
        cost = cost_of({"highway": "footway"})
        assert cost.components[0].code is CostCode.DISTANCE
        assert cost.components[0].effective_metres == pytest.approx(LENGTH)


class TestProfileRegistry:
    def test_every_selectable_profile_exists(self) -> None:
        for key in SELECTABLE_PROFILE_KEYS:
            assert get_profile(key).key == key

    def test_an_unknown_profile_names_the_known_ones(self) -> None:
        with pytest.raises(UnknownProfileError, match="wheelchair"):
            get_profile("hovercraft")

    def test_only_the_standard_profile_reports_itself_as_standard(self) -> None:
        standard = [key for key, profile in PROFILES.items() if profile.is_standard]
        assert standard == ["standard"]

    def test_the_standard_profile_is_not_offered_as_a_mobility_choice(self) -> None:
        # It is the baseline the others are compared against, not a way of moving.
        assert "standard" not in SELECTABLE_PROFILE_KEYS

    def test_wheelchair_constraints_are_stricter_than_crutches(self) -> None:
        wheelchair = get_profile("wheelchair")
        crutches = get_profile("crutches")

        assert wheelchair.exclude_steps
        assert not crutches.exclude_steps
        assert wheelchair.max_incline_percent is not None
        assert crutches.max_incline_percent is not None
        assert wheelchair.max_incline_percent < crutches.max_incline_percent


class TestCustomProfile:
    def test_it_inherits_from_its_base(self) -> None:
        custom = build_custom_profile(base="wheelchair")

        assert custom.key == "custom"
        assert custom.exclude_steps is True
        assert custom.max_incline_percent == WHEELCHAIR.max_incline_percent

    def test_an_override_applies(self) -> None:
        custom = build_custom_profile(base="wheelchair", exclude_steps=False)

        assert custom.exclude_steps is False
        cost = evaluate_edge(normalise_edge({"highway": "steps"}), LENGTH, custom)
        assert cost.passable

    def test_rough_surface_can_be_allowed(self) -> None:
        custom = build_custom_profile(base="wheelchair", avoid_rough_surface=False)
        cost = evaluate_edge(
            normalise_edge({"highway": "path", "surface": "gravel"}), LENGTH, custom
        )

        assert cost.passable
        # Allowed, but still not free.
        assert cost.effective_metres > LENGTH

    def test_a_wider_minimum_excludes_more(self) -> None:
        custom = build_custom_profile(base="wheelchair", min_width_m=1.5)
        cost = evaluate_edge(normalise_edge({"highway": "footway", "width": "1.2"}), LENGTH, custom)

        assert not cost.passable
        assert cost.blocked_reason is BlockReason.TOO_NARROW


class TestFeatureClassesUsedByTheModel:
    """Guards the enum values the cost tables are keyed by."""

    def test_surface_classes_are_stable(self) -> None:
        assert {member.value for member in SurfaceClass} == {
            "paved",
            "compacted",
            "rough",
            "unknown",
        }

    def test_smoothness_classes_are_stable(self) -> None:
        assert {member.value for member in SmoothnessClass} == {
            "excellent",
            "good",
            "intermediate",
            "bad",
            "unknown",
        }

    def test_kerb_types_are_stable(self) -> None:
        assert {member.value for member in KerbType} == {
            "lowered",
            "flush",
            "raised",
            "none",
            "unknown",
        }

    def test_tristate_is_three_valued(self) -> None:
        assert {member.value for member in TriState} == {"yes", "no", "unknown"}
