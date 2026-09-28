"""The shadow-routing study against real PostGIS: it reads the active dataset and writes nothing.

PA-GEO-07 must leave production exactly as it found it. Tested here: every
transaction it opens is refused writes by PostgreSQL itself, and a whole run
of the command leaves the dataset's rows and content checksum unchanged.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from pathable_api.cli import main
from pathable_api.core.config import get_settings
from pathable_api.core.event_loop import selector_loop_factory
from pathable_api.geo.fixtures import load_synthetic_dataset
from pathable_api.geo.kitchener.osm_extract import (
    OsmNode,
    OsmWay,
    StudyExtract,
    write_study_extract,
)
from pathable_api.geo.kitchener.shadow_page import WATERMARK
from pathable_api.geo.kitchener.shadow_run import active_dataset, read_only
from tests.unit.kitchener_geo06_artifact import write_geo06_artifact

pytestmark = pytest.mark.integration

Cli = Callable[[list[str]], int]
REGION = "waterloo-synthetic"


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, migrated_database_url: str) -> Iterator[Cli]:
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    get_settings.cache_clear()
    yield main
    get_settings.cache_clear()


def _live_fixture(database_url: str) -> str:
    async def load() -> str:
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with AsyncSession(engine) as session:
                result = await load_synthetic_dataset(session)
                await session.commit()
                return str(result.dataset_id)
        finally:
            await engine.dispose()

    return asyncio.run(load(), loop_factory=selector_loop_factory())


def _rows(database_url: str) -> list[tuple[object, ...]]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return [
                tuple(row)
                for row in connection.execute(
                    text(
                        "SELECT id, status, checksum, content_checksum, "
                        "(SELECT count(*) FROM graph_edges e WHERE e.dataset_version_id = d.id) "
                        "FROM dataset_versions d ORDER BY id"
                    )
                )
            ]
    finally:
        engine.dispose()


def test_every_transaction_it_opens_refuses_writes(migrated_database_url: str) -> None:
    _live_fixture(migrated_database_url)

    async def attempt() -> None:
        engine = create_async_engine(migrated_database_url, poolclass=NullPool)
        try:
            async with AsyncSession(engine) as session:
                await read_only(session)
                await active_dataset(session, REGION)
                with pytest.raises(DBAPIError, match="read-only transaction"):
                    await session.execute(text("UPDATE dataset_versions SET source_name = 'x'"))
        finally:
            await engine.dispose()

    asyncio.run(attempt(), loop_factory=selector_loop_factory())


def test_a_whole_run_leaves_the_active_dataset_as_it_was(
    cli: Cli, migrated_database_url: str, tmp_path: Path
) -> None:
    dataset_id = _live_fixture(migrated_database_url)
    before = _rows(migrated_database_url)
    extract = tmp_path / "study.jsonl.gz"
    sha = write_study_extract(
        StudyExtract(
            nodes={
                1: OsmNode(1, -80.5, 43.45, 1, None, {}),
                2: OsmNode(2, -80.49, 43.45, 1, None, {}),
            },
            ways={100: OsmWay(100, 1, None, {"highway": "footway"}, (1, 2))},
        ),
        extract,
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "dataset": {"dataset_id": dataset_id, "source_bbox": [-80.6, 43.4, -80.4, 43.6]},
                "output": {"sha256": sha},
            }
        ),
        encoding="utf-8",
    )
    artifact, committed = write_geo06_artifact(
        tmp_path / "geo06", evidence_name="kitchener-geo06-reconciliation.json"
    )
    out, page = tmp_path / "evidence.json", tmp_path / "changes.html"

    code = cli(
        [
            "kitchener", "shadow-routing", "--region", REGION,
            "--geo06-artifact", str(artifact), "--evidence-dir", str(committed.parent),
            "--extract", str(extract), "--extract-manifest", str(manifest),
            "--broad-size", "2", "--per-stratum", "1",
            "--json", str(out), "--html", str(page),
        ]
    )  # fmt: skip

    assert code == 0
    assert _rows(migrated_database_url) == before
    document = json.loads(out.read_text("utf-8"))
    isolation = document["production_isolation"]
    assert isolation["database"]["unchanged"]
    assert (
        isolation["database"]["content_checksum_before"]
        == isolation["database"]["content_checksum_after"]
    )
    assert isolation["baseline_graph_unchanged"]
    # The fixture's segments come from no OSM way, so nothing can be located or filled.
    assert document["surface_evidence"]["network"]["candidate_municipal_segments"] == 0
    assert WATERMARK in page.read_text("utf-8")


def test_an_extract_cut_for_another_dataset_is_refused(
    cli: Cli, migrated_database_url: str, tmp_path: Path
) -> None:
    _live_fixture(migrated_database_url)
    extract = tmp_path / "study.jsonl.gz"
    sha = write_study_extract(StudyExtract(), extract)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "dataset": {
                    "dataset_id": "00000000-0000-0000-0000-000000000000",
                    "source_bbox": [-80.6, 43.4, -80.4, 43.6],
                },
                "output": {"sha256": sha},
            }
        ),
        encoding="utf-8",
    )
    artifact, committed = write_geo06_artifact(
        tmp_path / "geo06", evidence_name="kitchener-geo06-reconciliation.json"
    )

    code = cli(
        [
            "kitchener", "shadow-routing", "--region", REGION,
            "--geo06-artifact", str(artifact), "--evidence-dir", str(committed.parent),
            "--extract", str(extract), "--extract-manifest", str(manifest),
            "--json", str(tmp_path / "out.json"),
        ]
    )  # fmt: skip

    assert code == 1
    assert not (tmp_path / "out.json").exists()
