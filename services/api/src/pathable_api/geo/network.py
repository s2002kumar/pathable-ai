"""In-memory representation of a network before it is persisted.

Both the synthetic fixture and the OSM importer build one of these, so
validation, checksumming and persistence are written once and behave identically
whatever the source was.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import LineString, Point

from pathable_api.geo.checksum import dataset_checksum
from pathable_api.geo.directionality import TWO_WAY, FootDirection
from pathable_api.geo.features import EdgeFeatures
from pathable_api.geo.geometry import geodesic_length_m


@dataclass(frozen=True, slots=True)
class OsmEdit:
    """An OSM element's version and when that version was saved.

    Only a source that carries them supplies one. Absent means unknown — not
    unchanged, and not old.
    """

    version: int
    edited_at: dt.datetime | None


@dataclass(frozen=True, slots=True)
class NetworkNode:
    source_node_id: str
    geometry: Point
    raw_tags: dict[str, Any] = field(default_factory=dict)
    osm: OsmEdit | None = None

    @property
    def longitude(self) -> float:
        return float(self.geometry.x)

    @property
    def latitude(self) -> float:
        return float(self.geometry.y)


@dataclass(frozen=True, slots=True)
class NetworkEdge:
    source_u: str
    source_v: str
    edge_key: int
    geometry: LineString
    features: EdgeFeatures
    source_way_id: str | None = None
    #: Which directions a person may walk. Two-way by default; a restriction
    #: only ever comes from a foot-specific tag.
    direction: FootDirection = TWO_WAY
    length_m: float | None = None
    #: The source way's version and edit time.
    osm_way: OsmEdit | None = None
    #: The latest edit across the way and every node it references; None when
    #: any of them could not be read. A moved node changes a way's shape without
    #: changing the way's version, and this is what shows it.
    osm_way_latest_edit_at: dt.datetime | None = None

    @property
    def directed(self) -> bool:
        """True when the segment is walkable one way only."""
        return self.direction.is_one_way

    @property
    def length(self) -> float:
        """Metric length, computed geodesically when the source did not supply one."""
        if self.length_m is not None and self.length_m > 0:
            return self.length_m
        return geodesic_length_m(self.geometry)

    def checksum_attributes(self) -> list[tuple[str, Any]]:
        """Routing-relevant attributes that must change the dataset checksum."""
        features = self.features
        return [
            ("highway", features.highway),
            ("foot_access", features.foot_access.value),
            ("general_access", features.general_access.value),
            ("steps", features.steps.value),
            ("step_count", features.step_count),
            ("surface_class", features.surface_class.value),
            ("smoothness_class", features.smoothness_class.value),
            ("incline_percent", features.incline_percent),
            ("incline_direction", features.incline_direction.value),
            ("kerb", features.kerb.value),
            ("is_crossing", int(features.is_crossing)),
            ("width_m", features.width_m),
            # Directionality is part of what the network *is*: a segment that
            # became one-way is a different network, and the checksum has to
            # notice.
            ("foot_forward", int(self.direction.forward)),
            ("foot_backward", int(self.direction.backward)),
            ("conveying", features.conveying.value),
        ]


@dataclass(slots=True)
class NetworkPayload:
    """A complete network, ready to validate and persist."""

    nodes: list[NetworkNode]
    edges: list[NetworkEdge]

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def checksum(self) -> str:
        return dataset_checksum(
            ((node.source_node_id, node.longitude, node.latitude) for node in self.nodes),
            (
                (
                    edge.source_u,
                    edge.source_v,
                    edge.edge_key,
                    edge.length,
                    edge.directed,
                    edge.checksum_attributes(),
                )
                for edge in self.edges
            ),
        )

    def bounds(self) -> tuple[float, float, float, float] | None:
        """(min_lon, min_lat, max_lon, max_lat) over every geometry."""
        if not self.nodes and not self.edges:
            return None
        longitudes: list[float] = []
        latitudes: list[float] = []
        for node in self.nodes:
            longitudes.append(node.longitude)
            latitudes.append(node.latitude)
        for edge in self.edges:
            min_x, min_y, max_x, max_y = edge.geometry.bounds
            longitudes.extend([min_x, max_x])
            latitudes.extend([min_y, max_y])
        if not longitudes:
            return None
        return (min(longitudes), min(latitudes), max(longitudes), max(latitudes))
