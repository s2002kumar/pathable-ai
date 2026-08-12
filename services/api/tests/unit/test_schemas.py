"""Response model serialisation.

These models are the contract source of truth, so their serialised shape is
asserted explicitly: a silent rename here would silently change the generated
TypeScript.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pathable_api.schemas.errors import ApiErrorResponse, ErrorDetail
from pathable_api.schemas.health import (
    DependencyCheck,
    LivenessResponse,
    ReadinessChecks,
    ReadinessResponse,
)


class TestLivenessResponse:
    def test_serialises_to_the_documented_shape(self) -> None:
        model = LivenessResponse(status="ok", service="pathable-api", version="0.1.0")

        assert model.model_dump(mode="json") == {
            "status": "ok",
            "service": "pathable-api",
            "version": "0.1.0",
        }

    def test_status_is_pinned_to_ok(self) -> None:
        with pytest.raises(ValidationError):
            LivenessResponse.model_validate(
                {"status": "degraded", "service": "pathable-api", "version": "0.1.0"}
            )

    def test_is_immutable(self) -> None:
        model = LivenessResponse(status="ok", service="pathable-api", version="0.1.0")

        with pytest.raises(ValidationError):
            model.service = "other"  # type: ignore[misc]


class TestReadinessResponse:
    @staticmethod
    def build(*, ready: bool = True) -> ReadinessResponse:
        state = "ok" if ready else "unavailable"
        return ReadinessResponse(
            status="ready" if ready else "not_ready",
            service="pathable-api",
            version="0.1.0",
            checks=ReadinessChecks(
                database=DependencyCheck.model_validate(
                    {"status": state, "detail": "connected", "latency_ms": 4.21}
                ),
                postgis=DependencyCheck.model_validate(
                    {"status": state, "detail": "postgis 3.4.2", "latency_ms": 1.08}
                ),
            ),
        )

    def test_nested_serialisation(self) -> None:
        assert self.build().model_dump(mode="json") == {
            "status": "ready",
            "service": "pathable-api",
            "version": "0.1.0",
            "checks": {
                "database": {"status": "ok", "detail": "connected", "latency_ms": 4.21},
                "postgis": {"status": "ok", "detail": "postgis 3.4.2", "latency_ms": 1.08},
            },
        }

    def test_failure_uses_the_identical_key_set(self) -> None:
        assert (
            self.build(ready=True).model_dump().keys()
            == self.build(ready=False).model_dump().keys()
        )

    def test_unknown_dependency_state_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DependencyCheck.model_validate({"status": "degraded", "detail": "x"})

    def test_latency_is_optional(self) -> None:
        check = DependencyCheck.model_validate({"status": "unavailable", "detail": "x"})

        assert check.latency_ms is None
        assert check.model_dump(mode="json")["latency_ms"] is None


class TestApiErrorResponse:
    def test_minimal_error_serialisation(self) -> None:
        model = ApiErrorResponse(code="not_found", message="Nope.")

        assert model.model_dump(mode="json") == {
            "code": "not_found",
            "message": "Nope.",
            "request_id": None,
            "details": None,
        }

    def test_details_serialisation(self) -> None:
        model = ApiErrorResponse(
            code="validation_error",
            message="Bad input.",
            request_id="trace-abcdef",
            details=[ErrorDetail(field="query.zoom", message="too large")],
        )

        dumped = model.model_dump(mode="json")
        assert dumped["details"] == [{"field": "query.zoom", "message": "too large"}]
        assert dumped["request_id"] == "trace-abcdef"

    def test_is_immutable(self) -> None:
        model = ApiErrorResponse(code="not_found", message="Nope.")

        with pytest.raises(ValidationError):
            model.code = "other"  # type: ignore[misc]
