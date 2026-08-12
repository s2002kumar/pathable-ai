"""Liveness, and the readiness paths that need no live database."""

from __future__ import annotations

from fastapi.testclient import TestClient

from pathable_api.core.request_context import REQUEST_ID_HEADER
from pathable_api.main import create_app
from pathable_api.schemas.health import LivenessResponse, ReadinessResponse
from tests.conftest import build_settings

LIVE_URL = "/api/v1/health/live"
READY_URL = "/api/v1/health/ready"


class TestLiveness:
    def test_returns_ok(self, client: TestClient) -> None:
        response = client.get(LIVE_URL)

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "service": "pathable-api",
            "version": "0.1.0",
        }

    def test_body_matches_the_published_schema(self, client: TestClient) -> None:
        parsed = LivenessResponse.model_validate(client.get(LIVE_URL).json())

        assert parsed.status == "ok"

    def test_reflects_configured_identity(self) -> None:
        settings = build_settings(service_name="pathable-api-canary", app_version="9.9.9")

        with TestClient(create_app(settings)) as client:
            body = client.get(LIVE_URL).json()

        assert body["service"] == "pathable-api-canary"
        assert body["version"] == "9.9.9"

    def test_succeeds_when_no_database_is_configured(self, client: TestClient) -> None:
        assert client.get(LIVE_URL).status_code == 200

    def test_succeeds_when_the_configured_database_is_unreachable(self) -> None:
        # The whole point of splitting liveness from readiness: a database outage
        # must not make an orchestrator kill a perfectly healthy process. Port 1 on
        # loopback refuses immediately, so no network round trip is involved.
        settings = build_settings(
            database_url="postgresql+psycopg://nobody:nothing@127.0.0.1:1/pathable",
            readiness_timeout_seconds=0.5,
        )

        with TestClient(create_app(settings)) as client:
            assert client.get(LIVE_URL).status_code == 200

    def test_echoes_a_request_id(self, client: TestClient) -> None:
        assert client.get(LIVE_URL).headers[REQUEST_ID_HEADER]


class TestReadinessWithoutDatabaseConfiguration:
    def test_reports_not_ready(self, client: TestClient) -> None:
        response = client.get(READY_URL)

        assert response.status_code == 503

        body = ReadinessResponse.model_validate(response.json())
        assert body.status == "not_ready"
        assert body.checks.database.status == "unavailable"
        assert body.checks.postgis.status == "unavailable"

    def test_names_the_missing_variable(self, client: TestClient) -> None:
        body = client.get(READY_URL).json()

        assert "DATABASE_URL" in body["checks"]["database"]["detail"]

    def test_failure_body_uses_the_same_shape_as_success(self, client: TestClient) -> None:
        # One shape means the client parses readiness once, not twice.
        body = client.get(READY_URL).json()

        assert set(body) == {"status", "service", "version", "checks"}
        assert set(body["checks"]) == {"database", "postgis"}


class TestReadinessWithUnreachableDatabase:
    def test_reports_not_ready_without_leaking_connection_details(self) -> None:
        settings = build_settings(
            database_url="postgresql+psycopg://pathable:sup3r-s3cret@127.0.0.1:1/pathable",
            readiness_timeout_seconds=1.0,
        )

        with TestClient(create_app(settings)) as client:
            response = client.get(READY_URL)

        assert response.status_code == 503

        raw = response.text
        assert "sup3r-s3cret" not in raw
        assert "127.0.0.1" not in raw
        assert "Traceback" not in raw

        body = ReadinessResponse.model_validate(response.json())
        assert body.status == "not_ready"
        assert body.checks.database.status == "unavailable"

        # Either safe detail is correct here, and which one appears depends on the
        # platform: a refused connection to a closed port resolves immediately on
        # some systems and outlives the probe timeout on others. Both are failures
        # that leak nothing, which is what this test exists to guarantee — pinning
        # one string would make the suite fail for a reason that is not a defect.
        assert body.checks.database.detail in {
            "database unreachable",
            "probe exceeded the configured readiness timeout",
        }
