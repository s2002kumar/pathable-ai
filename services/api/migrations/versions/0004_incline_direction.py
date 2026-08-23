"""Keep the direction of a slope that OSM described without a number.

Revision ID: 0004_incline_direction
Revises: 0003_directional_evidence
Create Date: 2026-08-17

`incline=up` and `incline=down` are roughly 85% of all incline tagging in
OpenStreetMap — about 1.48 million ways against 189,000 that give a percentage.
The previous parser returned `None` for both, on the reasoning that a direction
without a magnitude cannot be costed. That reasoning conflated magnitude with
direction and threw away five of every six mapped slopes.

Direction alone is actionable for the users this product is for: "the ramp ahead
climbs" changes a decision even when nobody recorded how steeply. It is stored
in its own column rather than as a fabricated percentage, so it can be shown and
costed as what it is — a direction — and never mistaken for a measurement.

The sign convention is OSM's own, so reverse traversal flips it exactly as a
numeric incline negates.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_incline_direction"
down_revision: str | None = "0003_directional_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Added with a default so an existing populated table can take a NOT NULL
    # column, then dropped so the application stays the only thing that decides
    # what an edge says.
    op.add_column(
        "graph_edges",
        sa.Column(
            "incline_direction",
            sa.String(length=8),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.alter_column("graph_edges", "incline_direction", server_default=None)


def downgrade() -> None:
    op.drop_column("graph_edges", "incline_direction")
