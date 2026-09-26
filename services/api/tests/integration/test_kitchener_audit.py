"""The Kitchener audit against real PostGIS: it reads PathAble, and it cannot write.

Two guarantees are tested here rather than asserted in prose. The read runs in
a ``READ ONLY`` transaction, so a write slipped into it is refused by
PostgreSQL. And it reads only columns that exist from migration 0005 onward, so
it can inspect a database that has never been migrated to the current head —
which is the state of the local production-smoke database this card read.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import osmium
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from pathable_api.cli import main
from pathable_api.core.config import get_settings
from pathable_api.geo.fixtures import load_synthetic_dataset
from pathable_api.geo.kitchener import geography
from pathable_api.geo.kitchener.geography import PathAbleReadError, read_pathable_edges
from pathable_api.geo.kitchener.normalize import normalize_snapshot
from tests.integration.conftest import alembic_config
from tests.kitchener_fixture import snapshot

pytestmark = pytest.mark.integration

Cli = Callable[[list[str]], int]
DATASET_ROW = text(
    "SELECT id, status, checksum, activated_at, retired_at, node_count, edge_count, "
    "source_name, ingestion_configuration::text FROM dataset_versions ORDER BY id"
)


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, migrated_database_url: str) -> Iterator[Cli]:
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    get_settings.cache_clear()
    yield main
    get_settings.cache_clear()


def _dataset_rows(database_url: str) -> list[tuple[Any, ...]]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return [tuple(row) for row in connection.execute(DATASET_ROW)]
    finally:
        engine.dispose()


def _waterloo_extract(path: Path) -> Path:
    """Two short footways inside the Waterloo pilot box."""
    stamp = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    writer = osmium.SimpleWriter(str(path))
    try:
        for node_id, location in (
            (1, (-80.5400, 43.4700)),
            (2, (-80.5390, 43.4705)),
            (3, (-80.5380, 43.4710)),
        ):
            writer.add_node(
                osmium.osm.mutable.Node(id=node_id, version=1, timestamp=stamp, location=location)
            )
        for way_id, refs in ((100, [1, 2]), (200, [2, 3])):
            writer.add_way(
                osmium.osm.mutable.Way(
                    id=way_id, version=1, timestamp=stamp, nodes=refs, tags={"highway": "footway"}
                )
            )
    finally:
        writer.close()
    return path


class TestRead:
    async def test_the_graph_is_read_with_the_facts_that_identify_it(
        self, db_session: AsyncSession
    ) -> None:
        loaded = await load_synthetic_dataset(db_session, activate=True)
        await db_session.commit()

        edges = await read_pathable_edges(db_session, region_slug="waterloo-synthetic")

        assert edges.facts.dataset_id == str(loaded.dataset_id)
        assert edges.facts.status == "active"
        assert len(edges.highway) == edges.facts.edge_count == loaded.edge_count
        # Reprojected into the Kitchener source's NAD83 / UTM 17N metres.
        x, y = edges.geometries[0].coords[0]
        assert 500_000 < x < 560_000
        assert 4_800_000 < y < 4_830_000
        assert not db_session.in_transaction()

    async def test_a_write_during_the_read_is_refused_by_postgres(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await load_synthetic_dataset(db_session, activate=True)
        await db_session.commit()
        monkeypatch.setattr(
            geography,
            "_ACTIVE",
            text(
                "UPDATE dataset_versions SET source_name = 'tampered' "
                "WHERE pilot_region_id = :region RETURNING id"
            ),
        )

        with pytest.raises(DBAPIError, match="read-only transaction"):
            await read_pathable_edges(db_session, region_slug="waterloo-synthetic")

        names = (await db_session.execute(text("SELECT source_name FROM dataset_versions"))).all()
        assert all(name != "tampered" for (name,) in names)

    async def test_a_region_without_one_active_dataset_is_an_error(
        self, db_session: AsyncSession
    ) -> None:
        await load_synthetic_dataset(db_session, activate=False)
        await db_session.commit()

        with pytest.raises(PathAbleReadError, match="0 active datasets"):
            await read_pathable_edges(db_session, region_slug="waterloo-synthetic")

    async def test_a_database_still_at_0005_can_be_read(
        self, db_session: AsyncSession, migrated_database_url: str
    ) -> None:
        loaded = await load_synthetic_dataset(db_session, activate=True)
        await db_session.commit()
        await db_session.close()
        from alembic import command

        command.downgrade(alembic_config(migrated_database_url), "0005_kerb_tiers")

        edges = await read_pathable_edges(db_session, region_slug="waterloo-synthetic")

        assert edges.facts.dataset_id == str(loaded.dataset_id)
        assert len(edges.highway) == loaded.edge_count


class TestCommand:
    def test_audit_runs_end_to_end_and_leaves_the_dataset_untouched(
        self, cli: Cli, migrated_database_url: str, tmp_path: Path
    ) -> None:
        pbf = _waterloo_extract(tmp_path / "waterloo.osm.pbf")
        assert cli(["regions", "seed"]) == 0
        assert cli(["ingest", "pbf", "--region", "waterloo", "--file", str(pbf)]) == 0
        before = _dataset_rows(migrated_database_url)
        (candidate_id,) = {str(row[0]) for row in before}
        taken = snapshot(tmp_path / "snapshots")
        normalized = normalize_snapshot(taken.folder, tmp_path / "normalized").folder
        profile_path = tmp_path / "profile.json"
        sample_path = tmp_path / "sample.geojson"

        code = cli(
            [
                "kitchener", "audit", "--region", "waterloo", "--dataset", candidate_id,
                "--snapshot", str(taken.folder), "--normalized", str(normalized),
                "--json", str(profile_path), "--sample", str(sample_path),
            ]
        )  # fmt: skip

        assert code == 0
        assert _dataset_rows(migrated_database_url) == before
        profile = json.loads(profile_path.read_text("utf-8"))
        study = profile["geography"]["study_area"]
        assert study["region"] == "waterloo"
        assert study["database_boundary_matches_definition"] is True
        assert study["dataset"]["dataset_id"] == candidate_id
        # The fixture sits far from Waterloo: nothing overlaps, and the report says so.
        assert profile["geography"]["records_intersecting_study_area"] == 0
        assert json.loads(sample_path.read_text("utf-8"))["features"] == []
