"""A place index per pilot region, for search.

Revision ID: 0007_place_search
Revises: 0006_dataset_lifecycle
Create Date: 2026-10-07

Two tables, deliberately outside the dataset lifecycle 0006 enforces:

* ``gazetteer_builds`` — the index serving one region and the extract it was
  read from: file name, SHA-256, and the time the OpenStreetMap data is current
  to. One row per region; a rebuild replaces it in one transaction.
* ``gazetteer_entries`` — one searchable point per place, address or street,
  with the OSM element it came from.

A search result is a coordinate the routing endpoint snaps like a map click; it
never becomes a routing fact. So nothing here references ``graph_edges``, nothing
is sealed, and the network's content checksum cannot see it.

``pg_trgm`` backs the typo-tolerant search and the GIN index. It is a *trusted*
extension from PostgreSQL 13, so a database owner without superuser can create
it — which the managed-hosting restore path (KI-8) depends on.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision: str = "0007_place_search"
down_revision: str | None = "0006_dataset_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "gazetteer_builds",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("pilot_region_id", sa.UUID(), nullable=False),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("file_name", sa.String(length=200), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("place_count", sa.Integer(), nullable=False),
        sa.Column("address_count", sa.Integer(), nullable=False),
        sa.Column("street_count", sa.Integer(), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "place_count >= 0 AND address_count >= 0 AND street_count >= 0",
            name=op.f("ck_gazetteer_builds_counts_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["pilot_region_id"],
            ["pilot_regions.id"],
            name=op.f("fk_gazetteer_builds_pilot_region_id_pilot_regions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gazetteer_builds")),
        sa.UniqueConstraint("pilot_region_id", name="uq_gazetteer_builds_region"),
    )

    op.create_geospatial_table(
        "gazetteer_entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("build_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column(
            "geometry",
            Geometry(
                geometry_type="POINT",
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("osm_type", sa.String(length=8), nullable=False),
        sa.Column("osm_id", sa.BigInteger(), nullable=False),
        sa.Column("osm_version", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('place', 'address', 'street')", name=op.f("ck_gazetteer_entries_kind")
        ),
        sa.CheckConstraint(
            "osm_type IN ('node', 'way', 'relation')",
            name=op.f("ck_gazetteer_entries_osm_type"),
        ),
        sa.CheckConstraint(
            "char_length(search_text) > 0", name=op.f("ck_gazetteer_entries_searchable")
        ),
        sa.ForeignKeyConstraint(
            ["build_id"],
            ["gazetteer_builds.id"],
            name=op.f("fk_gazetteer_entries_build_id_gazetteer_builds"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gazetteer_entries")),
    )
    op.create_index("ix_gazetteer_entries_build", "gazetteer_entries", ["build_id"], unique=False)
    op.create_index(
        "ix_gazetteer_entries_search_text_trgm",
        "gazetteer_entries",
        ["search_text"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_gazetteer_entries_search_text_trgm",
        table_name="gazetteer_entries",
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )
    op.drop_index("ix_gazetteer_entries_build", table_name="gazetteer_entries")
    op.drop_geospatial_table("gazetteer_entries")
    op.drop_table("gazetteer_builds")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
