"""Versions come only from the exact extract a dataset was built from.

A real, tiny ``.osm.pbf`` is written with osmium for each test, so the reader
is exercised through libosmium rather than through a mock of it.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import osmium
import pytest

from pathable_api.geo.overture.evidence import file_sha256
from pathable_api.geo.overture.osm_versions import (
    ElementState,
    VersionEvidenceError,
    read_versions,
)


def _time(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text).replace(tzinfo=dt.UTC)


@pytest.fixture
def extract(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.osm.pbf"
    writer = osmium.SimpleWriter(str(path))
    try:
        for node_id, version, stamp in (
            (1, 2, "2024-01-01T00:00:00"),
            (2, 1, "2025-06-01T12:30:00"),
            (3, 4, "2023-01-01T00:00:00"),
        ):
            writer.add_node(
                osmium.osm.mutable.Node(
                    id=node_id, version=version, timestamp=_time(stamp), location=(10.0, 10.0)
                )
            )
        for way_id, version, stamp, nodes in (
            (10, 3, "2024-02-01T00:00:00", [1, 2]),  # a node was edited after the way
            (11, 1, "2022-01-01T00:00:00", [1, 3]),
            (12, 1, "2024-03-01T00:00:00", [1, 99]),  # node 99 is not in the file
        ):
            writer.add_way(
                osmium.osm.mutable.Way(
                    id=way_id, version=version, timestamp=_time(stamp), nodes=nodes
                )
            )
    finally:
        writer.close()
    return path


def test_versions_and_the_latest_member_edit_are_read(extract: Path) -> None:
    evidence = read_versions(
        extract, expected_sha256=file_sha256(extract), way_ids={10, 11, 12, 13}, node_ids={1}
    )

    assert evidence.ways[10] == ElementState(3, "2024-02-01T00:00:00Z", "2025-06-01T12:30:00Z")
    assert evidence.ways[11] == ElementState(1, "2022-01-01T00:00:00Z", "2024-01-01T00:00:00Z")
    # A member that cannot be read makes the latest edit unknowable, not "the way's own".
    assert evidence.ways[12].latest_member_timestamp is None
    assert 13 not in evidence.ways
    # Nodes read only to date the ways are not reported as requested nodes.
    assert set(evidence.nodes) == {1}


def test_a_different_extract_is_refused(extract: Path) -> None:
    with pytest.raises(VersionEvidenceError, match="Refusing"):
        read_versions(extract, expected_sha256="0" * 64, way_ids={10}, node_ids=set())


def test_a_dataset_without_a_recorded_hash_cannot_be_given_versions(extract: Path) -> None:
    with pytest.raises(VersionEvidenceError, match="no source-file hash"):
        read_versions(extract, expected_sha256=None, way_ids={10}, node_ids=set())


def test_a_missing_file_is_an_error_not_an_empty_result(tmp_path: Path) -> None:
    with pytest.raises(VersionEvidenceError, match="does not exist"):
        read_versions(
            tmp_path / "gone.osm.pbf", expected_sha256="0" * 64, way_ids={1}, node_ids=set()
        )
