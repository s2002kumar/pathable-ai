"""Versioned pedestrian-network schema.

The organising idea is that a *network dataset is immutable once activated*.
Ingestion never edits the live network; it writes a new version, validates it,
and swaps activation in one transaction. That gives reproducibility (every route
can name the dataset it came from), safe rollback, and a failed import that
cannot damage the data people are currently routing on.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pathable_api.db.base import Base
from pathable_api.geo.enums import (
    AccessValue,
    DatasetStatus,
    IngestionStatus,
    KerbType,
    SmoothnessClass,
    SourceType,
    SurfaceClass,
    TriState,
)

#: WGS84. Everything is stored in 4326; metric work uses a projected CRS or
#: PostGIS `geography`, never raw degrees.
SRID = 4326


def _utcnow() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _enum_check(column: str, enum: type[Any], name: str) -> CheckConstraint:
    """Constrain a text column to an enum's values in the database.

    Native PostgreSQL enums are painful to evolve in migrations; a CHECK gives
    the same protection and can be altered with ordinary DDL.
    """
    values = ", ".join(f"'{member.value}'" for member in enum)
    return CheckConstraint(f"{column} IN ({values})", name=name)


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )


class PilotRegion(TimestampMixin, Base):
    """A geography PathAble serves.

    Waterloo is a row here, not a constant in the code — see ADR 0006. Routing,
    ingestion and snapping all take a region, so adding a city is data entry.
    """

    __tablename__ = "pilot_regions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)

    #: Routable extent. Requests outside it are rejected rather than snapped to
    #: the nearest edge of coverage.
    boundary: Mapped[Any] = mapped_column(
        Geometry("MULTIPOLYGON", srid=SRID, spatial_index=False), nullable=False
    )
    centre: Mapped[Any] = mapped_column(
        Geometry("POINT", srid=SRID, spatial_index=False), nullable=False
    )
    default_zoom: Mapped[float] = mapped_column(Float, nullable=False, default=14.0)

    #: Metre-based CRS for this region (e.g. EPSG:32617 for Waterloo). Used for
    #: length and distance work where degrees would be meaningless.
    local_projected_crs: Mapped[str] = mapped_column(String(32), nullable=False)

    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    datasets: Mapped[list[DatasetVersion]] = relationship(
        back_populates="region", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("default_zoom >= 0 AND default_zoom <= 22", name="default_zoom_range"),
        Index("ix_pilot_regions_boundary", "boundary", postgresql_using="gist"),
    )


class DatasetVersion(TimestampMixin, Base):
    """One immutable snapshot of a region's pedestrian network."""

    __tablename__ = "dataset_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pilot_region_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pilot_regions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    source_type: Mapped[SourceType] = mapped_column(String(32), nullable=False)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)

    #: When the upstream data was produced, versus when we fetched it. These are
    #: genuinely different facts and freshness reasoning needs both.
    source_timestamp: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    acquired_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Deterministic over the network content — same input, same checksum.
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Exactly what was requested, so an import can be reproduced.
    ingestion_configuration: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    bounds: Mapped[Any | None] = mapped_column(Geometry("POLYGON", srid=SRID, spatial_index=False))
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[DatasetStatus] = mapped_column(
        String(16), nullable=False, default=DatasetStatus.DRAFT
    )
    validation_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    validated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    region: Mapped[PilotRegion] = relationship(back_populates="datasets")
    nodes: Mapped[list[GraphNode]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )
    edges: Mapped[list[GraphEdge]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )
    ingestion_runs: Mapped[list[IngestionRun]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        _enum_check("status", DatasetStatus, "dataset_status"),
        _enum_check("source_type", SourceType, "dataset_source_type"),
        CheckConstraint("node_count >= 0 AND edge_count >= 0", name="dataset_counts_non_negative"),
        # The single-active-dataset rule, enforced by the database rather than by
        # application discipline. A partial unique index is the cheapest way to
        # make "two active networks" unrepresentable.
        Index(
            "uq_dataset_versions_one_active_per_region",
            "pilot_region_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_dataset_versions_region_status", "pilot_region_id", "status"),
    )


class IngestionRun(Base):
    """One attempt to build a dataset, successful or not.

    Kept separate from the dataset so a failed import leaves an auditable record
    without producing a half-built network anyone could route on.
    """

    __tablename__ = "ingestion_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[IngestionStatus] = mapped_column(
        String(16), nullable=False, default=IngestionStatus.RUNNING
    )
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    validation_results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    failure_summary: Mapped[str | None] = mapped_column(Text)

    dataset: Mapped[DatasetVersion] = relationship(back_populates="ingestion_runs")

    __table_args__ = (_enum_check("status", IngestionStatus, "ingestion_status"),)


class GraphNode(TimestampMixin, Base):
    """A junction in the pedestrian network."""

    __tablename__ = "graph_nodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )

    #: Upstream identity (the OSM node id), kept so a segment can be traced back
    #: to the map and so re-imports are comparable.
    source_node_id: Mapped[str] = mapped_column(String(64), nullable=False)

    geometry: Mapped[Any] = mapped_column(
        Geometry("POINT", srid=SRID, spatial_index=False), nullable=False
    )

    #: Elevation is deliberately absent rather than zero-filled. Inventing it
    #: would make grade look known when nothing has measured it.
    elevation_m: Mapped[float | None] = mapped_column(Float)

    raw_tags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    dataset: Mapped[DatasetVersion] = relationship(back_populates="nodes")

    __table_args__ = (
        UniqueConstraint("dataset_version_id", "source_node_id", name="uq_node_identity"),
        Index("ix_graph_nodes_geometry", "geometry", postgresql_using="gist"),
        Index("ix_graph_nodes_dataset", "dataset_version_id"),
    )


class GraphEdge(TimestampMixin, Base):
    """A walkable segment, with its deterministic accessibility attributes.

    Every derived attribute defaults to unknown. Nothing here is a prediction:
    these are facts asserted by the source, or the explicit absence of one. When
    learned predictions arrive they go in their own table, joined by edge id, so
    that "OSM says" and "a model thinks" can never be confused.
    """

    __tablename__ = "graph_edges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )

    # --- Upstream identity ------------------------------------------------
    source_way_id: Mapped[str | None] = mapped_column(String(64))
    source_u: Mapped[str] = mapped_column(String(64), nullable=False)
    source_v: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Distinguishes parallel edges between the same pair of nodes.
    edge_key: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- Topology ---------------------------------------------------------
    from_node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False
    )
    to_node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False
    )

    geometry: Mapped[Any] = mapped_column(
        Geometry("LINESTRING", srid=SRID, spatial_index=False), nullable=False
    )
    length_m: Mapped[float] = mapped_column(Float, nullable=False)
    directed: Mapped[bool] = mapped_column(nullable=False, default=False)

    # --- Deterministic normalised attributes ------------------------------
    highway: Mapped[str | None] = mapped_column(String(48))
    foot_access: Mapped[AccessValue] = mapped_column(
        String(16), nullable=False, default=AccessValue.UNKNOWN
    )
    general_access: Mapped[AccessValue] = mapped_column(
        String(16), nullable=False, default=AccessValue.UNKNOWN
    )

    steps: Mapped[TriState] = mapped_column(String(8), nullable=False, default=TriState.UNKNOWN)
    step_count: Mapped[int | None] = mapped_column(Integer)

    surface: Mapped[str | None] = mapped_column(String(48))
    surface_class: Mapped[SurfaceClass] = mapped_column(
        String(16), nullable=False, default=SurfaceClass.UNKNOWN
    )
    smoothness: Mapped[str | None] = mapped_column(String(48))
    smoothness_class: Mapped[SmoothnessClass] = mapped_column(
        String(16), nullable=False, default=SmoothnessClass.UNKNOWN
    )

    incline_percent: Mapped[float | None] = mapped_column(Float)
    kerb: Mapped[KerbType] = mapped_column(String(16), nullable=False, default=KerbType.UNKNOWN)

    sidewalk: Mapped[str | None] = mapped_column(String(32))
    is_crossing: Mapped[bool] = mapped_column(nullable=False, default=False)
    crossing_type: Mapped[str | None] = mapped_column(String(32))

    lit: Mapped[TriState] = mapped_column(String(8), nullable=False, default=TriState.UNKNOWN)
    indoor: Mapped[TriState] = mapped_column(String(8), nullable=False, default=TriState.UNKNOWN)
    bridge: Mapped[TriState] = mapped_column(String(8), nullable=False, default=TriState.UNKNOWN)
    tunnel: Mapped[TriState] = mapped_column(String(8), nullable=False, default=TriState.UNKNOWN)

    width_m: Mapped[float | None] = mapped_column(Float)

    #: Everything the source said, preserved verbatim for debugging and for
    #: normalisation rules we have not written yet.
    raw_tags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    dataset: Mapped[DatasetVersion] = relationship(back_populates="edges")

    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id", "source_u", "source_v", "edge_key", name="uq_edge_identity"
        ),
        CheckConstraint("length_m > 0", name="edge_length_positive"),
        CheckConstraint(
            "step_count IS NULL OR step_count >= 0", name="edge_step_count_non_negative"
        ),
        CheckConstraint("width_m IS NULL OR width_m > 0", name="edge_width_positive"),
        _enum_check("steps", TriState, "edge_steps"),
        _enum_check("foot_access", AccessValue, "edge_foot_access"),
        _enum_check("general_access", AccessValue, "edge_general_access"),
        _enum_check("surface_class", SurfaceClass, "edge_surface_class"),
        _enum_check("smoothness_class", SmoothnessClass, "edge_smoothness_class"),
        _enum_check("kerb", KerbType, "edge_kerb"),
        Index("ix_graph_edges_geometry", "geometry", postgresql_using="gist"),
        Index("ix_graph_edges_dataset", "dataset_version_id"),
        Index("ix_graph_edges_from_node", "from_node_id"),
        Index("ix_graph_edges_to_node", "to_node_id"),
    )
