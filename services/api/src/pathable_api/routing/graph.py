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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from networkx import MultiDiGraph
from shapely import wkb as shapely_wkb
from shapely.geometry import LineString, Point
from sqlalchemy import case, func, select
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
    def segments(self) -> tuple[RoutableEdge, ...]:
        """Every physical segment, once, in load order. Read-only."""
        return tuple(self._segments)

    @property
    def edge_index(self) -> EdgeIndex:
        """Spatial index over segment geometry, built lazily."""
        if self._edge_index is None:
            self._edge_index = EdgeIndex(self._segments)
        return self._edge_index

    def snap_to_edge(
        self,
        longitude: float,
        latitude: float,
        *,
        accept: Callable[[RoutableEdge], bool] | None = None,
        max_distance_m: float | None = None,
    ) -> EdgeSnap | None:
        """Nearest usable point along any segment — where a route honestly starts.

        ``accept`` lets a caller refuse a segment the traveller may not use. Not
        passing it means "any segment will do", which is only correct for
        diagnostics.
        """
        return self.edge_index.nearest(
            longitude, latitude, accept=accept, max_distance_m=max_distance_m
        )


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


#: Exactly the columns a routing graph needs, named so a row reads like a record.
#:
#: Selecting the mapped entity instead measured **147.5 s against 5.0 s** for the
#: same 180,554 rows — SQLAlchemy builds a full ORM object per edge, with identity
#: map and change tracking that a read-only graph never uses. This is the single
#: largest cost in loading a region.
#:
#: `raw_tags` is deliberately absent. It is a JSONB blob of every OSM tag, 765,290
#: of them across the region, and the runtime graph reads exactly one key from it.
#: The name is extracted in SQL instead, so the blob never crosses the wire.
_EDGE_COLUMNS = (
    GraphEdge.id,
    GraphEdge.source_u,
    GraphEdge.source_v,
    GraphEdge.edge_key,
    GraphEdge.length_m,
    GraphEdge.highway,
    GraphEdge.foot_access,
    GraphEdge.general_access,
    GraphEdge.steps,
    GraphEdge.step_count,
    GraphEdge.surface,
    GraphEdge.surface_class,
    GraphEdge.smoothness,
    GraphEdge.smoothness_class,
    GraphEdge.incline_percent,
    GraphEdge.incline_direction,
    GraphEdge.kerb,
    GraphEdge.sidewalk,
    GraphEdge.is_crossing,
    GraphEdge.crossing_type,
    GraphEdge.lit,
    GraphEdge.indoor,
    GraphEdge.bridge,
    GraphEdge.tunnel,
    GraphEdge.width_m,
    GraphEdge.tactile_paving,
    GraphEdge.kerb_from_node,
    GraphEdge.derived_grade_percent,
    GraphEdge.conveying,
    GraphEdge.conflicting_attributes,
    GraphEdge.vehicle_oneway_ignored,
    GraphEdge.ambiguous_direction,
    GraphEdge.foot_forward,
    GraphEdge.foot_backward,
)


async def load_graph(
    session: AsyncSession, dataset: DatasetVersion, region_slug: str
) -> RoutableGraph:
    """Read one dataset out of PostGIS and build its NetworkX graph.

    Deliberately a Core read rather than an ORM one. Nothing here is ever
    written back, so the identity map, change tracking and lazy-loading machinery
    are pure overhead — and at city scale they were the dominant cost of starting
    the service.
    """
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
        position = (float(longitude), float(latitude))
        positions[source_node_id] = position
        graph.add_node(source_node_id, x=position[0], y=position[1])

    # WKB rather than WKT: the same geometry parses about 2.5x faster from bytes
    # than from text, and the text form is 3x the bytes on the wire.
    edge_rows = await session.execute(
        select(
            *_EDGE_COLUMNS,
            # Only a JSON string is a name. `->>` would happily render a number
            # or an OSMnx-merged list of names as text, and the Python loader
            # this replaced dropped those; the SQL side has to agree with it.
            case(
                (
                    func.jsonb_typeof(GraphEdge.raw_tags["name"]) == "string",
                    GraphEdge.raw_tags["name"].astext,
                ),
                else_=None,
            ).label("name"),
            func.ST_AsBinary(GraphEdge.geometry).label("geometry_wkb"),
        ).where(GraphEdge.dataset_version_id == dataset.id)
    )

    segment_count = 0
    segments: list[RoutableEdge] = []
    for row in edge_rows:
        edge = _to_routable_edge(row)
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


def _to_routable_edge(row: Any) -> RoutableEdge:
    """Build one routable segment from a Core result row.

    The row is a plain record of named columns, not a mapped entity — see
    `_EDGE_COLUMNS` for why.
    """
    geometry = shapely_wkb.loads(bytes(row.geometry_wkb))
    if not isinstance(geometry, LineString):
        msg = f"Edge {row.source_u}->{row.source_v} is not a linestring: {geometry.geom_type}"
        raise TypeError(msg)

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
            # `raw_tags` is intentionally left empty on a loaded graph. It exists
            # on the row in the database as provenance; nothing that routes reads
            # it, and carrying 765,290 tag entries in memory to answer one
            # question per edge is not a trade worth making.
        ),
        name=row.name if isinstance(row.name, str) else None,
        foot_forward=bool(row.foot_forward),
        foot_backward=bool(row.foot_backward),
    )
