"""What the map actually records about a region, category by category.

This is the report that says whether the product has anything useful to tell
somebody. A routing engine over data that records surface for 8% of segments is
not a routing engine that knows about surfaces — and the difference has to be
visible to us before it can be honest to a user.

**There is deliberately no single accessibility-data score here.** Collapsing
these categories into one percentage would be the most misleading number the
project could produce: a region with excellent kerb mapping and no surface data
would average out to "moderate", which describes nothing real and hides exactly
the gap a user needs to know about. Each category is counted separately and
reported separately, and the report refuses to add them up.

Counts are over **physical segments**, not directed edges. A two-way footway is
one piece of pavement with one surface, and counting it twice would inflate
every coverage figure by however many segments happen to be walkable both ways.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import Integer, func, select

from pathable_api.geo.enums import KerbType, SmoothnessClass, SurfaceClass, TriState
from pathable_api.geo.models import DatasetVersion, GraphEdge, GraphNode

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.ext.asyncio import AsyncSession

#: Bumped when a change here would move a reported number, so a figure quoted in
#: a document can be traced to the definition that produced it.
COVERAGE_REPORT_VERSION = 1


@dataclass(slots=True)
class CategoryCoverage:
    """How much of the network says anything about one attribute."""

    name: str
    #: Segments where the map states a value.
    known: int
    #: Segments where nothing is recorded. Not "no barrier" — no information.
    unknown: int
    #: Distribution of the stated values, so "known" cannot hide a single value
    #: repeated everywhere.
    values: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.known + self.unknown

    @property
    def known_fraction(self) -> float:
        return self.known / self.total if self.total else 0.0

    def describe(self) -> str:
        return f"{self.name:<28} {self.known:>7}/{self.total:<7} ({self.known_fraction:6.1%}) known"


@dataclass(slots=True)
class CoverageReport:
    """Everything measured about one dataset, kept as separate facts."""

    dataset_id: str
    region: str
    generated_at: dt.datetime
    segments: int
    directed_edges: int
    nodes: int
    total_length_km: float
    categories: list[CategoryCoverage] = field(default_factory=list)
    #: Facts that are counts rather than coverage ratios — step segments, total
    #: steps, one-way pedestrian segments and so on.
    counts: dict[str, int] = field(default_factory=dict)
    #: Evidence age, bucketed. Empty when the dataset records no source time.
    freshness: dict[str, int] = field(default_factory=dict)
    version: int = COVERAGE_REPORT_VERSION

    def category(self, name: str) -> CategoryCoverage | None:
        return next((entry for entry in self.categories if entry.name == name), None)

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "dataset_id": self.dataset_id,
            "region": self.region,
            "generated_at": self.generated_at.isoformat(),
            "segments": self.segments,
            "directed_edges": self.directed_edges,
            "nodes": self.nodes,
            "total_length_km": round(self.total_length_km, 2),
            "categories": {
                entry.name: {
                    "known": entry.known,
                    "unknown": entry.unknown,
                    "known_fraction": round(entry.known_fraction, 4),
                    "values": entry.values,
                }
                for entry in self.categories
            },
            "counts": self.counts,
            "freshness": self.freshness,
        }


async def build_coverage_report(
    session: AsyncSession,
    *,
    dataset: DatasetVersion,
    region: str,
) -> CoverageReport:
    """Count what the map records, one category at a time."""
    totals = (
        await session.execute(
            select(
                func.count(GraphEdge.id),
                func.coalesce(func.sum(GraphEdge.length_m), 0.0),
                func.sum(
                    func.cast(GraphEdge.foot_forward, Integer)
                    + func.cast(GraphEdge.foot_backward, Integer)
                ),
            ).where(GraphEdge.dataset_version_id == dataset.id)
        )
    ).one()
    segments = int(totals[0])
    total_length_m = float(totals[1] or 0.0)
    directed_edges = int(totals[2] or 0)

    nodes = int(
        (
            await session.execute(
                select(func.count(GraphNode.id)).where(GraphNode.dataset_version_id == dataset.id)
            )
        ).scalar_one()
    )

    report = CoverageReport(
        dataset_id=str(dataset.id),
        region=region,
        generated_at=dt.datetime.now(tz=dt.UTC),
        segments=segments,
        directed_edges=directed_edges,
        nodes=nodes,
        total_length_km=total_length_m / 1000.0,
    )
    if segments == 0:
        return report

    report.categories = [
        await _class_coverage(
            session, dataset, "surface", GraphEdge.surface_class, SurfaceClass.UNKNOWN
        ),
        await _class_coverage(
            session, dataset, "smoothness", GraphEdge.smoothness_class, SmoothnessClass.UNKNOWN
        ),
        await _nullable_coverage(
            session, dataset, "grade (OSM incline)", GraphEdge.incline_percent
        ),
        await _nullable_coverage(
            session, dataset, "grade (from elevation)", GraphEdge.derived_grade_percent
        ),
        await _nullable_coverage(session, dataset, "width", GraphEdge.width_m),
        await _crossing_kerb_coverage(session, dataset),
        await _crossing_type_coverage(session, dataset),
        await _tactile_coverage(session, dataset),
    ]
    report.counts = await _counts(session, dataset)
    report.freshness = await _freshness(session, dataset)
    return report


async def _class_coverage(
    session: AsyncSession,
    dataset: DatasetVersion,
    name: str,
    column: Any,
    unknown_value: object,
) -> CategoryCoverage:
    rows = (
        await session.execute(
            select(column, func.count())
            .where(GraphEdge.dataset_version_id == dataset.id)
            .group_by(column)
        )
    ).all()
    values = {str(value): int(count) for value, count in rows}
    unknown = values.pop(str(unknown_value), 0)
    return CategoryCoverage(name=name, known=sum(values.values()), unknown=unknown, values=values)


async def _nullable_coverage(
    session: AsyncSession,
    dataset: DatasetVersion,
    name: str,
    column: Any,
) -> CategoryCoverage:
    known = int(
        (
            await session.execute(
                select(func.count()).where(
                    GraphEdge.dataset_version_id == dataset.id,
                    column.is_not(None),
                )
            )
        ).scalar_one()
    )
    total = int(
        (
            await session.execute(
                select(func.count()).where(GraphEdge.dataset_version_id == dataset.id)
            )
        ).scalar_one()
    )
    return CategoryCoverage(name=name, known=known, unknown=total - known)


async def _crossing_kerb_coverage(
    session: AsyncSession, dataset: DatasetVersion
) -> CategoryCoverage:
    """Kerb information, counted only over crossings.

    Measuring kerb coverage across the whole network would be meaningless: a kerb
    is a property of where a path meets a road, and most segments are not that.
    The number that matters is how many crossings we can say anything about.
    """
    rows = (
        await session.execute(
            select(GraphEdge.kerb, func.count())
            .where(GraphEdge.dataset_version_id == dataset.id, GraphEdge.is_crossing.is_(True))
            .group_by(GraphEdge.kerb)
        )
    ).all()
    values = {str(value): int(count) for value, count in rows}
    unknown = values.pop(str(KerbType.UNKNOWN), 0)
    return CategoryCoverage(
        name="kerb (crossings only)", known=sum(values.values()), unknown=unknown, values=values
    )


async def _crossing_type_coverage(
    session: AsyncSession, dataset: DatasetVersion
) -> CategoryCoverage:
    rows = (
        await session.execute(
            select(GraphEdge.crossing_type, func.count())
            .where(GraphEdge.dataset_version_id == dataset.id, GraphEdge.is_crossing.is_(True))
            .group_by(GraphEdge.crossing_type)
        )
    ).all()
    values = {str(value): int(count) for value, count in rows if value is not None}
    unknown = sum(int(count) for value, count in rows if value is None)
    return CategoryCoverage(
        name="crossing type", known=sum(values.values()), unknown=unknown, values=values
    )


async def _tactile_coverage(session: AsyncSession, dataset: DatasetVersion) -> CategoryCoverage:
    rows = (
        await session.execute(
            select(GraphEdge.tactile_paving, func.count())
            .where(GraphEdge.dataset_version_id == dataset.id, GraphEdge.is_crossing.is_(True))
            .group_by(GraphEdge.tactile_paving)
        )
    ).all()
    values = {str(value): int(count) for value, count in rows}
    unknown = values.pop(str(TriState.UNKNOWN), 0)
    return CategoryCoverage(
        name="tactile paving (crossings)",
        known=sum(values.values()),
        unknown=unknown,
        values=values,
    )


async def _counts(session: AsyncSession, dataset: DatasetVersion) -> dict[str, int]:
    """Facts that are counts, not ratios."""
    scope = GraphEdge.dataset_version_id == dataset.id

    async def count_where(*conditions: Any) -> int:
        return int(
            (await session.execute(select(func.count()).where(scope, *conditions))).scalar_one()
        )

    step_total = (
        await session.execute(
            select(func.coalesce(func.sum(GraphEdge.step_count), 0)).where(
                scope, GraphEdge.steps == TriState.YES
            )
        )
    ).scalar_one()

    return {
        "step_segments": await count_where(GraphEdge.steps == TriState.YES),
        "steps_counted": int(step_total or 0),
        "crossings": await count_where(GraphEdge.is_crossing.is_(True)),
        "kerb_from_node": await count_where(GraphEdge.kerb_from_node.is_(True)),
        # Genuine pedestrian one-ways. A vehicle `oneway` is not one of these.
        "pedestrian_one_way": await count_where(
            (GraphEdge.foot_forward.is_(False)) | (GraphEdge.foot_backward.is_(False))
        ),
        "vehicle_oneway_ignored": await count_where(GraphEdge.vehicle_oneway_ignored.is_(True)),
        "ambiguous_direction": await count_where(GraphEdge.ambiguous_direction.is_(True)),
        "conflicting_attributes": await count_where(
            func.jsonb_array_length(GraphEdge.conflicting_attributes) > 0
        ),
        "pedestrian_prohibited": await count_where(GraphEdge.foot_access == "no"),
    }


async def _freshness(session: AsyncSession, dataset: DatasetVersion) -> dict[str, int]:
    """How old the evidence is, in buckets.

    A dataset carries one source timestamp today, so this is currently a
    dataset-level fact rather than a per-segment one. It is reported as buckets
    anyway, because per-element edit times are the next thing to acquire and the
    shape of the answer should not change when they arrive.
    """
    source_time = dataset.source_timestamp
    if source_time is None:
        return {}

    age_days = (dt.datetime.now(tz=dt.UTC) - source_time).days
    segments = int(
        (
            await session.execute(
                select(func.count()).where(GraphEdge.dataset_version_id == dataset.id)
            )
        ).scalar_one()
    )
    return {_bucket(age_days): segments}


def _bucket(age_days: int) -> str:
    if age_days <= 7:
        return "0-7 days"
    if age_days <= 30:
        return "8-30 days"
    if age_days <= 180:
        return "31-180 days"
    if age_days <= 365:
        return "181-365 days"
    return "over a year"


def render(report: CoverageReport) -> list[str]:
    """The report as lines a person reads, with no summary score at the end."""
    lines = [
        f"Accessibility data coverage — {report.region}",
        f"  dataset {report.dataset_id}",
        f"  {report.segments} physical segments, {report.directed_edges} routable directed edges",
        f"  {report.nodes} nodes, {report.total_length_km:.1f} km of walkable network",
        "",
        "Coverage by category (each measured separately; these are not combined):",
    ]
    lines.extend(f"  {entry.describe()}" for entry in report.categories)

    lines.extend(["", "Counts:"])
    lines.extend(f"  {name:<28} {value}" for name, value in report.counts.items())

    if report.freshness:
        lines.extend(["", "Evidence age:"])
        lines.extend(
            f"  {bucket:<28} {count} segments" for bucket, count in report.freshness.items()
        )
    return lines
