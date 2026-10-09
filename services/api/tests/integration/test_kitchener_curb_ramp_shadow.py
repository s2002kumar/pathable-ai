"""The curb-ramp shadow study against real PostGIS: it reads the active dataset and writes nothing.

PA-GEO-09 must leave production exactly as it found it. Tested here: a whole
run of the command, bound to a fixture snapshot and a fixture copy of
PA-GEO-08's evidence, leaves the dataset's rows and content checksum
unchanged, writes evidence that says so, and watermarks its page.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pyproj
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from pathable_api.cli import main
from pathable_api.core.config import get_settings
from pathable_api.core.event_loop import selector_loop_factory
from pathable_api.geo.fixtures import load_synthetic_dataset
from pathable_api.geo.kitchener.conflation import load_inputs
from pathable_api.geo.kitchener.curb_ramp_page import WATERMARK
from pathable_api.geo.kitchener.curb_ramp_reconciliation import ACCEPTED_MATCHER, decide_pilot
from pathable_api.geo.kitchener.normalize import normalize_snapshot
from pathable_api.geo.kitchener.osm_extract import (
    OsmNode,
    OsmWay,
    StudyExtract,
    write_study_extract,
)
from pathable_api.geo.kitchener.source import NATIVE_WKID
from tests.kitchener_fixture import X0, Y0, snapshot

pytestmark = pytest.mark.integration

Cli = Callable[[list[str]], int]
REGION = "waterloo-synthetic"
#: Wide enough to hold both the fixture's City records (near X0, Y0 in UTM 17N)
#: and the synthetic dataset's nodes (near Waterloo), shrunk by 50 m inside.
BBOX = [-81.2, 43.3, -80.3, 45.4]


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


def _inputs(tmp_path: Path, dataset_id: str) -> tuple[Path, Path, Path, Path]:
    """A fixture snapshot normalized, a tiny extract beside its records, and their manifests."""
    taken = snapshot(tmp_path / "snapshots")
    normalized = normalize_snapshot(taken.folder, tmp_path / "normalized").folder
    to_lonlat = pyproj.Transformer.from_crs(f"EPSG:{NATIVE_WKID}", "OGC:CRS84", always_xy=True)
    west, south = to_lonlat.transform(X0 - 10, Y0 - 3)
    east, north = to_lonlat.transform(X0 + 110, Y0 - 3)
    extract = tmp_path / "study.jsonl.gz"
    sha = write_study_extract(
        StudyExtract(
            nodes={
                1: OsmNode(1, west, south, 1, None, {}),
                2: OsmNode(2, east, north, 1, None, {}),
            },
            ways={100: OsmWay(100, 1, None, {"highway": "footway", "footway": "sidewalk"}, (1, 2))},
        ),
        extract,
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {"dataset": {"dataset_id": dataset_id, "source_bbox": BBOX}, "output": {"sha256": sha}}
        ),
        encoding="utf-8",
    )
    # A fixture copy of PA-GEO-08's evidence, bound to exactly these inputs.
    inputs = load_inputs(normalized, extract, manifest)
    decisions = decide_pilot(inputs)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "kitchener-geo08-matcher-v2.json").write_text(
        json.dumps(
            {
                "content_sha256": "c" * 64,
                "policy": {"version": ACCEPTED_MATCHER},
                "inputs": {
                    "kitchener": {"snapshot_id": inputs.identity["kitchener"]["snapshot_id"]},
                    "osm_frozen": {"extract_sha256": sha},
                },
                "full_pilot_dry_run": {
                    "records": len(decisions.v2),
                    "decisions_sha256": decisions.v2_digest,
                    "potential_evidence": {
                        "curb_ramps_at_a_local_way_extent_where_osm_records_no_kerb": 0,
                        "curb_ramps_whose_record_spans_over_20m": 0,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return normalized, extract, manifest, evidence_dir


def test_a_whole_run_leaves_the_active_dataset_as_it_was(
    cli: Cli, migrated_database_url: str, tmp_path: Path
) -> None:
    dataset_id = _live_fixture(migrated_database_url)
    before = _rows(migrated_database_url)
    normalized, extract, manifest, evidence_dir = _inputs(tmp_path, dataset_id)
    out, page = tmp_path / "evidence.json", tmp_path / "changes.html"

    code = cli(
        [
            "kitchener", "curb-ramp-shadow-routing", "--region", REGION,
            "--normalized", str(normalized), "--extract", str(extract),
            "--extract-manifest", str(manifest), "--evidence-dir", str(evidence_dir),
            "--artifact-dir", str(tmp_path / "artifact"),
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
    # The fixture's segments come from no OSM way, so no assertion can reach a crossing.
    assert document["input_funnel"]["final_affected_crossing_segments"] == 0
    assert document["reconciliation"]["routing_eligibility"] == "not_routing_eligible on every row"
    assert (tmp_path / "artifact" / "manifest.json").is_file()
    assert WATERMARK in page.read_text("utf-8")


def test_evidence_that_does_not_bind_these_inputs_is_refused(
    cli: Cli, migrated_database_url: str, tmp_path: Path
) -> None:
    dataset_id = _live_fixture(migrated_database_url)
    normalized, extract, manifest, evidence_dir = _inputs(tmp_path, dataset_id)
    bound = json.loads((evidence_dir / "kitchener-geo08-matcher-v2.json").read_text("utf-8"))
    bound["full_pilot_dry_run"]["decisions_sha256"] = "0" * 64
    (evidence_dir / "kitchener-geo08-matcher-v2.json").write_text(
        json.dumps(bound), encoding="utf-8"
    )

    code = cli(
        [
            "kitchener", "curb-ramp-shadow-routing", "--region", REGION,
            "--normalized", str(normalized), "--extract", str(extract),
            "--extract-manifest", str(manifest), "--evidence-dir", str(evidence_dir),
            "--artifact-dir", str(tmp_path / "artifact"),
            "--json", str(tmp_path / "out.json"),
        ]
    )  # fmt: skip

    assert code == 1
    assert not (tmp_path / "out.json").exists()
