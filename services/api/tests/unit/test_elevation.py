"""Elevation, and the grade derived from it.

Every provider here is a fake. Normal CI must never reach a public elevation
service: it would make the suite depend on somebody else's donated server, make
failures non-reproducible, and — for the rate-limited provider — risk getting
this application blocked by the test suite itself.

The behaviour under test is the part that matters for safety: a missing sample
stays missing. Zero-filling elevation would turn "nobody measured this" into
"flat", which is the same class of error as treating a missing surface tag as a
smooth surface.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from pathable_api.geo.elevation import (
    DisabledElevation,
    ElevationSample,
    build_provider,
    derive_grade,
    min_segment_length_for_grade,
    resolution_caveat,
)


def sample(elevation: float | None, *, resolution: float = 1.0) -> ElevationSample:
    return ElevationSample(
        longitude=-80.52,
        latitude=43.47,
        elevation_m=elevation,
        source="fake",
        dataset="fake-dtm",
        resolution_m=resolution,
    )


class TestDerivedGrade:
    def test_a_climb_is_positive_in_the_direction_of_travel(self) -> None:
        grade = derive_grade(sample(300.0), sample(305.0), 100.0)

        assert grade.grade_percent == pytest.approx(5.0)
        assert grade.rise_m == pytest.approx(5.0)

    def test_the_same_segment_walked_back_is_a_descent(self) -> None:
        # Uphill and downhill are not the same journey. A model that reports one
        # number for both is describing a hill nobody has to climb.
        uphill = derive_grade(sample(300.0), sample(305.0), 100.0)
        downhill = derive_grade(sample(305.0), sample(300.0), 100.0)

        assert uphill.grade_percent == pytest.approx(-(downhill.grade_percent or 0.0))

    def test_a_flat_segment_is_zero_not_missing(self) -> None:
        grade = derive_grade(sample(300.0), sample(300.0), 100.0)

        assert grade.grade_percent == pytest.approx(0.0)


class TestMissingIsMissing:
    def test_a_missing_start_produces_no_grade(self) -> None:
        assert derive_grade(sample(None), sample(305.0), 100.0).grade_percent is None

    def test_a_missing_end_produces_no_grade(self) -> None:
        assert derive_grade(sample(300.0), sample(None), 100.0).grade_percent is None

    def test_both_missing_produces_no_grade(self) -> None:
        assert derive_grade(sample(None), sample(None), 100.0).grade_percent is None

    def test_a_missing_sample_is_never_read_as_sea_level(self) -> None:
        # The failure this guards: treating None as 0.0 would turn a node with no
        # coverage into a 300 m cliff and put a fabricated 300% grade on every
        # segment touching it.
        grade = derive_grade(sample(None), sample(300.0), 100.0)

        assert grade.grade_percent is None
        assert grade.rise_m is None

    @pytest.mark.asyncio
    async def test_the_disabled_provider_returns_unknown_not_zero(self) -> None:
        samples = await DisabledElevation().sample([(-80.52, 43.47), (-80.53, 43.48)])

        assert len(samples) == 2
        assert all(entry.elevation_m is None for entry in samples)
        assert all(not entry.is_known for entry in samples)


class TestRefusingToGuess:
    def test_a_segment_shorter_than_the_model_can_resolve_gets_no_grade(self) -> None:
        # Two samples 20 m apart from a 30 m model differ mostly by noise. The
        # measured error of a 30 m model over short segments exceeds the real
        # gradient it is measuring, so no number is the honest answer.
        grade = derive_grade(sample(300.0, resolution=30.0), sample(301.0, resolution=30.0), 20.0)

        assert grade.grade_percent is None
        assert grade.too_short is True

    def test_a_fine_model_may_answer_about_a_much_shorter_segment(self) -> None:
        grade = derive_grade(sample(300.0), sample(301.0), 20.0)

        assert grade.grade_percent == pytest.approx(5.0)
        assert grade.too_short is False

    def test_the_usable_length_scales_with_resolution(self) -> None:
        assert min_segment_length_for_grade(30.0) > min_segment_length_for_grade(1.0)

    def test_an_implausible_slope_is_reported_not_used(self) -> None:
        # A bridge read as a cliff, or a sample that landed on a rooftop. The
        # rise is kept as a diagnostic; the grade is not.
        grade = derive_grade(sample(300.0), sample(360.0), 100.0)

        assert grade.grade_percent is None
        assert grade.implausible is True
        assert grade.rise_m == pytest.approx(60.0)


class TestProviderSelection:
    def test_the_default_is_no_elevation_at_all(self) -> None:
        assert build_provider("none").enabled is False

    def test_a_misspelled_provider_fails_loudly(self) -> None:
        # A deployment that meant to enable elevation and typed it wrong should
        # hear about it at startup, not wonder why every grade is unknown.
        with pytest.raises(ValueError, match="Unknown elevation provider"):
            build_provider("hrdem-1m")

    def test_the_canadian_lidar_source_reports_its_real_resolution(self) -> None:
        provider = build_provider("hrdem")

        assert provider.resolution_m == 1.0
        assert "Open Government Licence" in provider.attribution

    def test_the_fallback_reports_its_much_coarser_resolution(self) -> None:
        assert build_provider("opentopodata").resolution_m == 30.0


class TestStatedLimitations:
    def test_a_coarse_model_says_it_can_miss_a_ramp(self) -> None:
        caveat = resolution_caveat(30.0, "aster30m")

        assert caveat is not None
        assert "30 m" in caveat
        assert "ramp" in caveat

    def test_a_fine_model_still_says_it_is_not_the_path_surface(self) -> None:
        # Even 1 m LiDAR is bare earth. It cannot see a ramp laid on top of the
        # ground, and claiming otherwise would be the same overreach as inventing
        # a number.
        caveat = resolution_caveat(1.0, "hrdem-mosaic-1m-dtm")

        assert caveat is not None
        assert "ground, not the path surface" in caveat

    def test_no_model_means_no_caveat_to_state(self) -> None:
        assert resolution_caveat(None, "none") is None


class TestGradeIsNotIncline:
    def test_a_derived_grade_never_overwrites_a_reported_incline(self) -> None:
        from pathable_api.geo.features import normalise_edge

        features = normalise_edge({"highway": "footway", "incline": "6%"})
        with_terrain = replace(features, derived_grade_percent=-2.0)

        # OSM wins for costing, and the disagreement stays visible rather than
        # being averaged into a number neither source claimed.
        assert with_terrain.effective_grade_percent == pytest.approx(6.0)
        assert with_terrain.grade_source == "osm_incline"
        assert with_terrain.grade_disagreement_percent == pytest.approx(-8.0)

    def test_a_derived_grade_fills_the_silence_where_osm_says_nothing(self) -> None:
        from pathable_api.geo.features import normalise_edge

        features = normalise_edge({"highway": "footway"})
        with_terrain = replace(features, derived_grade_percent=4.5)

        assert with_terrain.effective_grade_percent == pytest.approx(4.5)
        assert with_terrain.grade_source == "derived_elevation"

    def test_reversing_a_segment_flips_a_derived_grade_too(self) -> None:
        from pathable_api.geo.features import normalise_edge

        features = normalise_edge({"highway": "footway"})
        uphill = replace(features, derived_grade_percent=7.0)

        assert uphill.reversed().derived_grade_percent == pytest.approx(-7.0)

    def test_a_missing_derived_grade_stays_missing_when_reversed(self) -> None:
        from pathable_api.geo.features import normalise_edge

        features = normalise_edge({"highway": "footway"})

        assert features.reversed().derived_grade_percent is None
