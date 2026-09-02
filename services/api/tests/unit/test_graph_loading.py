"""Building a routable segment from a database row.

`load_graph` reads narrow Core columns rather than ORM entities, and the OSM
`name` is extracted in SQL rather than from the tag blob. This pins what a row
must contain and what happens to a name that is not a string — the two places
where a faster loader could quietly change what the product says.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from shapely.geometry import LineString, Point

from pathable_api.routing.graph import _EDGE_COLUMNS, _to_routable_edge

_GEOMETRY = LineString([(-80.54, 43.47), (-80.539, 43.471)])


def _row(**overrides: Any) -> SimpleNamespace:
    """A row shaped exactly like the Core select in `load_graph`."""
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "source_u": "1",
        "source_v": "2",
        "edge_key": 0,
        "length_m": 120.5,
        "highway": "footway",
        "foot_access": "unknown",
        "general_access": "unknown",
        "steps": "unknown",
        "step_count": None,
        "surface": None,
        "surface_class": "unknown",
        "smoothness": None,
        "smoothness_class": "unknown",
        "incline_percent": None,
        "incline_direction": "unknown",
        "kerb": "unknown",
        "sidewalk": None,
        "is_crossing": False,
        "crossing_type": None,
        "lit": "unknown",
        "indoor": "unknown",
        "bridge": "unknown",
        "tunnel": "unknown",
        "width_m": None,
        "tactile_paving": "unknown",
        "kerb_from_node": False,
        "derived_grade_percent": None,
        "conveying": "none",
        "conflicting_attributes": [],
        "vehicle_oneway_ignored": False,
        "ambiguous_direction": False,
        "foot_forward": True,
        "foot_backward": True,
        "name": None,
        "geometry_wkb": _GEOMETRY.wkb,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestName:
    def test_a_string_name_is_kept(self) -> None:
        edge = _to_routable_edge(_row(name="Ring Road"))

        assert edge.name == "Ring Road"

    def test_a_missing_name_is_none(self) -> None:
        assert _to_routable_edge(_row(name=None)).name is None

    def test_a_name_that_is_not_text_is_none_rather_than_its_repr(self) -> None:
        # The SQL side already returns NULL for a non-string JSON value; this is
        # the second line of defence, so a number never becomes the street's name.
        assert _to_routable_edge(_row(name=42)).name is None


class TestRow:
    def test_the_selected_columns_cover_everything_the_builder_reads(self) -> None:
        # Every attribute `_to_routable_edge` touches must be in the select, or
        # the first real load raises AttributeError halfway through a city.
        selected = {column.key for column in _EDGE_COLUMNS} | {"name", "geometry_wkb"}
        row = _row()

        assert set(vars(row)) <= selected

    def test_raw_tags_are_not_carried_into_memory(self) -> None:
        edge = _to_routable_edge(_row(name="Ring Road"))

        assert edge.features.raw_tags == {}

    def test_geometry_comes_back_as_the_stored_linestring(self) -> None:
        edge = _to_routable_edge(_row())

        assert edge.geometry.equals(_GEOMETRY)
        assert edge.length_m == pytest.approx(120.5)

    def test_a_non_linestring_geometry_is_refused(self) -> None:
        with pytest.raises(TypeError, match="not a linestring"):
            _to_routable_edge(_row(geometry_wkb=Point(0, 0).wkb))
