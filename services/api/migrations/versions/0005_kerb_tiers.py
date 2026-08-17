"""Widen the kerb constraint for the tiers the OSM wiki actually defines.

Revision ID: 0005_kerb_tiers
Revises: 0004_incline_direction
Create Date: 2026-08-17

`rolled` and `present_unknown` were added to `KerbType` when the tag semantics
were corrected: a rolled kerb is documented as not wheelchair-traversable and
must not be priced as a lowered one, and `barrier=kerb` with no height states
that a kerb exists rather than that nothing is known. The database CHECK still
listed the old five values, so a real Waterloo import failed on the first
crossing carrying either — which is exactly what the constraint is for.

`incline_direction` gains the CHECK it should have had when the column was
added, so every enum-backed text column in this table is guarded the same way.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_kerb_tiers"
down_revision: str | None = "0004_incline_direction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_KERB = "kerb IN ('lowered', 'flush', 'raised', 'none', 'unknown')"
_NEW_KERB = (
    "kerb IN ('none', 'flush', 'lowered', 'rolled', 'present_unknown', 'raised', 'unknown')"
)
_INCLINE_DIRECTION = "incline_direction IN ('up', 'down', 'unknown')"


def upgrade() -> None:
    op.drop_constraint("edge_kerb", "graph_edges", type_="check")
    op.create_check_constraint("edge_kerb", "graph_edges", sa.text(_NEW_KERB))
    op.create_check_constraint(
        "edge_incline_direction", "graph_edges", sa.text(_INCLINE_DIRECTION)
    )


def downgrade() -> None:
    op.drop_constraint("edge_incline_direction", "graph_edges", type_="check")
    op.drop_constraint("edge_kerb", "graph_edges", type_="check")
    # Rows carrying a value the old constraint forbids would block its creation,
    # so they are folded back to the nearest value it allows. `rolled` becomes
    # `lowered` and a kerb of unrecorded height becomes `unknown` — which is the
    # information loss this migration exists to undo.
    op.execute("UPDATE graph_edges SET kerb = 'lowered' WHERE kerb = 'rolled'")
    op.execute("UPDATE graph_edges SET kerb = 'unknown' WHERE kerb = 'present_unknown'")
    op.create_check_constraint("edge_kerb", "graph_edges", sa.text(_OLD_KERB))
