"""Alembic environment.

Uses a *synchronous* engine even though the application runs on the async engine.
Psycopg 3 serves both from the identical ``postgresql+psycopg://`` URL, so this
avoids Alembic's async boilerplate without introducing a second connection string.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from pathable_api.core.config import get_settings

config = context.config

# No ORM models exist in Phase 0. Autogenerate is therefore not wired up; the
# baseline migration is hand-written. Phase 1 will set this to the declarative
# Base metadata once the pedestrian graph tables land.
target_metadata = None


def _database_url() -> str:
    """Resolve the target database URL.

    Order of precedence:
      1. ``alembic -x db_url=...`` (used by integration tests against a throwaway DB)
      2. ``DATABASE_URL`` via the validated application Settings
    """
    override = context.get_x_argument(as_dictionary=True).get("db_url")
    if override:
        return str(override)
    return get_settings().require_database_url()


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live database."""
    engine = create_engine(_database_url(), poolclass=pool.NullPool, future=True)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                # Keeps `alembic_version` out of the default search_path ambiguity
                # if a future deployment introduces multiple schemas.
                version_table="alembic_version",
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
