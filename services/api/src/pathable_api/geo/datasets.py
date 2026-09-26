"""Dataset ingestion: a source network becomes a new candidate.

The lifecycle exists to make one guarantee: *the network people route on is
always a network that passed validation and a route regression, and it does not
change underneath them*. Ingestion is the first step and only the first:
:func:`ingest_network` validates the network in memory, writes it as a **draft**
candidate, and stops. It never activates anything.

``draft → validated → active → retired``, with ``retired → active`` for rollback
and ``failed`` as a terminal branch. Enrichment happens while a dataset is a
draft; sealing (:mod:`pathable_api.geo.lifecycle`) freezes it; activation and
rollback (:mod:`pathable_api.routing.activation`) are gated on recorded
evidence. The transitions and the freeze are enforced by the database as well as
here, because application discipline alone is not a guarantee.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from geoalchemy2.elements import WKTElement
from shapely.geometry import box
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from pathable_api.core.logging import get_logger
from pathable_api.geo.enums import DatasetStatus, IngestionStatus, SourceType
from pathable_api.geo.models import (
    SRID,
    DatasetVersion,
    GraphEdge,
    GraphNode,
    IngestionRun,
    PilotRegion,
)
from pathable_api.geo.network import NetworkPayload
from pathable_api.geo.validation import ValidationReport, validate_network

logger = get_logger(__name__)

#: Rows per bulk INSERT. Large enough that a 40k-edge Waterloo import is not
#: thousands of round trips, small enough not to build a multi-hundred-MB
#: statement in memory.
_INSERT_CHUNK = 2_000


#: Where a candidate records the enrichment it must carry before it is sealed.
ENRICHMENT_KEY = "enrichment"
REQUIRED = "required"
NOT_REQUIRED = "not_required"


class DatasetLifecycleError(RuntimeError):
    """Raised when a lifecycle transition is not permitted."""


class DatasetValidationError(DatasetLifecycleError):
    """Raised when a dataset cannot be activated because validation found errors."""

    def __init__(self, dataset_id: uuid.UUID, report: ValidationReport) -> None:
        self.dataset_id = dataset_id
        self.report = report
        errors = report.errors
        preview = "; ".join(f"{f.code}: {f.message}" for f in errors[:3])
        super().__init__(
            f"Dataset {dataset_id} failed validation with {len(errors)} error(s). {preview}"
        )


@dataclass(slots=True)
class IngestionResult:
    dataset_id: uuid.UUID
    checksum: str
    node_count: int
    edge_count: int
    status: DatasetStatus
    report: ValidationReport


def _utcnow() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


async def get_region(session: AsyncSession, slug: str) -> PilotRegion | None:
    result = await session.execute(select(PilotRegion).where(PilotRegion.slug == slug))
    return result.scalar_one_or_none()


async def require_region(session: AsyncSession, slug: str) -> PilotRegion:
    region = await get_region(session, slug)
    if region is None:
        msg = f"Pilot region {slug!r} does not exist. Seed it before ingesting."
        raise DatasetLifecycleError(msg)
    return region


async def get_active_dataset(session: AsyncSession, region_id: uuid.UUID) -> DatasetVersion | None:
    result = await session.execute(
        select(DatasetVersion).where(
            DatasetVersion.pilot_region_id == region_id,
            DatasetVersion.status == DatasetStatus.ACTIVE,
        )
    )
    return result.scalar_one_or_none()


async def ingest_network(
    session: AsyncSession,
    *,
    region: PilotRegion,
    payload: NetworkPayload,
    source_type: SourceType,
    source_name: str,
    ingestion_configuration: dict[str, Any],
    elevation_required: bool,
    source_timestamp: dt.datetime | None = None,
    declared_bounds: tuple[float, float, float, float] | None = None,
) -> IngestionResult:
    """Persist a network as a new draft candidate.

    The whole sequence runs inside the caller's transaction, and nothing about
    it touches the active dataset: a failed import cannot degrade the live
    network, and a successful one is only a candidate.

    ``elevation_required`` is recorded with the candidate and checked when it is
    sealed. It has no default: whether a network may go live without elevation
    is a decision, and a real import should not be able to skip it by omission.
    """
    checksum = payload.checksum()
    bounds = payload.bounds()

    dataset = DatasetVersion(
        id=uuid.uuid4(),
        pilot_region_id=region.id,
        source_type=source_type,
        source_name=source_name,
        source_timestamp=source_timestamp,
        acquired_at=_utcnow(),
        checksum=checksum,
        ingestion_configuration={
            **ingestion_configuration,
            ENRICHMENT_KEY: {"elevation": REQUIRED if elevation_required else NOT_REQUIRED},
        },
        bounds=_bounds_geometry(bounds),
        node_count=payload.node_count,
        edge_count=payload.edge_count,
        status=DatasetStatus.DRAFT,
    )
    session.add(dataset)

    run = IngestionRun(
        id=uuid.uuid4(),
        dataset_version_id=dataset.id,
        status=IngestionStatus.RUNNING,
        started_at=_utcnow(),
    )
    session.add(run)
    await session.flush()

    # --- Validate before writing a single graph row -----------------------
    # Structural problems are cheaper to find in memory than after inserting
    # 40,000 edges, and a dataset that cannot pass has no reason to occupy space.
    report = validate_network(
        payload,
        # The meaningful check is against the *region's* extent — geometry that
        # escaped the requested area. Comparing the payload to its own bounds
        # would be a tautology.
        declared_bounds=declared_bounds,
        expected_node_count=dataset.node_count,
        expected_edge_count=dataset.edge_count,
    )
    summary = report.summary()

    run.node_count = payload.node_count
    run.edge_count = payload.edge_count
    run.warning_count = len(report.warnings)
    run.error_count = len(report.errors)
    run.validation_results = [f.to_dict() for f in report.findings[:200]]
    dataset.validation_summary = summary

    if not report.is_valid:
        dataset.status = DatasetStatus.FAILED
        run.status = IngestionStatus.FAILED
        run.completed_at = _utcnow()
        run.failure_summary = f"{len(report.errors)} validation error(s)"
        await session.flush()
        raise DatasetValidationError(dataset.id, report)

    await _persist_nodes_and_edges(session, dataset.id, payload)

    run.status = IngestionStatus.SUCCEEDED
    run.completed_at = _utcnow()
    await session.flush()

    logger.info(
        "Candidate dataset ingested",
        extra={
            "dataset_id": str(dataset.id),
            "region": region.slug,
            "source_type": source_type.value,
            "node_count": payload.node_count,
            "edge_count": payload.edge_count,
            "warning_count": len(report.warnings),
        },
    )

    return IngestionResult(
        dataset_id=dataset.id,
        checksum=checksum,
        node_count=payload.node_count,
        edge_count=payload.edge_count,
        status=dataset.status,
        report=report,
    )


def _bounds_geometry(bounds: tuple[float, float, float, float] | None) -> WKTElement | None:
    if bounds is None:
        return None
    min_lon, min_lat, max_lon, max_lat = bounds
    if min_lon == max_lon or min_lat == max_lat:
        # A degenerate box is not a polygon. Give it a hair of width rather than
        # storing an invalid geometry.
        padding = 1e-6
        min_lon, max_lon = min_lon - padding, max_lon + padding
        min_lat, max_lat = min_lat - padding, max_lat + padding
    return WKTElement(box(min_lon, min_lat, max_lon, max_lat).wkt, srid=SRID)


async def _persist_nodes_and_edges(
    session: AsyncSession, dataset_id: uuid.UUID, payload: NetworkPayload
) -> None:
    """Bulk-insert the graph.

    Node primary keys are generated here rather than read back, so edges can
    reference them without a second query over tens of thousands of rows.
    """
    node_ids: dict[str, uuid.UUID] = {}
    node_rows: list[dict[str, Any]] = []
    for node in payload.nodes:
        node_id = uuid.uuid4()
        node_ids[node.source_node_id] = node_id
        node_rows.append(
            {
                "id": node_id,
                "dataset_version_id": dataset_id,
                "source_node_id": node.source_node_id,
                "geometry": WKTElement(node.geometry.wkt, srid=SRID),
                "elevation_m": None,
                "osm_version": None if node.osm is None else node.osm.version,
                "osm_edited_at": None if node.osm is None else node.osm.edited_at,
                "raw_tags": node.raw_tags,
            }
        )

    edge_rows: list[dict[str, Any]] = []
    for edge in payload.edges:
        features = edge.features
        edge_rows.append(
            {
                "id": uuid.uuid4(),
                "dataset_version_id": dataset_id,
                "source_way_id": edge.source_way_id,
                "osm_way_version": None if edge.osm_way is None else edge.osm_way.version,
                "osm_way_edited_at": None if edge.osm_way is None else edge.osm_way.edited_at,
                "osm_way_latest_edit_at": edge.osm_way_latest_edit_at,
                "source_u": edge.source_u,
                "source_v": edge.source_v,
                "edge_key": edge.edge_key,
                "from_node_id": node_ids[edge.source_u],
                "to_node_id": node_ids[edge.source_v],
                "geometry": WKTElement(edge.geometry.wkt, srid=SRID),
                "length_m": edge.length,
                "foot_forward": edge.direction.forward,
                "foot_backward": edge.direction.backward,
                "direction_reason": edge.direction.reason[:200] or None,
                "ambiguous_direction": edge.direction.ambiguous,
                "vehicle_oneway_ignored": features.vehicle_oneway_ignored,
                "conveying": features.conveying.value,
                "highway": features.highway,
                "foot_access": features.foot_access.value,
                "general_access": features.general_access.value,
                "steps": features.steps.value,
                "step_count": features.step_count,
                "surface": features.surface,
                "surface_class": features.surface_class.value,
                "smoothness": features.smoothness,
                "smoothness_class": features.smoothness_class.value,
                "incline_percent": features.incline_percent,
                "incline_direction": features.incline_direction.value,
                "kerb": features.kerb.value,
                "sidewalk": features.sidewalk,
                "is_crossing": features.is_crossing,
                "crossing_type": features.crossing_type,
                "tactile_paving": features.tactile_paving.value,
                "kerb_from_node": features.kerb_from_node,
                "derived_grade_percent": features.derived_grade_percent,
                "conflicting_attributes": list(features.conflicting_attributes),
                "lit": features.lit.value,
                "indoor": features.indoor.value,
                "bridge": features.bridge.value,
                "tunnel": features.tunnel.value,
                "width_m": features.width_m,
                "raw_tags": features.raw_tags,
            }
        )

    for chunk in _chunked(node_rows, _INSERT_CHUNK):
        await session.execute(insert(GraphNode), chunk)
    for chunk in _chunked(edge_rows, _INSERT_CHUNK):
        await session.execute(insert(GraphEdge), chunk)


def _chunked(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]
