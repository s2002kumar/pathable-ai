"""The content checksum contract, without a database.

The checksum is what an activation, a regression run and a rollback all name a
dataset by. If it can be fooled — by a column nobody added to it, by rows that
arrive in a different order, by a float that prints the same but is not — then
"the content this route was judged on" stops meaning anything. The stored-row
behaviour is covered against PostGIS in tests/integration/test_dataset_activation.py.
"""

from __future__ import annotations

from typing import Any

import pytest

from pathable_api.geo.content_checksum import (
    EDGE_FIELDS,
    NODE_FIELDS,
    ContentHasher,
    ContentOrderError,
)
from pathable_api.geo.models import GraphEdge, GraphNode

#: Columns stored on a row that deliberately do not describe the network. Adding
#: a column to the model fails the coverage tests below until it is placed in
#: the contract (a new version) or here, with a reason.
NODE_COLUMNS_OUTSIDE_CONTENT = {
    "id": "a database row id; a rebuild assigns new ones",
    "dataset_version_id": "which dataset the row belongs to, not what it says",
    "geometry": "hashed as longitude and latitude",
    "elevation_acquired_at": "when the terrain model was sampled, not what it said",
    "osm_version": "edit provenance, frozen beside the content",
    "osm_edited_at": "edit provenance, frozen beside the content",
    "raw_tags": "routing never reads a node's tags; their evidence is on the edges",
    "created_at": "row bookkeeping",
}
EDGE_COLUMNS_OUTSIDE_CONTENT = {
    "id": "a database row id",
    "dataset_version_id": "which dataset the row belongs to",
    "from_node_id": "a row id; the endpoints are hashed as source_u and source_v",
    "to_node_id": "a row id; the endpoints are hashed as source_u and source_v",
    "geometry": "hashed as geometry_wkb_hex",
    "osm_way_version": "edit provenance",
    "osm_way_edited_at": "edit provenance",
    "osm_way_latest_edit_at": "edit provenance",
    "raw_tags": "hashed only as the name a route reports",
    "created_at": "row bookkeeping",
}
#: Contract fields computed from a column rather than read straight from one.
DERIVED_EDGE_FIELDS = {"geometry_wkb_hex", "name"}
DERIVED_NODE_FIELDS = {"longitude", "latitude"}


def node(source_id: str = "1", **changes: Any) -> list[Any]:
    values: dict[str, Any] = {
        "source_node_id": source_id,
        "longitude": -80.54,
        "latitude": 43.47,
        "elevation_m": 331.25,
        "elevation_source": "nrcan-hrdem",
        "elevation_dataset": "hrdem-lidar-dtm-1m",
        "elevation_resolution_m": 1.0,
    }
    values.update(changes)
    return [values[field] for field in NODE_FIELDS]


def edge(u: str = "1", v: str = "2", key: int = 0, **changes: Any) -> list[Any]:
    values: dict[str, Any] = dict.fromkeys(EDGE_FIELDS)
    values.update(
        source_u=u,
        source_v=v,
        edge_key=key,
        source_way_id="100",
        geometry_wkb_hex="0102000000",
        length_m=12.5,
        foot_forward=True,
        foot_backward=True,
        highway="footway",
        steps="false",
        derived_grade_percent=4.2,
        conflicting_attributes=[],
    )
    values.update(changes)
    return [values[field] for field in EDGE_FIELDS]


def digest(nodes: list[list[Any]], edges: list[list[Any]]) -> str:
    hasher = ContentHasher()
    for values in nodes:
        hasher.add_node(values)
    for values in edges:
        hasher.add_edge(values)
    return hasher.hexdigest()


class TestCoverage:
    def test_every_edge_column_is_either_hashed_or_excluded_with_a_reason(self) -> None:
        # KI-10 was a checksum that could not see derived grade. A new routing
        # attribute added to the model without being hashed would reopen it.
        columns = {column.name for column in GraphEdge.__table__.columns}
        hashed = set(EDGE_FIELDS) - DERIVED_EDGE_FIELDS

        assert columns - hashed - set(EDGE_COLUMNS_OUTSIDE_CONTENT) == set()
        assert hashed - columns == set()

    def test_every_node_column_is_either_hashed_or_excluded_with_a_reason(self) -> None:
        columns = {column.name for column in GraphNode.__table__.columns}
        hashed = set(NODE_FIELDS) - DERIVED_NODE_FIELDS

        assert columns - hashed - set(NODE_COLUMNS_OUTSIDE_CONTENT) == set()
        assert hashed - columns == set()

    def test_elevation_and_derived_grade_are_content(self) -> None:
        assert {"elevation_m", "elevation_source"} <= set(NODE_FIELDS)
        assert "derived_grade_percent" in EDGE_FIELDS


class TestSensitivity:
    def test_the_same_content_hashes_the_same(self) -> None:
        assert digest([node("1"), node("2")], [edge()]) == digest([node("1"), node("2")], [edge()])

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("derived_grade_percent", 4.3),
            ("derived_grade_percent", None),
            ("surface_class", "paved"),
            ("foot_backward", False),
            ("length_m", 12.500000000000002),
        ],
    )
    def test_a_changed_edge_value_changes_the_hash(self, field: str, value: Any) -> None:
        # The float case differs in its last bit: two datasets that round alike
        # are not the same dataset.
        before = digest([node("1"), node("2")], [edge()])
        after = digest([node("1"), node("2")], [edge(**{field: value})])

        assert before != after

    def test_a_changed_elevation_changes_the_hash(self) -> None:
        before = digest([node("1"), node("2")], [edge()])
        after = digest([node("1", elevation_m=331.5), node("2")], [edge()])

        assert before != after

    def test_nan_has_no_canonical_form_and_is_refused(self) -> None:
        with pytest.raises(ValueError, match="Out of range float"):
            digest([node("1", elevation_m=float("nan"))], [])


class TestOrdering:
    def test_nodes_out_of_order_are_refused_rather_than_hashed(self) -> None:
        # A query that lost its ORDER BY would otherwise yield a checksum that
        # changes with the heap's physical order.
        hasher = ContentHasher()
        hasher.add_node(node("2"))
        with pytest.raises(ContentOrderError):
            hasher.add_node(node("10"))

    def test_a_duplicate_node_is_refused(self) -> None:
        hasher = ContentHasher()
        hasher.add_node(node("1"))
        with pytest.raises(ContentOrderError):
            hasher.add_node(node("1"))

    def test_edges_out_of_order_are_refused(self) -> None:
        hasher = ContentHasher()
        hasher.add_edge(edge("1", "2", 1))
        with pytest.raises(ContentOrderError):
            hasher.add_edge(edge("1", "2", 0))

    def test_a_node_after_an_edge_is_refused(self) -> None:
        hasher = ContentHasher()
        hasher.add_edge(edge())
        with pytest.raises(ContentOrderError):
            hasher.add_node(node("1"))

    def test_a_short_line_is_refused(self) -> None:
        with pytest.raises(ValueError, match="fields"):
            ContentHasher().add_edge(edge()[:-1])
