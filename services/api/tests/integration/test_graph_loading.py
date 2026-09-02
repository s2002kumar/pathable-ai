"""Loading the routing graph out of real PostGIS.

The name is extracted in SQL from the `raw_tags` JSONB column, and the tag
blob itself is never brought into memory. Both are only provable against the
real database: a JSON number, a JSON array and a missing key behave
differently in PostgreSQL than in Python, and the tests below set each one
on a stored edge and read it back through `load_graph`.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pathable_api.geo.datasets import get_active_dataset
from pathable_api.geo.fixtures import SYNTHETIC_REGION_SLUG, load_synthetic_dataset
from pathable_api.geo.models import GraphEdge, PilotRegion
from pathable_api.routing.graph import load_graph

pytestmark = pytest.mark.integration


async def _edges(session: AsyncSession) -> list[GraphEdge]:
    rows = await session.execute(
        select(GraphEdge).order_by(GraphEdge.source_u, GraphEdge.source_v, GraphEdge.edge_key)
    )
    return list(rows.scalars())


async def _set_name(session: AsyncSession, edge: GraphEdge, value: object) -> None:
    await session.execute(
        text("UPDATE graph_edges SET raw_tags = raw_tags || CAST(:patch AS jsonb) WHERE id = :id"),
        {"patch": json.dumps({"name": value}), "id": edge.id},
    )


class TestNameFromTheDatabase:
    async def test_names_survive_and_non_text_names_do_not(self, db_session: AsyncSession) -> None:
        await load_synthetic_dataset(db_session)
        await db_session.commit()
        edges = await _edges(db_session)
        assert len(edges) >= 4

        await _set_name(db_session, edges[0], "Ring Road")
        await _set_name(db_session, edges[1], 42)
        await _set_name(db_session, edges[2], ["Ring Road", "University Avenue"])
        # edges[3] keeps whatever the fixture stored: no name at all.
        await db_session.commit()

        region = (
            await db_session.execute(
                select(PilotRegion).where(PilotRegion.slug == SYNTHETIC_REGION_SLUG)
            )
        ).scalar_one()
        dataset = await get_active_dataset(db_session, region.id)
        assert dataset is not None
        graph = await load_graph(db_session, dataset, SYNTHETIC_REGION_SLUG)
        by_identity = {segment.identity: segment for segment in graph.segments}

        def name_of(edge: GraphEdge) -> str | None:
            return by_identity[f"{edge.source_u}->{edge.source_v}#{edge.edge_key}"].name

        assert name_of(edges[0]) == "Ring Road"
        # A JSON number is not a street name, whatever PostgreSQL's text cast says.
        assert name_of(edges[1]) is None
        # OSMnx can merge parallel ways into a list of names; that is not a name either.
        assert name_of(edges[2]) is None
        assert name_of(edges[3]) is None

    async def test_the_tag_blob_stays_in_the_database(self, db_session: AsyncSession) -> None:
        # raw_tags is provenance. The runtime graph reads one key from it, in
        # SQL; carrying 765,290 tag entries for Waterloo in memory to answer
        # that question was half the process's heap.
        await load_synthetic_dataset(db_session)
        await db_session.commit()
        region = (
            await db_session.execute(
                select(PilotRegion).where(PilotRegion.slug == SYNTHETIC_REGION_SLUG)
            )
        ).scalar_one()
        dataset = await get_active_dataset(db_session, region.id)
        assert dataset is not None

        graph = await load_graph(db_session, dataset, SYNTHETIC_REGION_SLUG)

        assert graph.segment_count == 13
        assert all(segment.features.raw_tags == {} for segment in graph.segments)
