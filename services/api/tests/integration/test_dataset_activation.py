"""The gated lifecycle, on real PostGIS: seal, judge, accept, switch, roll back.

KI-10 was four ways a live network could change or go live without evidence.
Each test here is one of those doors, tried from the outside: the database is
asked to do the wrong thing and must refuse, or the lifecycle is asked to move
without the evidence it rests on and must stop — and where it does move, the
record must say why.

Candidates are built from the synthetic fixture. Where a candidate must route
differently from the live network, every segment is lengthened while it is
still a draft: a change that is certain to move every route, made the only way
the lifecycle allows, before sealing.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from collections.abc import Sequence

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from pathable_api.geo.datasets import DatasetLifecycleError, ingest_network
from pathable_api.geo.elevation import ElevationSample
from pathable_api.geo.elevation_apply import ElevationTargetError, apply_elevation
from pathable_api.geo.enums import DatasetStatus, SourceType
from pathable_api.geo.fixtures import (
    SYNTHETIC_REGION_SLUG,
    build_synthetic_network,
    load_synthetic_dataset,
)
from pathable_api.geo.lifecycle import (
    SealRefusedError,
    enrich_with_elevation,
    record_content_checksum,
    resolve_candidate,
    seal_candidate,
    verify_content_checksum,
)
from pathable_api.geo.models import DatasetVersion, GraphEdge, GraphNode, RouteRegressionRun
from pathable_api.geo.regions import WATERLOO_SYNTHETIC, seed_region
from pathable_api.routing import activation
from pathable_api.routing.activation import (
    DIFFERENCES,
    IDENTICAL,
    NO_BASELINE,
    ActivationRefusedError,
    accept_regression,
    activate_candidate,
    activation_history,
    evaluate_candidate,
    promote,
    rollback,
    rollback_target,
    verify_rollback_target,
)
from pathable_api.routing.graph import GraphRepository

pytestmark = pytest.mark.integration

REASON = "Every segment lengthened on purpose, to prove the gate sees a changed network."
ROLLBACK_REASON = "The new network routes people further; restore the one before it."
BYPASS = text("SET LOCAL pathable.allow_sealed_writes = on")


class FlatEarth:
    """Every point at 300 m: a real, if dull, elevation run."""

    name = "fake-flat"
    dataset = "fake"
    resolution_m: float | None = 1.0
    enabled = True
    attribution = ""

    async def sample(self, points: Sequence[tuple[float, float]]) -> list[ElevationSample]:
        return [
            ElevationSample(longitude, latitude, 300.0, self.name, self.dataset, self.resolution_m)
            for longitude, latitude in points
        ]


async def live(session: AsyncSession) -> uuid.UUID:
    """The fixture, promoted through the gate, committed."""
    result = await load_synthetic_dataset(session)
    await session.commit()
    return result.dataset_id


async def candidate(
    session: AsyncSession, *, stretch: float | None = None, elevate: bool = False
) -> uuid.UUID:
    """A committed draft, changed while it still may be."""
    result = await load_synthetic_dataset(session, activate=False)
    if stretch is not None:
        await session.execute(
            update(GraphEdge)
            .where(GraphEdge.dataset_version_id == result.dataset_id)
            .values(length_m=GraphEdge.length_m * stretch)
        )
    if elevate:
        await enrich_with_elevation(session, dataset_id=result.dataset_id, provider=FlatEarth())
    await session.commit()
    return result.dataset_id


async def judged(session: AsyncSession, dataset_id: uuid.UUID) -> RouteRegressionRun:
    """Sealed and evaluated against whatever is live, committed."""
    await seal_candidate(session, dataset_id)
    run = await evaluate_candidate(session, dataset_id, app_version="test")
    await session.commit()
    return run


async def dataset(session: AsyncSession, dataset_id: uuid.UUID) -> DatasetVersion:
    found = await session.get(DatasetVersion, dataset_id, populate_existing=True)
    assert found is not None
    return found


async def active_ids(session: AsyncSession) -> list[uuid.UUID]:
    return list(
        (
            await session.execute(
                select(DatasetVersion.id).where(DatasetVersion.status == DatasetStatus.ACTIVE)
            )
        ).scalars()
    )


async def refused(session: AsyncSession, statement: str, match: str, **params: object) -> None:
    with pytest.raises(IntegrityError, match=match):
        await session.execute(text(statement), params)
    await session.rollback()


class TestTheDatabaseRefuses:
    async def test_editing_the_live_network(self, db_session: AsyncSession) -> None:
        # The exact write KI-10 found: grade written into the dataset being served.
        live_id = await live(db_session)

        await refused(
            db_session,
            "UPDATE graph_edges SET derived_grade_percent = 1.0 WHERE dataset_version_id = :id",
            "can no longer change",
            id=live_id,
        )

    async def test_removing_a_segment_from_a_sealed_candidate(
        self, db_session: AsyncSession
    ) -> None:
        sealed = await candidate(db_session)
        await seal_candidate(db_session, sealed)
        await db_session.commit()

        await refused(
            db_session,
            "DELETE FROM graph_edges WHERE id = "
            "(SELECT id FROM graph_edges WHERE dataset_version_id = :id LIMIT 1)",
            "can no longer change",
            id=sealed,
        )

    async def test_rewriting_what_a_sealed_dataset_records(self, db_session: AsyncSession) -> None:
        live_id = await live(db_session)

        await refused(
            db_session,
            "UPDATE dataset_versions SET ingestion_configuration = '{}' WHERE id = :id",
            "content can no longer change",
            id=live_id,
        )
        await refused(
            db_session,
            "UPDATE dataset_versions SET content_checksum = repeat('0', 64) WHERE id = :id",
            "cannot be rewritten",
            id=live_id,
        )

    async def test_skipping_a_lifecycle_step(self, db_session: AsyncSession) -> None:
        live_id = await live(db_session)
        draft = await candidate(db_session)

        await refused(
            db_session,
            "UPDATE dataset_versions SET status = 'active' WHERE id = :id",
            "cannot move from draft to active",
            id=draft,
        )
        await refused(
            db_session,
            "UPDATE dataset_versions SET status = 'validated' WHERE id = :id",
            "cannot move from active to validated",
            id=live_id,
        )

    async def test_deleting_the_live_dataset(self, db_session: AsyncSession) -> None:
        live_id = await live(db_session)

        await refused(
            db_session,
            "DELETE FROM dataset_versions WHERE id = :id",
            "is live and cannot be deleted",
            id=live_id,
        )

    async def test_changing_or_removing_the_evidence(self, db_session: AsyncSession) -> None:
        await live(db_session)

        await refused(
            db_session,
            "UPDATE dataset_activation_events SET to_content_checksum = repeat('0', 64)",
            "audit record",
        )
        await refused(db_session, "DELETE FROM route_regression_acceptances", "audit record")
        await refused(db_session, "DELETE FROM route_regression_runs", "audit record")

    async def test_an_acceptance_with_no_real_reason(self, db_session: AsyncSession) -> None:
        # The application refuses first; this is the floor under it.
        run = await judged(db_session, await candidate(db_session))
        assert run.outcome == NO_BASELINE

        await refused(
            db_session,
            "INSERT INTO route_regression_acceptances (id, regression_run_id, reason, accepted_at) "
            "VALUES (gen_random_uuid(), :run, '   looks ok   ', now())",
            "acceptance_reason_is_a_sentence",
            run=run.id,
        )

    async def test_but_a_candidate_never_released_can_still_be_discarded(
        self, db_session: AsyncSession
    ) -> None:
        # Deleting a whole unreleased dataset is housekeeping, not an edit: its
        # rows go with it, and nothing ever routed on it.
        sealed = await candidate(db_session)
        await seal_candidate(db_session, sealed)
        await db_session.commit()

        await db_session.execute(
            text("DELETE FROM dataset_versions WHERE id = :id"), {"id": sealed}
        )
        await db_session.commit()

        remaining = await db_session.scalar(
            select(func.count())
            .select_from(GraphEdge)
            .where(GraphEdge.dataset_version_id == sealed)
        )
        assert remaining == 0


class TestEnrichment:
    async def test_the_live_network_is_never_enriched(self, db_session: AsyncSession) -> None:
        live_id = await live(db_session)
        served = await dataset(db_session, live_id)
        region_id = served.pilot_region_id

        with pytest.raises(ElevationTargetError):
            await apply_elevation(db_session, dataset=served, provider=FlatEarth())
        with pytest.raises(DatasetLifecycleError, match="only a draft candidate can change"):
            await enrich_with_elevation(db_session, dataset_id=live_id, provider=FlatEarth())
        await db_session.rollback()
        # With no candidate, "the region's candidate" is not the live dataset.
        with pytest.raises(DatasetLifecycleError, match="no draft candidate"):
            await resolve_candidate(db_session, region_id, None)

    async def test_a_candidate_that_needs_elevation_is_not_sealed_without_it(
        self, db_session: AsyncSession
    ) -> None:
        region = await seed_region(db_session, WATERLOO_SYNTHETIC)
        result = await ingest_network(
            db_session,
            region=region,
            payload=build_synthetic_network(),
            source_type=SourceType.SYNTHETIC,
            source_name="needs-elevation",
            ingestion_configuration={},
            declared_bounds=WATERLOO_SYNTHETIC.bounds,
            elevation_required=True,
        )
        await db_session.commit()

        with pytest.raises(SealRefusedError) as refusal:
            await seal_candidate(db_session, result.dataset_id)
        await db_session.rollback()

        assert [finding.code for finding in refusal.value.report.errors] == [
            "enrichment.elevation_missing"
        ]
        assert (await dataset(db_session, result.dataset_id)).status == DatasetStatus.DRAFT

        await enrich_with_elevation(db_session, dataset_id=result.dataset_id, provider=FlatEarth())
        sealed = await seal_candidate(db_session, result.dataset_id)
        await db_session.commit()
        assert (
            sealed.checksum.value == (await dataset(db_session, result.dataset_id)).content_checksum
        )


class TestContentChecksum:
    async def test_the_same_network_hashes_the_same_whatever_order_it_was_written_in(
        self, db_session: AsyncSession
    ) -> None:
        forwards = await candidate(db_session)
        payload = build_synthetic_network()
        backwards = dataclasses.replace(
            payload, nodes=list(reversed(payload.nodes)), edges=list(reversed(payload.edges))
        )
        region = await seed_region(db_session, WATERLOO_SYNTHETIC)
        reversed_result = await ingest_network(
            db_session,
            region=region,
            payload=backwards,
            source_type=SourceType.SYNTHETIC,
            source_name="written-backwards",
            ingestion_configuration={},
            declared_bounds=WATERLOO_SYNTHETIC.bounds,
            elevation_required=False,
        )
        first = await seal_candidate(db_session, forwards)
        second = await seal_candidate(db_session, reversed_result.dataset_id)

        assert first.checksum.value == second.checksum.value

    async def test_elevation_changes_the_content_checksum_but_not_the_ingest_one(
        self, db_session: AsyncSession
    ) -> None:
        # KI-10: two datasets differing only in grade used to share a checksum.
        plain = await candidate(db_session)
        elevated = await candidate(db_session, elevate=True)
        await seal_candidate(db_session, plain)
        await seal_candidate(db_session, elevated)
        await db_session.commit()

        a, b = await dataset(db_session, plain), await dataset(db_session, elevated)
        assert a.checksum == b.checksum
        assert a.content_checksum != b.content_checksum

    async def test_going_live_and_retiring_do_not_change_what_a_dataset_is(
        self, db_session: AsyncSession
    ) -> None:
        first = await live(db_session)
        sealed_as = (await dataset(db_session, first)).content_checksum
        await live(db_session)

        assert (await dataset(db_session, first)).status == DatasetStatus.RETIRED
        verification = await verify_content_checksum(db_session, first)
        assert verification.matches
        assert verification.computed.value == sealed_as


class TestActivationGate:
    async def test_a_sealed_candidate_needs_a_regression_run(
        self, db_session: AsyncSession
    ) -> None:
        await live(db_session)
        sealed = await candidate(db_session)
        await seal_candidate(db_session, sealed)
        await db_session.commit()

        with pytest.raises(ActivationRefusedError, match="no route regression"):
            await activate_candidate(db_session, sealed)

    async def test_changed_routes_go_live_only_with_a_recorded_reason(
        self, db_session: AsyncSession
    ) -> None:
        incumbent = await live(db_session)
        stretched = await candidate(db_session, stretch=1.5)
        run = await judged(db_session, stretched)

        assert run.outcome == DIFFERENCES
        assert run.baseline_dataset_id == incumbent
        assert {item["field"] for item in run.differences} >= {"distance_m", "duration_seconds"}

        run_id = run.id
        with pytest.raises(ActivationRefusedError, match="Review required: routes changed"):
            await activate_candidate(db_session, stretched)
        await db_session.rollback()
        with pytest.raises(ActivationRefusedError, match="reason is required"):
            await accept_regression(db_session, run_id, reason="fine")
        assert await active_ids(db_session) == [incumbent]

        acceptance = await accept_regression(db_session, run_id, reason=REASON)
        switch = await activate_candidate(db_session, stretched)
        await db_session.commit()

        assert await active_ids(db_session) == [stretched]
        assert switch.previous_id == incumbent
        assert switch.event.regression_run_id == run_id
        assert switch.event.acceptance_id == acceptance.id

    async def test_identical_routes_need_no_acceptance(self, db_session: AsyncSession) -> None:
        await live(db_session)
        rebuilt = await candidate(db_session)
        run = await judged(db_session, rebuilt)

        assert run.outcome == IDENTICAL
        assert run.difference_count == 0
        with pytest.raises(ActivationRefusedError, match="nothing to accept"):
            await accept_regression(db_session, run.id, reason=REASON)
        switch = await activate_candidate(db_session, rebuilt)
        await db_session.commit()

        assert switch.event.acceptance_id is None
        assert await active_ids(db_session) == [rebuilt]

    async def test_a_run_against_a_network_no_longer_live_is_refused(
        self, db_session: AsyncSession
    ) -> None:
        await live(db_session)
        first, second = await candidate(db_session), await candidate(db_session)
        await judged(db_session, first)
        await judged(db_session, second)
        await activate_candidate(db_session, second)
        await db_session.commit()

        # `first` was judged against a network that has since been replaced.
        with pytest.raises(ActivationRefusedError, match="live dataset changed"):
            await activate_candidate(db_session, first)

    async def test_another_candidates_run_is_refused(self, db_session: AsyncSession) -> None:
        await live(db_session)
        first, second = await candidate(db_session), await candidate(db_session)
        await judged(db_session, first)
        other = await judged(db_session, second)

        with pytest.raises(ActivationRefusedError, match="is not a regression run for dataset"):
            await activate_candidate(db_session, first, regression_run_id=other.id)

    async def test_a_run_under_a_different_routing_policy_is_refused(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await live(db_session)
        rebuilt = await candidate(db_session)
        await judged(db_session, rebuilt)
        monkeypatch.setattr(activation, "ROUTING_POLICY_VERSION", 10_000)

        with pytest.raises(ActivationRefusedError, match="routing policy changed"):
            await activate_candidate(db_session, rebuilt)

    async def test_two_switches_at_once_cannot_both_win(
        self, db_session: AsyncSession, migrated_database_url: str
    ) -> None:
        # Both candidates were judged against the same live network. The region
        # lock makes the second switch wait for the first, then see that what it
        # was judged against is gone.
        incumbent = await live(db_session)
        first, second = await candidate(db_session), await candidate(db_session)
        await judged(db_session, first)
        await judged(db_session, second)

        engine = create_async_engine(migrated_database_url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as other:
                await activate_candidate(db_session, first)  # holds the region, uncommitted
                racing = asyncio.create_task(activate_candidate(other, second))
                await asyncio.sleep(0.5)
                assert not racing.done()

                await db_session.commit()
                with pytest.raises(ActivationRefusedError, match="live dataset changed"):
                    await racing
                await other.rollback()
        finally:
            await engine.dispose()

        assert await active_ids(db_session) == [first]
        assert (await dataset(db_session, incumbent)).status == DatasetStatus.RETIRED


class TestRollback:
    async def test_it_restores_the_previous_dataset_exactly_as_it_was(
        self, db_session: AsyncSession
    ) -> None:
        first = await live(db_session)
        first_nodes = set(
            (
                await db_session.execute(
                    select(GraphNode.id).where(GraphNode.dataset_version_id == first)
                )
            ).scalars()
        )
        stretched = await candidate(db_session, stretch=1.5)
        await promote(db_session, stretched, acceptance_reason=REASON)
        await db_session.commit()
        datasets_before = await db_session.scalar(select(func.count()).select_from(DatasetVersion))
        region_id = (await dataset(db_session, first)).pilot_region_id

        target = await rollback_target(db_session, region_id, None)
        verified = await verify_rollback_target(db_session, target)
        switch = await rollback(
            db_session,
            region_id=region_id,
            target_id=target.id,
            verified_checksum=verified.value,
            reason=ROLLBACK_REASON,
        )
        await db_session.commit()

        assert target.id == first
        assert switch.previous_id == stretched
        assert await active_ids(db_session) == [first]
        assert (await dataset(db_session, stretched)).status == DatasetStatus.RETIRED
        # Nothing was rebuilt: no new dataset, and the very same rows.
        assert await db_session.scalar(select(func.count()).select_from(DatasetVersion)) == (
            datasets_before
        )
        assert first_nodes == set(
            (
                await db_session.execute(
                    select(GraphNode.id).where(GraphNode.dataset_version_id == first)
                )
            ).scalars()
        )
        assert verified.value == (await dataset(db_session, first)).content_checksum

        history = await activation_history(db_session, region_id)
        assert [(event.action, event.to_dataset_id) for event in history] == [
            ("activate", first),
            ("activate", stretched),
            ("rollback", first),
        ]
        assert history[-1].reason == ROLLBACK_REASON
        assert history[-1].from_dataset_id == stretched

    async def test_it_needs_a_reason(self, db_session: AsyncSession) -> None:
        first = await live(db_session)
        await live(db_session)
        region_id = (await dataset(db_session, first)).pilot_region_id
        verified = await verify_rollback_target(db_session, await dataset(db_session, first))

        with pytest.raises(ActivationRefusedError, match="reason is required"):
            await rollback(
                db_session,
                region_id=region_id,
                target_id=first,
                verified_checksum=verified.value,
                reason="undo",
            )

    async def test_a_candidate_that_never_went_live_is_not_a_target(
        self, db_session: AsyncSession
    ) -> None:
        await live(db_session)
        sealed = await candidate(db_session)
        await seal_candidate(db_session, sealed)
        await db_session.commit()

        with pytest.raises(ActivationRefusedError, match="only a retired dataset"):
            await verify_rollback_target(db_session, await dataset(db_session, sealed))

    async def test_a_target_whose_rows_no_longer_match_is_refused(
        self, db_session: AsyncSession
    ) -> None:
        first = await live(db_session)
        await live(db_session)
        # Only a restore may write sealed rows; this plays a botched one.
        await db_session.execute(BYPASS)
        await db_session.execute(
            text(
                "UPDATE graph_edges SET length_m = length_m + 1 WHERE id = "
                "(SELECT id FROM graph_edges WHERE dataset_version_id = :id LIMIT 1)"
            ),
            {"id": first},
        )
        await db_session.commit()

        with pytest.raises(ActivationRefusedError, match="no longer matches the content"):
            await verify_rollback_target(db_session, await dataset(db_session, first))

    async def test_a_legacy_dataset_is_hashed_from_its_rows_before_anything_rests_on_it(
        self, db_session: AsyncSession
    ) -> None:
        # A dataset activated before PA-GEO-02 has no content checksum, and
        # nothing may be compared against it, or rolled back to, until one is
        # recorded from what is actually stored.
        legacy = await live(db_session)
        await db_session.execute(BYPASS)
        await db_session.execute(
            text(
                "UPDATE dataset_versions SET content_checksum = NULL, "
                "content_checksum_version = NULL WHERE id = :id"
            ),
            {"id": legacy},
        )
        await db_session.commit()
        rebuilt = await candidate(db_session)
        await seal_candidate(db_session, rebuilt)
        await db_session.commit()

        with pytest.raises(ActivationRefusedError, match="predates content checksums"):
            await evaluate_candidate(db_session, rebuilt, app_version="test")
        await db_session.rollback()

        recorded = await record_content_checksum(db_session, legacy)
        await db_session.commit()
        with pytest.raises(DatasetLifecycleError, match="already has a content checksum"):
            await record_content_checksum(db_session, legacy)
        await db_session.rollback()

        run = await evaluate_candidate(db_session, rebuilt, app_version="test")
        assert run.baseline_content_checksum == recorded.value
        assert run.outcome == IDENTICAL


class TestServingCache:
    async def test_the_cache_follows_each_switch_and_never_serves_a_changed_graph(
        self, db_session: AsyncSession
    ) -> None:
        # Graphs are cached by dataset id. That is only correct because a
        # dataset's content can no longer change once it is live — so a
        # rollback may serve the cached graph of the dataset it restores.
        repository = GraphRepository()
        first = await live(db_session)
        before = await repository.active_graph(db_session, SYNTHETIC_REGION_SLUG)

        stretched = await candidate(db_session, stretch=1.5)
        await promote(db_session, stretched, acceptance_reason=REASON)
        await db_session.commit()
        during = await repository.active_graph(db_session, SYNTHETIC_REGION_SLUG)

        region_id = (await dataset(db_session, first)).pilot_region_id
        verified = await verify_rollback_target(db_session, await dataset(db_session, first))
        await rollback(
            db_session,
            region_id=region_id,
            target_id=first,
            verified_checksum=verified.value,
            reason=ROLLBACK_REASON,
        )
        await db_session.commit()
        after = await repository.active_graph(db_session, SYNTHETIC_REGION_SLUG)

        assert (before.dataset_id, during.dataset_id, after.dataset_id) == (
            first,
            stretched,
            first,
        )
        assert after is before
        assert sum(edge.length_m for edge in during.segments) > sum(
            edge.length_m for edge in before.segments
        )
