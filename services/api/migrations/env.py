"""Alembic environment.

Uses a *synchronous* engine even though the application runs on the async engine.
Psycopg 3 serves both from the identical ``postgresql+psycopg://`` URL, so this
avoids Alembic's async boilerplate without introducing a second connection string.
"""

from __future__ import annotations

from typing import Any

from alembic import context
from geoalchemy2 import alembic_helpers
from sqlalchemy import Table, create_engine, pool
from sqlalchemy.schema import SchemaItem

from pathable_api.core.config import get_settings
from pathable_api.db.base import Base
from pathable_api.geo import models as _geo_models  # noqa: F401  (registers tables)

config = context.config

target_metadata = Base.metadata


def _is_ours(table_name: str | None) -> bool:
    return table_name in target_metadata.tables


def include_object(
    obj: SchemaItem,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: SchemaItem | None,
) -> bool:
    """Restrict autogenerate to tables PathAble actually declares.

    The ``postgis/postgis`` image puts ``topology`` and ``tiger`` on the default
    search path, so reflection sees several hundred TIGER geocoder tables that
    belong to the extension. Without this filter autogenerate proposes dropping
    all of them, which would be both wrong and destructive. Allowing only tables
    present in our metadata is a stronger rule than a deny-list — it also
    protects anything a future extension adds.
    """
    if type_ == "table":
        return _is_ours(name)
    if type_ == "index":
        table = getattr(obj, "table", None)
        if isinstance(table, Table):
            return _is_ours(table.name)
    # geoalchemy2 additionally hides the indexes and columns PostGIS manages
    # on our own tables. Its helper is untyped, hence the cast.
    geo_filter: Any = alembic_helpers.include_object
    return bool(geo_filter(obj, name, type_, reflected, compare_to))


#: Renders geoalchemy2 types in generated migrations and emits the matching
#: ``import geoalchemy2``; the writer rewrites geometry DDL into the ops that
#: keep PostGIS's metadata tables in step.
_RENDER_ITEM: Any = alembic_helpers.render_item
_WRITER: Any = alembic_helpers.writer


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
        include_object=include_object,
        render_item=_RENDER_ITEM,
        process_revision_directives=_WRITER,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live database."""
    engine = create_engine(
        _database_url(),
        poolclass=pool.NullPool,
        future=True,
        # The postgis image ships `topology, tiger` on the default search path.
        # Pinning it keeps DDL landing in `public` whatever the image does.
        #
        # This goes through libpq options rather than a `SET search_path`
        # statement on purpose: executing SQL here would open an implicit
        # transaction, and Alembic's `begin_transaction()` would then be a no-op
        # that never commits — migrations appear to run and silently roll back.
        connect_args={"options": "-csearch_path=public"},
    )
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                include_object=include_object,
                render_item=_RENDER_ITEM,
                process_revision_directives=_WRITER,
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
