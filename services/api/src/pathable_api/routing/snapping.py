"""Joining a requested coordinate to the network.

Snapping to the nearest *junction* was the old behaviour and it was wrong in a
specific, visible way: on a 300 m block the nearest junction can be 150 m from
the door somebody actually asked about, so the route began somewhere they were
not, and the distance it reported was a distance they would never walk.

Here a request attaches to the nearest point **along a segment**, wherever that
falls. The segment is split for this request only — the cached graph is never
mutated, because it is shared between concurrent requests and keyed on a dataset
version that is supposed to be immutable.

Two things have to be got right for the split to be honest:

* **Direction survives.** Half of a one-way segment is still one-way, and the
  half that runs against the permitted direction must not appear.
* **Cost is prorated, not recomputed.** A 40 m piece of a 200 m gravel path is
  a fifth of the gravel, not a fresh segment with the same fixed penalties. Flat
  costs that describe a *place* rather than a length — a kerb at a crossing —
  belong to whichever half contains that place.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from pathable_api.geo.geometry import geodesic_distance_m, geodesic_length_m

if TYPE_CHECKING:
    from pathable_api.routing.graph import DirectedEdge, RoutableEdge

#: Identifies the temporary node a snap introduces. Prefixed so it can never
#: collide with an OSM node id, which is always numeric.
VIRTUAL_NODE_PREFIX = "pathable:snap:"


@dataclass(frozen=True, slots=True)
class EdgeSnap:
    """Where a request joined the network, and on which segment."""

    edge: RoutableEdge
    #: Position along the segment, 0.0 at ``source_u`` and 1.0 at ``source_v``.
    fraction: float
    longitude: float
    latitude: float
    #: Straight-line distance from the requested point to where it attached.
    distance_m: float
    #: Set when the snap landed exactly on an existing junction, in which case no
    #: split is needed and routing can start from that node directly.
    node_id: str | None = None

    @property
    def point(self) -> Point:
        return Point(self.longitude, self.latitude)

    @property
    def is_on_node(self) -> bool:
        return self.node_id is not None


class EdgeIndex:
    """A spatial index over segment geometry, built once per dataset.

    A linear scan over every segment was tolerable at ten thousand nodes and is
    not at city scale. Shapely's STRtree is the right tool and costs one build
    per dataset — which the dataset-version cache already amortises.
    """

    __slots__ = ("_edges", "_geometries", "_tree")

    def __init__(self, edges: list[RoutableEdge]) -> None:
        self._edges = edges
        self._geometries = [edge.geometry for edge in edges]
        self._tree = STRtree(self._geometries) if self._geometries else None

    def __len__(self) -> int:
        return len(self._edges)

    def nearest(
        self, longitude: float, latitude: float, *, candidates: int = 12
    ) -> EdgeSnap | None:
        """Find the closest point on any segment to a requested coordinate.

        The index ranks by planar degree distance, which is not metres and is
        mildly wrong at this latitude — a degree of longitude is about 73% of a
        degree of latitude here. So it is used only to shortlist, and the winner
        is chosen by a real geodesic measurement among the candidates.
        """
        if self._tree is None:
            return None

        point = Point(longitude, latitude)
        indices = self._tree.query_nearest(
            point, max_distance=None, return_distance=False, all_matches=True, exclusive=False
        )
        shortlist = [int(index) for index in indices][:candidates]
        if not shortlist:
            return None

        best: EdgeSnap | None = None
        for index in shortlist:
            edge = self._edges[index]
            snap = _project_onto(edge, point)
            if best is None or snap.distance_m < best.distance_m:
                best = snap
        return best


def _project_onto(edge: RoutableEdge, point: Point) -> EdgeSnap:
    """Closest point on one segment, measured properly."""
    geometry = edge.geometry
    # `project`/`interpolate` work in the geometry's own units (degrees), which
    # is fine for locating the position; the *distance* is then measured
    # geodesically, because degrees are not metres.
    raw_fraction = geometry.project(point, normalized=True)
    fraction = min(1.0, max(0.0, float(raw_fraction)))
    landing = geometry.interpolate(fraction, normalized=True)

    return EdgeSnap(
        edge=edge,
        fraction=fraction,
        longitude=float(landing.x),
        latitude=float(landing.y),
        distance_m=geodesic_distance_m(point, Point(landing.x, landing.y)),
    )


def split_geometry(geometry: LineString, fraction: float) -> tuple[LineString, LineString]:
    """Cut a linestring at a normalised position, keeping every vertex.

    Truncating to the two endpoints would straighten the piece and understate
    its length, which then understates every length-proportional cost on it.
    """
    landing = geometry.interpolate(fraction, normalized=True)
    cut = geometry.project(landing)

    before: list[tuple[float, float]] = []
    after: list[tuple[float, float]] = []
    for x, y, *_ in geometry.coords:
        position = geometry.project(Point(x, y))
        if position < cut:
            before.append((x, y))
        elif position > cut:
            after.append((x, y))

    landing_xy = (float(landing.x), float(landing.y))
    head = LineString([*before, landing_xy]) if before else LineString([landing_xy, landing_xy])
    tail = LineString([landing_xy, *after]) if after else LineString([landing_xy, landing_xy])

    # A snap at the very end produces a degenerate half. Fall back to the whole
    # geometry rather than a zero-length line, which nothing downstream can use.
    if len(before) == 0:
        head = LineString([geometry.coords[0], landing_xy])
    if len(after) == 0:
        tail = LineString([landing_xy, geometry.coords[-1]])
    return head, tail


def prorate(directed: DirectedEdge, geometry: LineString) -> DirectedEdge:
    """Build a partial segment whose attributes are honest for its length.

    Length-proportional facts carry over unchanged, because they are true of the
    piece as much as the whole: a 40 m stretch of a 200 m gravel path really is
    gravel, at that gradient, with that missing data. Only the length changes,
    and every length-proportional cost follows from it.

    Place-based facts — a stairway, a kerb at a crossing — are kept on **both**
    halves rather than guessed onto one. Two reasons. The source does not record
    *where* along the segment the feature sits, so choosing a half would be
    invention. And a route traverses at most one half of any split segment: the
    split only ever happens at an origin or a destination, so the route starts or
    ends there and cannot pass through. Keeping the barrier on both is therefore
    never double-charged in practice, and never silently dropped — which matters,
    because failing to warn about a kerb is the error that strands somebody.
    """
    from pathable_api.routing.graph import DirectedEdge as _DirectedEdge
    from pathable_api.routing.graph import RoutableEdge as _RoutableEdge

    length_m = geodesic_length_m(geometry)
    partial = _RoutableEdge(
        edge_id=directed.edge.edge_id,
        source_u=directed.edge.source_u,
        source_v=directed.edge.source_v,
        edge_key=directed.edge.edge_key,
        # A snap landing exactly on a vertex can produce a zero-length piece.
        # Zero would make every length-proportional cost vanish.
        length_m=max(length_m, 0.01),
        geometry=geometry,
        features=directed.edge.features,
        name=directed.edge.name,
        foot_forward=directed.edge.foot_forward,
        foot_backward=directed.edge.foot_backward,
    )
    return _DirectedEdge(edge=partial, features=directed.features, reversed=directed.reversed)


def virtual_node_id(label: str) -> str:
    """A node id for a snap point that cannot collide with an OSM id."""
    return f"{VIRTUAL_NODE_PREFIX}{label}:{uuid.uuid4().hex[:8]}"


__all__ = [
    "VIRTUAL_NODE_PREFIX",
    "EdgeIndex",
    "EdgeSnap",
    "prorate",
    "split_geometry",
    "virtual_node_id",
]
