"""Dependency probes.

Exercised against hand-built stand-ins rather than a live database so the failure
paths that matter most — unreachable, slow, PostGIS absent — are deterministic and
fast. The success path is additionally proven against real PostGIS in
``tests/integration/test_readiness.py``.
"""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Any, Self, cast

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from pathable_api.db.health import check_dependencies, is_ready
from pathable_api.schemas.health import DependencyCheck, ReadinessChecks

#: Stands in for a driver message that embeds the DSN — psycopg errors routinely do.
LEAKY_DRIVER_MESSAGE = (
    'connection to server at "db.internal" (10.0.0.4), port 5432 failed: '
    'password authentication failed for user "pathable" (password=sup3r-s3cret)'
)


class _FakeResult:
    def __init__(self, value: str | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> str | None:
        return self._value


class _FakeConnection:
    """Minimal stand-in for an ``AsyncConnection``."""

    def __init__(self, *, postgis_version: str | None, enter_delay: float = 0.0) -> None:
        self._postgis_version = postgis_version
        self._enter_delay = enter_delay
        self.executed = 0

    async def __aenter__(self) -> Self:
        if self._enter_delay:
            await asyncio.sleep(self._enter_delay)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return False

    async def execute(self, _statement: Any) -> _FakeResult:
        self.executed += 1
        # First call is the SELECT 1 connectivity probe; second is the PostGIS lookup.
        if self.executed == 1:
            return _FakeResult("1")
        return _FakeResult(self._postgis_version)


class _FakeEngine:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    def connect(self) -> _FakeConnection:
        return self._connection


class _RefusingEngine:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def connect(self) -> _FakeConnection:
        raise self._error


def as_engine(stub: object) -> AsyncEngine:
    """Narrow a stub to the parameter type.

    A precise cast rather than a blanket ignore: ``check_dependencies`` only ever
    calls ``.connect()``, and pinning that here keeps the stub honest.
    """
    return cast("AsyncEngine", stub)


class TestHealthyDatabase:
    async def test_reports_both_dependencies_ok(self) -> None:
        engine = _FakeEngine(_FakeConnection(postgis_version="3.4.2"))

        checks = await check_dependencies(as_engine(engine), timeout_seconds=2.0)

        assert checks.database.status == "ok"
        assert checks.database.detail == "connected"
        assert checks.postgis.status == "ok"
        assert checks.postgis.detail == "postgis 3.4.2"
        assert is_ready(checks) is True

    async def test_records_latency_for_each_probe(self) -> None:
        engine = _FakeEngine(_FakeConnection(postgis_version="3.4.2"))

        checks = await check_dependencies(as_engine(engine), timeout_seconds=2.0)

        assert checks.database.latency_ms is not None
        assert checks.database.latency_ms >= 0.0
        assert checks.postgis.latency_ms is not None


class TestMissingPostgis:
    async def test_database_is_ok_but_postgis_is_not(self) -> None:
        engine = _FakeEngine(_FakeConnection(postgis_version=None))

        checks = await check_dependencies(as_engine(engine), timeout_seconds=2.0)

        assert checks.database.status == "ok"
        assert checks.postgis.status == "unavailable"
        assert "not installed" in checks.postgis.detail
        assert is_ready(checks) is False


class TestUnreachableDatabase:
    async def test_reports_unavailable_without_raising(self) -> None:
        engine = _RefusingEngine(OSError("Connection refused"))

        checks = await check_dependencies(as_engine(engine), timeout_seconds=2.0)

        assert checks.database.status == "unavailable"
        assert checks.database.detail == "database unreachable"
        assert checks.postgis.status == "unavailable"
        assert checks.postgis.detail == "not probed: database unreachable"
        assert is_ready(checks) is False

    async def test_driver_message_never_reaches_the_response(self) -> None:
        # readiness is typically unauthenticated, so the DSN in a psycopg error must
        # stay in the logs and out of the body.
        engine = _RefusingEngine(
            OperationalError(
                LEAKY_DRIVER_MESSAGE, params=None, orig=Exception(LEAKY_DRIVER_MESSAGE)
            )
        )

        checks = await check_dependencies(as_engine(engine), timeout_seconds=2.0)

        serialised = checks.model_dump_json()
        assert "sup3r-s3cret" not in serialised
        assert "db.internal" not in serialised
        assert "10.0.0.4" not in serialised
        assert "pathable" not in serialised

    async def test_logs_the_failure_for_operators(self, caplog: pytest.LogCaptureFixture) -> None:
        engine = _RefusingEngine(OSError("Connection refused"))

        with caplog.at_level("WARNING", logger="pathable_api.db.health"):
            await check_dependencies(as_engine(engine), timeout_seconds=2.0)

        assert "Readiness probe failed" in caplog.text


class TestTimeout:
    async def test_slow_database_is_bounded_by_the_configured_timeout(self) -> None:
        # Without the bound, a hung database would hold the readiness request open
        # until the client or load balancer gave up.
        engine = _FakeEngine(_FakeConnection(postgis_version="3.4.2", enter_delay=5.0))

        checks = await asyncio.wait_for(
            check_dependencies(as_engine(engine), timeout_seconds=0.05), timeout=2.0
        )

        assert checks.database.status == "unavailable"
        assert "timeout" in checks.database.detail
        assert is_ready(checks) is False


class TestIsReady:
    @pytest.mark.parametrize(
        ("database", "postgis", "expected"),
        [
            ("ok", "ok", True),
            ("ok", "unavailable", False),
            ("unavailable", "ok", False),
            ("unavailable", "unavailable", False),
        ],
    )
    def test_requires_every_dependency(self, database: str, postgis: str, expected: bool) -> None:
        checks = ReadinessChecks(
            database=DependencyCheck.model_validate({"status": database, "detail": "x"}),
            postgis=DependencyCheck.model_validate({"status": postgis, "detail": "x"}),
        )

        assert is_ready(checks) is expected
