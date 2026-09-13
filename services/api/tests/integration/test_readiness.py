"""Readiness against a real PostgreSQL/PostGIS database."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from pathable_api.geo.fixtures import SYNTHETIC_REGION_SLUG, load_synthetic_dataset
from pathable_api.main import create_app
from pathable_api.schemas.health import ReadinessResponse
from tests.conftest import build_settings

pytestmark = pytest.mark.integration

READY_URL = "/api/v1/health/ready"
LIVE_URL = "/api/v1/health/live"


def client_for(
    database_url: str, *, timeout: float = 5.0, preload: tuple[str, ...] = ()
) -> TestClient:
    settings = build_settings(
        database_url=database_url,
        readiness_timeout_seconds=timeout,
        graph_preload_regions=preload,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


def wait_for_graph(client: TestClient, *, attempts: int = 100) -> ReadinessResponse:
    """Poll readiness until the preload has finished one way or the other."""
    body = ReadinessResponse.model_validate(client.get(READY_URL).json())
    for _ in range(attempts):
        if body.checks.graph.status == "ok" or "loading" not in body.checks.graph.detail:
            return body
        time.sleep(0.1)
        body = ReadinessResponse.model_validate(client.get(READY_URL).json())
    return body


class TestReadyDatabase:
    def test_reports_ready(self, migrated_database_url: str) -> None:
        with client_for(migrated_database_url) as client:
            response = client.get(READY_URL)

        assert response.status_code == 200

        body = ReadinessResponse.model_validate(response.json())
        assert body.status == "ready"
        assert body.checks.database.status == "ok"
        assert body.checks.database.detail == "connected"

    def test_reports_the_installed_postgis_version(self, migrated_database_url: str) -> None:
        with client_for(migrated_database_url) as client:
            body = ReadinessResponse.model_validate(client.get(READY_URL).json())

        assert body.checks.postgis.status == "ok"
        assert body.checks.postgis.detail.startswith("postgis ")
        # A real version string, not a placeholder.
        assert body.checks.postgis.detail.split(" ", 1)[1][0].isdigit()

    def test_records_probe_latencies(self, migrated_database_url: str) -> None:
        with client_for(migrated_database_url) as client:
            body = ReadinessResponse.model_validate(client.get(READY_URL).json())

        assert body.checks.database.latency_ms is not None
        assert body.checks.postgis.latency_ms is not None
        assert body.checks.database.latency_ms >= 0.0

    def test_repeated_probes_reuse_the_pool(self, migrated_database_url: str) -> None:
        # Catches a connection leak: without pooling or with a leak, the tenth
        # probe would fail once the server's connection limit is reached.
        with client_for(migrated_database_url) as client:
            statuses = [client.get(READY_URL).status_code for _ in range(10)]

        assert statuses == [200] * 10


class TestDatabaseWithoutPostgis:
    def test_reports_not_ready_when_the_extension_is_missing(self, empty_database_url: str) -> None:
        # An un-migrated database is reachable but unusable for routing work, and
        # readiness must say so rather than reporting a healthy instance.
        with client_for(empty_database_url) as client:
            response = client.get(READY_URL)

        assert response.status_code == 503

        body = ReadinessResponse.model_validate(response.json())
        assert body.status == "not_ready"
        assert body.checks.database.status == "ok"
        assert body.checks.postgis.status == "unavailable"
        assert "not installed" in body.checks.postgis.detail


class TestUnreachableDatabase:
    def test_reports_not_ready(self, migrated_database_url: str) -> None:
        unreachable = migrated_database_url.replace("/pathable_test_", "/pathable_absent_")

        with client_for(unreachable, timeout=3.0) as client:
            response = client.get(READY_URL)

        assert response.status_code == 503
        assert ReadinessResponse.model_validate(response.json()).status == "not_ready"

    def test_liveness_still_succeeds(self, migrated_database_url: str) -> None:
        unreachable = migrated_database_url.replace("/pathable_test_", "/pathable_absent_")

        with client_for(unreachable, timeout=3.0) as client:
            assert client.get(LIVE_URL).status_code == 200

    def test_response_does_not_leak_the_connection_string(self, migrated_database_url: str) -> None:
        unreachable = migrated_database_url.replace("/pathable_test_", "/pathable_absent_")

        with client_for(unreachable, timeout=3.0) as client:
            raw = client.get(READY_URL).text

        assert "pathable_absent_" not in raw
        assert "password" not in raw.lower()
        assert "Traceback" not in raw


class TestReadinessWithGraphPreload:
    async def test_ready_only_once_the_configured_graph_is_loaded(
        self, migrated_database_url: str, db_session: AsyncSession
    ) -> None:
        # The deployment contract: a 200 from /ready means routes can be served
        # now, not after a load that has not started. The synthetic fixture is
        # small, so the "loading" state may be over before the first poll; what
        # must hold is that the final state is ready with the graph accounted for.
        await load_synthetic_dataset(db_session)
        await db_session.commit()

        with client_for(migrated_database_url, preload=(SYNTHETIC_REGION_SLUG,)) as client:
            body = wait_for_graph(client)
            status = client.get(READY_URL).status_code

        assert status == 200
        assert body.status == "ready"
        assert body.checks.graph.status == "ok"
        assert (
            f"{SYNTHETIC_REGION_SLUG}: 9 nodes, 13 segments loaded in" in body.checks.graph.detail
        )
        assert body.checks.graph.latency_ms is not None

    def test_a_region_without_a_dataset_keeps_the_instance_not_ready(
        self, migrated_database_url: str
    ) -> None:
        # PostgreSQL and PostGIS are fine; the graph is not. That must be a 503
        # with a reason an operator can act on, not a 200 followed by 404s.
        with client_for(migrated_database_url, preload=("waterloo",)) as client:
            body = wait_for_graph(client)
            status = client.get(READY_URL).status_code

        assert status == 503
        assert body.status == "not_ready"
        assert body.checks.database.status == "ok"
        assert body.checks.postgis.status == "ok"
        assert body.checks.graph.status == "unavailable"
        assert body.checks.graph.detail == "waterloo: no active dataset"
