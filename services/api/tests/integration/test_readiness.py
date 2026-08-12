"""Readiness against a real PostgreSQL/PostGIS database."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pathable_api.main import create_app
from pathable_api.schemas.health import ReadinessResponse
from tests.conftest import build_settings

pytestmark = pytest.mark.integration

READY_URL = "/api/v1/health/ready"
LIVE_URL = "/api/v1/health/live"


def client_for(database_url: str, *, timeout: float = 5.0) -> TestClient:
    settings = build_settings(database_url=database_url, readiness_timeout_seconds=timeout)
    return TestClient(create_app(settings), raise_server_exceptions=False)


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
