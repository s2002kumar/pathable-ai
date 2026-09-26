"""Candidate generation and the descriptive signals behind it, on invented geometry.

Distances are in metres in a local frame; nothing here is a match decision.
"""

from __future__ import annotations

from typing import Any

import pytest
import shapely
from shapely.geometry import LineString, MultiLineString, Point

from pathable_api.geo.kitchener.correspondence import (
    KitchenerFeature,
    KitchenerIndex,
    OsmIndex,
    candidates_for,
    class_compatibility,
    kitchener_end_neighbours,
    kitchener_family,
    line_angle,
    nodes_near,
    osm_class,
    osm_end_junctions,
    pair_metrics,
    records_along,
    road_context,
    same_street,
    side_of,
    vertex_agreement,
)
from pathable_api.geo.kitchener.osm_extract import OsmNode, OsmWay, StudyExtract


class TestClasses:
    @pytest.mark.parametrize(
        ("tags", "expected"),
        [
            ({"highway": "steps"}, "steps"),
            ({"highway": "footway", "footway": "sidewalk"}, "sidewalk"),
            ({"highway": "footway", "footway": "crossing"}, "crossing"),
            ({"highway": "cycleway", "crossing": "uncontrolled"}, "crossing"),
            ({"highway": "cycleway", "foot": "designated"}, "path"),
            ({"highway": "residential"}, "road"),
            ({"highway": "service", "service": "driveway"}, "service"),
            ({"highway": "construction"}, "other"),
        ],
    )
    def test_osm_tags_become_one_class(self, tags: dict[str, str], expected: str) -> None:
        assert osm_class(tags) == expected

    def test_stairs_come_before_the_subcategory(self) -> None:
        assert kitchener_family("WALKWAY", "STAIRS", "pedestrian_way") == "stairs"
        assert kitchener_family("SIDEWALK", "SURFACE", "pedestrian_way") == "sidewalk"
        assert kitchener_family("LINK (PEDESTRIAN)", None, "virtual_link") == "virtual_link"

    def test_compatibility_is_directional_and_defaults_to_different(self) -> None:
        assert class_compatibility("sidewalk", "sidewalk") == "same"
        assert class_compatibility("sidewalk", "road") == "different_representation"
        assert class_compatibility("stairs", "road") == "different"
        assert class_compatibility("unheard_of", "path") == "different"


class TestPairMetrics:
    def test_a_parallel_line_one_metre_away(self) -> None:
        record = LineString([(0, 0), (100, 0)])
        osm = LineString([(0, 1), (100, 1)])

        metrics = pair_metrics(record, osm)

        assert metrics.min_distance_m == pytest.approx(1.0)
        assert metrics.max_offset_m == pytest.approx(1.0)
        assert metrics.median_offset_m == pytest.approx(1.0)
        assert metrics.overlap_2m == 1.0
        assert metrics.osm_share_within_5m == 1.0
        assert metrics.orientation_deg == 0.0
        assert metrics.end_distances_m == pytest.approx((1.0, 1.0))

    def test_touching_is_not_running_along(self) -> None:
        # A crossing that meets the record at one end: closest approach 0,
        # worst point the full length away.
        record = LineString([(0, 0), (0, 15)])
        osm = LineString([(0, 0), (40, 0)])

        metrics = pair_metrics(record, osm)

        assert metrics.min_distance_m == 0.0
        assert metrics.max_offset_m == pytest.approx(15.0)
        assert metrics.overlap_5m < 0.4
        assert metrics.orientation_deg == pytest.approx(90.0)

    def test_a_long_osm_way_covers_the_record_but_not_the_reverse(self) -> None:
        record = LineString([(0, 0), (20, 0)])
        osm = LineString([(-40, 0.5), (60, 0.5)])

        metrics = pair_metrics(record, osm)

        assert metrics.overlap_2m == 1.0
        # 101 OSM samples a metre apart; those from x = -4 to 24 lie within 5 m
        # of the record, which reaches past its own ends.
        assert metrics.osm_share_within_5m == pytest.approx(29 / 101)

    def test_a_multi_part_record_reports_every_end(self) -> None:
        record = MultiLineString([[(0, 0), (10, 0)], [(20, 0), (30, 0)]])

        metrics = pair_metrics(record, LineString([(0, 2), (30, 2)]))

        assert len(metrics.end_distances_m) == 4

    def test_angles_ignore_direction(self) -> None:
        assert line_angle(10.0, 190.0) == pytest.approx(0.0)
        assert line_angle(0.0, 135.0) == pytest.approx(45.0)


class TestVertices:
    def test_a_shifted_copy_shares_its_vertices(self) -> None:
        record = LineString([(0, 0), (10, 3), (20, 0), (30, 4), (40, 0)])
        osm = shapely.affinity.translate(record, 0.8, -0.6)

        found = vertex_agreement(record, osm)

        assert found.paired == 5
        assert found.median_displacement_m == pytest.approx(1.0)
        assert found.displacement_spread_m == pytest.approx(0.0, abs=1e-9)

    def test_independent_vertices_do_not_pair(self) -> None:
        record = LineString([(0, 0), (40, 0)])
        osm = LineString([(0, 1), (13, 1.2), (27, 0.8), (40, 1)])

        found = vertex_agreement(record, osm)

        assert found.osm_vertices_near == 4
        assert found.paired == 2  # only the ends sit near the record's ends


class TestRoads:
    def test_left_and_right_of_a_road(self) -> None:
        road = LineString([(0, 0), (100, 0)])

        assert side_of(road, Point(50, 5)) == 1
        assert side_of(road, Point(50, -5)) == -1
        assert side_of(road, Point(50, 0.4)) == 0

    @pytest.mark.parametrize(
        ("kitchener", "osm", "expected"),
        [
            ("KING ST W", "King Street West", True),
            ("WEBER ST E", "Weber Street West", False),
            ("HICKORY HEIGHTS CRES", "Hickory Heights Crescent", True),
            (None, "King Street West", None),
            ("KING ST W", None, None),
        ],
    )
    def test_street_names_are_compared_as_words(
        self, kitchener: str | None, osm: str | None, expected: bool | None
    ) -> None:
        assert same_street(kitchener, osm) is expected


def _index() -> tuple[OsmIndex, KitchenerIndex]:
    """A street with a sidewalk each side, a crossing, and a kerb node, in metres.

    Coordinates are fed to OsmIndex through an identity "transformer", so the
    extract's lon/lat are read as metres.
    """
    points = {
        1: (0.0, 0.0),
        2: (100.0, 0.0),
        3: (0.0, 6.0),
        4: (100.0, 6.0),
        5: (0.0, -6.0),
        6: (100.0, -6.0),
        7: (50.0, 6.0),
        8: (50.0, -6.0),
    }
    nodes = {
        node_id: OsmNode(node_id, x, y, None, None, {"kerb": "lowered"} if node_id == 7 else {})
        for node_id, (x, y) in points.items()
    }
    ways = {
        10: OsmWay(
            10,
            3,
            "2019-01-01T00:00:00Z",
            {"highway": "residential", "name": "Fixture Street"},
            (1, 2),
        ),
        11: OsmWay(
            11, 1, "2020-01-01T00:00:00Z", {"highway": "footway", "footway": "sidewalk"}, (3, 7, 4)
        ),
        12: OsmWay(
            12, 1, "2020-01-01T00:00:00Z", {"highway": "footway", "footway": "sidewalk"}, (5, 8, 6)
        ),
        13: OsmWay(
            13, 2, "2021-01-01T00:00:00Z", {"highway": "footway", "footway": "crossing"}, (7, 8)
        ),
    }
    extract = StudyExtract(nodes=nodes, ways=ways)
    osm = OsmIndex.build(extract, _Identity())
    kitchener = KitchenerIndex.build(
        [
            KitchenerFeature(
                1, "physical_active", "pedestrian_way", "SIDEWALK", LineString([(0, 7), (60, 7)])
            ),
            KitchenerFeature(
                2, "physical_active", "pedestrian_way", "SIDEWALK", LineString([(60, 7), (100, 7)])
            ),
            KitchenerFeature(
                3,
                "physical_active",
                "pedestrian_crossing",
                "CROSSWALK",
                LineString([(51, 7), (51, -7)]),
            ),
        ]
    )
    return osm, kitchener


class _Identity:
    def transform(self, xx: Any, yy: Any) -> Any:
        return xx, yy


class TestCandidates:
    def test_the_same_inputs_give_the_same_candidates_in_the_same_order(self) -> None:
        osm, kitchener = _index()
        record = kitchener.features[1].geometry
        road = road_context(record, "FIXTURE ST", osm)

        first = [c.as_dict() for c in candidates_for(record, "sidewalk", road, osm, kitchener)]
        second = [c.as_dict() for c in candidates_for(record, "sidewalk", road, osm, kitchener)]

        assert first == second
        assert first[0]["osm"] == "way/11"  # the sidewalk it runs along

    def test_the_road_and_the_far_sidewalk_are_candidates_too(self) -> None:
        osm, kitchener = _index()
        record = kitchener.features[1].geometry
        road = road_context(record, "FIXTURE ST", osm)

        found = {c.osm_id: c for c in candidates_for(record, "sidewalk", road, osm, kitchener)}

        assert road.osm_id == 10
        assert road.street_matches is True
        assert found[10].is_record_road
        assert found[10].compatibility == "different_representation"
        assert found[11].same_side_as_record is True
        assert found[12].same_side_as_record is False
        assert "same_side_of_road" in found[11].reasons

    def test_n_to_one_shows_in_the_records_along_a_way(self) -> None:
        osm, kitchener = _index()

        assert records_along(osm.lines[11], kitchener) == (1, 2)

    def test_nodes_and_junctions_for_topology(self) -> None:
        osm, kitchener = _index()
        crosswalk = kitchener.features[3].geometry

        near = nodes_near(crosswalk, osm)
        ends = osm_end_junctions(13, osm)

        assert [n["osm"] for n in near] == ["node/7"]
        assert near[0]["on_ways"] == ["way/11", "way/13"]
        assert ends[0]["ways"] == ["way/11"]
        assert kitchener_end_neighbours(1, kitchener.features[1].geometry, kitchener) == [[], [2]]
