"""Alembic against a real PostgreSQL server."""

from __future__ import annotations

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text

from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration

BASELINE_REVISION = "0001_postgis"


def engine_for(url: str) -> Engine:
    return create_engine(url, future=True)


def postgis_version(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
        ).scalar_one_or_none()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        exists = connection.execute(
            text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        ).scalar_one()
        if not exists:
            return None
        return connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()


class TestUpgradeFromEmpty:
    def test_database_starts_without_postgis(self, empty_database_url: str) -> None:
        # Guards the fixture itself: if the template database already had PostGIS,
        # the upgrade assertions below would prove nothing.
        engine = engine_for(empty_database_url)
        try:
            assert postgis_version(engine) is None
            assert current_revision(engine) is None
        finally:
            engine.dispose()

    def test_upgrade_installs_postgis(self, empty_database_url: str) -> None:
        command.upgrade(alembic_config(empty_database_url), "head")

        engine = engine_for(empty_database_url)
        try:
            assert postgis_version(engine) is not None
        finally:
            engine.dispose()

    def test_upgrade_records_the_revision(self, empty_database_url: str) -> None:
        command.upgrade(alembic_config(empty_database_url), "head")

        engine = engine_for(empty_database_url)
        try:
            assert current_revision(engine) == BASELINE_REVISION
        finally:
            engine.dispose()

    def test_upgrade_is_idempotent(self, empty_database_url: str) -> None:
        # The container entrypoint runs migrations on every start, so a second
        # upgrade against an already-current database must be a no-op, not a crash.
        config = alembic_config(empty_database_url)
        command.upgrade(config, "head")
        command.upgrade(config, "head")

        engine = engine_for(empty_database_url)
        try:
            assert current_revision(engine) == BASELINE_REVISION
        finally:
            engine.dispose()

    def test_spatial_functions_are_usable_after_upgrade(self, empty_database_url: str) -> None:
        # Proves the extension is genuinely loaded, not merely listed.
        command.upgrade(alembic_config(empty_database_url), "head")

        engine = engine_for(empty_database_url)
        try:
            with engine.connect() as connection:
                distance = connection.execute(
                    text(
                        "SELECT ST_Distance("
                        "  ST_SetSRID(ST_MakePoint(-80.5449, 43.4643), 4326)::geography,"
                        "  ST_SetSRID(ST_MakePoint(-80.5204, 43.4723), 4326)::geography"
                        ")"
                    )
                ).scalar_one()
        finally:
            engine.dispose()

        # Roughly the distance across uptown Waterloo, in metres.
        assert 1_500 < float(distance) < 3_500


class TestDowngrade:
    def test_downgrade_removes_postgis_and_clears_the_version(
        self, migrated_database_url: str
    ) -> None:
        command.downgrade(alembic_config(migrated_database_url), "base")

        engine = engine_for(migrated_database_url)
        try:
            assert postgis_version(engine) is None
            assert current_revision(engine) is None
        finally:
            engine.dispose()

    def test_upgrade_downgrade_upgrade_round_trip(self, migrated_database_url: str) -> None:
        config = alembic_config(migrated_database_url)

        command.downgrade(config, "base")
        command.upgrade(config, "head")

        engine = engine_for(migrated_database_url)
        try:
            assert postgis_version(engine) is not None
            assert current_revision(engine) == BASELINE_REVISION
        finally:
            engine.dispose()
