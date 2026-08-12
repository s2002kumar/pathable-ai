"""Global error handling: one shape, no internals."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from pathable_api.core.errors import ApiError, status_to_code
from pathable_api.core.request_context import REQUEST_ID_HEADER, is_valid_request_id
from pathable_api.main import create_app
from pathable_api.schemas.errors import ApiErrorResponse
from tests.conftest import build_settings

#: A string that must never appear in a response body. Stands in for a real
#: connection string or credential ending up inside an exception message.
LEAKED_SECRET = "postgresql://pathable:sup3r-s3cret@db.internal:5432/pathable"


@pytest.fixture
def failing_app() -> FastAPI:
    """An app with routes that fail in each way the handlers must cover."""
    application = create_app(build_settings())

    @application.get("/api/v1/_test/boom")
    async def boom() -> None:
        raise RuntimeError(f"connection failed for {LEAKED_SECRET}")

    @application.get("/api/v1/_test/teapot")
    async def teapot() -> None:
        raise HTTPException(status_code=418, detail="I refuse to brew coffee.")

    @application.get("/api/v1/_test/known")
    async def known() -> None:
        raise ApiError(
            status_code=409,
            code="pilot_region_locked",
            message="The pilot region cannot be changed while a job is running.",
        )

    @application.get("/api/v1/_test/echo")
    async def echo(count: int) -> dict[str, int]:
        return {"count": count}

    return application


@pytest.fixture
def failing_client(failing_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(failing_app, raise_server_exceptions=False) as test_client:
        yield test_client


class TestStatusToCode:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (404, "not_found"),
            (405, "method_not_allowed"),
            (418, "i'm_a_teapot"),
            (500, "internal_server_error"),
            (503, "service_unavailable"),
        ],
    )
    def test_known_statuses_map_to_slugs(self, status: int, expected: str) -> None:
        assert status_to_code(status) == expected

    def test_unknown_status_falls_back(self) -> None:
        assert status_to_code(799) == "error"


class TestUnhandledExceptions:
    def test_returns_a_generic_500(self, failing_client: TestClient) -> None:
        response = failing_client.get("/api/v1/_test/boom")

        assert response.status_code == 500

        body = ApiErrorResponse.model_validate(response.json())
        assert body.code == "internal_error"
        assert body.details is None

    def test_never_leaks_the_exception_message(self, failing_client: TestClient) -> None:
        raw = failing_client.get("/api/v1/_test/boom").text

        assert "sup3r-s3cret" not in raw
        assert "db.internal" not in raw
        assert "postgresql://" not in raw
        assert "RuntimeError" not in raw
        assert "Traceback" not in raw
        assert "site-packages" not in raw

    def test_carries_a_request_id_for_correlation(self, failing_client: TestClient) -> None:
        # Without this the generic message would be untraceable, which is exactly
        # why the correlation context is unwound *after* the handler runs.
        response = failing_client.get("/api/v1/_test/boom")

        body = ApiErrorResponse.model_validate(response.json())
        assert body.request_id is not None
        assert is_valid_request_id(body.request_id)
        assert response.headers[REQUEST_ID_HEADER] == body.request_id

    def test_preserves_an_inbound_request_id(self, failing_client: TestClient) -> None:
        response = failing_client.get(
            "/api/v1/_test/boom", headers={REQUEST_ID_HEADER: "client-trace-88"}
        )

        assert response.json()["request_id"] == "client-trace-88"


class TestHttpExceptions:
    def test_uses_the_uniform_shape(self, failing_client: TestClient) -> None:
        response = failing_client.get("/api/v1/_test/teapot")

        assert response.status_code == 418

        body = ApiErrorResponse.model_validate(response.json())
        assert body.code == "i'm_a_teapot"
        assert body.message == "I refuse to brew coffee."

    def test_unknown_route_returns_the_uniform_shape(self, failing_client: TestClient) -> None:
        response = failing_client.get("/api/v1/does-not-exist")

        assert response.status_code == 404

        body = ApiErrorResponse.model_validate(response.json())
        assert body.code == "not_found"
        assert body.request_id is not None

    def test_wrong_method_returns_the_uniform_shape(self, failing_client: TestClient) -> None:
        response = failing_client.post("/api/v1/health/live")

        assert response.status_code == 405
        assert ApiErrorResponse.model_validate(response.json()).code == "method_not_allowed"


class TestIntentionalApiErrors:
    def test_status_code_and_slug_are_preserved(self, failing_client: TestClient) -> None:
        response = failing_client.get("/api/v1/_test/known")

        assert response.status_code == 409

        body = ApiErrorResponse.model_validate(response.json())
        assert body.code == "pilot_region_locked"
        assert "pilot region" in body.message


class TestValidationErrors:
    def test_returns_422_with_field_details(self, failing_client: TestClient) -> None:
        response = failing_client.get("/api/v1/_test/echo", params={"count": "not-a-number"})

        assert response.status_code == 422

        body = ApiErrorResponse.model_validate(response.json())
        assert body.code == "validation_error"
        assert body.details is not None
        assert body.details[0].field == "query.count"
        assert body.details[0].message

    def test_does_not_echo_the_rejected_input(self, failing_client: TestClient) -> None:
        # Pydantic's raw error list includes `input` and `ctx`. Echoing them would
        # reflect caller-controlled data straight back out and into any log that
        # captured the response.
        response = failing_client.get(
            "/api/v1/_test/echo", params={"count": "<script>alert(1)</script>"}
        )

        assert "<script>" not in response.text
        assert "ctx" not in response.json()

    def test_missing_required_parameter_is_reported(self, failing_client: TestClient) -> None:
        response = failing_client.get("/api/v1/_test/echo")

        assert response.status_code == 422

        body = ApiErrorResponse.model_validate(response.json())
        assert body.details is not None
        assert body.details[0].field == "query.count"
