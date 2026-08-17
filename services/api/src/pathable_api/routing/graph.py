"""The routable graph held in memory.

Routing reads the whole active dataset once and keeps it as a NetworkX graph.
That is the right trade at pilot scale — the Waterloo walk network is tens of
thousands of edges, which is a few tens of megabytes — and it avoids a database
round trip per expanded node, which is what makes naive SQL-backed routing slow.

The cache is keyed by **dataset version id**, not by region. A dataset is
immutable once activated, so a cached graph can never go stale: activating a new
dataset produces a new id and therefore a new cache entry. That is the whole
reason activation swaps versions instead of mutating rows.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from networkx import MultiDiGraph
from shapely import wkt as shapely_wkt
from shapely.geometry import LineString, Point
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pathable_api.core.logging import get_logger
from pathable_api.geo.datasets import get_active_dataset
from pathable_api.geo.directionality import Conveying
from pathable_api.geo.enums import (
    AccessValue,
    InclineDirection,
    KerbType,
    SmoothnessClass,
    SurfaceClass,
    TriState,
)
from pathable_api.geo.features import EdgeFeatures
from pathable_api.geo.models import DatasetVersion, GraphEdge, GraphNode, PilotRegion
from pathable_api.geo.network import NetworkPayload
from pathable_api.routing.snapping import EdgeIndex, EdgeSnap

logger = get_logger(__name__)

#: How many dataset graphs to keep resident. Two is enough to serve requests
#: in flight against the previous dataset while a new one becomes active,
#: without holding every historical version in memory.
_CACHE_CAPACITY = 2


@dataclass(frozen=True, slots=True)
class RoutableEdge:
    """One physical segment, described along its own ``source_u -> source_v``."""

    edge_id: uuid.UUID
    source_u: str
    source_v: str
    edge_key: int
    length_m: float
    geometry: LineString
    features: EdgeFeatures
    name: str | None
    foot_forward: bool = True
    foot_backward: bool = True

    @property
    def identity(self) -> str:
        return f"{self.source_u}->{self.source_v}#{self.edge_key}"


@dataclass(frozen=True, slots=True)
class DirectedEdge:
    """One physical segment as travelled one particular way.

    The oriented features are computed once at graph-build time rather than per
    evaluation. Dijkstra touches an edge many times, and flipping an incline
    sign in the inner loop would allocate on every touch — but getting the sign
    wrong would send somebody up a ramp the router believed went down, so it
    cannot simply be skipped either.
    """

    edge: RoutableEdge
    features: EdgeFeatures
    reversed: bool

    @property
    def length_m(self) -> float:
        return self.edge.length_m

    @property
    def identity(self) -> str:
        return self.edge.identity

    @property
    def name(self) -> str | None:
        return self.edge.name

    def coordinates(self) -> tuple[tuple[float, float], ...]:
        """Geometry oriented along travel."""
        positions = tuple((float(x), float(y)) for x, y, *_ in self.edge.geometry.coords)
        return tuple(reversed(positions)) if self.reversed else positions


@dataclass(frozen=True, slots=True)
class SnappedPoint:
    """Where a requested coordinate actually entered the network."""

    node_id: str
    longitude: float
    latitude: float
    distance_m: float

    @property
    def point(self) -> Point:
        return Point(self.longitude, self.latitude)


@dataclass(slots=True)
class RoutableGraph:
    """An immutable dataset, ready to route on."""

    dataset_id: uuid.UUID
    region_slug: str
    checksum: str
    graph: MultiDiGraph[str]
    node_positions: dict[str, tuple[float, float]]
    #: Segments in the dataset. Distinct from the graph's edge count, which holds
    #: two directed entries for every two-way segment.
    segment_count: int = 0
    load_seconds: float = 0.0
    #: Built on first use and reused for the life of the dataset, which the
    #: version-keyed cache already amortises across every request.
    _edge_index: EdgeIndex | None = None
    _segments: list[RoutableEdge] = field(default_factory=list)

    @property
    def node_count(self) -> int:
        return int(self.graph.number_of_nodes())

    def edge_between(self, u: str, v: str, key: int) -> DirectedEdge:
        data: dict[str, Any] = self.graph.edges[u, v, key]
        edge: DirectedEdge = data["edge"]
        return edge

    @property
    def edge_index(self) -> EdgeIndex:
        """Spatial index over segment geometry, built lazily."""
        if self._edge_index is None:
            self._edge_index = EdgeIndex(self._segments)
        return self._edge_index

    def snap_to_edge(self, longitude: float, latitude: float) -> EdgeSnap | None:
        """Nearest point along any segment — the honest place to start a route."""
        return self.edge_index.nearest(longitude, latitude)


class NoActiveDatasetError(RuntimeError):
    """Raised when a region has no activated network to route on."""


class GraphRepository:
    """Loads dataset graphs and caches them by dataset version."""

    def __init__(self, capacity: int = _CACHE_CAPACITY) -> None:
        self._cache: OrderedDict[uuid.UUID, RoutableGraph] = OrderedDict()
        self._capacity = capacity
        # One load at a time. Without this, two simultaneous first requests would
        # each read the whole dataset and build the graph twice.
        self._lock = asyncio.Lock()

    def cached_dataset_ids(self) -> tuple[uuid.UUID, ...]:
        return tuple(self._cache)

    def clear(self) -> None:
        self._cache.clear()

    async def active_graph(self, session: AsyncSession, region_slug: str) -> RoutableGraph:
        """Return the graph for a region's active dataset, loading it if needed."""
        region = (
            await session.execute(select(PilotRegion).where(PilotRegion.slug == region_slug))
        ).scalar_one_or_none()
        if region is None:
            msg = f"Pilot region {region_slug!r} does not exist."
            raise NoActiveDatasetError(msg)

        dataset = await get_active_dataset(session, region.id)
        if dataset is None:
            msg = (
                f"Region {region_slug!r} has no active network dataset. "
                f"Run `pathable ingest osm --region {region_slug}`."
            )
            raise NoActiveDatasetError(msg)

        cached = self._cache.get(dataset.id)
        if cached is not None:
            self._cache.move_to_end(dataset.id)
            return cached

        async with self._lock:
            # Another request may have loaded it while we waited.
            cached = self._cache.get(dataset.id)
            if cached is not None:
                self._cache.move_to_end(dataset.id)
                return cached

            graph = await load_graph(session, dataset, region_slug)
            self._cache[dataset.id] = graph
            while len(self._cache) > self._capacity:
                evicted, _ = self._cache.popitem(last=False)
                logger.info("Evicted cached graph", extra={"dataset_id": str(evicted)})
            return graph


async def load_graph(
    session: AsyncSession, dataset: DatasetVersion, region_slug: str
) -> RoutableGraph:
    """Read one dataset out of PostGIS and build its NetworkX graph."""
    started = time.perf_counter()

    graph: MultiDiGraph[str] = MultiDiGraph()
    positions: dict[str, tuple[float, float]] = {}

    node_rows = await session.execute(
        select(
            GraphNode.source_node_id,
            func.ST_X(GraphNode.geometry),
            func.ST_Y(GraphNode.geometry),
        ).where(GraphNode.dataset_version_id == dataset.id)
    )
    for source_node_id, longitude, latitude in node_rows:
        positions[source_node_id] = (float(longitude), float(latitude))
        graph.add_node(source_node_id, x=float(longitude), y=float(latitude))

    edge_rows = await session.execute(
        select(GraphEdge, func.ST_AsText(GraphEdge.geometry)).where(
            GraphEdge.dataset_version_id == dataset.id
        )
    )
    segment_count = 0
    segments: list[RoutableEdge] = []
    for row, geometry_wkt in edge_rows:
        edge = _to_routable_edge(row, geometry_wkt)
        _add_edge(graph, edge)
        segments.append(edge)
        segment_count += 1

    elapsed = time.perf_counter() - started
    logger.info(
        "Routing graph loaded",
        extra={
            "dataset_id": str(dataset.id),
            "region": region_slug,
            "node_count": graph.number_of_nodes(),
            "edge_count": segment_count,
            "load_seconds": round(elapsed, 3),
        },
    )

    return RoutableGraph(
        dataset_id=dataset.id,
        region_slug=region_slug,
        checksum=dataset.checksum,
        graph=graph,
        node_positions=positions,
        segment_count=segment_count,
        load_seconds=elapsed,
        _segments=segments,
    )


def graph_from_payload(
    payload: NetworkPayload,
    *,
    dataset_id: uuid.UUID | None = None,
    region_slug: str = "in-memory",
) -> RoutableGraph:
    """Build a routable graph directly from a network payload, without a database.

    Used by tests and by the fixture-backed development path. It builds the same
    structure :func:`load_graph` does, so a test exercising this is exercising the
    real router rather than a parallel implementation.
    """
    graph: MultiDiGraph[str] = MultiDiGraph()
    positions: dict[str, tuple[float, float]] = {}
    segments: list[RoutableEdge] = []

    for node in payload.nodes:
        positions[node.source_node_id] = (node.longitude, node.latitude)
        graph.add_node(node.source_node_id, x=node.longitude, y=node.latitude)

    for edge in payload.edges:
        routable = RoutableEdge(
            edge_id=uuid.uuid4(),
            source_u=edge.source_u,
            source_v=edge.source_v,
            edge_key=edge.edge_key,
            length_m=edge.length,
            geometry=edge.geometry,
            features=edge.features,
            name=_name_of(edge.features.raw_tags),
            foot_forward=edge.direction.forward,
            foot_backward=edge.direction.backward,
        )
        _add_edge(graph, routable)
        segments.append(routable)

    return RoutableGraph(
        dataset_id=dataset_id or uuid.uuid4(),
        region_slug=region_slug,
        checksum=payload.checksum(),
        graph=graph,
        node_positions=positions,
        segment_count=payload.edge_count,
        _segments=segments,
    )


def _add_edge(graph: MultiDiGraph[str], edge: RoutableEdge) -> None:
    """Insert a segment into the directed graph, once per walkable direction.

    Both entries share one `RoutableEdge`, so identity and geometry stay
    single-sourced; only the adjacency and the *orientation* of the features
    differ. The reverse entry carries features whose incline sign is flipped,
    which is the whole reason the graph is directed rather than undirected.
    """
    if edge.foot_forward:
        graph.add_edge(
            edge.source_u,
            edge.source_v,
            key=edge.edge_key,
            edge=DirectedEdge(edge=edge, features=edge.features, reversed=False),
        )
    if edge.foot_backward:
        graph.add_edge(
            edge.source_v,
            edge.source_u,
            key=edge.edge_key,
            edge=DirectedEdge(edge=edge, features=edge.features.reversed(), reversed=True),
        )


def _name_of(raw_tags: dict[str, Any]) -> str | None:
    name = raw_tags.get("name")
    return name if isinstance(name, str) else None


def _to_routable_edge(row: GraphEdge, geometry_wkt: str) -> RoutableEdge:
    geometry = shapely_wkt.loads(geometry_wkt)
    if not isinstance(geometry, LineString):
        msg = f"Edge {row.source_u}->{row.source_v} is not a linestring: {geometry.geom_type}"
        raise TypeError(msg)
    raw_tags: dict[str, Any] = row.raw_tags or {}
    name = raw_tags.get("name")

    return RoutableEdge(
        edge_id=row.id,
        source_u=row.source_u,
        source_v=row.source_v,
        edge_key=row.edge_key,
        length_m=float(row.length_m),
        geometry=geometry,
        features=EdgeFeatures(
            highway=row.highway,
            foot_access=AccessValue(row.foot_access),
            general_access=AccessValue(row.general_access),
            steps=TriState(row.steps),
            step_count=row.step_count,
            surface=row.surface,
            surface_class=SurfaceClass(row.surface_class),
            smoothness=row.smoothness,
            smoothness_class=SmoothnessClass(row.smoothness_class),
            incline_percent=row.incline_percent,
            incline_direction=InclineDirection(row.incline_direction),
            kerb=KerbType(row.kerb),
            sidewalk=row.sidewalk,
            is_crossing=row.is_crossing,
            crossing_type=row.crossing_type,
            lit=TriState(row.lit),
            indoor=TriState(row.indoor),
            bridge=TriState(row.bridge),
            tunnel=TriState(row.tunnel),
            width_m=row.width_m,
            tactile_paving=TriState(row.tactile_paving),
            kerb_from_node=bool(row.kerb_from_node),
            derived_grade_percent=row.derived_grade_percent,
            conveying=Conveying(row.conveying),
            conflicting_attributes=tuple(row.conflicting_attributes or ()),
            vehicle_oneway_ignored=bool(row.vehicle_oneway_ignored),
            ambiguous_direction=bool(row.ambiguous_direction),
            raw_tags=raw_tags,
        ),
        name=str(name) if isinstance(name, str) else None,
        foot_forward=bool(row.foot_forward),
        foot_backward=bool(row.foot_backward),
    )
