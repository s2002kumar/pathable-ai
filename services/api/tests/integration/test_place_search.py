"""Place search against real PostGIS: the index, its ranking, the API and the CLI.

Ranking is decided by SQL that only PostgreSQL can run — word-start regular
expressions, ``pg_trgm`` similarity — so none of it is worth testing against
anything else. The entries are invented and live only in the throwaway database
each test gets.
"""

from __future__ import annotations

import datetime as dt
import zlib
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pathable_api.cli import main
from pathable_api.core.config import Settings, get_settings
from pathable_api.geo.enums import PlaceKind
from pathable_api.geo.gazetteer import GazetteerImport, PlaceEntry
from pathable_api.geo.gazetteer_store import (
    GazetteerMatch,
    replace_gazetteer,
    search_gazetteer,
)
from pathable_api.geo.models import GazetteerBuild, GazetteerEntry
from pathable_api.geo.place_text import normalise_text
from pathable_api.geo.regions import WATERLOO, seed_region
from pathable_api.main import create_app
from tests.unit.test_gazetteer import write_extract

pytestmark = pytest.mark.integration

SEARCH = "/api/v1/geocode/search"
AS_OF = dt.datetime(2026, 8, 16, 20, 21, 42, tzinfo=dt.UTC)


def entry(kind: PlaceKind, label: str, category: str | None, lon: float, lat: float) -> PlaceEntry:
    return PlaceEntry(
        kind=kind,
        label=label,
        category=category,
        search_text=normalise_text(label),
        longitude=lon,
        latitude=lat,
        osm_type="node",
        osm_id=zlib.crc32(label.encode()),
        osm_version=None,
    )


PLACE, STREET, ADDRESS = PlaceKind.PLACE, PlaceKind.STREET, PlaceKind.ADDRESS

ENTRIES = [
    entry(PLACE, "Conestoga Mall", "mall", -80.5300, 43.4980),
    entry(STREET, "Conestoga Mall Lane", "street", -80.5290, 43.4990),
    entry(PLACE, "Conestoga Station", "transit platform", -80.5320, 43.4975),
    entry(PLACE, "University of Waterloo", "university", -80.5440, 43.4720),
    entry(STREET, "University Avenue West, Waterloo", "street", -80.5400, 43.4730),
    entry(ADDRESS, "200 University Avenue West, Waterloo", "address", -80.5390, 43.4725),
    entry(ADDRESS, "1200 University Avenue West, Waterloo", "address", -80.5600, 43.4800),
    entry(PLACE, "Davis Centre", "university", -80.5420, 43.4728),
    # Three features that share a name, as at the real Waterloo Public Square.
    entry(PLACE, "Waterloo Public Square", "information", -80.5226, 43.4641),
    entry(PLACE, "Waterloo Public Square", "transit station", -80.5228, 43.4642),
    entry(PLACE, "Waterloo Public Square, 75 King Street South", "square", -80.5224, 43.4638),
    *(
        entry(PLACE, f"Coffee Shop {index}", "cafe", -80.52 - index / 1000, 43.47)
        for index in range(6)
    ),
]


def extract_of(entries: list[PlaceEntry]) -> GazetteerImport:
    return GazetteerImport(
        entries=entries,
        file_name="fixture.osm.pbf",
        file_sha256="a" * 64,
        source_timestamp=AS_OF,
        configuration={"source": "openstreetmap", "provider": "test"},
    )


async def build_index(session: AsyncSession, entries: list[PlaceEntry]) -> GazetteerBuild:
    region = await seed_region(session, WATERLOO)
    build = await replace_gazetteer(
        session,
        region=region,
        source_name="openstreetmap-pbf:waterloo",
        extract=extract_of(entries),
    )
    await session.commit()
    return build


@pytest_asyncio.fixture
async def index(db_session: AsyncSession) -> GazetteerBuild:
    return await build_index(db_session, ENTRIES)


async def labels(session: AsyncSession, build: GazetteerBuild, query: str) -> list[str]:
    found: list[GazetteerMatch] = await search_gazetteer(session, build.id, query, limit=5)
    return [match.label for match in found]


class TestSchema:
    async def test_the_migration_installs_trigram_matching(self, db_session: AsyncSession) -> None:
        installed = await db_session.scalar(
            text("SELECT count(*) FROM pg_extension WHERE extname = 'pg_trgm'")
        )
        assert installed == 1

    async def test_one_index_per_region_is_enforced_by_the_database(
        self, db_session: AsyncSession, index: GazetteerBuild
    ) -> None:
        db_session.add(
            GazetteerBuild(
                pilot_region_id=index.pilot_region_id,
                source_name="another",
                file_name="other.osm.pbf",
                file_sha256="b" * 64,
                place_count=0,
                address_count=0,
                street_count=0,
                configuration={},
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()


class TestRanking:
    async def test_an_exact_name_comes_first(
        self, db_session: AsyncSession, index: GazetteerBuild
    ) -> None:
        found = await labels(db_session, index, "Conestoga Mall")

        assert found[:2] == ["Conestoga Mall", "Conestoga Mall Lane"]

    async def test_places_come_before_streets_for_a_name(
        self, db_session: AsyncSession, index: GazetteerBuild
    ) -> None:
        found = await labels(db_session, index, "University")

        assert found.index("University of Waterloo") < found.index(
            "University Avenue West, Waterloo"
        )

    async def test_a_query_that_starts_with_a_number_wants_the_address(
        self, db_session: AsyncSession, index: GazetteerBuild
    ) -> None:
        found = await labels(db_session, index, "200 University Ave W")

        assert found[0] == "200 University Avenue West, Waterloo"

    async def test_a_house_number_matches_whole(
        self, db_session: AsyncSession, index: GazetteerBuild
    ) -> None:
        # "200" is a different door from "1200"; a prefix match would send
        # somebody a kilometre away.
        found = await labels(db_session, index, "200 University Avenue West")

        assert "1200 University Avenue West, Waterloo" not in found

    async def test_a_word_can_be_typed_partly(
        self, db_session: AsyncSession, index: GazetteerBuild
    ) -> None:
        assert "Conestoga Mall" in await labels(db_session, index, "conest mall")

    async def test_every_word_typed_must_match(
        self, db_session: AsyncSession, index: GazetteerBuild
    ) -> None:
        assert await labels(db_session, index, "Conestoga Station") == ["Conestoga Station"]

    async def test_the_place_comes_before_what_is_named_after_it(
        self, db_session: AsyncSession, index: GazetteerBuild
    ) -> None:
        # Regression: on the real index, "Davis Centre" put a taxi stand first,
        # because an exact name outranked everything. The square comes first,
        # then the stop that serves it, then the information board.
        found = await labels(db_session, index, "Waterloo Public Square")

        assert found == [
            "Waterloo Public Square, 75 King Street South",
            "Waterloo Public Square",
            "Waterloo Public Square",
        ]
        [square, stop, board] = await search_gazetteer(
            db_session, index.id, "Waterloo Public Square", limit=5
        )
        assert (square.category, stop.category, board.category) == (
            "square",
            "transit station",
            "information",
        )

    async def test_a_misspelling_still_finds_the_place(
        self, db_session: AsyncSession, index: GazetteerBuild
    ) -> None:
        found = await labels(db_session, index, "Konestoga Mall")

        assert found[0] == "Conestoga Mall"

    async def test_no_more_than_five_results_come_back(
        self, db_session: AsyncSession, index: GazetteerBuild
    ) -> None:
        assert len(await labels(db_session, index, "coffee")) == 5

    async def test_a_query_with_no_words_finds_nothing(
        self, db_session: AsyncSession, index: GazetteerBuild
    ) -> None:
        assert await labels(db_session, index, "!!! ???") == []

    async def test_a_result_carries_its_kind_category_and_point(
        self, db_session: AsyncSession, index: GazetteerBuild
    ) -> None:
        [davis] = await search_gazetteer(db_session, index.id, "Davis Centre", limit=1)

        assert davis.kind is PlaceKind.PLACE
        assert davis.category == "university"
        assert (davis.longitude, davis.latitude) == pytest.approx((-80.5420, 43.4728))


class TestReplacement:
    async def test_a_rebuild_replaces_the_whole_index(
        self, db_session: AsyncSession, index: GazetteerBuild
    ) -> None:
        replacement = [entry(PLACE, "Waterloo Park", "park", -80.5330, 43.4660)]
        rebuilt = await build_index(db_session, replacement)

        builds = await db_session.scalar(select(func.count()).select_from(GazetteerBuild))
        entries = await db_session.scalar(select(func.count()).select_from(GazetteerEntry))
        assert (builds, entries) == (1, 1)
        assert rebuilt.id != index.id
        assert await labels(db_session, rebuilt, "Conestoga") == []
        assert await labels(db_session, rebuilt, "Waterloo Park") == ["Waterloo Park"]

    async def test_the_build_records_where_it_came_from(
        self, db_session: AsyncSession, index: GazetteerBuild
    ) -> None:
        stored = await db_session.scalar(select(GazetteerBuild))

        assert stored is not None
        assert stored.file_sha256 == "a" * 64
        assert stored.source_timestamp == AS_OF
        assert (stored.place_count, stored.address_count, stored.street_count) == (13, 2, 2)


# --- Through the HTTP API -------------------------------------------------------


@pytest_asyncio.fixture
async def region_database_url(
    migrated_database_url: str, db_session: AsyncSession
) -> AsyncIterator[str]:
    """A migrated database with the Waterloo region seeded and no place index."""
    await seed_region(db_session, WATERLOO)
    await db_session.commit()
    yield migrated_database_url


def client_for(database_url: str) -> TestClient:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        allowed_origins=("http://localhost:3000",),
        log_level="WARNING",
        log_format="console",
        geocoding_provider="local",
    )
    return TestClient(create_app(settings))


def search(client: TestClient, query: str, **extra: Any) -> dict[str, Any]:
    response = client.post(SEARCH, json={"region": "waterloo", "query": query, **extra})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


@pytest_asyncio.fixture
async def indexed_database_url(
    region_database_url: str, db_session: AsyncSession
) -> AsyncIterator[str]:
    """The same database, with the place index built."""
    await build_index(db_session, ENTRIES)
    yield region_database_url


class TestApi:
    def test_a_region_with_no_index_says_nothing_was_searched(
        self, region_database_url: str
    ) -> None:
        with client_for(region_database_url) as client:
            body = search(client, "Davis Centre")

        assert body == {"provider": "local", "enabled": False, "matches": [], "attribution": None}

    def test_a_built_index_answers_with_its_attribution_and_date(
        self, indexed_database_url: str
    ) -> None:
        with client_for(indexed_database_url) as client:
            body = search(client, "Davis Centre")

        assert body["provider"] == "local"
        assert body["enabled"] is True
        assert body["matches"][0] == {
            "label": "Davis Centre",
            "longitude": pytest.approx(-80.5420),
            "latitude": pytest.approx(43.4728),
            "category": "university",
        }
        assert "as of 2026-08-16" in body["attribution"]
        assert "OpenStreetMap contributors, ODbL" in body["attribution"]

    def test_nothing_found_is_distinguishable_from_nothing_searched(
        self, indexed_database_url: str
    ) -> None:
        with client_for(indexed_database_url) as client:
            body = search(client, "Atlantis Boulevard")

        assert body["enabled"] is True
        assert body["matches"] == []

    def test_the_caller_can_ask_for_fewer(self, indexed_database_url: str) -> None:
        with client_for(indexed_database_url) as client:
            body = search(client, "coffee", limit=2)

        assert len(body["matches"]) == 2


# --- Through the command line -----------------------------------------------------

Cli = Callable[[list[str]], int]


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, migrated_database_url: str) -> Iterator[Cli]:
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    get_settings.cache_clear()
    yield main
    get_settings.cache_clear()


class TestCommandLine:
    def test_build_then_search(
        self, cli: Cli, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        extract = write_extract(tmp_path / "fixture.osm.pbf")

        assert cli(["regions", "seed"]) == 0
        assert cli(["gazetteer", "build", "--region", "waterloo", "--file", str(extract)]) == 0
        built = capsys.readouterr().out
        assert "data as of 2026-08-16T20:21:42+00:00 (pbf-header)" in built
        assert "no active network records an extract" in built

        assert cli(["gazetteer", "search", "--region", "waterloo", "Porter Library"]) == 0
        found = capsys.readouterr().out
        assert "Porter Library  [library]" in found
        assert "as of 2026-08-16" in found

    def test_searching_before_building_is_an_error(self, cli: Cli) -> None:
        assert cli(["regions", "seed"]) == 0
        assert cli(["gazetteer", "search", "--region", "waterloo", "anything"]) == 1

    def test_a_missing_extract_is_a_configuration_error(self, cli: Cli, tmp_path: Path) -> None:
        missing = tmp_path / "absent.osm.pbf"
        assert cli(["gazetteer", "build", "--region", "waterloo", "--file", str(missing)]) == 2

    def test_building_for_an_unseeded_region_is_refused(self, cli: Cli, tmp_path: Path) -> None:
        extract = write_extract(tmp_path / "fixture.osm.pbf")
        assert cli(["gazetteer", "build", "--region", "waterloo", "--file", str(extract)]) == 2
