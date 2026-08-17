"""Apply elevation to a stored dataset, and derive grade from it.

A separate pass rather than part of ingestion, for two reasons. Terrain changes
on a scale of decades while OpenStreetMap changes hourly, so tying the two
together would mean re-sampling a DEM every time somebody fixes a tag. And when
a better elevation model becomes available — a newer LiDAR survey, or one that
covers a region HRDEM does not — it can be applied to the network already in the
database instead of forcing a re-ingest.

What this pass writes:

* ``graph_nodes.elevation_m`` plus the source, dataset, resolution and
  acquisition time that let the number be judged later.
* ``graph_edges.derived_grade_percent``, signed along ``source_u -> source_v``,
  computed from the two endpoint elevations and the segment's real length.

What it never writes: a zero for a sample the provider could not give. A node
without coverage keeps a null elevation and every segment touching it keeps a
null grade, because "nobody measured this" and "flat" are different facts and
this product exists to keep them apart.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from geoalchemy2.functions import ST_X, ST_Y
from sqlalchemy import bindparam, select, update

from pathable_api.core.logging import get_logger
from pathable_api.geo.elevation import (
    ELEVATION_POLICY_VERSION,
    DerivedGrade,
    ElevationSample,
    acquisition_metadata,
    derive_grade,
)
from pathable_api.geo.models import DatasetVersion, GraphEdge, GraphNode

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from pathable_api.geo.elevation import ElevationProvider

logger = get_logger(__name__)

#: Points per provider call. Large enough that a remote read amortises its setup,
#: small enough that a failure loses a bounded amount of work.
_BATCH_SIZE = 2000


@dataclass(slots=True)
class ElevationRun:
    """What a sampling pass actually did, for the record and for the report."""

    nodes_total: int = 0
    nodes_with_elevation: int = 0
    edges_total: int = 0
    edges_with_grade: int = 0
    #: Segments shorter than the model can resolve. Not a failure — a refusal.
    edges_too_short: int = 0
    #: Grades so steep they are almost certainly a model artefact.
    edges_implausible: int = 0
    #: Segments where OSM states an incline and the terrain model disagrees by
    #: more than a couple of points. Surfaced, never silently reconciled.
    edges_disagreeing: int = 0
    provider: str = ""
    dataset: str = ""
    resolution_m: float | None = None
    duration_seconds: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def node_coverage(self) -> float:
        return self.nodes_with_elevation / self.nodes_total if self.nodes_total else 0.0

    @property
    def edge_grade_coverage(self) -> float:
        return self.edges_with_grade / self.edges_total if self.edges_total else 0.0


#: How far an OSM-reported incline and a terrain-derived grade may differ before
#: it is worth telling somebody. Below this the two are agreeing within the
#: model's own error; above it, one of them is describing something the other
#: cannot see — a ramp, a bridge, or a mis-tagged way.
DISAGREEMENT_THRESHOLD_PERCENT = 3.0


async def apply_elevation(
    session: AsyncSession,
    *,
    dataset: DatasetVersion,
    provider: ElevationProvider,
    batch_size: int = _BATCH_SIZE,
) -> ElevationRun:
    """Sample elevation for a dataset's nodes and derive grade for its edges."""
    started = dt.datetime.now(tz=dt.UTC)
    run = ElevationRun(
        provider=provider.name,
        dataset=provider.dataset,
        resolution_m=provider.resolution_m,
    )

    nodes = (
        await session.execute(
            select(
                GraphNode.id,
                ST_X(GraphNode.geometry).label("longitude"),
                ST_Y(GraphNode.geometry).label("latitude"),
            )
            .where(GraphNode.dataset_version_id == dataset.id)
            .order_by(GraphNode.id)
        )
    ).all()
    run.nodes_total = len(nodes)
    if not nodes:
        return run

    elevations: dict[UUID, ElevationSample] = {}
    for start in range(0, len(nodes), batch_size):
        chunk = nodes[start : start + batch_size]
        samples = await provider.sample([(row.longitude, row.latitude) for row in chunk])
        for row, sample in zip(chunk, samples, strict=True):
            elevations[row.id] = sample

        await _write_node_elevations(session, chunk, samples, acquired_at=started)
        logger.info(
            "Elevation sampled",
            extra={"done": min(start + batch_size, len(nodes)), "total": len(nodes)},
        )

    run.nodes_with_elevation = sum(1 for sample in elevations.values() if sample.is_known)
    await _derive_edge_grades(session, dataset=dataset, elevations=elevations, run=run)

    run.duration_seconds = (dt.datetime.now(tz=dt.UTC) - started).total_seconds()
    run.metadata = {
        **acquisition_metadata(provider, started),
        "nodes_total": run.nodes_total,
        "nodes_with_elevation": run.nodes_with_elevation,
        "edges_total": run.edges_total,
        "edges_with_grade": run.edges_with_grade,
        "edges_too_short": run.edges_too_short,
        "edges_implausible": run.edges_implausible,
        "edges_disagreeing_with_osm": run.edges_disagreeing,
        "duration_seconds": round(run.duration_seconds, 2),
    }
    return run


async def _write_node_elevations(
    session: AsyncSession,
    rows: Sequence[object],
    samples: Sequence[ElevationSample],
    *,
    acquired_at: dt.datetime,
) -> None:
    """Store each sample with the provenance needed to judge it later.

    An unknown sample is written as an explicit null with no provenance, rather
    than skipped: a node that was asked about and had no coverage is a different
    state from one that was never asked, and only the first should stay null
    after a successful run.
    """
    payload = [
        {
            "node_pk": row.id,  # type: ignore[attr-defined]
            "elevation_m": sample.elevation_m,
            "elevation_source": sample.source if sample.is_known else None,
            "elevation_dataset": sample.dataset if sample.is_known else None,
            "elevation_resolution_m": sample.resolution_m if sample.is_known else None,
            "elevation_acquired_at": acquired_at if sample.is_known else None,
        }
        for row, sample in zip(rows, samples, strict=True)
    ]
    if not payload:
        return

    # One executemany rather than a statement per node: this runs over six-figure
    # node counts, and a round trip each would dominate the sampling itself.
    await session.execute(
        update(GraphNode).where(GraphNode.id == bindparam("node_pk")),
        payload,
    )


async def _derive_edge_grades(
    session: AsyncSession,
    *,
    dataset: DatasetVersion,
    elevations: dict[UUID, ElevationSample],
    run: ElevationRun,
) -> None:
    edges = (
        await session.execute(
            select(
                GraphEdge.id,
                GraphEdge.from_node_id,
                GraphEdge.to_node_id,
                GraphEdge.length_m,
                GraphEdge.incline_percent,
            ).where(GraphEdge.dataset_version_id == dataset.id)
        )
    ).all()
    run.edges_total = len(edges)

    updates: list[dict[str, object]] = []
    for edge in edges:
        grade: DerivedGrade = derive_grade(
            elevations.get(edge.from_node_id),
            elevations.get(edge.to_node_id),
            edge.length_m,
        )
        if grade.too_short:
            run.edges_too_short += 1
        if grade.implausible:
            run.edges_implausible += 1
        if grade.grade_percent is None:
            continue

        run.edges_with_grade += 1
        if (
            edge.incline_percent is not None
            and abs(grade.grade_percent - edge.incline_percent) > DISAGREEMENT_THRESHOLD_PERCENT
        ):
            run.edges_disagreeing += 1

        updates.append({"edge_pk": edge.id, "derived_grade_percent": grade.grade_percent})

    if updates:
        await session.execute(
            update(GraphEdge).where(GraphEdge.id == bindparam("edge_pk")),
            updates,
        )


def summarise(run: ElevationRun) -> list[str]:
    """Lines a person can read, with the caveats attached to the numbers."""
    return [
        f"  provider    {run.provider} ({run.dataset}, {run.resolution_m or '?'} m)",
        f"  nodes       {run.nodes_with_elevation}/{run.nodes_total} "
        f"({run.node_coverage:.1%}) have an elevation",
        f"  grades      {run.edges_with_grade}/{run.edges_total} "
        f"({run.edge_grade_coverage:.1%}) segments have a derived grade",
        f"  too short   {run.edges_too_short} segments below the model's usable length",
        f"  implausible {run.edges_implausible} segments rejected as model artefacts",
        f"  disagrees   {run.edges_disagreeing} segments where OSM's incline differs "
        f"by more than {DISAGREEMENT_THRESHOLD_PERCENT:.0f} points",
        f"  policy      elevation v{ELEVATION_POLICY_VERSION}",
    ]
