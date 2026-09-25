"""The linkage against a real PostGIS dataset: it reads, and it cannot write.

The guarantee that matters is that inspecting Overture can never alter the
network people route on. It is enforced by a ``READ ONLY`` transaction, so it
is tested by attempting a write in the middle of the read and requiring
PostgreSQL to refuse it — and by comparing the dataset row before and after a
full command-line run.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import osmium
import pytest
from sqlalchemy import create_engine, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from pathable_api.cli import main
from pathable_api.core.config import get_settings
from pathable_api.geo.datasets import get_active_dataset
from pathable_api.geo.fixtures import load_synthetic_dataset
from pathable_api.geo.models import DatasetVersion
from pathable_api.geo.overture.pathable import PathAbleSideError, load_identities
from pathable_api.geo.regions import seed_pilot_regions
from tests.overture_fixture import build_release, extract

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


def _stamp(text_value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text_value).replace(tzinfo=dt.UTC)


def _waterloo_extract(path: Path) -> Path:
    """Three walkable ways inside the Waterloo pilot box, with known versions and times.

    Their ids match the Overture fixture: w100@3 and w200@1, both cited with
    update_time 2024-01-01; w1000 is not cited at all.
    """
    writer = osmium.SimpleWriter(str(path))
    try:
        nodes = {
            1: ("2023-01-01T00:00:00", (-80.5400, 43.4700)),
            2: ("2023-01-01T00:00:00", (-80.5390, 43.4705)),
            3: ("2024-01-01T00:00:00", (-80.5380, 43.4710)),  # edited after way 200 was
            4: ("2023-01-01T00:00:00", (-80.5370, 43.4715)),
            5: ("2023-01-01T00:00:00", (-80.5360, 43.4720)),
        }
        for node_id, (stamp, location) in nodes.items():
            writer.add_node(
                osmium.osm.mutable.Node(
                    id=node_id, version=1, timestamp=_stamp(stamp), location=location
                )
            )
        for way_id, version, stamp, refs in (
            (100, 3, "2024-01-01T00:00:00", [1, 2]),
            (200, 1, "2023-06-01T00:00:00", [2, 3]),
            (1000, 1, "2023-01-01T00:00:00", [4, 5]),
        ):
            writer.add_way(
                osmium.osm.mutable.Way(
                    id=way_id,
                    version=version,
                    timestamp=_stamp(stamp),
                    nodes=refs,
                    tags={"highway": "footway"},
                )
            )
    finally:
        writer.close()
    return path


class TestReadOnly:
    async def test_identities_are_read_as_stored(self, db_session: AsyncSession) -> None:
        await load_synthetic_dataset(db_session, activate=True)
        await db_session.commit()

        identities = await load_identities(db_session, region_slug="waterloo-synthetic")

        assert identities.facts.status == "active"
        assert identities.way_edges
        # The fixture's ids are names, never OSM ids, and are read back as such.
        assert all(way.startswith("synthetic-") for way in identities.way_edges)
        assert not db_session.in_transaction()

    async def test_a_write_during_the_read_is_refused_by_postgres(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await load_synthetic_dataset(db_session, activate=True)
        await db_session.commit()
        refused: list[BaseException] = []

        async def tampering(session: AsyncSession, region_id: Any) -> Any:
            try:
                async with session.begin_nested():
                    await session.execute(update(DatasetVersion).values(source_name="tampered"))
            except DBAPIError as error:
                refused.append(error)
            return await get_active_dataset(session, region_id)

        monkeypatch.setattr("pathable_api.geo.overture.pathable.get_active_dataset", tampering)
        await load_identities(db_session, region_slug="waterloo-synthetic")

        assert refused
        assert "read-only transaction" in str(refused[0])
        names = (await db_session.execute(text("SELECT source_name FROM dataset_versions"))).all()
        assert all(name != "tampered" for (name,) in names)

    async def test_a_region_without_an_active_dataset_is_an_error(
        self, db_session: AsyncSession
    ) -> None:
        await load_synthetic_dataset(db_session, activate=False)
        await db_session.commit()

        with pytest.raises(PathAbleSideError, match="no active dataset"):
            await load_identities(db_session, region_slug="waterloo-synthetic")

    async def test_a_dataset_from_another_region_is_refused(self, db_session: AsyncSession) -> None:
        result = await load_synthetic_dataset(db_session, activate=True)
        await seed_pilot_regions(db_session)
        await db_session.commit()

        with pytest.raises(PathAbleSideError, match="does not exist in region waterloo"):
            await load_identities(db_session, region_slug="waterloo", dataset_id=result.dataset_id)


class TestCommand:
    def test_link_runs_end_to_end_and_leaves_the_dataset_untouched(
        self, cli: Cli, migrated_database_url: str, tmp_path: Path
    ) -> None:
        pbf = _waterloo_extract(tmp_path / "waterloo.osm.pbf")
        assert cli(["regions", "seed"]) == 0
        assert cli(["ingest", "pbf", "--region", "waterloo", "--file", str(pbf)]) == 0
        folder = extract(
            build_release(tmp_path / "release"), tmp_path / "out", region_slug="waterloo"
        )
        before = _dataset_rows(migrated_database_url)
        report_path = tmp_path / "linkage.json"

        code = cli(
            [
                "overture", "link", "--region", "waterloo", "--extract", str(folder),
                "--osm-pbf", str(pbf), "--json", str(report_path),
            ]
        )  # fmt: skip

        assert code == 0
        assert _dataset_rows(migrated_database_url) == before
        report = json.loads(report_path.read_text("utf-8"))
        assert report["ways"]["by_match"] == {"linked": 2, "not_in_overture_sources": 1}
        # w100: same version, and Overture's time is the way's own edit.
        # w200: same version, and Overture's time is node 3's later edit.
        assert report["ways"]["by_version_status"] == {"exact_version_match": 2}
        assert report["ways"]["update_time_semantics"]["by_relation"] == {
            "equals_latest_node_edit_time": 1,
            "equals_way_edit_time": 1,
        }

    def test_link_refuses_an_extract_made_for_another_region(
        self, cli: Cli, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        folder = extract(build_release(tmp_path / "release"), tmp_path / "out")

        code = cli(["overture", "link", "--region", "waterloo", "--extract", str(folder)])

        assert code == 2
        assert "fixture-region" in capsys.readouterr().err
