"""Liveness and readiness endpoints."""

from __future__ import annotations

from http import HTTPStatus

from fastapi import APIRouter, Response

from pathable_api.api.deps import DatabaseDep, SettingsDep, WarmupDep
from pathable_api.db.health import check_dependencies, is_ready
from pathable_api.schemas.health import (
    DependencyCheck,
    LivenessResponse,
    ReadinessChecks,
    ReadinessResponse,
)

router = APIRouter(prefix="/health", tags=["health"])

_UNCONFIGURED_DETAIL = "DATABASE_URL is not configured for this instance"


@router.get(
    "/live",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description=(
        "Reports that the process is running and able to serve HTTP. Touches no "
        "dependency, so a database outage never causes an orchestrator to restart "
        "an otherwise healthy instance. Use /health/ready for traffic gating."
    ),
    operation_id="getLiveness",
)
async def liveness(settings: SettingsDep) -> LivenessResponse:
    return LivenessResponse(
        status="ok",
        service=settings.service_name,
        version=settings.app_version,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description=(
        "Reports whether this instance should receive traffic. Probes PostgreSQL "
        "connectivity and PostGIS availability under a bounded timeout, and reports "
        "whether every preloaded routing graph is loaded. Returns 200 when ready and "
        "503 when not; the body shape is identical in both cases."
    ),
    operation_id="getReadiness",
    responses={
        HTTPStatus.SERVICE_UNAVAILABLE: {
            "model": ReadinessResponse,
            "description": "One or more dependencies are unavailable.",
        }
    },
)
async def readiness(
    settings: SettingsDep,
    database: DatabaseDep,
    warmup: WarmupDep,
    response: Response,
) -> ReadinessResponse:
    if database is None:
        checks = ReadinessChecks(
            database=DependencyCheck(status="unavailable", detail=_UNCONFIGURED_DETAIL),
            postgis=DependencyCheck(status="unavailable", detail=_UNCONFIGURED_DETAIL),
        )
    else:
        checks = await check_dependencies(
            database.engine, timeout_seconds=settings.readiness_timeout_seconds
        )

    # The graph line comes from the lifespan's preload state, not from a probe:
    # a graph that is still loading is a fact about this process, not the database.
    checks = checks.model_copy(update={"graph": warmup.check()})

    ready = is_ready(checks)
    response.status_code = HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        service=settings.service_name,
        version=settings.app_version,
        checks=checks,
    )
