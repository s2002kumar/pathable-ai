"""Freezing the OSM side of the lineage study against real PostGIS.

The study compares against the map PathAble routes on, so the extract must be
cut from the very file the active dataset records it was built from. Tested
here: the dataset's own record is read without writing, the matching file is
frozen, and any other file is refused.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import osmium
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from pathable_api.cli import main
from pathable_api.core.config import get_settings
from pathable_api.core.event_loop import selector_loop_factory
from pathable_api.geo.kitchener.geography import DatasetSource, read_dataset_source
from pathable_api.geo.kitchener.osm_extract import load_study_extract
from pathable_api.geo.overture.evidence import file_sha256

pytestmark = pytest.mark.integration

Cli = Callable[[list[str]], int]


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, migrated_database_url: str) -> Iterator[Cli]:
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    get_settings.cache_clear()
    yield main
    get_settings.cache_clear()


def _extract(path: Path, *, far_node: tuple[float, float] = (-80.3, 43.6)) -> Path:
    """Two footways inside the Waterloo box, and a path that runs far out of it."""
    stamp = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    writer = osmium.SimpleWriter(str(path))
    try:
        for node_id, location in (
            (1, (-80.5400, 43.4700)),
            (2, (-80.5390, 43.4705)),
            (3, (-80.5380, 43.4710)),
            (4, far_node),
        ):
            writer.add_node(
                osmium.osm.mutable.Node(id=node_id, version=1, timestamp=stamp, location=location)
            )
        for way_id, refs, tags in (
            (100, [1, 2], {"highway": "footway"}),
            (200, [2, 3], {"highway": "footway"}),
            (300, [3, 4], {"highway": "path"}),
        ):
            writer.add_way(
                osmium.osm.mutable.Way(id=way_id, version=1, timestamp=stamp, nodes=refs, tags=tags)
            )
    finally:
        writer.close()
    return path


def _dataset_rows(database_url: str) -> list[tuple[object, ...]]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            query = text(
                "SELECT id, status, checksum, ingestion_configuration::text FROM dataset_versions"
            )
            return [tuple(row) for row in connection.execute(query)]
    finally:
        engine.dispose()


class TestLineageExtract:
    def test_the_osm_side_is_frozen_from_the_datasets_own_file(
        self, cli: Cli, migrated_database_url: str, tmp_path: Path
    ) -> None:
        pbf = _extract(tmp_path / "waterloo.osm.pbf")
        assert cli(["regions", "seed"]) == 0
        assert cli(["ingest", "pbf", "--region", "waterloo", "--file", str(pbf)]) == 0
        before = _dataset_rows(migrated_database_url)
        (dataset_id,) = {str(row[0]) for row in before}
        out, manifest = tmp_path / "study.jsonl.gz", tmp_path / "manifest.json"

        code = cli(
            [
                "kitchener", "lineage-extract", "--region", "waterloo", "--dataset", dataset_id,
                "--pbf", str(pbf), "--out", str(out), "--json", str(manifest),
            ]
        )  # fmt: skip

        assert code == 0
        assert _dataset_rows(migrated_database_url) == before
        written = json.loads(manifest.read_text("utf-8"))
        assert written["dataset"]["dataset_id"] == dataset_id
        assert written["dataset"]["source_file_sha256"] == file_sha256(pbf)
        extract = load_study_extract(out, expected_sha256=written["output"]["sha256"])
        assert sorted(extract.ways) == [100, 200, 300]
        # Kept whole, far beyond the box: PathAble's graph has this way too.
        assert extract.ways[300].refs == (3, 4)

    def test_another_file_is_refused(self, cli: Cli, tmp_path: Path) -> None:
        pbf = _extract(tmp_path / "waterloo.osm.pbf")
        other = _extract(tmp_path / "other.osm.pbf", far_node=(-80.2, 43.7))
        assert cli(["regions", "seed"]) == 0
        assert cli(["ingest", "pbf", "--region", "waterloo", "--file", str(pbf)]) == 0
        out = tmp_path / "study.jsonl.gz"

        code = cli(
            [
                "kitchener", "lineage-extract", "--region", "waterloo",
                "--pbf", str(other), "--out", str(out), "--json", str(tmp_path / "m.json"),
            ]
        )  # fmt: skip

        assert code == 1
        assert not out.exists()

    def test_the_source_record_is_read_without_writing(
        self, cli: Cli, migrated_database_url: str, tmp_path: Path
    ) -> None:
        pbf = _extract(tmp_path / "waterloo.osm.pbf")
        assert cli(["regions", "seed"]) == 0
        assert cli(["ingest", "pbf", "--region", "waterloo", "--file", str(pbf)]) == 0
        before = _dataset_rows(migrated_database_url)
        (dataset_id,) = {uuid.UUID(str(row[0])) for row in before}  # a draft: named, not active

        async def read() -> DatasetSource:
            engine = create_async_engine(migrated_database_url, poolclass=NullPool)
            try:
                async with AsyncSession(engine) as session:
                    source = await read_dataset_source(
                        session, region_slug="waterloo", dataset_id=dataset_id
                    )
                    assert not session.in_transaction()
                    return source
            finally:
                await engine.dispose()

        source = asyncio.run(read(), loop_factory=selector_loop_factory())

        assert source.file_sha256 == file_sha256(pbf)
        assert source.file_name == "waterloo.osm.pbf"
        assert source.bbox == (-80.59, 43.42, -80.46, 43.52)
        assert source.as_dict()["source_file_bytes"] == pbf.stat().st_size
        assert _dataset_rows(migrated_database_url) == before
