"""Dependency probes backing the readiness endpoint.

Deliberate design point: driver exception text never reaches the HTTP response.
psycopg failure messages routinely embed the host, port, database name and
occasionally the user, and a readiness endpoint is typically unauthenticated. The
full exception is logged with the correlation id; the caller gets a fixed,
information-free string.
"""

from __future__ import annotations

import asyncio
import time
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from pathable_api.core.logging import get_logger
from pathable_api.schemas.health import DependencyCheck, ReadinessChecks

logger = get_logger(__name__)

_CONNECTIVITY_PROBE: Final = text("SELECT 1")
_POSTGIS_PROBE: Final = text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")

_UNREACHABLE_DETAIL: Final = "database unreachable"
_TIMEOUT_DETAIL: Final = "probe exceeded the configured readiness timeout"
_NOT_PROBED_DETAIL: Final = "not probed: database unreachable"
_MISSING_POSTGIS_DETAIL: Final = "postgis extension is not installed in this database"


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


async def _probe(engine: AsyncEngine) -> ReadinessChecks:
    """Run both probes on a single pooled connection."""
    async with engine.connect() as connection:
        db_started = time.perf_counter()
        await connection.execute(_CONNECTIVITY_PROBE)
        database = DependencyCheck(
            status="ok", detail="connected", latency_ms=_elapsed_ms(db_started)
        )

        gis_started = time.perf_counter()
        result = await connection.execute(_POSTGIS_PROBE)
        version = result.scalar_one_or_none()
        gis_latency = _elapsed_ms(gis_started)

    if version is None:
        postgis = DependencyCheck(
            status="unavailable", detail=_MISSING_POSTGIS_DETAIL, latency_ms=gis_latency
        )
    else:
        postgis = DependencyCheck(status="ok", detail=f"postgis {version}", latency_ms=gis_latency)

    return ReadinessChecks(database=database, postgis=postgis)


async def check_dependencies(engine: AsyncEngine, *, timeout_seconds: float) -> ReadinessChecks:
    """Probe PostgreSQL and PostGIS under a bounded timeout.

    Never raises: an unreachable or slow database is an expected readiness outcome,
    not an API error.
    """
    started = time.perf_counter()
    try:
        return await asyncio.wait_for(_probe(engine), timeout=timeout_seconds)
    except TimeoutError:
        latency = _elapsed_ms(started)
        logger.warning(
            "Readiness probe timed out",
            extra={"timeout_seconds": timeout_seconds, "duration_ms": latency},
        )
        return ReadinessChecks(
            database=DependencyCheck(
                status="unavailable", detail=_TIMEOUT_DETAIL, latency_ms=latency
            ),
            postgis=DependencyCheck(
                status="unavailable", detail=_NOT_PROBED_DETAIL, latency_ms=None
            ),
        )
    except Exception as exc:
        latency = _elapsed_ms(started)
        # Full detail to logs (private), exception type only to the caller (public).
        logger.warning(
            "Readiness probe failed",
            exc_info=exc,
            extra={"exception_type": type(exc).__name__, "duration_ms": latency},
        )
        return ReadinessChecks(
            database=DependencyCheck(
                status="unavailable", detail=_UNREACHABLE_DETAIL, latency_ms=latency
            ),
            postgis=DependencyCheck(
                status="unavailable", detail=_NOT_PROBED_DETAIL, latency_ms=None
            ),
        )


def is_ready(checks: ReadinessChecks) -> bool:
    """Readiness requires every dependency to be usable."""
    return (
        checks.database.status == "ok"
        and checks.postgis.status == "ok"
        and checks.graph.status == "ok"
    )
