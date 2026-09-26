"""Freezing the OSM side of the lineage study from a real (tiny) PBF file.

The file is written with osmium, the same library that reads it, around an
invented box far from Waterloo. Each element's fate is in its id.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import osmium
import pytest

from pathable_api.geo.kitchener.osm_extract import (
    ExtractSourceError,
    load_study_extract,
    read_study_extract,
    write_study_extract,
)
from pathable_api.geo.overture.evidence import file_sha256

BOX = (10.0, 10.0, 10.1, 10.1)
STAMP = dt.datetime(2020, 5, 1, tzinfo=dt.UTC)


def _pbf(path: Path) -> Path:
    writer = osmium.SimpleWriter(str(path))
    try:
        nodes = {
            1: (10.05, 10.05, {}),
            2: (10.06, 10.05, {}),
            3: (10.07, 10.05, {"kerb": "lowered", "barrier": "kerb"}),
            # Just outside the box but inside the read margin: resolves a way that
            # leaves the box and comes back.
            4: (10.102, 10.05, {}),
            # Far outside: only an outside way uses it.
            5: (11.0, 11.0, {}),
            6: (11.1, 11.0, {}),
            # A kerb node outside the box is not kept on its own.
            7: (10.103, 10.06, {"kerb": "raised"}),
            # An untagged node inside, used by nothing: dropped.
            8: (10.02, 10.02, {}),
        }
        for node_id, (lon, lat, tags) in nodes.items():
            writer.add_node(
                osmium.osm.mutable.Node(
                    id=node_id, version=2, timestamp=STAMP, location=(lon, lat), tags=tags
                )
            )
        for way_id, refs, tags in (
            (100, [1, 2, 3], {"highway": "footway", "footway": "sidewalk"}),
            (101, [3, 4], {"highway": "residential", "name": "Fixture Street"}),
            (102, [5, 6], {"highway": "footway"}),
            (103, [1, 2], {"building": "yes"}),
        ):
            writer.add_way(
                osmium.osm.mutable.Way(id=way_id, version=3, timestamp=STAMP, nodes=refs, tags=tags)
            )
    finally:
        writer.close()
    return path


@pytest.fixture
def pbf(tmp_path: Path) -> Path:
    return _pbf(tmp_path / "fixture.osm.pbf")


class TestRead:
    def test_highway_ways_touching_the_box_are_kept_whole(self, pbf: Path) -> None:
        extract, facts = read_study_extract(pbf, expected_sha256=file_sha256(pbf), bounds=BOX)

        assert sorted(extract.ways) == [100, 101]
        assert extract.ways[101].refs == (3, 4)  # leaves the box, kept whole
        assert extract.ways[100].tags == {"highway": "footway", "footway": "sidewalk"}
        assert extract.ways[100].version == 3
        assert extract.ways[100].timestamp == "2020-05-01T00:00:00Z"
        assert facts["ways"] == 2

    def test_fact_nodes_inside_the_box_keep_their_tags_and_version(self, pbf: Path) -> None:
        extract, _facts = read_study_extract(pbf, expected_sha256=file_sha256(pbf), bounds=BOX)

        assert extract.nodes[3].tags == {"kerb": "lowered", "barrier": "kerb"}
        assert extract.nodes[3].version == 2
        assert 7 not in extract.nodes  # a kerb outside the box
        assert 8 not in extract.nodes  # used by nothing kept
        assert extract.nodes[4].tags == {}  # geometry only

    def test_a_different_file_is_refused(self, pbf: Path) -> None:
        with pytest.raises(ExtractSourceError, match="would describe a different map"):
            read_study_extract(pbf, expected_sha256="0" * 64, bounds=BOX)


class TestWrite:
    def test_the_same_extract_writes_the_same_bytes_and_loads_back(
        self, pbf: Path, tmp_path: Path
    ) -> None:
        extract, _facts = read_study_extract(pbf, expected_sha256=file_sha256(pbf), bounds=BOX)

        first = write_study_extract(extract, tmp_path / "a.jsonl.gz")
        second = write_study_extract(extract, tmp_path / "b.jsonl.gz")
        loaded = load_study_extract(tmp_path / "a.jsonl.gz", expected_sha256=first)

        assert first == second
        assert loaded.ways == extract.ways
        assert loaded.nodes == extract.nodes

    def test_a_changed_extract_is_refused_on_load(self, pbf: Path, tmp_path: Path) -> None:
        extract, _facts = read_study_extract(pbf, expected_sha256=file_sha256(pbf), bounds=BOX)
        path = tmp_path / "a.jsonl.gz"
        write_study_extract(extract, path)

        with pytest.raises(ExtractSourceError, match="recorded SHA-256"):
            load_study_extract(path, expected_sha256="f" * 64)
