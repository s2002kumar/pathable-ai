"""Candidates: build, enrich, seal.

A dataset is written as a **draft** — a candidate — and stays writable only while
it is one. Deterministic enrichment such as elevation is applied to the
candidate, never to a network people are routing on. **Sealing** validates what
was actually stored, hashes it under the versioned content contract, and moves
it to ``validated``; from then on the database refuses any change to its rows or
its defining columns (migration 0006). Activation and rollback live in
:mod:`pathable_api.routing.activation`, because judging a candidate means
routing on it.

So "the dataset changed after it was approved" is not a state that exists: the
approval is recorded against a content checksum, and the content under a
checksum cannot move.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased

from pathable_api.geo.content_checksum import (
    CONTENT_CHECKSUM_VERSION,
    ContentChecksum,
    compute_content_checksum,
)
from pathable_api.geo.datasets import (
    ENRICHMENT_KEY,
    REQUIRED,
    DatasetLifecycleError,
)
from pathable_api.geo.elevation_apply import ElevationRun, apply_elevation
from pathable_api.geo.enums import DatasetStatus, IngestionStatus, Severity
from pathable_api.geo.models import DatasetVersion, GraphEdge, GraphNode, IngestionRun
from pathable_api.geo.validation import ValidationFinding, ValidationReport

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.ext.asyncio import AsyncSession

    from pathable_api.geo.elevation import ElevationProvider

#: Statuses whose content is frozen by the database.
SEALED_STATUSES: Final = frozenset(
    {DatasetStatus.VALIDATED, DatasetStatus.ACTIVE, DatasetStatus.RETIRED}
)


class SealRefusedError(DatasetLifecycleError):
    """The stored candidate failed validation; it stays a draft."""

    def __init__(self, dataset_id: uuid.UUID, report: ValidationReport) -> None:
        self.dataset_id = dataset_id
        self.report = report
        preview = "; ".join(f"{finding.code}: {finding.message}" for finding in report.errors[:3])
        super().__init__(f"Dataset {dataset_id} cannot be sealed. {preview}")


@dataclass(frozen=True, slots=True)
class SealResult:
    dataset_id: uuid.UUID
    checksum: ContentChecksum
    report: ValidationReport


def _utcnow() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


async def lock_dataset(session: AsyncSession, dataset_id: uuid.UUID) -> DatasetVersion:
    """Load a dataset row and hold it against concurrent lifecycle changes."""
    dataset = (
        await session.execute(
            select(DatasetVersion)
            .where(DatasetVersion.id == dataset_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if dataset is None:
        msg = f"Dataset {dataset_id} does not exist."
        raise DatasetLifecycleError(msg)
    return dataset


async def require_candidate(session: AsyncSession, dataset_id: uuid.UUID) -> DatasetVersion:
    """A draft, locked. Anything else is refused with the reason."""
    dataset = await lock_dataset(session, dataset_id)
    if dataset.status != DatasetStatus.DRAFT:
        msg = (
            f"Dataset {dataset.id} is {dataset.status}; only a draft candidate can change. "
            "Build a new candidate instead of editing this one."
        )
        raise DatasetLifecycleError(msg)
    return dataset


async def resolve_candidate(
    session: AsyncSession, region_id: uuid.UUID, dataset_id: uuid.UUID | None
) -> DatasetVersion:
    """The candidate an operator means: the one named, or the region's only draft.

    Never the active dataset. With no draft, or more than one, it says so and
    asks for an id rather than guessing.
    """
    if dataset_id is not None:
        dataset = await require_candidate(session, dataset_id)
        if dataset.pilot_region_id != region_id:
            msg = f"Dataset {dataset.id} belongs to another region."
            raise DatasetLifecycleError(msg)
        return dataset

    drafts = (
        (
            await session.execute(
                select(DatasetVersion.id)
                .where(
                    DatasetVersion.pilot_region_id == region_id,
                    DatasetVersion.status == DatasetStatus.DRAFT,
                )
                .order_by(DatasetVersion.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    if not drafts:
        msg = "The region has no draft candidate. Ingest one first; the live dataset is never enriched."
        raise DatasetLifecycleError(msg)
    if len(drafts) > 1:
        listed = ", ".join(str(item) for item in drafts)
        msg = f"The region has {len(drafts)} draft candidates ({listed}); name one with --dataset."
        raise DatasetLifecycleError(msg)
    return await require_candidate(session, drafts[0])


async def enrich_with_elevation(
    session: AsyncSession,
    *,
    dataset_id: uuid.UUID,
    provider: ElevationProvider,
    batch_size: int = 2000,
) -> ElevationRun:
    """Sample elevation into a candidate and record the run with it.

    Repeating it on the same draft replaces the previous sample, node for node;
    it is refused on anything that has been sealed.
    """
    dataset = await require_candidate(session, dataset_id)
    run = await apply_elevation(session, dataset=dataset, provider=provider, batch_size=batch_size)
    # The run belongs to the dataset's record: a grade without the sampling that
    # produced it cannot be judged or reproduced later.
    dataset.ingestion_configuration = {
        **(dataset.ingestion_configuration or {}),
        "elevation": run.metadata,
    }
    await session.flush()
    return run


async def validate_stored_content(
    session: AsyncSession, dataset: DatasetVersion
) -> ValidationReport:
    """Check the rows as stored, which is what will be hashed and routed on.

    Ingest validated the network in memory; this validates the database, after
    enrichment, where a partial write or an enrichment that never ran would
    otherwise pass unseen.
    """
    findings: list[ValidationFinding] = []

    def error(code: str, message: str, **details: Any) -> None:
        findings.append(
            ValidationFinding(
                code=code,
                severity=Severity.ERROR,
                message=message,
                entity_type="dataset",
                entity_reference=str(dataset.id),
                details=details,
            )
        )

    run_failed = await session.scalar(
        select(func.count())
        .select_from(IngestionRun)
        .where(
            IngestionRun.dataset_version_id == dataset.id,
            IngestionRun.status != IngestionStatus.SUCCEEDED,
        )
    )
    if run_failed:
        error("dataset.ingestion_incomplete", "An ingestion run for this dataset did not succeed.")

    nodes = await session.scalar(
        select(func.count())
        .select_from(GraphNode)
        .where(GraphNode.dataset_version_id == dataset.id)
    )
    edges = await session.scalar(
        select(func.count())
        .select_from(GraphEdge)
        .where(GraphEdge.dataset_version_id == dataset.id)
    )
    if nodes != dataset.node_count:
        error(
            "dataset.stored_node_count_mismatch",
            "Stored node rows do not match the recorded count.",
            expected=dataset.node_count,
            actual=nodes,
        )
    if edges != dataset.edge_count:
        error(
            "dataset.stored_edge_count_mismatch",
            "Stored edge rows do not match the recorded count.",
            expected=dataset.edge_count,
            actual=edges,
        )
    if not nodes or not edges:
        error("dataset.empty", "A dataset with no nodes or no edges cannot be routed on.")

    start = aliased(GraphNode)
    end = aliased(GraphNode)
    foreign = await session.scalar(
        select(func.count())
        .select_from(GraphEdge)
        .join(start, GraphEdge.from_node_id == start.id)
        .join(end, GraphEdge.to_node_id == end.id)
        .where(
            GraphEdge.dataset_version_id == dataset.id,
            or_(
                start.dataset_version_id != dataset.id,
                end.dataset_version_id != dataset.id,
            ),
        )
    )
    if foreign:
        error(
            "edge.endpoint_in_another_dataset",
            "Edges reference nodes that belong to a different dataset.",
            count=foreign,
        )

    invalid = await session.scalar(
        select(func.count())
        .select_from(GraphEdge)
        .where(
            GraphEdge.dataset_version_id == dataset.id,
            or_(
                ~func.ST_IsValid(GraphEdge.geometry),
                func.ST_NPoints(GraphEdge.geometry) < 2,
            ),
        )
    )
    if invalid:
        error("edge.invalid_geometry", "Stored edge geometry is invalid.", count=invalid)

    unexplained = await session.scalar(
        select(func.count())
        .select_from(GraphNode)
        .where(
            GraphNode.dataset_version_id == dataset.id,
            (GraphNode.elevation_m.is_(None)) != (GraphNode.elevation_source.is_(None)),
        )
    )
    if unexplained:
        error(
            "node.elevation_without_provenance",
            "An elevation and its source must be recorded together.",
            count=unexplained,
        )

    groundless = await session.scalar(
        select(func.count())
        .select_from(GraphEdge)
        .join(start, GraphEdge.from_node_id == start.id)
        .join(end, GraphEdge.to_node_id == end.id)
        .where(
            GraphEdge.dataset_version_id == dataset.id,
            GraphEdge.derived_grade_percent.is_not(None),
            or_(start.elevation_m.is_(None), end.elevation_m.is_(None)),
        )
    )
    if groundless:
        error(
            "edge.grade_without_elevation",
            "A derived grade exists where an endpoint has no elevation.",
            count=groundless,
        )

    config = dataset.ingestion_configuration or {}
    plan = config.get(ENRICHMENT_KEY) or {}
    if plan.get("elevation") == REQUIRED:
        record = config.get("elevation")
        with_elevation = await session.scalar(
            select(func.count())
            .select_from(GraphNode)
            .where(
                GraphNode.dataset_version_id == dataset.id,
                GraphNode.elevation_m.is_not(None),
            )
        )
        if not isinstance(record, dict):
            error(
                "enrichment.elevation_missing",
                "This candidate requires elevation and none has been applied. "
                "Run `pathable elevation apply` on it first.",
            )
        elif record.get("nodes_with_elevation") != with_elevation:
            error(
                "enrichment.elevation_record_mismatch",
                "The recorded elevation run does not match the stored elevations.",
                recorded=record.get("nodes_with_elevation"),
                stored=with_elevation,
            )
        elif not with_elevation:
            error(
                "enrichment.elevation_empty",
                "Elevation was applied but no node received one.",
            )

    return ValidationReport(findings=tuple(findings))


async def seal_candidate(session: AsyncSession, dataset_id: uuid.UUID) -> SealResult:
    """Validate a candidate's stored content, hash it, and freeze it.

    Runs in the caller's transaction and holds the dataset row for its duration,
    so no enrichment can land between the validation and the hash. A refusal
    leaves the candidate a draft, fixable and sealable later.
    """
    dataset = await require_candidate(session, dataset_id)
    report = await validate_stored_content(session, dataset)
    if not report.is_valid:
        raise SealRefusedError(dataset.id, report)

    checksum = await compute_content_checksum(session, dataset.id)
    dataset.content_checksum = checksum.value
    dataset.content_checksum_version = checksum.version
    dataset.validated_content_checksum = checksum.value
    dataset.validation_summary = {
        **(dataset.validation_summary or {}),
        "content": {
            **report.summary(),
            "content_checksum": checksum.value,
            "content_checksum_version": checksum.version,
            "checksum_seconds": round(checksum.seconds, 3),
        },
    }
    dataset.status = DatasetStatus.VALIDATED
    dataset.validated_at = _utcnow()
    await session.flush()
    return SealResult(dataset_id=dataset.id, checksum=checksum, report=report)


async def record_content_checksum(session: AsyncSession, dataset_id: uuid.UUID) -> ContentChecksum:
    """Compute and record the content checksum of a dataset sealed before it existed.

    Only where none is recorded, and only from the rows as they are: a dataset
    ingested before PA-GEO-02 has no seal-time hash, and this gives it one
    without claiming it was validated under the new rules.
    """
    dataset = await lock_dataset(session, dataset_id)
    if dataset.status not in SEALED_STATUSES:
        msg = (
            f"Dataset {dataset.id} is {dataset.status}; a candidate gets its checksum when sealed."
        )
        raise DatasetLifecycleError(msg)
    if dataset.content_checksum is not None:
        msg = f"Dataset {dataset.id} already has a content checksum; verify it instead."
        raise DatasetLifecycleError(msg)
    checksum = await compute_content_checksum(session, dataset.id)
    dataset.content_checksum = checksum.value
    dataset.content_checksum_version = checksum.version
    await session.flush()
    return checksum


@dataclass(frozen=True, slots=True)
class ChecksumVerification:
    dataset_id: uuid.UUID
    recorded: str | None
    recorded_version: int | None
    computed: ContentChecksum

    @property
    def matches(self) -> bool:
        return (
            self.recorded is not None
            and self.recorded_version == CONTENT_CHECKSUM_VERSION
            and self.recorded == self.computed.value
        )


async def verify_content_checksum(
    session: AsyncSession, dataset_id: uuid.UUID
) -> ChecksumVerification:
    """Recompute a dataset's content checksum from its rows and compare."""
    dataset = await session.get(DatasetVersion, dataset_id)
    if dataset is None:
        msg = f"Dataset {dataset_id} does not exist."
        raise DatasetLifecycleError(msg)
    computed = await compute_content_checksum(session, dataset.id)
    return ChecksumVerification(
        dataset_id=dataset.id,
        recorded=dataset.content_checksum,
        recorded_version=dataset.content_checksum_version,
        computed=computed,
    )
