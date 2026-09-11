"""Startup graph preload: what readiness says while a region loads, or cannot.

Nothing here touches a database. The loader is a stand-in whose behaviour each
test chooses, because what is under test is the state machine and the words it
hands to an unauthenticated readiness caller — not graph loading itself, which
the PostGIS integration suite covers.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import pytest

from pathable_api.routing.graph import NoActiveDatasetError
from pathable_api.routing.warmup import GraphWarmup


@dataclass
class _FakeGraph:
    dataset_id: str = "0c9d1b3a-0000-4000-8000-000000000000"
    node_count: int = 9
    segment_count: int = 13


class _FakeDatabase:
    @asynccontextmanager
    async def session(self) -> AsyncIterator[object]:
        yield object()


class _FakeRepository:
    """Loads according to a script: a graph, an exception to raise, or a delay."""

    def __init__(self, outcomes: dict[str, Any], *, delay: float = 0.0) -> None:
        self._outcomes = outcomes
        self._delay = delay
        self.calls: list[str] = []

    async def active_graph(self, session: object, region_slug: str) -> _FakeGraph:
        self.calls.append(region_slug)
        if self._delay:
            await asyncio.sleep(self._delay)
        outcome = self._outcomes[region_slug]
        if isinstance(outcome, BaseException):
            raise outcome
        graph: _FakeGraph = outcome
        return graph


async def _settle(warmup: GraphWarmup) -> None:
    for _ in range(200):
        if warmup.complete:
            return
        await asyncio.sleep(0.01)
    msg = "warmup never completed"
    raise AssertionError(msg)


class TestUnconfigured:
    def test_no_regions_means_lazy_loading_and_ready(self) -> None:
        # The development default: nothing preloads and readiness must not wait
        # on a load that will never be scheduled.
        warmup = GraphWarmup.for_regions(())

        assert warmup.configured is False
        check = warmup.check()
        assert check.status == "ok"
        assert "first request" in check.detail

    async def test_start_is_a_no_op_without_regions(self) -> None:
        warmup = GraphWarmup.for_regions(())
        repository = _FakeRepository({})

        warmup.start(_FakeDatabase(), repository)  # type: ignore[arg-type]
        await asyncio.sleep(0)

        assert repository.calls == []
        assert warmup.complete is True


class TestLoading:
    async def test_not_ready_until_the_region_has_loaded(self) -> None:
        # Readiness is a promise to the load balancer. Returning 200 while the
        # graph is still being built would route users into a twenty-second
        # window where every route request blocks or fails.
        warmup = GraphWarmup.for_regions(("waterloo",))
        repository = _FakeRepository({"waterloo": _FakeGraph()}, delay=0.05)

        warmup.start(_FakeDatabase(), repository)  # type: ignore[arg-type]
        await asyncio.sleep(0.01)

        loading = warmup.check()
        assert loading.status == "unavailable"
        assert loading.detail == "loading waterloo"

        await _settle(warmup)

        ready = warmup.check()
        assert ready.status == "ok"
        assert "waterloo: 9 nodes, 13 segments loaded in" in ready.detail
        assert ready.latency_ms is not None
        assert ready.latency_ms >= 50.0

    async def test_regions_load_one_at_a_time_in_configured_order(self) -> None:
        # Two loads at once would double the transient memory peak that the
        # deployment envelope is sized against.
        warmup = GraphWarmup.for_regions(("first", "second"))
        repository = _FakeRepository({"first": _FakeGraph(), "second": _FakeGraph()})

        warmup.start(_FakeDatabase(), repository)  # type: ignore[arg-type]
        await _settle(warmup)

        assert repository.calls == ["first", "second"]
        assert warmup.check().status == "ok"

    async def test_starting_twice_does_not_load_twice(self) -> None:
        warmup = GraphWarmup.for_regions(("waterloo",))
        repository = _FakeRepository({"waterloo": _FakeGraph()})

        warmup.start(_FakeDatabase(), repository)  # type: ignore[arg-type]
        warmup.start(_FakeDatabase(), repository)  # type: ignore[arg-type]
        await _settle(warmup)

        assert repository.calls == ["waterloo"]


class TestFailure:
    async def test_a_region_with_no_active_dataset_keeps_the_instance_not_ready(self) -> None:
        # Permanently, not transiently: nothing will make it routable until an
        # operator ingests a dataset, and traffic should not be sent meanwhile.
        warmup = GraphWarmup.for_regions(("waterloo",))
        repository = _FakeRepository({"waterloo": NoActiveDatasetError("no dataset")})

        warmup.start(_FakeDatabase(), repository)  # type: ignore[arg-type]
        await _settle(warmup)

        check = warmup.check()
        assert check.status == "unavailable"
        assert check.detail == "waterloo: no active dataset"

    async def test_an_unexpected_error_reports_its_type_and_nothing_else(self) -> None:
        # The readiness endpoint is unauthenticated. An exception message can
        # carry a hostname, a path or a query; the type name carries none of that.
        warmup = GraphWarmup.for_regions(("waterloo",))
        secret = "postgresql://user:s3cret@db.internal:5432/pathable"
        repository = _FakeRepository({"waterloo": RuntimeError(f"could not reach {secret}")})

        warmup.start(_FakeDatabase(), repository)  # type: ignore[arg-type]
        await _settle(warmup)

        check = warmup.check()
        assert check.status == "unavailable"
        assert check.detail == "waterloo: preload failed (RuntimeError)"
        assert "s3cret" not in check.detail
        assert "db.internal" not in check.detail

    async def test_one_failed_region_outranks_another_that_loaded(self) -> None:
        warmup = GraphWarmup.for_regions(("waterloo", "atlantis"))
        repository = _FakeRepository(
            {"waterloo": _FakeGraph(), "atlantis": NoActiveDatasetError("nothing")}
        )

        warmup.start(_FakeDatabase(), repository)  # type: ignore[arg-type]
        await _settle(warmup)

        check = warmup.check()
        assert check.status == "unavailable"
        assert check.detail == "atlantis: no active dataset"

    def test_preload_without_a_database_fails_every_region(self) -> None:
        warmup = GraphWarmup.for_regions(("waterloo",))

        warmup.fail_without_database()

        check = warmup.check()
        assert check.status == "unavailable"
        assert "DATABASE_URL" in check.detail
        assert warmup.complete is True


class TestShutdown:
    async def test_stop_cancels_an_in_flight_load(self) -> None:
        warmup = GraphWarmup.for_regions(("waterloo",))
        repository = _FakeRepository({"waterloo": _FakeGraph()}, delay=10.0)

        warmup.start(_FakeDatabase(), repository)  # type: ignore[arg-type]
        await asyncio.sleep(0.01)
        await warmup.stop()

        assert warmup.regions["waterloo"].state == "failed"
        assert "cancelled" in warmup.regions["waterloo"].detail

    async def test_stop_after_completion_is_harmless(self) -> None:
        warmup = GraphWarmup.for_regions(("waterloo",))
        repository = _FakeRepository({"waterloo": _FakeGraph()})

        warmup.start(_FakeDatabase(), repository)  # type: ignore[arg-type]
        await _settle(warmup)
        await warmup.stop()

        assert warmup.check().status == "ok"


@pytest.mark.parametrize("state", ["pending", "loading"])
def test_unfinished_states_are_reported_as_unavailable(state: str) -> None:
    warmup = GraphWarmup.for_regions(("waterloo",))
    warmup.regions["waterloo"].state = state  # type: ignore[assignment]
    warmup.regions["waterloo"].detail = f"{state} waterloo"

    check = warmup.check()
    assert check.status == "unavailable"
    assert check.detail == f"{state} waterloo"
