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

    def test_a_preset_gradient_threshold_costs_but_does_not_block(self) -> None:
        # A preset saying wheelchair users prefer under 8% is a preference, not a
        # claim about the physical world. Plenty of people get up an 11% ramp,
        # and a default must not declare their journey impossible.
        cost = cost_of({"highway": "footway", "incline": "12%"})

        assert cost.passable
        assert cost.effective_metres > LENGTH * 3

    def test_a_gradient_the_user_declared_does_block(self) -> None:
        # What a person states about themselves IS a fact about their world.
        profile = build_custom_profile(base="wheelchair", max_incline_percent=8.0)
        cost = evaluate_edge(
            normalise_edge({"highway": "footway", "incline": "12%"}), LENGTH, profile
        )

        assert not cost.passable
        assert cost.blocked_reason is BlockReason.TOO_STEEP
        assert "you set" in cost.blocked_detail

    def test_a_declared_gradient_limit_only_blocks_the_climb(self) -> None:
        # Rolling down a 12% slope is not hauling up it, and excluding both
        # removes a segment in the direction that was never the problem.
        profile = build_custom_profile(base="wheelchair", max_incline_percent=8.0)
        downhill = normalise_edge({"highway": "footway", "incline": "-12%"})

        assert evaluate_edge(downhill, LENGTH, profile).passable

    def test_an_unrecorded_gradient_never_blocks(self) -> None:
        # The alternative would exclude most of the network on the basis of
        # nobody having surveyed it.
        cost = cost_of({"highway": "footway"})
        assert cost.passable

    def test_incline_up_carries_no_magnitude_and_so_cannot_block(self) -> None:
        cost = cost_of({"highway": "footway", "incline": "up"})
        assert cost.passable

    def test_a_preset_width_threshold_costs_but_does_not_block(self) -> None:
        cost = cost_of({"highway": "footway", "width": "0.6"})

        assert cost.passable
        assert cost.effective_metres > LENGTH

    def test_a_width_the_user_declared_does_block(self) -> None:
        profile = build_custom_profile(base="wheelchair", min_width_m=0.9)
        cost = evaluate_edge(
            normalise_edge({"highway": "footway", "width": "0.6"}), LENGTH, profile
        )

        assert not cost.passable
        assert cost.blocked_reason is BlockReason.TOO_NARROW

    def test_an_unrecorded_width_never_blocks(self) -> None:
        assert cost_of({"highway": "footway"}).passable

    def test_a_rough_surface_costs_heavily_but_does_not_block_a_preset(self) -> None:
        cost = cost_of({"highway": "path", "surface": "gravel"})

        assert cost.passable
        assert cost.effective_metres > LENGTH * 10

    def test_a_rough_surface_blocks_when_the_user_asked_it_to(self) -> None:
        profile = build_custom_profile(base="wheelchair", avoid_rough_surface=True)
        cost = evaluate_edge(
            normalise_edge({"highway": "path", "surface": "gravel"}), LENGTH, profile
        )

        assert not cost.passable
        assert cost.blocked_reason is BlockReason.SURFACE_EXCLUDED

    def test_an_unrecorded_surface_never_blocks(self) -> None:
        assert cost_of({"highway": "footway"}).passable

    def test_bad_smoothness_costs_heavily_but_does_not_block(self) -> None:
        cost = cost_of({"highway": "footway", "surface": "asphalt", "smoothness": "very_bad"})

        assert cost.passable
        assert cost.effective_metres > LENGTH * 10

    def test_a_blocked_edge_costs_infinity(self) -> None:
        # A large finite number could be outbid by a long enough detour; infinity
        # cannot.
        assert cost_of({"highway": "steps"}).effective_metres == float("inf")

    def test_only_steps_are_excluded_by_a_preset(self) -> None:
        # The single documented preset default. Everything else a preset cares
        # about is expressed as cost, so a route is never declared impossible on
        # the strength of an assumption nobody checked with the traveller.
        for key in SELECTABLE_PROFILE_KEYS:
            limits = get_profile(key).hard_limits
            assert limits.max_incline_percent is None, key
            assert limits.min_width_m is None, key
            assert limits.exclude_rough_surface is False, key

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

    def test_wheelchair_guidance_is_stricter_than_crutches(self) -> None:
        wheelchair = get_profile("wheelchair")
        crutches = get_profile("crutches")

        assert wheelchair.hard_limits.exclude_steps
        assert not crutches.hard_limits.exclude_steps
        assert wheelchair.steep_incline_percent is not None
        assert crutches.steep_incline_percent is not None
        assert wheelchair.steep_incline_percent < crutches.steep_incline_percent

    def test_a_profile_states_its_hard_requirements_in_words(self) -> None:
        assert get_profile("wheelchair").hard_limits.describe() == ("cannot use steps",)
        assert get_profile("crutches").hard_limits.describe() == ()


class TestCustomProfile:
    def test_it_inherits_from_its_base(self) -> None:
        custom = build_custom_profile(base="wheelchair")

        assert custom.key == "custom"
        assert custom.hard_limits.exclude_steps is True
        # Guidance is inherited; the preset preference is not promoted into a
        # hard limit merely because the user built a custom profile.
        assert custom.steep_incline_percent == WHEELCHAIR.steep_incline_percent
        assert custom.hard_limits.max_incline_percent is None

    def test_an_override_applies(self) -> None:
        custom = build_custom_profile(base="wheelchair", exclude_steps=False)

        assert custom.hard_limits.exclude_steps is False
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

    def test_the_description_states_what_was_declared(self) -> None:
        custom = build_custom_profile(base="wheelchair", max_incline_percent=5.0)
        assert "5%" in custom.description

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
            "none",
            "flush",
            "lowered",
            "rolled",
            "present_unknown",
            "raised",
            "unknown",
        }

    def test_tristate_is_three_valued(self) -> None:
        assert {member.value for member in TriState} == {"yes", "no", "unknown"}
