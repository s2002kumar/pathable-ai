"""Enable PostGIS — migration baseline.

Revision ID: 0001_postgis
Revises:
Create Date: 2026-08-05

This is the foundation migration. It deliberately creates **no application
tables**: PathAble's pedestrian-graph schema is Phase 1 work (P0-A02 onward), and
inventing tables now would bake in a shape before the routing requirements exist.

What it does establish is the thing every later migration depends on — the PostGIS
extension — plus proof that the migration pipeline runs end to end from an empty
database.

Downgrade note: dropping the extension is safe *at this revision only*, because no
PathAble object depends on it yet. Once a geometry column exists, this downgrade
will correctly fail rather than silently destroy data, and the migration that adds
that column owns its own reversal.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_postgis"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXTENSION_NAME = "postgis"


def upgrade() -> None:
    # IF NOT EXISTS keeps this idempotent against images such as postgis/postgis,
    # whose entrypoint may already have created the extension in the default
    # database via /docker-entrypoint-initdb.d.
    op.execute(f"CREATE EXTENSION IF NOT EXISTS {EXTENSION_NAME}")


def downgrade() -> None:
    op.execute(f"DROP EXTENSION IF EXISTS {EXTENSION_NAME}")
