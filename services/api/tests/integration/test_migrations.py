"""Alembic against a real PostgreSQL server."""

from __future__ import annotations

import asyncio

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from pathable_api.core.event_loop import selector_loop_factory
from pathable_api.geo.fixtures import load_synthetic_dataset
from tests.integration.conftest import API_ROOT, alembic_config

pytestmark = pytest.mark.integration


def head_revision() -> str:
    """The current head, read from the migration scripts.

    Derived rather than hard-coded so adding a migration does not silently turn
    these assertions into a check that the *old* head is still applied.
    """
    config = alembic_config("postgresql+psycopg://unused/unused")
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    return ScriptDirectory.from_config(config).get_current_head() or ""


HEAD_REVISION = head_revision()


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
            assert current_revision(engine) == HEAD_REVISION
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
            assert current_revision(engine) == HEAD_REVISION
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
            assert current_revision(engine) == HEAD_REVISION
        finally:
            engine.dispose()


async def _load_live_fixture(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await load_synthetic_dataset(session)
            await session.commit()
    finally:
        await engine.dispose()


class TestDatasetLifecycleMigration:
    def test_a_dataset_live_before_it_stays_live_with_no_invented_evidence(
        self, migrated_database_url: str
    ) -> None:
        # Stored under 0006, taken down to 0005 and back up: the state of every
        # database that held a live dataset before content checksums existed.
        asyncio.run(_load_live_fixture(migrated_database_url), loop_factory=selector_loop_factory())
        config = alembic_config(migrated_database_url)
        command.downgrade(config, "0005_kerb_tiers")
        command.upgrade(config, "head")

        engine = engine_for(migrated_database_url)
        try:
            with engine.connect() as connection:
                dataset = connection.execute(
                    text(
                        "SELECT status, content_checksum, content_checksum_version, "
                        "validated_content_checksum FROM dataset_versions"
                    )
                ).one()
                # Still live, and nothing claims it was hashed or validated
                # under rules it never went through.
                assert tuple(dataset) == ("active", None, None, None)
                assert (
                    connection.execute(
                        text("SELECT count(osm_version) + count(osm_edited_at) FROM graph_nodes")
                    ).scalar_one()
                    == 0
                )
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM dataset_activation_events")
                    ).scalar_one()
                    == 0
                )
                # And it is frozen from the moment the migration lands.
                with pytest.raises(IntegrityError, match="can no longer change"):
                    connection.execute(text("UPDATE graph_edges SET derived_grade_percent = 1"))
        finally:
            engine.dispose()
