"""Where Kitchener records sit relative to PathAble's graph — described, not matched.

The fixture graph is placed by hand around the fixture records, so every
distance asserted here can be checked with a ruler.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from pathable_api.geo.kitchener.audit import KitchenerRecord, load_records
from pathable_api.geo.kitchener.geography import (
    RecordGeography,
    band,
    band_order,
    describe_records,
    graph_along_inventory,
    study_area,
)
from pathable_api.geo.kitchener.normalize import NORMALIZED_FILE, normalize_snapshot
from pathable_api.geo.regions import RegionDefinition
from tests.kitchener_fixture import fixture_edges, fixture_region, snapshot


@pytest.fixture
def records(tmp_path: Path) -> list[KitchenerRecord]:
    taken = snapshot(tmp_path / "s")
    folder = normalize_snapshot(taken.folder, tmp_path / "n").folder
    return load_records(folder / NORMALIZED_FILE)


def _describe(
    records: list[KitchenerRecord], region: RegionDefinition | None = None
) -> dict[int | None, RecordGeography]:
    area = (region or fixture_region()).boundary()
    described = describe_records(
        [r.primary for r in records], [r.native for r in records], area, fixture_edges()
    )
    return {r.activetransportid: g for r, g in zip(records, described, strict=True)}


class TestProximity:
    def test_touching_at_one_corner_is_near_but_not_along(
        self, records: list[KitchenerRecord]
    ) -> None:
        # Why the worst-point offset exists: the crosswalk touches an OSM
        # footway at one end, so its closest approach is 0 m, yet its far end
        # is 14 m from any OSM pedestrian way. Closest approach alone would
        # have called it coincident.
        crosswalk = _describe(records)[1003]

        assert crosswalk.nearest_edge_m == 0.0
        assert crosswalk.max_offset_to_osm_pedestrian_m == pytest.approx(14.142, abs=0.01)

    def test_a_line_running_alongside_has_a_small_worst_point(
        self, records: list[KitchenerRecord]
    ) -> None:
        described = _describe(records)

        assert described[1001].max_offset_to_osm_pedestrian_m == pytest.approx(1.0)
        assert described[1005].max_offset_to_osm_pedestrian_m == pytest.approx(5.0)
        assert described[1010].max_offset_to_osm_pedestrian_m == pytest.approx(19.0)

    def test_the_nearest_street_is_named(self, records: list[KitchenerRecord]) -> None:
        sidewalk = _describe(records)[1001]

        assert sidewalk.nearest_road_highway == "residential"
        assert sidewalk.nearest_road_m == pytest.approx(10.0)

    def test_records_outside_the_study_area_are_not_measured(
        self, records: list[KitchenerRecord]
    ) -> None:
        region = fixture_region()
        west, south, east, north = region.bounds
        # A box covering only the southern part of the fixture (below y ≈ +150 m).
        narrow = replace(region, bounds=(west, south, east, south + (north - south) * 0.5))

        described = _describe(records, narrow)

        assert described[1001].intersects_study_area
        assert not described[1005].intersects_study_area
        assert described[1005].nearest_edge_m is None
        assert described[1005].max_offset_to_osm_pedestrian_m is None

    def test_bands_are_labelled_in_order(self) -> None:
        assert band(0.3) == "0-1m"
        assert band(1.0) == "1-2m"
        assert band(199.9) == "50-200m"
        assert band(None) == ">200m_or_none"
        assert band_order()[0] == "0-1m"
        assert band_order()[-1] == ">200m_or_none"


class TestGraphAlongInventory:
    def test_it_counts_edges_near_the_inventory_and_what_osm_says_on_them(
        self, records: list[KitchenerRecord]
    ) -> None:
        pedestrian = [
            r.physical_class == "physical_active"
            and r.network_role in ("pedestrian_way", "pedestrian_crossing")
            for r in records
        ]

        along = graph_along_inventory([r.native for r in records], pedestrian, fixture_edges())

        assert along["edges_along_inventory"] == 4
        assert along["osm_baseline_on_those_edges"] == {
            "crossing_edges": 1,
            "crossing_edges_with_known_kerb": 1,
            "separate_pedestrian_edges": 3,
            "separate_pedestrian_edges_with_known_surface": 2,
            "separate_pedestrian_edges_with_width": 1,
            "steps_edges": 0,
        }

    def test_no_overlap_is_reported_in_the_same_shape(self, records: list[KitchenerRecord]) -> None:
        # Regression: with nothing selected the function returned a shorter
        # dictionary, and the adoption matrix failed on the missing baseline —
        # found by the command-line run against a region the fixture misses.
        along = graph_along_inventory(
            [r.native for r in records], [False] * len(records), fixture_edges()
        )

        assert along["edges_along_inventory"] == 0
        assert along["by_highway"] == {}
        assert set(along["osm_baseline_on_those_edges"].values()) == {0}


class TestStudyArea:
    def test_it_is_the_pilot_definition_and_says_how_it_relates_to_the_graph(self) -> None:
        region = fixture_region()

        described = study_area(region, fixture_edges(region))

        assert described["bounds"] == list(region.bounds)
        assert described["database_boundary_matches_definition"] is True
        assert described["edges_extend_beyond_study_area"] is False
        assert described["dataset_bounds_max_offset_deg"] == 0.0

    def test_a_stored_boundary_that_differs_is_reported(self) -> None:
        region = fixture_region()
        edges = fixture_edges(region)
        edges.region_boundary_wkt = "MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)))"

        assert study_area(region, edges)["database_boundary_matches_definition"] is False
