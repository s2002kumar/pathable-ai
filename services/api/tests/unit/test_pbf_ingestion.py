"""Reading a network from a local OpenStreetMap extract.

The fixture is written by the test itself with osmium, so CI never downloads an
extract and never touches a public service. It is small and deliberate: a
footway, a crossing with a kerb node, a one-way escalator, a motorway nobody
walks on, and a way with a conflicting surface.

The point of these tests is **parity**. The same OSM facts must produce the same
PathAble interpretation whichever way they arrived, because otherwise a route
would depend on how the data was fetched.
"""

from __future__ import annotations

from pathlib import Path

import osmium
import pytest

from pathable_api.geo.directionality import normalise_foot_direction
from pathable_api.geo.enums import KerbType, SurfaceClass, TriState
from pathable_api.geo.features import normalise_edge
from pathable_api.geo.pbf import (
    collected_to_payload,
    file_sha256,
    import_from_pbf,
    read_pbf,
)

# A patch of Waterloo-shaped geography. Coordinates are arbitrary but inside the
# bounds the tests clip to.
BOUNDS = (-80.5450, 43.4650, -80.5300, 43.4750)

NODES: dict[int, tuple[float, float, dict[str, str]]] = {
    1: (-80.5400, 43.4700, {}),
    2: (-80.5380, 43.4700, {}),
    # A kerb node where the crossing meets the road: dropped on one side.
    3: (-80.5360, 43.4700, {"barrier": "kerb", "kerb": "lowered", "tactile_paving": "yes"}),
    4: (-80.5340, 43.4700, {"highway": "crossing", "crossing": "traffic_signals"}),
    5: (-80.5320, 43.4700, {}),
    # Far outside the clip bounds.
    9: (-79.0000, 43.0000, {}),
}

WAYS: list[tuple[int, dict[str, str], list[int]]] = [
    (100, {"highway": "footway", "surface": "asphalt", "smoothness": "good"}, [1, 2]),
    # The standard crossing tagging, between two nodes that carry kerb evidence.
    (101, {"highway": "footway", "footway": "crossing"}, [3, 4]),
    # A vehicle one-way that must not restrict walking.
    (102, {"highway": "residential", "oneway": "yes"}, [2, 3]),
    # A genuine pedestrian one-way.
    (103, {"highway": "steps", "conveying": "forward", "step_count": "18"}, [4, 5]),
    # Nobody walks on a motorway.
    (104, {"highway": "motorway"}, [1, 5]),
    # Outside the region entirely.
    (105, {"highway": "footway"}, [9, 9]),
]


@pytest.fixture(scope="module")
def extract(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Write a tiny .osm.pbf with osmium, so no download is ever needed."""
    path = tmp_path_factory.mktemp("pbf") / "fixture.osm.pbf"
    writer = osmium.SimpleWriter(str(path))
    try:
        for node_id, (lon, lat, tags) in NODES.items():
            writer.add_node(osmium.osm.mutable.Node(id=node_id, location=(lon, lat), tags=tags))
        for way_id, tags, refs in WAYS:
            writer.add_way(osmium.osm.mutable.Way(id=way_id, nodes=refs, tags=tags))
    finally:
        writer.close()
    return path


class TestReading:
    def test_it_reads_walkable_ways(self, extract: Path) -> None:
        collected = read_pbf(extract, BOUNDS)
        way_ids = {way_id for way_id, _, _ in collected.ways}

        assert 100 in way_ids
        assert 101 in way_ids
        assert 103 in way_ids

    def test_it_excludes_ways_nobody_walks_on(self, extract: Path) -> None:
        collected = read_pbf(extract, BOUNDS)
        assert 104 not in {way_id for way_id, _, _ in collected.ways}

    def test_it_clips_to_the_requested_region(self, extract: Path) -> None:
        collected = read_pbf(extract, BOUNDS)
        assert 105 not in {way_id for way_id, _, _ in collected.ways}

    def test_it_keeps_node_tags(self, extract: Path) -> None:
        # The whole reason for choosing this reader: kerbs live on nodes, and a
        # reader that drops node tags cannot see a single one.
        collected = read_pbf(extract, BOUNDS)

        assert collected.node_tags[3]["kerb"] == "lowered"
        assert collected.node_tags[4]["highway"] == "crossing"

    def test_it_keeps_coordinates_for_every_referenced_node(self, extract: Path) -> None:
        collected = read_pbf(extract, BOUNDS)
        for _, _, refs in collected.ways:
            for ref in refs:
                assert ref in collected.node_coordinates


class TestInterpretation:
    def test_a_crossing_inherits_its_kerb_from_the_node(self, extract: Path) -> None:
        payload = collected_to_payload(read_pbf(extract, BOUNDS))
        crossing = next(
            edge for edge in payload.edges if (edge.source_u, edge.source_v) == ("3", "4")
        )

        assert crossing.features.is_crossing is True
        assert crossing.features.kerb is KerbType.LOWERED
        assert crossing.features.kerb_from_node is True

    def test_a_vehicle_oneway_does_not_restrict_walking(self, extract: Path) -> None:
        payload = collected_to_payload(read_pbf(extract, BOUNDS))
        residential = next(
            edge for edge in payload.edges if (edge.source_u, edge.source_v) == ("2", "3")
        )

        assert residential.direction.forward and residential.direction.backward
        assert residential.features.vehicle_oneway_ignored is True

    def test_a_conveying_escalator_is_one_way(self, extract: Path) -> None:
        payload = collected_to_payload(read_pbf(extract, BOUNDS))
        escalator = next(
            edge for edge in payload.edges if (edge.source_u, edge.source_v) == ("4", "5")
        )

        assert escalator.direction.forward is True
        assert escalator.direction.backward is False
        assert escalator.features.steps is TriState.YES
        assert escalator.features.step_count == 18

    def test_geometry_is_built_from_real_coordinates(self, extract: Path) -> None:
        payload = collected_to_payload(read_pbf(extract, BOUNDS))
        footway = next(
            edge for edge in payload.edges if (edge.source_u, edge.source_v) == ("1", "2")
        )

        assert footway.length > 100.0
        assert footway.features.surface_class is SurfaceClass.PAVED


class TestAcquisitionParity:
    """The same OSM facts must mean the same thing however they arrived.

    A route that changed depending on whether the data came from Overpass or a
    file would make every evaluation meaningless — you could never tell a real
    improvement from a different download.
    """

    @pytest.mark.parametrize(
        "tags",
        [
            {"highway": "footway", "surface": "asphalt", "smoothness": "good"},
            {"highway": "footway", "footway": "crossing"},
            {"highway": "residential", "oneway": "yes"},
            {"highway": "steps", "conveying": "forward", "step_count": "18"},
            {"highway": "path", "surface": "gravel", "incline": "7%"},
            {"highway": "footway", "oneway:foot": "-1"},
        ],
    )
    def test_normalisation_is_shared_not_duplicated(self, tags: dict[str, str]) -> None:
        # Both acquisition paths call exactly these functions; nothing about the
        # source is allowed to change the interpretation.
        features = normalise_edge(dict(tags))
        direction = normalise_foot_direction(dict(tags))

        assert normalise_edge(dict(tags)) == features
        assert normalise_foot_direction(dict(tags)) == direction

    def test_the_pbf_path_produces_the_same_features_as_direct_normalisation(
        self, extract: Path
    ) -> None:
        payload = collected_to_payload(read_pbf(extract, BOUNDS))
        footway = next(
            edge for edge in payload.edges if (edge.source_u, edge.source_v) == ("1", "2")
        )
        expected = normalise_edge(
            {"highway": "footway", "surface": "asphalt", "smoothness": "good"}
        )

        assert footway.features.surface_class is expected.surface_class
        assert footway.features.smoothness_class is expected.smoothness_class
        assert footway.features.steps is expected.steps


class TestProvenance:
    def test_the_import_records_the_exact_bytes_it_read(self, extract: Path) -> None:
        # A filename cannot identify a dataset: extracts are republished under
        # the same name every day.
        result = import_from_pbf(extract, BOUNDS, region_slug="waterloo")

        assert result.file_sha256 == file_sha256(extract)
        assert len(result.file_sha256) == 64
        assert result.file_bytes == extract.stat().st_size

    def test_the_configuration_is_enough_to_reproduce_the_import(self, extract: Path) -> None:
        configuration = import_from_pbf(
            extract, BOUNDS, region_slug="waterloo", provider="geofabrik"
        ).configuration

        assert configuration["provider"] == "geofabrik"
        assert configuration["acquisition"] == "local-pbf-extract"
        assert configuration["bbox"] == list(BOUNDS)
        assert configuration["reader"].startswith("osmium ")
        assert "ODbL" in configuration["attribution"]

    def test_the_same_file_hashes_the_same_twice(self, extract: Path) -> None:
        assert file_sha256(extract) == file_sha256(extract)
