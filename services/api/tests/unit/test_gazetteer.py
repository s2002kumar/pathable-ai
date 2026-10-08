"""Reading a place index out of an OpenStreetMap extract.

The fixture is written by the test with osmium, as the network-import tests do,
so nothing is downloaded. Every element is there to prove one rule: what becomes
a searchable place, address or street, where its point lands, and what is left
out. Names are invented; coordinates sit inside the same small test box the
network-import tests use.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import osmium
import pytest
from shapely.geometry import Point, Polygon

from pathable_api.geo.enums import PlaceKind
from pathable_api.geo.gazetteer import (
    PlaceEntry,
    deduplicate,
    extract_timestamp,
    import_gazetteer,
    place_category,
    read_places,
    way_point,
)

BOUNDS = (-80.5450, 43.4650, -80.5300, 43.4750)

Tags = dict[str, str]

#: Building outlines and the park, by corner, so tests can check containment.
DAVIS = [(-80.5350, 43.4690), (-80.5340, 43.4690), (-80.5340, 43.4700), (-80.5350, 43.4700)]
ENGINEERING = [(-80.5440, 43.4730), (-80.5430, 43.4730), (-80.5430, 43.4740), (-80.5440, 43.4740)]
HOUSE = [(-80.5373, 43.4682), (-80.5371, 43.4682), (-80.5371, 43.4684), (-80.5373, 43.4684)]
PARK = [(-80.5420, 43.4655), (-80.5380, 43.4655), (-80.5380, 43.4675), (-80.5420, 43.4675)]
CAMPUS = [(-80.5449, 43.4655), (-80.5430, 43.4655), (-80.5430, 43.4670), (-80.5449, 43.4670)]
#: A second site of the same campus, in another city far outside the region.
FAR_SITE = [(-79.5000, 43.0000), (-79.4900, 43.0000), (-79.4900, 43.0100), (-79.5000, 43.0100)]

NODES: dict[int, tuple[float, float, Tags]] = {
    1: (-80.5420, 43.4698, {"amenity": "library", "name": "Porter Library"}),
    2: (
        -80.5400,
        43.4720,
        {
            "amenity": "cafe",
            "name": "Campus Coffee",
            "addr:housenumber": "200",
            "addr:street": "University Avenue West",
            "addr:city": "Waterloo",
        },
    ),
    3: (-80.5380, 43.4710, {"highway": "bus_stop", "name": "University / Seagram"}),
    # A name with nothing that makes it a place somebody would look for.
    4: (-80.5390, 43.4705, {"natural": "tree", "name": "Old Oak"}),
    # Where a vehicle halts; the platform is what a person searches for.
    5: (-80.5381, 43.4711, {"public_transport": "stop_position", "name": "Seagram Stop"}),
    # A real place, outside the region.
    6: (-80.6000, 43.4000, {"amenity": "library", "name": "Far Library"}),
    # The same place as the building way around it, mapped twice.
    7: (-80.5345, 43.4695, {"office": "university", "name": "Davis Centre"}),
    # A node far outside even the reading margin.
    8: (-79.0000, 43.0000, {}),
    **{10 + index: (lon, lat, {}) for index, (lon, lat) in enumerate(DAVIS)},
    **{20 + index: (lon, lat, {}) for index, (lon, lat) in enumerate(ENGINEERING)},
    **{30 + index: (lon, lat, {}) for index, (lon, lat) in enumerate(HOUSE)},
    **{50 + index: (lon, lat, {}) for index, (lon, lat) in enumerate(PARK)},
    **{90 + index: (lon, lat, {}) for index, (lon, lat) in enumerate(CAMPUS)},
    **{94 + index: (lon, lat, {}) for index, (lon, lat) in enumerate(FAR_SITE)},
    # Seagram Drive, first stretch: two ways sharing node 62.
    60: (-80.5380, 43.4680, {}),
    61: (-80.5370, 43.4680, {}),
    62: (-80.5360, 43.4680, {}),
    63: (-80.5350, 43.4680, {}),
    # Seagram Drive, a second stretch nowhere near the first.
    64: (-80.5320, 43.4740, {}),
    65: (-80.5310, 43.4740, {}),
    # A trail, a motorway and some named steps.
    70: (-80.5440, 43.4660, {}),
    71: (-80.5440, 43.4700, {}),
    72: (-80.5300, 43.4660, {}),
    73: (-80.5300, 43.4700, {}),
    74: (-80.5410, 43.4710, {}),
    75: (-80.5410, 43.4712, {}),
    # Erb Street, and one block of its sidewalk mapped as a separate line about
    # 20 m north — its midpoint in a different cell from the road's.
    80: (-80.5440, 43.4720, {}),
    81: (-80.5400, 43.4720, {}),
    82: (-80.5440, 43.47218, {}),
    83: (-80.5432, 43.47218, {}),
    # Long Road: a short way inside the region and a long one running out of it.
    84: (-80.5320, 43.4745, {}),
    85: (-80.5320, 43.4900, {}),
    86: (-80.5330, 43.4745, {}),
    # An information board named after the park, in the park's own cell.
    87: (-80.5401, 43.4664, {"tourism": "information", "name": "Waterloo Park"}),
}

WAYS: list[tuple[int, Tags, list[int]]] = [
    (100, {"building": "university", "name": "Davis Centre"}, [10, 11, 12, 13, 10]),
    (101, {"building": "university", "name": "Engineering 7"}, [20, 21, 22, 23, 20]),
    (
        102,
        {
            "building": "house",
            "addr:housenumber": "12",
            "addr:street": "Seagram Drive",
            "addr:city": "Waterloo",
        },
        [30, 31, 32, 33, 30],
    ),
    # An outline with a corner beyond the reading margin cannot be placed honestly.
    (103, {"building": "yes", "name": "Edge Hall"}, [10, 11, 8, 10]),
    (200, {"highway": "residential", "name": "Seagram Drive"}, [60, 61, 62]),
    (201, {"highway": "residential", "name": "Seagram Drive"}, [62, 63]),
    (202, {"highway": "residential", "name": "Seagram Drive"}, [64, 65]),
    (203, {"highway": "footway", "name": "Laurel Trail"}, [70, 71]),
    (204, {"highway": "motorway", "name": "Conestoga Parkway"}, [72, 73]),
    (205, {"highway": "steps", "name": "Library Steps"}, [74, 75]),
    (210, {"highway": "secondary", "name": "Erb Street"}, [80, 81]),
    (211, {"highway": "footway", "footway": "sidewalk", "name": "Erb Street"}, [82, 83]),
    (220, {"highway": "secondary", "name": "Long Road"}, [84, 85]),
    (221, {"highway": "secondary", "name": "Long Road"}, [86, 84]),
    # The park's outline, in two untagged pieces.
    (300, {}, [50, 51, 52]),
    (301, {}, [52, 53, 50]),
    # The campus's two sites, untagged.
    (303, {}, [90, 91, 92, 93, 90]),
    (304, {}, [94, 95, 96, 97, 94]),
    # Untagged and nobody's member: pure geometry.
    (302, {}, [60, 70]),
]

RELATIONS: list[tuple[int, Tags, list[tuple[str, int, str]]]] = [
    (
        400,
        {"type": "multipolygon", "leisure": "park", "name": "Waterloo Park"},
        [("w", 300, "outer"), ("w", 301, "outer")],
    ),
    (
        401,
        {"type": "multipolygon", "amenity": "university", "name": "Split Campus"},
        [("w", 303, "outer"), ("w", 304, "outer")],
    ),
]

EXTRACT_DATE = "2026-08-16T20:21:42Z"


def write_extract(path: Path, *, timestamp: str | None = EXTRACT_DATE) -> Path:
    header = osmium.io.Header()
    if timestamp is not None:
        header.set("osmosis_replication_timestamp", timestamp)
    writer = osmium.SimpleWriter(str(path), header=header)
    try:
        for node_id, (lon, lat, tags) in NODES.items():
            writer.add_node(
                osmium.osm.mutable.Node(id=node_id, location=(lon, lat), tags=tags, version=3)
            )
        for way_id, tags, refs in WAYS:
            writer.add_way(osmium.osm.mutable.Way(id=way_id, nodes=refs, tags=tags, version=2))
        for relation_id, tags, members in RELATIONS:
            writer.add_relation(
                osmium.osm.mutable.Relation(id=relation_id, members=members, tags=tags, version=5)
            )
    finally:
        writer.close()
    return path


@pytest.fixture(scope="module")
def extract(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_extract(tmp_path_factory.mktemp("gazetteer") / "fixture.osm.pbf")


@pytest.fixture(scope="module")
def entries(extract: Path) -> list[PlaceEntry]:
    return read_places(extract, BOUNDS)


def labelled(entries: list[PlaceEntry], label: str) -> list[PlaceEntry]:
    return [entry for entry in entries if entry.label == label]


def only(entries: list[PlaceEntry], label: str) -> PlaceEntry:
    found = labelled(entries, label)
    assert len(found) == 1, f"{label!r}: {found}"
    return found[0]


class TestPlaces:
    def test_named_features_with_a_category_become_places(self, entries: list[PlaceEntry]) -> None:
        library = only(entries, "Porter Library")

        assert library.kind is PlaceKind.PLACE
        assert library.category == "library"
        assert (library.osm_type, library.osm_id, library.osm_version) == ("node", 1, 3)
        assert only(entries, "University / Seagram").category == "transit stop"

    def test_a_name_alone_does_not_make_a_place(self, entries: list[PlaceEntry]) -> None:
        assert labelled(entries, "Old Oak") == []

    def test_a_stop_position_is_left_for_its_platform(self, entries: list[PlaceEntry]) -> None:
        assert labelled(entries, "Seagram Stop") == []

    def test_places_outside_the_region_are_left_out(self, entries: list[PlaceEntry]) -> None:
        assert labelled(entries, "Far Library") == []

    def test_a_place_mapped_as_a_node_and_its_building_is_one_result(
        self, entries: list[PlaceEntry]
    ) -> None:
        davis = only(entries, "Davis Centre")

        # The node is kept: it is read first and is the more specific feature.
        assert davis.osm_type == "node"
        assert davis.category == "university"

    def test_a_building_is_placed_inside_its_outline(self, entries: list[PlaceEntry]) -> None:
        building = only(entries, "Engineering 7")

        assert building.category == "university building"
        assert Polygon(ENGINEERING).contains(Point(building.longitude, building.latitude))

    def test_a_multipolygon_is_one_place_inside_its_outline(
        self, entries: list[PlaceEntry]
    ) -> None:
        park = only(entries, "Waterloo Park")

        assert (park.osm_type, park.osm_id, park.osm_version) == ("relation", 400, 5)
        assert park.category == "park"
        assert Polygon(PARK).contains(Point(park.longitude, park.latitude))

    def test_a_campus_with_a_site_far_away_is_placed_on_its_site_here(
        self, entries: list[PlaceEntry]
    ) -> None:
        # Regression: the University of Waterloo's campus relation also holds
        # its Cambridge and Stratford sites, and requiring every ring dropped it.
        campus = only(entries, "Split Campus")

        assert (campus.osm_type, campus.osm_id) == ("relation", 401)
        assert Polygon(CAMPUS).contains(Point(campus.longitude, campus.latitude))

    def test_an_outline_with_a_missing_corner_is_not_guessed(
        self, entries: list[PlaceEntry]
    ) -> None:
        assert labelled(entries, "Edge Hall") == []


class TestAddresses:
    def test_an_address_is_its_own_entry(self, entries: list[PlaceEntry]) -> None:
        house = only(entries, "12 Seagram Drive, Waterloo")

        assert house.kind is PlaceKind.ADDRESS
        assert house.category == "address"
        assert house.search_text == "12 seagram drive waterloo"
        assert Polygon(HOUSE).contains(Point(house.longitude, house.latitude))

    def test_a_named_place_shows_its_address_and_is_found_by_it(
        self, entries: list[PlaceEntry]
    ) -> None:
        cafe = only(entries, "Campus Coffee, 200 University Avenue West")

        assert cafe.kind is PlaceKind.PLACE
        assert "200 university avenue west" in cafe.search_text
        # Regression: every University of Waterloo building shares one address, so
        # a separate address entry per building put five identical lines in a list.
        assert labelled(entries, "200 University Avenue West, Waterloo") == []


class TestStreets:
    def test_unconnected_stretches_of_one_name_stay_separate(
        self, entries: list[PlaceEntry]
    ) -> None:
        streets = [
            entry
            for entry in entries
            if entry.kind is PlaceKind.STREET and entry.label.startswith("Seagram Drive")
        ]

        assert len(streets) == 2

    def test_a_stretch_is_named_with_the_city_its_addresses_give(
        self, entries: list[PlaceEntry]
    ) -> None:
        # Only the first stretch has an address within reach; the second is not
        # given a city it was never shown to be in.
        near = only(entries, "Seagram Drive, Waterloo")
        far = only(entries, "Seagram Drive")

        assert near.longitude < far.longitude
        assert near.search_text == "seagram drive waterloo"

    def test_a_street_point_lies_on_its_longest_way(self, entries: list[PlaceEntry]) -> None:
        near = only(entries, "Seagram Drive, Waterloo")

        assert near.osm_id == 200
        assert near.latitude == pytest.approx(43.4680)

    def test_a_named_footway_is_a_path(self, entries: list[PlaceEntry]) -> None:
        assert only(entries, "Laurel Trail").category == "path"

    def test_a_sidewalk_named_after_its_road_is_the_same_street(
        self, entries: list[PlaceEntry]
    ) -> None:
        # Regression: sidewalks and cycle tracks mapped beside a road share no
        # node with it, and grouping by shared nodes alone split Erb Street West
        # into five results. The point goes on the road, not the sidewalk.
        erb = only(entries, "Erb Street")

        assert (erb.osm_id, erb.category) == (210, "street")

    def test_a_street_leaving_the_region_is_placed_on_its_part_inside(
        self, entries: list[PlaceEntry]
    ) -> None:
        # Regression: King Street North vanished from the index because its
        # longest way runs out of town and that way's midpoint was outside.
        long_road = only(entries, "Long Road")

        assert long_road.osm_id == 221
        assert long_road.latitude <= BOUNDS[3]

    def test_nobody_is_routed_to_a_motorway_or_a_flight_of_steps(
        self, entries: list[PlaceEntry]
    ) -> None:
        assert labelled(entries, "Conestoga Parkway") == []
        assert labelled(entries, "Library Steps") == []


class TestProvenance:
    def test_it_records_the_extract_and_the_date_its_header_gives(self, extract: Path) -> None:
        result = import_gazetteer(extract, BOUNDS, region_slug="waterloo", provider="geofabrik")

        assert len(result.file_sha256) == 64
        assert result.file_name == "fixture.osm.pbf"
        assert result.source_timestamp == dt.datetime(2026, 8, 16, 20, 21, 42, tzinfo=dt.UTC)
        assert result.configuration["source_timestamp_from"] == "pbf-header"
        assert result.configuration["provider"] == "geofabrik"
        assert result.configuration["attribution"] == "© OpenStreetMap contributors, ODbL 1.0"
        assert result.count(PlaceKind.STREET) == 5

    def test_a_date_given_explicitly_wins(self, extract: Path) -> None:
        given = dt.datetime(2026, 8, 17, tzinfo=dt.UTC)
        result = import_gazetteer(extract, BOUNDS, region_slug="waterloo", source_timestamp=given)

        assert result.source_timestamp == given
        assert result.configuration["source_timestamp_from"] == "argument"

    def test_an_extract_that_does_not_say_has_no_date(self, tmp_path: Path) -> None:
        # Never the download time or the read time: unknown is recorded as unknown.
        undated = write_extract(tmp_path / "undated.osm.pbf", timestamp=None)

        assert extract_timestamp(undated) is None
        result = import_gazetteer(undated, BOUNDS, region_slug="waterloo")
        assert result.source_timestamp is None
        assert result.configuration["source_timestamp_from"] is None


class TestCategories:
    @pytest.mark.parametrize(
        ("tags", "expected"),
        [
            ({"building": "yes"}, "building"),
            ({"building": "university"}, "university building"),
            ({"public_transport": "platform"}, "transit platform"),
            ({"railway": "tram_stop"}, "tram stop"),
            ({"railway": "rail"}, None),
            ({"shop": "yes"}, "shop"),
            ({"amenity": "fast_food", "building": "yes"}, "fast food"),
            ({"building": "no"}, None),
            ({}, None),
        ],
    )
    def test_a_feature_is_named_by_its_most_telling_tag(
        self, tags: Tags, expected: str | None
    ) -> None:
        assert place_category(tags) == expected


class TestGeometry:
    def test_a_closed_way_gives_a_point_inside_it(self) -> None:
        # An L shape, whose centroid lies outside it.
        outline = [
            (0.0, 0.0),
            (4.0, 0.0),
            (4.0, 1.0),
            (1.0, 1.0),
            (1.0, 4.0),
            (0.0, 4.0),
            (0.0, 0.0),
        ]
        point = way_point(outline)

        assert point is not None
        assert Polygon(outline).contains(Point(point))

    def test_an_open_way_gives_its_midpoint(self) -> None:
        assert way_point([(0.0, 0.0), (2.0, 0.0)]) == pytest.approx((1.0, 0.0))

    def test_a_way_with_no_length_gives_nothing(self) -> None:
        assert way_point([(1.0, 1.0), (1.0, 1.0)]) is None
        assert way_point([(1.0, 1.0)]) is None


class TestDeduplication:
    def test_the_first_of_two_nearby_identical_entries_is_kept(self) -> None:
        def entry(osm_id: int, longitude: float) -> PlaceEntry:
            return PlaceEntry(
                kind=PlaceKind.PLACE,
                label="Davis Centre",
                category="university",
                search_text="davis centre",
                longitude=longitude,
                latitude=43.4695,
                osm_type="node",
                osm_id=osm_id,
                osm_version=None,
            )

        kept = deduplicate([entry(1, -80.53451), entry(2, -80.53452), entry(3, -80.5200)])

        assert [item.osm_id for item in kept] == [1, 3]

    def test_a_place_beats_an_incidental_feature_that_shares_its_name(
        self, entries: list[PlaceEntry]
    ) -> None:
        # Regression: the University of Waterloo campus was dropped because its
        # information board, read first, shares its name and its cell.
        park = only(entries, "Waterloo Park")

        assert (park.osm_type, park.category) == ("relation", "park")
