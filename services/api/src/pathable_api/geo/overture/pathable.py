"""What PathAble itself knows about a dataset's OSM identities, read without writing.

The read runs inside a ``READ ONLY`` transaction, so the guarantee that the
linkage cannot alter the network people route on is enforced by PostgreSQL,
not by the absence of an ``UPDATE`` in this file.

What PathAble stores is an OSM way id per segment and an OSM node id per
junction — no version, no edit time. That gap is the central limitation this
analysis measures, and nothing here fills it in.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pathable_api.geo.datasets import get_active_dataset, require_region
from pathable_api.geo.models import DatasetVersion, GraphEdge, GraphNode


class PathAbleSideError(RuntimeError):
    """The dataset to compare against could not be identified."""


@dataclass(frozen=True, slots=True)
class DatasetFacts:
    dataset_id: str
    region_slug: str
    status: str
    checksum: str
    source_type: str
    source_name: str
    source_timestamp: str | None
    acquired_at: str
    node_count: int
    edge_count: int
    #: The upstream artifact the network was read from, when one was recorded.
    source_file_name: str | None
    source_file_sha256: str | None
    source_provider: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "region": self.region_slug,
            "status": self.status,
            "checksum": self.checksum,
            "source_type": self.source_type,
            "source_name": self.source_name,
            "source_timestamp": self.source_timestamp,
            "acquired_at": self.acquired_at,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "source_file_name": self.source_file_name,
            "source_file_sha256": self.source_file_sha256,
            "source_provider": self.source_provider,
        }


@dataclass(slots=True)
class PathAbleIdentities:
    facts: DatasetFacts
    #: Raw ``source_way_id`` → number of PathAble segments carrying it.
    way_edges: dict[str, int] = field(default_factory=dict)
    #: Raw ``source_way_id`` → the ``highway`` value its segments carry.
    way_highway: dict[str, str] = field(default_factory=dict)
    #: Segments with no ``source_way_id`` at all.
    edges_without_way: int = 0
    node_ids: set[str] = field(default_factory=set)


async def load_identities(
    session: AsyncSession, *, region_slug: str, dataset_id: uuid.UUID | None = None
) -> PathAbleIdentities:
    """Read a dataset's OSM identities in a read-only transaction.

    The caller owns the session; this opens and closes its own transaction and
    leaves nothing pending.
    """
    if session.in_transaction():
        msg = "load_identities needs a session with no open transaction."
        raise PathAbleSideError(msg)
    async with session.begin():
        # Must be the first statement of the transaction to take effect.
        await session.execute(text("SET TRANSACTION READ ONLY"))
        region = await require_region(session, region_slug)
        if dataset_id is not None:
            dataset = await session.get(DatasetVersion, dataset_id)
            if dataset is None or dataset.pilot_region_id != region.id:
                msg = f"Dataset {dataset_id} does not exist in region {region_slug}."
                raise PathAbleSideError(msg)
        else:
            dataset = await get_active_dataset(session, region.id)
            if dataset is None:
                msg = f"Region {region_slug} has no active dataset."
                raise PathAbleSideError(msg)

        identities = PathAbleIdentities(facts=_facts(dataset, region_slug))

        highways: dict[str, Counter[str]] = {}
        rows = await session.execute(
            select(GraphEdge.source_way_id, GraphEdge.highway, func.count())
            .where(GraphEdge.dataset_version_id == dataset.id)
            .group_by(GraphEdge.source_way_id, GraphEdge.highway)
        )
        for way_id, highway, count in rows:
            if way_id is None:
                identities.edges_without_way += int(count)
                continue
            identities.way_edges[way_id] = identities.way_edges.get(way_id, 0) + int(count)
            highways.setdefault(way_id, Counter())[highway or "unknown"] += int(count)
        identities.way_highway = {
            way_id: sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0][0]
            for way_id, counter in highways.items()
        }

        nodes = await session.execute(
            select(GraphNode.source_node_id).where(GraphNode.dataset_version_id == dataset.id)
        )
        identities.node_ids = {str(node_id) for (node_id,) in nodes}
    return identities


def _facts(dataset: DatasetVersion, region_slug: str) -> DatasetFacts:
    configuration = dataset.ingestion_configuration or {}
    return DatasetFacts(
        dataset_id=str(dataset.id),
        region_slug=region_slug,
        status=str(dataset.status),
        checksum=dataset.checksum,
        source_type=str(dataset.source_type),
        source_name=dataset.source_name,
        source_timestamp=_iso(dataset.source_timestamp),
        acquired_at=_iso(dataset.acquired_at) or "",
        node_count=dataset.node_count,
        edge_count=dataset.edge_count,
        source_file_name=_optional_str(configuration.get("file_name")),
        source_file_sha256=_optional_str(configuration.get("file_sha256")),
        source_provider=_optional_str(configuration.get("provider")),
    )


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(dt.UTC).isoformat(timespec="seconds")


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
