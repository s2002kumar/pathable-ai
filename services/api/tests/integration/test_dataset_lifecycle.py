"""Dataset lifecycle against real PostGIS.

Mocking would prove nothing here: the guarantees under test — one active dataset
per region, geometry stored with the right SRID, a failed import leaving the live
network untouched — are enforced by the database.
"""

from __future__ import annotations

import dataclasses

import pytest
from shapely.geometry import LineString, Point
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pathable_api.geo.datasets import (
    DatasetValidationError,
    activate_dataset,
    get_active_dataset,
    ingest_network,
)
from pathable_api.geo.enums import DatasetStatus, IngestionStatus, SourceType
from pathable_api.geo.features import normalise_edge
from pathable_api.geo.fixtures import build_synthetic_network, load_synthetic_dataset
from pathable_api.geo.models import DatasetVersion, GraphEdge, GraphNode, IngestionRun, PilotRegion
from pathable_api.geo.network import NetworkEdge, NetworkNode, NetworkPayload
from pathable_api.geo.regions import WATERLOO, WATERLOO_SYNTHETIC, seed_pilot_regions, seed_region

pytestmark = pytest.mark.integration


async def _count(session: AsyncSession, model: type, **filters: object) -> int:
    statement = select(func.count()).select_from(model)
    for column, value in filters.items():
        statement = statement.where(getattr(model, column) == value)
    return int((await session.execute(statement)).scalar_one())


class TestRegionSeeding:
    async def test_seeding_creates_the_pilot_region(self, db_session: AsyncSession) -> None:
        regions = await seed_pilot_regions(db_session)
        await db_session.commit()

        assert [region.slug for region in regions] == [WATERLOO.slug]
        assert await _count(db_session, PilotRegion) == 1

    async def test_seeding_twice_does_not_duplicate(self, db_session: AsyncSession) -> None:
        await seed_pilot_regions(db_session)
        await seed_pilot_regions(db_session)
        await db_session.commit()

        assert await _count(db_session, PilotRegion) == 1

    async def test_the_boundary_round_trips_through_postgis(self, db_session: AsyncSession) -> None:
        region = await seed_region(db_session, WATERLOO)
        await db_session.commit()

        srid, area = (
            await db_session.execute(
                select(
                    func.ST_SRID(PilotRegion.boundary), func.ST_Area(PilotRegion.boundary)
                ).where(PilotRegion.id == region.id)
            )
        ).one()

        assert srid == 4326
        assert area > 0

    async def test_the_synthetic_region_is_disabled_by_default(
        self, db_session: AsyncSession
    ) -> None:
        # It must never be served as a real pilot region by accident.
        region = await seed_region(db_session, WATERLOO_SYNTHETIC)
        await db_session.commit()

        assert region.enabled is False
        assert "not real" in region.display_name.lower()


class TestIngestion:
    async def test_the_fixture_loads_end_to_end(self, db_session: AsyncSession) -> None:
        result = await load_synthetic_dataset(db_session)
        await db_session.commit()

        payload = build_synthetic_network()
        assert result.status is DatasetStatus.ACTIVE
        assert result.activated is True
        assert result.checksum == payload.checksum()
        assert await _count(db_session, GraphNode) == payload.node_count
        assert await _count(db_session, GraphEdge) == payload.edge_count

    async def test_edge_topology_is_wired_to_real_node_rows(self, db_session: AsyncSession) -> None:
        await load_synthetic_dataset(db_session)
        await db_session.commit()

        # Every edge endpoint must resolve to a node row; a foreign key alone
        # would not prove the *right* node was chosen.
        rows = (
            await db_session.execute(
                select(GraphEdge.source_u, GraphEdge.source_v, GraphNode.source_node_id).join(
                    GraphNode, GraphEdge.from_node_id == GraphNode.id
                )
            )
        ).all()

        assert rows
        for source_u, _, node_source_id in rows:
            assert source_u == node_source_id

    async def test_geometry_is_stored_as_wgs84(self, db_session: AsyncSession) -> None:
        await load_synthetic_dataset(db_session)
        await db_session.commit()

        srids = set(
            (
                await db_session.execute(select(func.ST_SRID(GraphEdge.geometry)).distinct())
            ).scalars()
        )
        assert srids == {4326}

    async def test_lengths_are_metres_not_degrees(self, db_session: AsyncSession) -> None:
        await load_synthetic_dataset(db_session)
        await db_session.commit()

        lengths = list((await db_session.execute(select(GraphEdge.length_m))).scalars())
        assert all(length > 1.0 for length in lengths)
        assert max(lengths) < 1000.0

    async def test_unknown_attributes_survive_the_round_trip(
        self, db_session: AsyncSession
    ) -> None:
        # The whole point of the schema is that "nobody recorded this" is
        # preserved rather than defaulted away on the way into the database.
        await load_synthetic_dataset(db_session)
        await db_session.commit()

        row = (
            await db_session.execute(
                select(GraphEdge).where(GraphEdge.source_u == "A", GraphEdge.source_v == "U")
            )
        ).scalar_one()

        assert row.steps == "unknown"
        assert row.surface_class == "unknown"
        assert row.kerb == "unknown"
        assert row.foot_access == "unknown"

    async def test_an_ingestion_run_is_recorded(self, db_session: AsyncSession) -> None:
        result = await load_synthetic_dataset(db_session)
        await db_session.commit()

        run = (
            await db_session.execute(
                select(IngestionRun).where(IngestionRun.dataset_version_id == result.dataset_id)
            )
        ).scalar_one()

        assert run.status == IngestionStatus.SUCCEEDED
        assert run.completed_at is not None
        assert run.error_count == 0
        assert run.warning_count == len(result.report.warnings)

    async def test_validation_warnings_are_persisted_for_audit(
        self, db_session: AsyncSession
    ) -> None:
        result = await load_synthetic_dataset(db_session)
        await db_session.commit()

        dataset = await db_session.get(DatasetVersion, result.dataset_id)
        assert dataset is not None
        assert dataset.validation_summary is not None
        assert dataset.validation_summary["valid"] is True
        assert dataset.validation_summary["warning_count"] > 0


class TestActivation:
    async def test_a_second_dataset_retires_the_first(self, db_session: AsyncSession) -> None:
        first = await load_synthetic_dataset(db_session)
        await db_session.commit()

        second = await load_synthetic_dataset(db_session)
        await db_session.commit()

        previous = await db_session.get(DatasetVersion, first.dataset_id)
        current = await db_session.get(DatasetVersion, second.dataset_id)
        assert previous is not None
        assert current is not None
        assert previous.status == DatasetStatus.RETIRED
        assert previous.retired_at is not None
        assert current.status == DatasetStatus.ACTIVE

    async def test_only_one_dataset_is_ever_active_per_region(
        self, db_session: AsyncSession
    ) -> None:
        for _ in range(3):
            await load_synthetic_dataset(db_session)
            await db_session.commit()

        active = await _count(db_session, DatasetVersion, status=DatasetStatus.ACTIVE)
        assert active == 1

    async def test_a_draft_dataset_cannot_be_activated(self, db_session: AsyncSession) -> None:
        result = await load_synthetic_dataset(db_session, activate=False)
        await db_session.commit()

        dataset = await db_session.get(DatasetVersion, result.dataset_id)
        assert dataset is not None
        assert dataset.status == DatasetStatus.VALIDATED

        dataset.status = DatasetStatus.DRAFT
        with pytest.raises(Exception, match="only a validated"):
            await activate_dataset(db_session, dataset)

    async def test_ingesting_without_activating_leaves_no_active_dataset(
        self, db_session: AsyncSession
    ) -> None:
        result = await load_synthetic_dataset(db_session, activate=False)
        await db_session.commit()

        dataset = await db_session.get(DatasetVersion, result.dataset_id)
        assert dataset is not None
        assert await get_active_dataset(db_session, dataset.pilot_region_id) is None

    async def test_get_active_dataset_finds_the_live_network(
        self, db_session: AsyncSession
    ) -> None:
        result = await load_synthetic_dataset(db_session)
        await db_session.commit()

        dataset = await db_session.get(DatasetVersion, result.dataset_id)
        assert dataset is not None
        active = await get_active_dataset(db_session, dataset.pilot_region_id)
        assert active is not None
        assert active.id == result.dataset_id


class TestFailedIngestion:
    async def test_a_broken_import_cannot_replace_the_live_network(
        self, db_session: AsyncSession
    ) -> None:
        good = await load_synthetic_dataset(db_session)
        await db_session.commit()

        region = (
            await db_session.execute(
                select(PilotRegion).where(PilotRegion.slug == WATERLOO_SYNTHETIC.slug)
            )
        ).scalar_one()
        # Read the id now: the rollback below expires every ORM instance, and
        # touching an expired attribute afterwards would trigger a lazy refresh
        # in a context that cannot perform IO.
        region_id = region.id

        broken = NetworkPayload(
            nodes=[NetworkNode(source_node_id="x", geometry=Point(-80.538, 43.470))],
            edges=[
                NetworkEdge(
                    source_u="x",
                    source_v="missing",
                    edge_key=0,
                    geometry=LineString([(-80.538, 43.470), (-80.537, 43.470)]),
                    features=normalise_edge({"highway": "footway"}),
                )
            ],
        )

        with pytest.raises(DatasetValidationError):
            await ingest_network(
                db_session,
                region=region,
                payload=broken,
                source_type=SourceType.SYNTHETIC,
                source_name="broken-import",
                ingestion_configuration={},
            )
        await db_session.rollback()

        active = await get_active_dataset(db_session, region_id)
        assert active is not None
        assert active.id == good.dataset_id
        assert await _count(db_session, GraphNode, source_node_id="x") == 0

    async def test_a_failed_import_writes_no_graph_rows(self, db_session: AsyncSession) -> None:
        region = await seed_region(db_session, WATERLOO_SYNTHETIC)
        payload = build_synthetic_network()
        # Break one edge's geometry: a zero-length segment is invalid data, not
        # a routable segment of length nothing.
        payload.edges[0] = dataclasses.replace(
            payload.edges[0], geometry=LineString([(-80.538, 43.470), (-80.538, 43.470)])
        )

        with pytest.raises(DatasetValidationError):
            await ingest_network(
                db_session,
                region=region,
                payload=payload,
                source_type=SourceType.SYNTHETIC,
                source_name="zero-length-edge",
                ingestion_configuration={},
            )

        # Still inside the failed transaction: nothing was written even before
        # the caller rolled back.
        assert await _count(db_session, GraphNode) == 0
        assert await _count(db_session, GraphEdge) == 0
        await db_session.rollback()

    async def test_the_failure_is_recorded_when_the_caller_keeps_the_audit_trail(
        self, db_session: AsyncSession
    ) -> None:
        region = await seed_region(db_session, WATERLOO_SYNTHETIC)
        await db_session.commit()

        with pytest.raises(DatasetValidationError) as failure:
            await ingest_network(
                db_session,
                region=region,
                payload=NetworkPayload(nodes=[], edges=[]),
                source_type=SourceType.SYNTHETIC,
                source_name="empty-import",
                ingestion_configuration={},
            )

        assert "no_nodes" in str(failure.value)
        assert failure.value.report.errors
        await db_session.rollback()

    async def test_geometry_outside_the_region_is_refused(self, db_session: AsyncSession) -> None:
        region = await seed_region(db_session, WATERLOO_SYNTHETIC)

        with pytest.raises(DatasetValidationError):
            await ingest_network(
                db_session,
                region=region,
                payload=build_synthetic_network(),
                source_type=SourceType.SYNTHETIC,
                source_name="wrong-place",
                ingestion_configuration={},
                # Toronto, not Waterloo.
                declared_bounds=(-79.5, 43.6, -79.3, 43.8),
            )
        await db_session.rollback()


class TestReproducibility:
    async def test_re_ingesting_unchanged_data_yields_the_same_checksum(
        self, db_session: AsyncSession
    ) -> None:
        # This is what makes "has the network actually changed?" answerable.
        first = await load_synthetic_dataset(db_session)
        await db_session.commit()
        second = await load_synthetic_dataset(db_session)
        await db_session.commit()

        assert first.checksum == second.checksum
        assert first.dataset_id != second.dataset_id

    async def test_the_ingestion_configuration_is_kept(self, db_session: AsyncSession) -> None:
        result = await load_synthetic_dataset(db_session)
        await db_session.commit()

        dataset = await db_session.get(DatasetVersion, result.dataset_id)
        assert dataset is not None
        assert dataset.source_type == SourceType.SYNTHETIC
        assert "generator" in dataset.ingestion_configuration
        assert dataset.acquired_at is not None
