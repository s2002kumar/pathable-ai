"""OSM edit provenance read from a local extract.

Written by the test with osmium, with metadata on some elements and not on
others, because real extracts come both ways: Geofabrik's public files carry
versions and timestamps, and an extract written without metadata reports
version 0 and the UNIX epoch. Those are absences, and must be stored as such.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import osmium
import pytest

from pathable_api.geo.network import NetworkEdge, NetworkNode, NetworkPayload, OsmEdit
from pathable_api.geo.pbf import (
    collected_to_payload,
    describe_provenance,
    latest_member_edit,
    read_pbf,
)

BOUNDS = (-80.5450, 43.4650, -80.5300, 43.4750)

EARLY = dt.datetime(2019, 3, 1, 9, 0, tzinfo=dt.UTC)
LATER = dt.datetime(2024, 6, 12, 17, 30, tzinfo=dt.UTC)
LATEST = dt.datetime(2025, 1, 20, 8, 15, tzinfo=dt.UTC)


def _node(
    node_id: int, lon: float, version: int = 0, at: dt.datetime | None = None
) -> osmium.osm.mutable.Node:
    if version:
        return osmium.osm.mutable.Node(
            id=node_id, location=(lon, 43.47), tags={}, version=version, timestamp=at
        )
    return osmium.osm.mutable.Node(id=node_id, location=(lon, 43.47), tags={})


@pytest.fixture(scope="module")
def extract(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("provenance") / "provenance.osm.pbf"
    writer = osmium.SimpleWriter(str(path))
    try:
        writer.add_node(_node(1, -80.5400, version=4, at=EARLY))
        writer.add_node(_node(2, -80.5390, version=9, at=LATEST))
        writer.add_node(_node(3, -80.5380, version=2, at=EARLY))
        # Written without metadata: version 0, timestamp at the epoch.
        writer.add_node(_node(4, -80.5370))
        writer.add_node(_node(5, -80.5360, version=1, at=EARLY))
        writer.add_node(_node(6, -80.5350, version=1, at=EARLY))
        # Every member known; node 2 was edited after the way itself.
        writer.add_way(
            osmium.osm.mutable.Way(
                id=100, nodes=[1, 2, 3], tags={"highway": "footway"}, version=6, timestamp=LATER
            )
        )
        # One member without an edit time.
        writer.add_way(
            osmium.osm.mutable.Way(
                id=101, nodes=[3, 4], tags={"highway": "footway"}, version=3, timestamp=LATER
            )
        )
        # The way itself carries no metadata.
        writer.add_way(osmium.osm.mutable.Way(id=102, nodes=[5, 6], tags={"highway": "footway"}))
    finally:
        writer.close()
    return path


@pytest.fixture(scope="module")
def payload(extract: Path) -> NetworkPayload:
    return collected_to_payload(read_pbf(extract, BOUNDS), BOUNDS)


def _edges_of(payload: NetworkPayload, way_id: str) -> list[NetworkEdge]:
    return [edge for edge in payload.edges if edge.source_way_id == way_id]


def _node_of(payload: NetworkPayload, node_id: str) -> NetworkNode:
    return next(node for node in payload.nodes if node.source_node_id == node_id)


class TestNodes:
    def test_a_node_carries_the_version_and_edit_time_it_was_read_with(
        self, payload: NetworkPayload
    ) -> None:
        assert _node_of(payload, "2").osm == OsmEdit(version=9, edited_at=LATEST)

    def test_a_node_written_without_metadata_has_no_provenance(
        self, payload: NetworkPayload
    ) -> None:
        # Not version 0 and not 1970-01-01: those are what "absent" looks like.
        assert _node_of(payload, "4").osm is None


class TestWays:
    def test_every_segment_of_a_way_carries_the_way_version(self, payload: NetworkPayload) -> None:
        segments = _edges_of(payload, "100")

        assert len(segments) == 2
        assert {edge.osm_way for edge in segments} == {OsmEdit(version=6, edited_at=LATER)}

    def test_a_node_edited_after_its_way_is_the_latest_edit(self, payload: NetworkPayload) -> None:
        # A moved node reshapes a way without touching the way's version.
        for edge in _edges_of(payload, "100"):
            assert edge.osm_way_latest_edit_at == LATEST

    def test_one_member_without_an_edit_time_makes_the_latest_edit_unknown(
        self, payload: NetworkPayload
    ) -> None:
        (segment,) = _edges_of(payload, "101")

        assert segment.osm_way is not None
        assert segment.osm_way_latest_edit_at is None

    def test_a_way_written_without_metadata_has_no_provenance(
        self, payload: NetworkPayload
    ) -> None:
        (segment,) = _edges_of(payload, "102")

        assert segment.osm_way is None
        assert segment.osm_way_latest_edit_at is None

    def test_the_coverage_is_counted_not_assumed(self, payload: NetworkPayload) -> None:
        provenance = describe_provenance(payload)

        assert provenance["nodes"] == 6
        assert provenance["nodes_with_version"] == 5
        assert provenance["edges_with_way_version"] == 3
        assert provenance["edges_with_way_latest_edit"] == 2


class TestLatestMemberEdit:
    def test_a_member_outside_the_area_read_makes_it_unknown(self) -> None:
        edits = {1: (1, 100), 2: (1, 200)}

        assert latest_member_edit((1, 50), [1, 2, 3], edits) is None

    def test_it_is_the_maximum_across_the_way_and_its_nodes(self) -> None:
        edits = {1: (1, 100), 2: (1, 300)}

        assert latest_member_edit((1, 200), [1, 2], edits) == dt.datetime.fromtimestamp(
            300, tz=dt.UTC
        )
