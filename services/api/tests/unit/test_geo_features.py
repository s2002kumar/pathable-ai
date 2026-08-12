"""Tag normalisation.

The single most consequential rule in the product is that missing accessibility
information is *unknown*, not *fine*. These tests exist to make that rule
expensive to break.
"""

from __future__ import annotations

import pytest

from pathable_api.geo.enums import AccessValue, KerbType, SmoothnessClass, SurfaceClass, TriState
from pathable_api.geo.features import (
    first_value,
    normalise_access,
    normalise_edge,
    normalise_incline,
    normalise_kerb,
    normalise_smoothness,
    normalise_steps,
    normalise_surface,
)


class TestUnknownIsNotFalse:
    """A missing tag must never be read as an accessibility guarantee."""

    def test_untagged_edge_is_unknown_everywhere(self) -> None:
        features = normalise_edge({})

        assert features.surface_class is SurfaceClass.UNKNOWN
        assert features.smoothness_class is SmoothnessClass.UNKNOWN
        assert features.kerb is KerbType.UNKNOWN
        assert features.foot_access is AccessValue.UNKNOWN
        assert features.steps is TriState.UNKNOWN
        assert features.incline_percent is None
        assert features.width_m is None

    def test_unknown_tristate_is_neither_yes_nor_no(self) -> None:
        # The property that stops `if not edge.steps.is_yes` from silently
        # treating an unsurveyed stairway as step-free.
        assert TriState.UNKNOWN.is_yes is False
        assert TriState.UNKNOWN.is_no is False
        assert TriState.UNKNOWN.is_known is False

    def test_missing_kerb_on_a_crossing_is_reported_as_missing(self) -> None:
        features = normalise_edge(
            {"highway": "footway", "footway": "crossing", "crossing": "unmarked"}
        )

        assert features.kerb is KerbType.UNKNOWN
        assert "kerb" in features.unknown_attributes

    def test_known_kerb_is_not_reported_as_missing(self) -> None:
        features = normalise_edge(
            {"highway": "footway", "crossing": "traffic_signals", "kerb": "lowered"}
        )

        assert features.kerb is KerbType.LOWERED
        assert "kerb" not in features.unknown_attributes

    def test_kerb_is_only_expected_where_it_is_meaningful(self) -> None:
        # A mid-block footway has no kerb to record, so its absence is not a gap.
        features = normalise_edge({"highway": "footway", "surface": "asphalt"})

        assert features.is_crossing is False
        assert "kerb" not in features.unknown_attributes

    def test_unrecognised_surface_value_does_not_imply_smoothness(self) -> None:
        raw, surface_class = normalise_surface("moon_dust")

        assert raw == "moon_dust"
        assert surface_class is SurfaceClass.UNKNOWN


class TestSteps:
    """The one place where absence legitimately means "no"."""

    def test_highway_steps_is_stairs(self) -> None:
        assert normalise_steps({"highway": "steps"}) == (TriState.YES, None)

    def test_step_count_is_kept_when_present(self) -> None:
        assert normalise_steps({"highway": "steps", "step_count": "14"}) == (TriState.YES, 14)

    def test_a_classified_footway_positively_asserts_no_steps(self) -> None:
        # `highway=footway` is a mapper stating the way *type*. Stairs are a
        # different type, so this is evidence of absence, not missing evidence.
        assert normalise_steps({"highway": "footway"}) == (TriState.NO, None)

    def test_missing_highway_leaves_steps_unknown(self) -> None:
        assert normalise_steps({}) == (TriState.UNKNOWN, None)

    def test_unrecognised_highway_leaves_steps_unknown(self) -> None:
        steps, _ = normalise_steps({"highway": "raceway"})
        assert steps is TriState.UNKNOWN


class TestAccess:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("yes", AccessValue.YES),
            ("designated", AccessValue.DESIGNATED),
            ("permissive", AccessValue.PERMISSIVE),
            ("no", AccessValue.NO),
            ("private", AccessValue.PRIVATE),
            ("customers", AccessValue.DESTINATION),
        ],
    )
    def test_known_values(self, value: str, expected: AccessValue) -> None:
        assert normalise_access(value) is expected

    def test_absence_is_unknown_not_permission(self) -> None:
        assert normalise_access(None) is AccessValue.UNKNOWN

    @pytest.mark.parametrize("value", ["no", "private"])
    def test_prohibited_values(self, value: str) -> None:
        assert normalise_access(value).is_prohibited is True

    @pytest.mark.parametrize("value", ["yes", "designated", "permissive", "unknown"])
    def test_unknown_is_not_treated_as_prohibited(self, value: str) -> None:
        # Refusing to route over every untagged path would make the product
        # useless; the cost model handles uncertainty instead.
        assert normalise_access(value).is_prohibited is False


class TestIncline:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("5%", 5.0),
            ("-5%", -5.0),
            ("+12.5%", 12.5),
            ("1/20", 5.0),
            ("-1/10", -10.0),
        ],
    )
    def test_parsed_gradients(self, raw: str, expected: float) -> None:
        result = normalise_incline(raw)
        assert result is not None
        assert result == pytest.approx(expected)

    @pytest.mark.parametrize("raw", ["up", "down", "steep", None, "1/0"])
    def test_direction_without_magnitude_yields_no_number(self, raw: str | None) -> None:
        # `incline=up` says which way, not how much. Inventing a gradient would
        # manufacture precision the surveyor never recorded.
        assert normalise_incline(raw) is None


class TestSurfaceAndSmoothness:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("asphalt", SurfaceClass.PAVED),
            ("paving_stones", SurfaceClass.PAVED),
            ("compacted", SurfaceClass.COMPACTED),
            ("gravel", SurfaceClass.ROUGH),
            ("cobblestone", SurfaceClass.ROUGH),
        ],
    )
    def test_surface_classes(self, raw: str, expected: SurfaceClass) -> None:
        _, surface_class = normalise_surface(raw)
        assert surface_class is expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("excellent", SmoothnessClass.EXCELLENT),
            ("intermediate", SmoothnessClass.INTERMEDIATE),
            ("very_horrible", SmoothnessClass.BAD),
            ("impassable", SmoothnessClass.BAD),
        ],
    )
    def test_smoothness_classes(self, raw: str, expected: SmoothnessClass) -> None:
        _, smoothness_class = normalise_smoothness(raw)
        assert smoothness_class is expected

    def test_raw_value_is_preserved_alongside_the_class(self) -> None:
        # The coarse class drives routing; the raw value stays visible so a user
        # can see what the map actually said.
        raw, surface_class = normalise_surface("paving_stones")
        assert (raw, surface_class) == ("paving_stones", SurfaceClass.PAVED)


class TestMultiValuedTags:
    def test_a_list_collapses_to_its_first_usable_value(self) -> None:
        # OSMnx produces a list when several source ways merged into one edge.
        assert first_value(["asphalt", "gravel"]) == "asphalt"

    def test_values_are_lowercased_and_trimmed(self) -> None:
        assert first_value("  Asphalt ") == "asphalt"

    def test_empty_values_are_absent_rather_than_empty_strings(self) -> None:
        assert first_value("   ") is None
        assert first_value([]) is None
        assert first_value([None, "", "gravel"]) == "gravel"

    def test_a_listed_surface_still_normalises(self) -> None:
        features = normalise_edge({"highway": "footway", "surface": ["concrete", "asphalt"]})
        assert features.surface_class is SurfaceClass.PAVED


class TestKerbAliases:
    def test_american_spelling_is_accepted(self) -> None:
        assert normalise_kerb({"curb": "lowered"}) is KerbType.LOWERED

    def test_rolled_counts_as_lowered(self) -> None:
        assert normalise_kerb({"kerb": "rolled"}) is KerbType.LOWERED

    def test_unrecognised_kerb_value_is_unknown(self) -> None:
        assert normalise_kerb({"kerb": "wibbly"}) is KerbType.UNKNOWN


class TestCrossingDetection:
    def test_a_crossing_tag_marks_the_edge(self) -> None:
        features = normalise_edge({"highway": "footway", "crossing": "marked"})
        assert features.is_crossing is True
        assert features.crossing_type == "marked"

    def test_highway_crossing_marks_the_edge(self) -> None:
        assert normalise_edge({"highway": "crossing"}).is_crossing is True

    def test_an_ordinary_footway_is_not_a_crossing(self) -> None:
        assert normalise_edge({"highway": "footway"}).is_crossing is False


class TestNumericGuards:
    @pytest.mark.parametrize("raw", ["0", "-3", "wide", ""])
    def test_non_positive_or_unparseable_width_is_absent(self, raw: str) -> None:
        # A zero-width path is not a fact about the world, it is bad data.
        assert normalise_edge({"width": raw}).width_m is None

    def test_width_with_a_unit_suffix_is_parsed(self) -> None:
        assert normalise_edge({"width": "2.5 m"}).width_m == pytest.approx(2.5)

    def test_negative_step_count_is_rejected(self) -> None:
        _, step_count = normalise_steps({"highway": "steps", "step_count": "-4"})
        assert step_count is None
