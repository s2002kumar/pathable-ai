"""Invented OSM streets for the Kitchener matcher tests.

Coordinates are metres; an identity transform stands in for the projection, so
every distance a test draws is the distance the matcher measures.
"""

from __future__ import annotations

from typing import Any

from pathable_api.geo.kitchener.correspondence import OsmIndex
from pathable_api.geo.kitchener.osm_extract import OsmNode, OsmWay, StudyExtract


class Identity:
    def transform(self, xx: Any, yy: Any) -> Any:
        return xx, yy


SIDEWALK = {"highway": "footway", "footway": "sidewalk"}
CROSSING = {"highway": "footway", "footway": "crossing"}
CYCLEWAY = {"highway": "cycleway"}
ROAD = {"highway": "residential", "name": "Fixture Street"}


class Street:
    """An invented OSM street: nodes and ways built as the test places them."""

    def __init__(self) -> None:
        self.nodes: dict[int, OsmNode] = {}
        self.ways: dict[int, OsmWay] = {}
        self._next = 1

    def node(self, x: float, y: float, tags: dict[str, str] | None = None) -> int:
        node_id = self._next
        self._next += 1
        self.nodes[node_id] = OsmNode(node_id, x, y, 1, "2024-01-01T00:00:00Z", dict(tags or {}))
        return node_id

    def way(self, way_id: int, refs: list[int], tags: dict[str, str]) -> int:
        self.ways[way_id] = OsmWay(way_id, 1, "2024-01-01T00:00:00Z", dict(tags), tuple(refs))
        return way_id

    def line(self, way_id: int, points: list[tuple[float, float]], tags: dict[str, str]) -> int:
        return self.way(way_id, [self.node(x, y) for x, y in points], tags)

    def index(self) -> OsmIndex:
        return OsmIndex.build(StudyExtract(nodes=self.nodes, ways=self.ways), Identity())
