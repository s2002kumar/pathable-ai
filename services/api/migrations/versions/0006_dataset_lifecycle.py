"""Immutable candidates, a route-regression gate, rollback, and OSM edit provenance.

Revision ID: 0006_dataset_lifecycle
Revises: 0005_kerb_tiers
Create Date: 2026-09-26

The lifecycle promised that a dataset is immutable once it goes live, and
PA-GEO-01 found four places where it was not (KI-10): elevation was written into
the active dataset, the checksum could not see elevation or grade, a retired
dataset could not be reactivated, and nothing required a route regression before
activation. This migration makes the promise something the database enforces.

* ``dataset_versions`` gains a versioned **content checksum** over the complete
  stored routing content, elevation included, and the checksum the validation
  was performed on. The existing ``checksum`` keeps its meaning — the network as
  ingested, before enrichment — because the API publishes it.
* Rows of a dataset that has left ``draft``/``validating`` cannot be inserted,
  updated or deleted, a sealed dataset's defining columns cannot change, and
  the live dataset cannot be deleted. Status moves
  only along the documented transitions, and ``retired → active`` is one of them:
  that is rollback.
* ``route_regression_runs``, ``route_regression_acceptances`` and
  ``dataset_activation_events`` record the evidence an activation rested on.
  They are append-only.
* Nodes and edges gain the OSM element version and edit time the ingest read.
  Existing rows keep NULL: nothing here invents provenance for data ingested
  before it was captured.

A restore of a dump into a fresh database has to write rows of sealed datasets.
It can, by setting ``pathable.allow_sealed_writes = on`` for its session — the
production-smoke restore script does. That setting exists for moving data
between databases, not for editing it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_dataset_lifecycle"
down_revision: str | None = "0005_kerb_tiers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Session setting that lets a restore write rows the triggers otherwise refuse.
_BYPASS = "coalesce(current_setting('pathable.allow_sealed_writes', true), '') = 'on'"

_GRAPH_ROW_GUARD = f"""
CREATE FUNCTION pathable_guard_graph_rows() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    owner_status text;
BEGIN
    IF {_BYPASS} THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.dataset_version_id <> OLD.dataset_version_id THEN
        RAISE EXCEPTION 'graph rows cannot move between datasets'
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT status INTO owner_status FROM dataset_versions WHERE id = NEW.dataset_version_id;
    IF owner_status IS NULL OR owner_status NOT IN ('draft', 'validating') THEN
        RAISE EXCEPTION
            'dataset % is %, and its network can no longer change; build a new candidate',
            NEW.dataset_version_id, coalesce(owner_status, 'missing')
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;
"""

_GRAPH_ROW_DELETE_GUARD = f"""
CREATE FUNCTION pathable_guard_graph_row_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    owner_status text;
BEGIN
    IF {_BYPASS} THEN
        RETURN OLD;
    END IF;
    SELECT status INTO owner_status FROM dataset_versions WHERE id = OLD.dataset_version_id;
    -- No owner: the whole dataset is being deleted and its rows go with it. A
    -- sealed dataset that still exists cannot lose a single node or edge.
    IF owner_status IS NOT NULL AND owner_status NOT IN ('draft', 'validating', 'failed') THEN
        RAISE EXCEPTION
            'dataset % is %, and its network can no longer change; build a new candidate',
            OLD.dataset_version_id, owner_status
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN OLD;
END;
$$;
"""

_DATASET_GUARD = f"""
CREATE FUNCTION pathable_guard_dataset_versions() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF {_BYPASS} THEN
        RETURN coalesce(NEW, OLD);
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'active' THEN
            RAISE EXCEPTION 'dataset % is live and cannot be deleted', OLD.id
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN OLD;
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.status NOT IN ('draft', 'validating', 'failed') THEN
            RAISE EXCEPTION 'a dataset is created as a draft, not as %', NEW.status
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;

    -- Allowed transitions. `retired -> active` is rollback.
    IF NEW.status <> OLD.status AND NOT (
           (OLD.status = 'draft' AND NEW.status IN ('validating', 'validated', 'failed'))
        OR (OLD.status = 'validating' AND NEW.status IN ('draft', 'validated', 'failed'))
        OR (OLD.status = 'validated' AND NEW.status = 'active')
        OR (OLD.status = 'active' AND NEW.status = 'retired')
        OR (OLD.status = 'retired' AND NEW.status = 'active')
    ) THEN
        RAISE EXCEPTION 'dataset % cannot move from % to %', OLD.id, OLD.status, NEW.status
            USING ERRCODE = 'check_violation';
    END IF;

    IF NEW.status = 'active' AND OLD.status <> 'active' AND NEW.content_checksum IS NULL THEN
        RAISE EXCEPTION 'dataset % has no content checksum and cannot go live', OLD.id
            USING ERRCODE = 'check_violation';
    END IF;

    -- Once sealed, what the dataset *is* cannot change. A content checksum may be
    -- recorded once for a dataset sealed before checksums existed, and never
    -- rewritten.
    IF OLD.status IN ('validated', 'active', 'retired') THEN
        IF NEW.pilot_region_id IS DISTINCT FROM OLD.pilot_region_id
            OR NEW.source_type IS DISTINCT FROM OLD.source_type
            OR NEW.source_name IS DISTINCT FROM OLD.source_name
            OR NEW.source_timestamp IS DISTINCT FROM OLD.source_timestamp
            OR NEW.acquired_at IS DISTINCT FROM OLD.acquired_at
            OR NEW.checksum IS DISTINCT FROM OLD.checksum
            OR NEW.ingestion_configuration IS DISTINCT FROM OLD.ingestion_configuration
            OR NEW.node_count IS DISTINCT FROM OLD.node_count
            OR NEW.edge_count IS DISTINCT FROM OLD.edge_count
            OR NEW.validation_summary IS DISTINCT FROM OLD.validation_summary
            OR NEW.validated_at IS DISTINCT FROM OLD.validated_at
            OR NEW.validated_content_checksum IS DISTINCT FROM OLD.validated_content_checksum
            OR ST_AsBinary(NEW.bounds) IS DISTINCT FROM ST_AsBinary(OLD.bounds)
        THEN
            RAISE EXCEPTION 'dataset % is %, and its content can no longer change', OLD.id, OLD.status
                USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.content_checksum IS NOT NULL AND (
               NEW.content_checksum IS DISTINCT FROM OLD.content_checksum
            OR NEW.content_checksum_version IS DISTINCT FROM OLD.content_checksum_version
        ) THEN
            RAISE EXCEPTION 'dataset % already has a content checksum; it cannot be rewritten', OLD.id
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
"""

_APPEND_ONLY = f"""
CREATE FUNCTION pathable_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF {_BYPASS} THEN
        RETURN coalesce(NEW, OLD);
    END IF;
    RAISE EXCEPTION '% is an audit record and cannot be changed or removed', TG_TABLE_NAME
        USING ERRCODE = 'check_violation';
END;
$$;
"""

_AUDIT_TABLES = (
    "route_regression_runs",
    "route_regression_acceptances",
    "dataset_activation_events",
)

#: A reason is a sentence somebody can read later, not a keystroke.
_REASON_CHECK = "char_length(btrim(reason)) >= 15"


def upgrade() -> None:
    # --- Content identity -------------------------------------------------
    op.add_column("dataset_versions", sa.Column("content_checksum", sa.String(64)))
    op.add_column("dataset_versions", sa.Column("content_checksum_version", sa.SmallInteger()))
    op.add_column("dataset_versions", sa.Column("validated_content_checksum", sa.String(64)))
    op.create_check_constraint(
        "dataset_content_checksum_versioned",
        "dataset_versions",
        sa.text("(content_checksum IS NULL) = (content_checksum_version IS NULL)"),
    )

    # --- OSM edit provenance ----------------------------------------------
    op.add_column("graph_nodes", sa.Column("osm_version", sa.Integer()))
    op.add_column("graph_nodes", sa.Column("osm_edited_at", sa.DateTime(timezone=True)))
    op.add_column("graph_edges", sa.Column("osm_way_version", sa.Integer()))
    op.add_column("graph_edges", sa.Column("osm_way_edited_at", sa.DateTime(timezone=True)))
    op.add_column(
        "graph_edges", sa.Column("osm_way_latest_edit_at", sa.DateTime(timezone=True))
    )
    op.create_check_constraint(
        "node_osm_version_positive", "graph_nodes", sa.text("osm_version IS NULL OR osm_version > 0")
    )
    op.create_check_constraint(
        "edge_osm_way_version_positive",
        "graph_edges",
        sa.text("osm_way_version IS NULL OR osm_way_version > 0"),
    )

    # --- Evidence behind an activation ------------------------------------
    op.create_table(
        "route_regression_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "pilot_region_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pilot_regions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "candidate_dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("candidate_content_checksum", sa.String(64), nullable=False),
        sa.Column(
            "baseline_dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
        ),
        sa.Column("baseline_content_checksum", sa.String(64)),
        sa.Column("corpus_key", sa.String(64), nullable=False),
        sa.Column("corpus_fingerprint", sa.String(64), nullable=False),
        sa.Column("profiles", postgresql.JSONB(), nullable=False),
        sa.Column("routing_policy_version", sa.Integer(), nullable=False),
        sa.Column("app_version", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("comparison_count", sa.Integer(), nullable=False),
        sa.Column("difference_count", sa.Integer(), nullable=False),
        sa.Column("results", postgresql.JSONB(), nullable=False),
        sa.Column("differences", postgresql.JSONB(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('identical', 'differences', 'no_baseline')",
            name="regression_outcome",
        ),
        sa.CheckConstraint(
            "(outcome = 'no_baseline') = (baseline_dataset_id IS NULL)",
            name="regression_baseline_matches_outcome",
        ),
        sa.CheckConstraint(
            "(baseline_dataset_id IS NULL) = (baseline_content_checksum IS NULL)",
            name="regression_baseline_identified",
        ),
        sa.CheckConstraint(
            "(outcome = 'identical') = (difference_count = 0 AND baseline_dataset_id IS NOT NULL)",
            name="regression_identical_means_no_differences",
        ),
    )
    op.create_index(
        "ix_route_regression_runs_candidate",
        "route_regression_runs",
        ["candidate_dataset_id", "completed_at"],
    )

    op.create_table(
        "route_regression_acceptances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "regression_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("route_regression_runs.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_REASON_CHECK, name="acceptance_reason_is_a_sentence"),
    )

    op.create_table(
        "dataset_activation_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "pilot_region_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pilot_regions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column(
            "from_dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "to_dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("to_content_checksum", sa.String(64), nullable=False),
        sa.Column(
            "regression_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("route_regression_runs.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "acceptance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("route_regression_acceptances.id", ondelete="RESTRICT"),
        ),
        sa.Column("reason", sa.Text()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action IN ('activate', 'rollback')", name="activation_action"),
        sa.CheckConstraint(
            "action <> 'activate' OR regression_run_id IS NOT NULL",
            name="activation_rests_on_a_regression_run",
        ),
        sa.CheckConstraint(
            f"action <> 'rollback' OR (reason IS NOT NULL AND {_REASON_CHECK})",
            name="rollback_has_a_reason",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR " + _REASON_CHECK,
            name="activation_reason_is_a_sentence",
        ),
    )
    op.create_index(
        "ix_dataset_activation_events_region",
        "dataset_activation_events",
        ["pilot_region_id", "occurred_at"],
    )

    # --- Enforcement ------------------------------------------------------
    op.execute(_GRAPH_ROW_GUARD)
    for table in ("graph_nodes", "graph_edges"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable_once_sealed BEFORE INSERT OR UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION pathable_guard_graph_rows()"
        )
    op.execute(_GRAPH_ROW_DELETE_GUARD)
    for table in ("graph_nodes", "graph_edges"):
        op.execute(
            f"CREATE TRIGGER {table}_kept_once_sealed BEFORE DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION pathable_guard_graph_row_delete()"
        )
    op.execute(_DATASET_GUARD)
    op.execute(
        "CREATE TRIGGER dataset_versions_lifecycle "
        "BEFORE INSERT OR UPDATE OR DELETE ON dataset_versions "
        "FOR EACH ROW EXECUTE FUNCTION pathable_guard_dataset_versions()"
    )
    op.execute(_APPEND_ONLY)
    for table in _AUDIT_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION pathable_append_only()"
        )


def downgrade() -> None:
    for table in _AUDIT_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS pathable_append_only()")
    op.execute("DROP TRIGGER IF EXISTS dataset_versions_lifecycle ON dataset_versions")
    op.execute("DROP FUNCTION IF EXISTS pathable_guard_dataset_versions()")
    for table in ("graph_nodes", "graph_edges"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_kept_once_sealed ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable_once_sealed ON {table}")
    op.execute("DROP FUNCTION IF EXISTS pathable_guard_graph_row_delete()")
    op.execute("DROP FUNCTION IF EXISTS pathable_guard_graph_rows()")

    op.drop_index("ix_dataset_activation_events_region", table_name="dataset_activation_events")
    op.drop_table("dataset_activation_events")
    op.drop_table("route_regression_acceptances")
    op.drop_index("ix_route_regression_runs_candidate", table_name="route_regression_runs")
    op.drop_table("route_regression_runs")

    op.drop_constraint("edge_osm_way_version_positive", "graph_edges", type_="check")
    op.drop_constraint("node_osm_version_positive", "graph_nodes", type_="check")
    for column in ("osm_way_latest_edit_at", "osm_way_edited_at", "osm_way_version"):
        op.drop_column("graph_edges", column)
    for column in ("osm_edited_at", "osm_version"):
        op.drop_column("graph_nodes", column)

    op.drop_constraint("dataset_content_checksum_versioned", "dataset_versions", type_="check")
    for column in ("validated_content_checksum", "content_checksum_version", "content_checksum"):
        op.drop_column("dataset_versions", column)
