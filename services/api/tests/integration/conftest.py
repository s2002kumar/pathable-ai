"""Integration fixtures backed by a real PostgreSQL/PostGIS server.

Every test here runs against a **throwaway database** created and dropped per
test. That is what makes "migrations work from an empty database" a real
assertion rather than a claim about whatever state the developer's database
happened to be in.

Set ``DATABASE_URL`` to point at the Compose database (see .env.example) or a CI
service container. Without it the whole module is skipped with an explanation
rather than failing.
"""

from __future__ import annotations

import argparse
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from pathable_api.core.config import Settings

API_ROOT = Path(__file__).resolve().parents[2]

#: Connecting to the target database to drop it would fail, so administrative
#: statements run against this always-present maintenance database.
MAINTENANCE_DATABASE = "postgres"

SKIP_REASON = (
    "DATABASE_URL is not set. Start the stack with `docker compose up -d db` and "
    "export DATABASE_URL (see .env.example), or run `pnpm test:integration` with "
    "the Compose database running."
)


def _normalised_database_url() -> str | None:
    """Read DATABASE_URL through the same validation the application uses."""
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        return None
    return Settings.model_validate({"database_url": raw}).database_url


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


@pytest.fixture(scope="session")
def base_database_url() -> str:
    url = _normalised_database_url()
    if url is None:
        pytest.skip(SKIP_REASON)
    return url


@pytest.fixture(scope="session")
def maintenance_url(base_database_url: str) -> str:
    return _with_database(base_database_url, MAINTENANCE_DATABASE)


@pytest.fixture
def empty_database_url(maintenance_url: str) -> Iterator[str]:
    """Create a pristine database for one test and drop it afterwards."""
    name = f"pathable_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(maintenance_url, isolation_level="AUTOCOMMIT", future=True)

    try:
        with admin.connect() as connection:
            # Identifier is a locally generated hex slug, never caller input.
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        yield _with_database(maintenance_url, name)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def alembic_config(database_url: str) -> Config:
    """Build an Alembic config aimed at ``database_url``.

    The URL is passed as an ``-x`` argument, which migrations/env.py prefers over
    the ambient DATABASE_URL — so a test can never migrate the developer's real
    database by accident.
    """
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.cmd_opts = argparse.Namespace(x=[f"db_url={database_url}"])
    return config


@pytest.fixture
def migrated_database_url(empty_database_url: str) -> str:
    """An empty database with every migration applied."""
    command.upgrade(alembic_config(empty_database_url), "head")
    return empty_database_url
