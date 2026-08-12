"""Geometry helpers.

All stored geometry is WGS84 (EPSG:4326), where coordinates are degrees. Degrees
are not metres and the conversion is latitude-dependent, so every metric
calculation here goes through a geodesic computation rather than pretending
otherwise.
"""

from __future__ import annotations

from typing import Any

from pyproj import Geod
from shapely.geometry import LineString, Point, mapping, shape

#: WGS84 ellipsoid. Geodesic length is accurate anywhere on Earth, which matters
#: because a degree of longitude in Waterloo is ~73% of a degree of latitude.
_GEOD = Geod(ellps="WGS84")


def geodesic_length_m(line: LineString) -> float:
    """Length of a WGS84 linestring in metres."""
    if line.is_empty or len(line.coords) < 2:
        return 0.0
    longitudes, latitudes = zip(*[(x, y) for x, y, *_ in line.coords], strict=True)
    return float(_GEOD.line_length(longitudes, latitudes))


def geodesic_distance_m(a: Point, b: Point) -> float:
    """Great-circle distance between two WGS84 points, in metres."""
    _, _, distance = _GEOD.inv(a.x, a.y, b.x, b.y)
    return float(abs(distance))


def to_ewkt(geometry: Any, srid: int = 4326) -> str:
    """Serialise a Shapely geometry for PostGIS insertion."""
    return f"SRID={srid};{geometry.wkt}"


def to_geojson(geometry: Any) -> dict[str, Any]:
    """Serialise a Shapely geometry as a GeoJSON geometry object."""
    return dict(mapping(geometry))


def from_geojson(payload: dict[str, Any]) -> Any:
    """Build a Shapely geometry from a GeoJSON geometry object."""
    return shape(payload)
