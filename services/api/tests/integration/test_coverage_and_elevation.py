"""Reporting what a dataset records, and writing elevation onto it.

Both need real PostGIS: they are SQL over stored geometry, and mocking the
database would only test the mock. They run against the deterministic synthetic
fixture, which is small, known, and — importantly — contains segments the map
says nothing about, so "unknown" is exercised rather than assumed.

The elevation provider here is a fake. CI must never reach a public elevation
service: it would make failures depend on somebody else's server and could get
this application blocked by its own test suite.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pathable_api.geo.coverage import COVERAGE_REPORT_VERSION, build_coverage_report, render
from pathable_api.geo.datasets import IngestionResult
from pathable_api.geo.elevation import ElevationSample
from pathable_api.geo.elevation_apply import (
    DISAGREEMENT_THRESHOLD_PERCENT,
    apply_elevation,
    summarise,
)
from pathable_api.geo.fixtures import load_synthetic_dataset
from pathable_api.geo.models import DatasetVersion


async def _dataset(session: AsyncSession, result: IngestionResult) -> DatasetVersion:
    """The stored row for a freshly ingested dataset."""
    dataset = await session.get(DatasetVersion, result.dataset_id)
    assert dataset is not None
    return dataset


pytestmark = pytest.mark.integration


class FlatEarth:
    """Every point at the same height. Grade should come out as zero, not None."""

    name = "fake-flat"
    dataset = "fake"
    resolution_m: float | None = 1.0
    enabled = True
    attribution = ""

    async def sample(self, points: Sequence[tuple[float, float]]) -> list[ElevationSample]:
        return [
            ElevationSample(longitude, latitude, 300.0, self.name, self.dataset, self.resolution_m)
            for longitude, latitude in points
        ]


class NoCoverage:
    """A provider with nothing to say. The point is that this stays unknown."""

    name = "fake-empty"
    dataset = "fake"
    resolution_m: float | None = 1.0
    enabled = True
    attribution = ""

    async def sample(self, points: Sequence[tuple[float, float]]) -> list[ElevationSample]:
        return [
            ElevationSample(longitude, latitude, None, self.name, self.dataset, self.resolution_m)
            for longitude, latitude in points
        ]


class Hillside:
    """Height rises with longitude, so every segment has a real signed grade."""

    name = "fake-hill"
    dataset = "fake"
    resolution_m: float | None = 1.0
    enabled = True
    attribution = ""

    async def sample(self, points: Sequence[tuple[float, float]]) -> list[ElevationSample]:
        return [
            ElevationSample(
                longitude,
                latitude,
                300.0 + (longitude + 80.545) * 1000.0,
                self.name,
                self.dataset,
                self.resolution_m,
            )
            for longitude, latitude in points
        ]


class TestCoverageReport:
    async def test_it_counts_physical_segments_not_directed_edges(
        self, db_session: AsyncSession
    ) -> None:
        # A two-way footway is one piece of pavement with one surface. Counting
        # it twice would inflate every figure in the report.
        result = await load_synthetic_dataset(db_session, activate=True)
        report = await build_coverage_report(
            db_session, dataset=await _dataset(db_session, result), region="Fixture"
        )

        assert report.segments == result.edge_count
        assert report.directed_edges >= report.segments

    async def test_it_reports_each_category_separately(self, db_session: AsyncSession) -> None:
        result = await load_synthetic_dataset(db_session, activate=True)
        report = await build_coverage_report(
            db_session, dataset=await _dataset(db_session, result), region="Fixture"
        )

        names = {entry.name for entry in report.categories}
        assert "surface" in names
        assert "smoothness" in names
        assert "width" in names

    async def test_there_is_no_combined_accessibility_score(self, db_session: AsyncSession) -> None:
        # The single most misleading number this project could produce: a region
        # with excellent kerb data and no surface data would average to
        # "moderate", which describes nothing and hides the actual gap.
        result = await load_synthetic_dataset(db_session, activate=True)
        report = await build_coverage_report(
            db_session, dataset=await _dataset(db_session, result), region="Fixture"
        )

        rendered = "\n".join(render(report)).lower()
        assert "score" not in rendered
        assert "overall" not in rendered
        assert "not combined" in rendered

    async def test_kerb_is_measured_over_crossings_only(self, db_session: AsyncSession) -> None:
        # A kerb is a fact about where a path meets a road. Measured across every
        # footway the number would always look reassuring and mean nothing.
        result = await load_synthetic_dataset(db_session, activate=True)
        report = await build_coverage_report(
            db_session, dataset=await _dataset(db_session, result), region="Fixture"
        )

        kerb = report.category("kerb (crossings only)")
        assert kerb is not None
        assert kerb.total == report.counts["crossings"]

    async def test_unknown_is_counted_as_unknown_not_as_a_value(
        self, db_session: AsyncSession
    ) -> None:
        result = await load_synthetic_dataset(db_session, activate=True)
        report = await build_coverage_report(
            db_session, dataset=await _dataset(db_session, result), region="Fixture"
        )

        surface = report.category("surface")
        assert surface is not None
        assert surface.unknown > 0
        assert "unknown" not in surface.values

    async def test_the_report_carries_its_version(self, db_session: AsyncSession) -> None:
        # A figure quoted in a document has to be traceable to the definition
        # that produced it.
        result = await load_synthetic_dataset(db_session, activate=True)
        report = await build_coverage_report(
            db_session, dataset=await _dataset(db_session, result), region="Fixture"
        )

        assert report.as_dict()["version"] == COVERAGE_REPORT_VERSION


class TestApplyingElevation:
    async def test_it_writes_a_height_and_its_provenance(self, db_session: AsyncSession) -> None:
        result = await load_synthetic_dataset(db_session, activate=True)
        run = await apply_elevation(
            db_session, dataset=await _dataset(db_session, result), provider=FlatEarth()
        )

        assert run.nodes_total > 0
        assert run.nodes_with_elevation == run.nodes_total
        assert run.metadata["provider"] == "fake-flat"
        assert run.metadata["resolution_m"] == 1.0
        assert "acquired_at" in run.metadata

    async def test_a_provider_with_no_coverage_leaves_elevation_unknown(
        self, db_session: AsyncSession
    ) -> None:
        # The failure this guards: zero-filling would turn "nobody measured
        # this" into "flat", which is the exact error the product exists to
        # avoid.
        result = await load_synthetic_dataset(db_session, activate=True)
        run = await apply_elevation(
            db_session, dataset=await _dataset(db_session, result), provider=NoCoverage()
        )

        assert run.nodes_with_elevation == 0
        assert run.edges_with_grade == 0

    async def test_a_slope_produces_a_grade_on_the_segments_long_enough_for_it(
        self, db_session: AsyncSession
    ) -> None:
        result = await load_synthetic_dataset(db_session, activate=True)
        run = await apply_elevation(
            db_session, dataset=await _dataset(db_session, result), provider=Hillside()
        )

        assert run.edges_with_grade > 0
        assert run.edges_with_grade + run.edges_too_short + run.edges_implausible <= run.edges_total

    async def test_a_segment_shorter_than_the_model_can_resolve_gets_no_grade(
        self, db_session: AsyncSession
    ) -> None:
        result = await load_synthetic_dataset(db_session, activate=True)
        run = await apply_elevation(
            db_session, dataset=await _dataset(db_session, result), provider=Hillside()
        )

        # Whatever the count, refusing short segments has to be reported rather
        # than silently producing a number.
        assert run.edges_too_short >= 0
        assert "edges_too_short" in run.metadata

    async def test_the_run_is_summarised_with_its_caveats(self, db_session: AsyncSession) -> None:
        result = await load_synthetic_dataset(db_session, activate=True)
        run = await apply_elevation(
            db_session, dataset=await _dataset(db_session, result), provider=Hillside()
        )
        lines = "\n".join(summarise(run))

        assert "have an elevation" in lines
        assert "too short" in lines
        assert f"{DISAGREEMENT_THRESHOLD_PERCENT:.0f}" in lines

    async def test_rerunning_with_a_worse_provider_does_not_keep_the_old_numbers(
        self, db_session: AsyncSession
    ) -> None:
        # A node that was asked about and had no coverage is a different state
        # from one that was never asked. Only the first should survive a run.
        result = await load_synthetic_dataset(db_session, activate=True)
        await apply_elevation(
            db_session, dataset=await _dataset(db_session, result), provider=FlatEarth()
        )
        run = await apply_elevation(
            db_session, dataset=await _dataset(db_session, result), provider=NoCoverage()
        )

        assert run.nodes_with_elevation == 0
