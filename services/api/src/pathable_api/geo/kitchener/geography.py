"""Where Kitchener's inventory and PathAble's pilot overlap — described, not matched.

The study geography is PathAble's own pilot region, read exactly: the
definition in :mod:`pathable_api.geo.regions`, the boundary stored for that
region, and the active dataset's recorded bounds and actual edge extent. If
they disagree, the report says so; nothing is widened or narrowed here.

PathAble is read with plain SQL inside a ``READ ONLY`` transaction, and only
columns that exist from migration 0005 onward, so the audit can read a
database that has not been migrated to the current head without touching it.

Every spatial relationship here is **descriptive**. "Within 5 m of a PathAble
edge" says where two datasets are near each other; it does not say they
describe the same thing. No record is matched, and no threshold here is a
matching threshold.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pyproj
import shapely
from shapely.geometry.base import BaseGeometry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pathable_api.geo.kitchener.source import NATIVE_WKID
from pathable_api.geo.regions import RegionDefinition

#: OSM ways PathAble carries as separately mapped pedestrian ways.
SEPARATE_PEDESTRIAN_HIGHWAYS = frozenset({"footway", "path", "pedestrian", "steps"})
#: OSM ways that are streets, for "which kind of street is this sidewalk beside".
ROAD_HIGHWAYS = frozenset(
    {
        "residential",
        "living_street",
        "unclassified",
        "tertiary",
        "tertiary_link",
        "secondary",
        "secondary_link",
        "primary",
        "primary_link",
        "trunk",
        "trunk_link",
    }
)

#: Distance bands for describing proximity, in metres. Descriptive only.
PROXIMITY_BANDS_M: tuple[float, ...] = (1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 50.0)
#: Beyond this, a record is "not near the graph" and no distance is kept.
PROXIMITY_LIMIT_M = 200.0
#: How close a PathAble edge must be to count as lying along the inventory.
CORRIDOR_M = 20.0
#: Spacing of the points at which a line's offset from OSM is measured.
OFFSET_SAMPLE_SPACING_M = 1.0


class PathAbleReadError(RuntimeError):
    """PathAble's side of the comparison could not be identified."""


@dataclass(frozen=True, slots=True)
class DatasetFacts:
    dataset_id: str
    status: str
    checksum: str
    source_name: str
    source_timestamp: str | None
    edge_count: int
    bounds_wkt: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "status": self.status,
            "checksum": self.checksum,
            "source_name": self.source_name,
            "source_timestamp": self.source_timestamp,
            "edge_count": self.edge_count,
            "bounds_wkt": self.bounds_wkt,
        }


@dataclass(slots=True)
class PathAbleEdges:
    region_boundary_wkt: str
    facts: DatasetFacts
    #: Edge geometries in the Kitchener source's native CRS, metres.
    geometries: np.ndarray[Any, Any]
    highway: list[str | None]
    is_crossing: list[bool]
    kerb: list[str | None]
    surface_class: list[str | None]
    width_m: list[float | None]
    edge_extent: tuple[float, float, float, float] | None
    transformation: dict[str, Any] = field(default_factory=dict)


_REGION = text("SELECT id, ST_AsText(boundary) FROM pilot_regions WHERE slug = :slug")
_ACTIVE = text(
    "SELECT id FROM dataset_versions WHERE pilot_region_id = :region AND status = 'active'"
)
_DATASET = text(
    "SELECT id::text, status, checksum, source_name, source_timestamp, edge_count, "
    "ST_AsText(bounds) FROM dataset_versions WHERE id = :dataset AND pilot_region_id = :region"
)
_EDGES = text(
    "SELECT ST_AsBinary(geometry), highway, is_crossing, kerb, surface_class, width_m "
    "FROM graph_edges WHERE dataset_version_id = :dataset ORDER BY id"
)
_EXTENT = text(
    "SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM "
    "(SELECT ST_Extent(geometry) AS e FROM graph_edges WHERE dataset_version_id = :dataset) s"
)


async def read_pathable_edges(
    session: AsyncSession, *, region_slug: str, dataset_id: uuid.UUID | None = None
) -> PathAbleEdges:
    """Read the dataset's edges, and the facts that identify it, without writing."""
    if session.in_transaction():
        msg = "read_pathable_edges needs a session with no open transaction."
        raise PathAbleReadError(msg)
    async with session.begin():
        # Must be the first statement of the transaction to take effect.
        await session.execute(text("SET TRANSACTION READ ONLY"))
        region = (await session.execute(_REGION, {"slug": region_slug})).first()
        if region is None:
            msg = f"Region {region_slug} does not exist in this database."
            raise PathAbleReadError(msg)
        region_id, boundary_wkt = region
        if dataset_id is None:
            active = (await session.execute(_ACTIVE, {"region": region_id})).all()
            if len(active) != 1:
                msg = f"Region {region_slug} has {len(active)} active datasets, expected one."
                raise PathAbleReadError(msg)
            dataset_id = uuid.UUID(str(active[0][0]))
        row = (
            await session.execute(_DATASET, {"dataset": dataset_id, "region": region_id})
        ).first()
        if row is None:
            msg = f"Dataset {dataset_id} does not exist in region {region_slug}."
            raise PathAbleReadError(msg)
        facts = DatasetFacts(
            dataset_id=str(row[0]),
            status=str(row[1]),
            checksum=str(row[2]),
            source_name=str(row[3]),
            source_timestamp=row[4].isoformat() if row[4] is not None else None,
            edge_count=int(row[5]),
            bounds_wkt=row[6],
        )
        edges = (await session.execute(_EDGES, {"dataset": dataset_id})).all()
        extent = (await session.execute(_EXTENT, {"dataset": dataset_id})).first()

    to_native = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{NATIVE_WKID}", always_xy=True)
    geographic = shapely.from_wkb([bytes(edge[0]) for edge in edges])
    return PathAbleEdges(
        region_boundary_wkt=str(boundary_wkt),
        facts=facts,
        geometries=_project(geographic, to_native),
        highway=[edge[1] for edge in edges],
        is_crossing=[bool(edge[2]) for edge in edges],
        kerb=[edge[3] for edge in edges],
        surface_class=[edge[4] for edge in edges],
        width_m=[edge[5] for edge in edges],
        edge_extent=(
            tuple(float(v) for v in extent)  # type: ignore[arg-type]
            if extent is not None and extent[0] is not None
            else None
        ),
        transformation={
            "description": to_native.description,
            "accuracy_m": to_native.accuracy,
        },
    )


def _project(geometries: Any, transformer: pyproj.Transformer) -> np.ndarray[Any, Any]:
    def project(coordinates: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        x, y = transformer.transform(coordinates[:, 0], coordinates[:, 1])
        return np.column_stack([x, y])

    return np.asarray(shapely.transform(np.asarray(geometries, dtype=object), project))


# ---------------------------------------------------------------------------
# Study area
# ---------------------------------------------------------------------------


def study_area(definition: RegionDefinition, edges: PathAbleEdges) -> dict[str, Any]:
    """The exact polygon this study uses, and how it relates to the graph."""
    polygon = definition.boundary()
    stored = shapely.from_wkt(edges.region_boundary_wkt)
    dataset_bounds = shapely.from_wkt(edges.facts.bounds_wkt) if edges.facts.bounds_wkt else None
    return {
        "region": definition.slug,
        "source": f"pathable_api.geo.regions: {definition.slug}",
        "crs": "EPSG:4326 (longitude, latitude)",
        "shape": "axis-aligned rectangle (ADR 0006: a coverage extent, not a municipal boundary)",
        "bounds": list(definition.bounds),
        "wkt": polygon.wkt,
        "database_boundary_matches_definition": bool(stored.equals(polygon)),
        "database_boundary_wkt": edges.region_boundary_wkt,
        "dataset": edges.facts.as_dict(),
        "dataset_bounds_max_offset_deg": (
            _max_offset(dataset_bounds.bounds, definition.bounds)
            if dataset_bounds is not None
            else None
        ),
        "edge_extent": list(edges.edge_extent) if edges.edge_extent is not None else None,
        "edges_extend_beyond_study_area": (
            edges.edge_extent is not None
            and not shapely.box(*definition.bounds)
            .buffer(1e-9)
            .contains(shapely.box(*edges.edge_extent))
        ),
    }


def _max_offset(bounds: Sequence[float], other: Sequence[float]) -> float:
    return max(abs(float(a) - float(b)) for a, b in zip(bounds, other, strict=True))


# ---------------------------------------------------------------------------
# Proximity (descriptive)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecordGeography:
    intersects_study_area: bool
    within_study_area: bool
    #: Closest approach to any PathAble edge. A line that touches an edge at one
    #: corner scores 0 here, so this says "near", never "runs along".
    nearest_edge_m: float | None
    nearest_edge_highway: str | None
    nearest_separate_pedestrian_edge_m: float | None
    #: The farthest any point of the record (sampled every
    #: :data:`OFFSET_SAMPLE_SPACING_M`) lies from an OSM footway, path,
    #: pedestrian way or steps — a directed Hausdorff distance. Small means the
    #: whole line runs along OSM pedestrian geometry.
    max_offset_to_osm_pedestrian_m: float | None
    nearest_road_m: float | None
    nearest_road_highway: str | None


def describe_records(
    primary: Sequence[BaseGeometry | None],
    native: Sequence[BaseGeometry | None],
    area: BaseGeometry,
    edges: PathAbleEdges,
) -> list[RecordGeography]:
    """For each Kitchener record: in the study area, and how near the graph.

    Distances are computed only for records that intersect the study area, in
    the source's native metres, and only up to :data:`PROXIMITY_LIMIT_M`;
    ``None`` means "not computed" outside the area and "beyond the limit" inside.
    """
    present = np.array([geometry is not None for geometry in primary], dtype=bool)
    inside = np.zeros(len(primary), dtype=bool)
    within = np.zeros(len(primary), dtype=bool)
    if present.any():
        candidates = np.array([g for g in primary if g is not None], dtype=object)
        inside[present] = shapely.intersects(candidates, area)
        within[present] = shapely.within(candidates, area)

    every = np.arange(len(edges.highway))
    pedestrian = np.array(
        [i for i, h in enumerate(edges.highway) if h in SEPARATE_PEDESTRIAN_HIGHWAYS], dtype=int
    )
    roads = np.array([i for i, h in enumerate(edges.highway) if h in ROAD_HIGHWAYS], dtype=int)
    nearest_any = _nearest(native, inside, edges.geometries, every)
    nearest_pedestrian = _nearest(native, inside, edges.geometries, pedestrian)
    nearest_road = _nearest(native, inside, edges.geometries, roads)
    offsets = max_offsets(native, inside, edges.geometries, pedestrian)

    def highway(edge: int | None) -> str | None:
        return edges.highway[edge] if edge is not None else None

    return [
        RecordGeography(
            intersects_study_area=bool(inside[index]),
            within_study_area=bool(within[index]),
            nearest_edge_m=nearest_any[index][0],
            nearest_edge_highway=highway(nearest_any[index][1]),
            nearest_separate_pedestrian_edge_m=nearest_pedestrian[index][0],
            max_offset_to_osm_pedestrian_m=offsets[index],
            nearest_road_m=nearest_road[index][0],
            nearest_road_highway=highway(nearest_road[index][1]),
        )
        for index in range(len(primary))
    ]


def max_offsets(
    native: Sequence[BaseGeometry | None],
    mask: np.ndarray[Any, Any],
    geometries: np.ndarray[Any, Any],
    subset: np.ndarray[Any, Any],
    *,
    spacing_m: float = OFFSET_SAMPLE_SPACING_M,
) -> list[float | None]:
    """For each masked record, the largest distance from its line to ``subset``.

    The line is densified so no two consecutive points are more than
    ``spacing_m`` apart, and each point's nearest subset edge is found. The
    record's value is the worst point. ``None`` beyond :data:`PROXIMITY_LIMIT_M`.
    """
    result: list[float | None] = [None] * len(native)
    indices = [i for i in range(len(native)) if mask[i] and native[i] is not None]
    if not indices or len(subset) == 0:
        return result
    tree = shapely.STRtree(geometries[subset])
    dense = shapely.segmentize(np.array([native[i] for i in indices], dtype=object), spacing_m)
    coordinates, owner = shapely.get_coordinates(dense, return_index=True)
    points = np.asarray(shapely.points(coordinates), dtype=object)
    pairs, distances = tree.query_nearest(
        points, max_distance=PROXIMITY_LIMIT_M, return_distance=True, all_matches=False
    )
    nearest = np.full(len(points), np.inf)
    nearest[pairs[0]] = distances
    worst = np.zeros(len(indices))
    np.maximum.at(worst, owner, nearest)
    for position, index in enumerate(indices):
        value = float(worst[position])
        result[index] = round(value, 3) if np.isfinite(value) else None
    return result


def _nearest(
    native: Sequence[BaseGeometry | None],
    mask: np.ndarray[Any, Any],
    geometries: np.ndarray[Any, Any],
    subset: np.ndarray[Any, Any],
) -> list[tuple[float | None, int | None]]:
    """Nearest edge among ``subset`` for each masked record: (metres, edge index)."""
    result: list[tuple[float | None, int | None]] = [(None, None)] * len(native)
    indices = [i for i in range(len(native)) if mask[i] and native[i] is not None]
    if not indices or len(subset) == 0:
        return result
    tree = shapely.STRtree(geometries[subset])
    queried = np.array([native[i] for i in indices], dtype=object)
    pairs, distances = tree.query_nearest(
        queried, max_distance=PROXIMITY_LIMIT_M, return_distance=True, all_matches=False
    )
    for (source, target), distance in zip(pairs.T, distances, strict=True):
        result[indices[int(source)]] = (round(float(distance), 3), int(subset[int(target)]))
    return result


def band(distance: float | None) -> str:
    if distance is None:
        return f">{PROXIMITY_LIMIT_M:g}m_or_none"
    lower = 0.0
    for upper in PROXIMITY_BANDS_M:
        if distance < upper:
            return f"{lower:g}-{upper:g}m"
        lower = upper
    return f"{lower:g}-{PROXIMITY_LIMIT_M:g}m"


def band_order() -> list[str]:
    labels = []
    lower = 0.0
    for upper in PROXIMITY_BANDS_M:
        labels.append(f"{lower:g}-{upper:g}m")
        lower = upper
    labels.append(f"{lower:g}-{PROXIMITY_LIMIT_M:g}m")
    labels.append(f">{PROXIMITY_LIMIT_M:g}m_or_none")
    return labels


def graph_along_inventory(
    native: Sequence[BaseGeometry | None],
    inventory_mask: Sequence[bool],
    edges: PathAbleEdges,
) -> dict[str, Any]:
    """PathAble edges lying along the Kitchener inventory, and what OSM says on them.

    An edge is "along the inventory" when any selected Kitchener record lies
    within :data:`CORRIDOR_M` of it. This measures how much of PathAble's graph
    the inventory could describe at all, and the OSM baseline there — so a
    later card can tell a gap Kitchener could fill from one it cannot.
    """
    selected = [
        geometry
        for geometry, keep in zip(native, inventory_mask, strict=True)
        if keep and geometry is not None
    ]
    total = len(edges.highway)
    along = np.zeros(total, dtype=bool)
    # No overlap is a result to report in the same shape, not a special case:
    # it is exactly what a pilot that misses the source would measure.
    if selected and total:
        tree = shapely.STRtree(np.array(selected, dtype=object))
        hits = tree.query(edges.geometries, predicate="dwithin", distance=CORRIDOR_M)
        along[np.unique(hits[0])] = True

    def count(predicate: Any) -> int:
        return int(sum(1 for i in range(total) if along[i] and predicate(i)))

    highways: Counter[str] = Counter(edges.highway[i] or "null" for i in range(total) if along[i])
    return {
        "corridor_m": CORRIDOR_M,
        "edges_total": total,
        "edges_along_inventory": int(along.sum()),
        "by_highway": dict(sorted(highways.items(), key=lambda kv: (-kv[1], kv[0]))),
        "osm_baseline_on_those_edges": {
            "crossing_edges": count(lambda i: edges.is_crossing[i]),
            "crossing_edges_with_known_kerb": count(
                lambda i: edges.is_crossing[i] and (edges.kerb[i] or "unknown") != "unknown"
            ),
            "separate_pedestrian_edges": count(
                lambda i: edges.highway[i] in SEPARATE_PEDESTRIAN_HIGHWAYS
            ),
            "separate_pedestrian_edges_with_known_surface": count(
                lambda i: edges.highway[i] in SEPARATE_PEDESTRIAN_HIGHWAYS
                and (edges.surface_class[i] or "unknown") != "unknown"
            ),
            "separate_pedestrian_edges_with_width": count(
                lambda i: edges.highway[i] in SEPARATE_PEDESTRIAN_HIGHWAYS
                and edges.width_m[i] is not None
            ),
            "steps_edges": count(lambda i: edges.highway[i] == "steps"),
        },
    }


def counts(values: Mapping[str, int]) -> dict[str, int]:
    return dict(sorted(values.items(), key=lambda kv: (-kv[1], kv[0])))
