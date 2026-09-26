"""The content checksum: what a stored dataset *is*, as one hash.

The ingest checksum (``checksum.py``) hashes the network as it arrived, before
enrichment. It cannot see elevation or the grade derived from it, so two datasets
that differed only in grade shared a checksum (KI-10). This one is computed from
the rows actually stored, after enrichment, and covers everything routing reads
from them — which is what makes it a statement about the dataset a route was
computed on.

**Contract, version 2.** A header line naming the version and the fields, then
one line per node in ``source_node_id`` order and one per edge in
``(source_u, source_v, edge_key)`` order, each a compact JSON array. Ordering is
by code point (``COLLATE "C"`` in PostgreSQL), so neither insertion order nor the
server's locale can move a line. Floats are written exactly (JSON's shortest
round-trip form), geometry as little-endian WKB: two datasets share a checksum
only if they store the same values, not merely values that round alike.

In: node identity, position, elevation and the elevation evidence that makes it
judgeable (source, model, resolution); edge identity, source way, geometry,
length, directionality, every normalised accessibility attribute, recorded
incline, derived grade, the conflicts recorded while normalising, and the name a
route reports.

Out, deliberately: lifecycle state and timestamps (status, validation,
activation, retirement), the time elevation was sampled, database row ids, raw
tag blobs, and OSM edit provenance. Activating a dataset must not change what it
is; neither may re-sampling the same terrain model or recording where the same
facts came from. OSM versions are stored beside the content and frozen with it,
but a rebuild that only adds them describes the same network.

Changing any of this is a new version number, never an edit to version 2.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from pathable_api.geo.models import GraphEdge, GraphNode

CONTENT_CHECKSUM_VERSION: Final = 2

NODE_FIELDS: Final = (
    "source_node_id",
    "longitude",
    "latitude",
    "elevation_m",
    "elevation_source",
    "elevation_dataset",
    "elevation_resolution_m",
)

EDGE_FIELDS: Final = (
    "source_u",
    "source_v",
    "edge_key",
    "source_way_id",
    "geometry_wkb_hex",
    "length_m",
    "foot_forward",
    "foot_backward",
    "direction_reason",
    "ambiguous_direction",
    "vehicle_oneway_ignored",
    "conveying",
    "highway",
    "foot_access",
    "general_access",
    "steps",
    "step_count",
    "surface",
    "surface_class",
    "smoothness",
    "smoothness_class",
    "incline_percent",
    "incline_direction",
    "kerb",
    "sidewalk",
    "is_crossing",
    "crossing_type",
    "tactile_paving",
    "kerb_from_node",
    "derived_grade_percent",
    "conflicting_attributes",
    "lit",
    "indoor",
    "bridge",
    "tunnel",
    "width_m",
    "name",
)

#: Where the conflict list sits in an edge line; normalised to sorted order.
_CONFLICTS: Final = EDGE_FIELDS.index("conflicting_attributes")

#: Rows fetched per round trip while streaming. The whole Waterloo edge table
#: never has to be in memory at once.
_STREAM_BATCH = 10_000


class ContentOrderError(ValueError):
    """Rows reached the hasher out of canonical order."""


def _line(values: Sequence[Any]) -> bytes:
    # allow_nan=False: a NaN has no canonical text and no business being stored.
    return (
        json.dumps(list(values), ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


class ContentHasher:
    """Hash canonical node and edge lines, refusing them out of order.

    The caller supplies rows already sorted — the database does it — and the
    hasher checks rather than trusts that: a query that lost its ORDER BY would
    otherwise produce a checksum that depends on the heap's physical order and
    change after a VACUUM.
    """

    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        self._digest.update(
            _line(
                [
                    "pathable-dataset-content",
                    CONTENT_CHECKSUM_VERSION,
                    list(NODE_FIELDS),
                    list(EDGE_FIELDS),
                ]
            )
        )
        self._last_node: str | None = None
        self._last_edge: tuple[str, str, int] | None = None
        self._edges_started = False
        self.node_count = 0
        self.edge_count = 0

    def add_node(self, values: Sequence[Any]) -> None:
        if self._edges_started:
            msg = "all nodes must be hashed before any edge"
            raise ContentOrderError(msg)
        if len(values) != len(NODE_FIELDS):
            msg = f"a node line has {len(NODE_FIELDS)} fields, not {len(values)}"
            raise ValueError(msg)
        key = str(values[0])
        if self._last_node is not None and key <= self._last_node:
            msg = f"node {key!r} arrived after {self._last_node!r}"
            raise ContentOrderError(msg)
        self._last_node = key
        self._digest.update(b"N" + _line(values))
        self.node_count += 1

    def add_edge(self, values: Sequence[Any]) -> None:
        if len(values) != len(EDGE_FIELDS):
            msg = f"an edge line has {len(EDGE_FIELDS)} fields, not {len(values)}"
            raise ValueError(msg)
        self._edges_started = True
        key = (str(values[0]), str(values[1]), int(values[2]))
        if self._last_edge is not None and key <= self._last_edge:
            msg = f"edge {key!r} arrived after {self._last_edge!r}"
            raise ContentOrderError(msg)
        self._last_edge = key
        self._digest.update(b"E" + _line(values))
        self.edge_count += 1

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def edge_name_expression() -> ColumnElement[str | None]:
    """A segment's name as routing reports it: only a JSON string is a name.

    ``->>`` would render a number, or an OSMnx-merged list of names, as text.
    Shared with the graph loader so the checksum hashes the name routes show.
    """
    return case(
        (
            func.jsonb_typeof(GraphEdge.raw_tags["name"]) == "string",
            GraphEdge.raw_tags["name"].astext,
        ),
        else_=None,
    )


@dataclass(frozen=True, slots=True)
class ContentChecksum:
    value: str
    version: int
    node_count: int
    edge_count: int
    seconds: float


async def compute_content_checksum(session: AsyncSession, dataset_id: uuid.UUID) -> ContentChecksum:
    """Hash a stored dataset's content, streaming it in canonical order."""
    started = time.perf_counter()
    hasher = ContentHasher()

    nodes = (
        select(
            GraphNode.source_node_id,
            func.ST_X(GraphNode.geometry),
            func.ST_Y(GraphNode.geometry),
            GraphNode.elevation_m,
            GraphNode.elevation_source,
            GraphNode.elevation_dataset,
            GraphNode.elevation_resolution_m,
        )
        .where(GraphNode.dataset_version_id == dataset_id)
        .order_by(GraphNode.source_node_id.collate("C"))
        .execution_options(yield_per=_STREAM_BATCH)
    )
    node_rows = await session.stream(nodes)
    async for row in node_rows:
        hasher.add_node(tuple(row))

    edges = (
        select(
            GraphEdge.source_u,
            GraphEdge.source_v,
            GraphEdge.edge_key,
            GraphEdge.source_way_id,
            func.encode(func.ST_AsBinary(GraphEdge.geometry, "NDR"), "hex"),
            GraphEdge.length_m,
            GraphEdge.foot_forward,
            GraphEdge.foot_backward,
            GraphEdge.direction_reason,
            GraphEdge.ambiguous_direction,
            GraphEdge.vehicle_oneway_ignored,
            GraphEdge.conveying,
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
            GraphEdge.tactile_paving,
            GraphEdge.kerb_from_node,
            GraphEdge.derived_grade_percent,
            GraphEdge.conflicting_attributes,
            GraphEdge.lit,
            GraphEdge.indoor,
            GraphEdge.bridge,
            GraphEdge.tunnel,
            GraphEdge.width_m,
            edge_name_expression(),
        )
        .where(GraphEdge.dataset_version_id == dataset_id)
        .order_by(
            GraphEdge.source_u.collate("C"),
            GraphEdge.source_v.collate("C"),
            GraphEdge.edge_key,
        )
        .execution_options(yield_per=_STREAM_BATCH)
    )
    edge_rows = await session.stream(edges)
    async for row in edge_rows:
        values = list(row)
        # A set of attribute names, stored as a list: order is not content.
        values[_CONFLICTS] = sorted(values[_CONFLICTS] or [])
        hasher.add_edge(values)

    return ContentChecksum(
        value=hasher.hexdigest(),
        version=CONTENT_CHECKSUM_VERSION,
        node_count=hasher.node_count,
        edge_count=hasher.edge_count,
        seconds=time.perf_counter() - started,
    )
