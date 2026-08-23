"""OpenAPI export determinism and completeness.

The drift check in CI compares a freshly generated document against the committed
one. That is only a meaningful signal if generation is byte-stable, so determinism
is asserted here rather than discovered as a flaky CI failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pathable_api.openapi_export import (
    build_openapi_document,
    export_settings,
    main,
    serialise,
    write_openapi,
)


@pytest.fixture(scope="module")
def document() -> dict[str, object]:
    return build_openapi_document()


class TestDeterminism:
    def test_two_generations_are_byte_identical(self) -> None:
        assert serialise(build_openapi_document()) == serialise(build_openapi_document())

    def test_export_settings_ignore_the_ambient_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("APP_VERSION", "99.99.99")
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@elsewhere:5432/other")

        settings = export_settings()

        assert settings.environment == "test"
        assert settings.app_version == "0.1.0"
        assert settings.database_url is None

    def test_serialisation_uses_sorted_keys(self) -> None:
        text = serialise({"b": 1, "a": 2})

        assert text.index('"a"') < text.index('"b"')

    def test_serialisation_ends_with_a_newline(self, document: dict[str, object]) -> None:
        # Keeps the committed file POSIX-clean and diff-friendly.
        assert serialise(document).endswith("\n")

    def test_serialisation_round_trips(self, document: dict[str, object]) -> None:
        assert json.loads(serialise(document)) == document


class TestDocumentContents:
    def test_declares_the_health_paths(self, document: dict[str, object]) -> None:
        paths = document["paths"]
        assert isinstance(paths, dict)

        assert "/api/v1/health/live" in paths
        assert "/api/v1/health/ready" in paths

    def test_operation_ids_are_stable_and_readable(self, document: dict[str, object]) -> None:
        # Generators derive client function names from these; FastAPI's default
        # auto-generated ids include the route path and change on any refactor.
        paths = document["paths"]
        assert isinstance(paths, dict)

        assert paths["/api/v1/health/live"]["get"]["operationId"] == "getLiveness"
        assert paths["/api/v1/health/ready"]["get"]["operationId"] == "getReadiness"

    def test_readiness_documents_its_failure_status(self, document: dict[str, object]) -> None:
        paths = document["paths"]
        assert isinstance(paths, dict)

        responses = paths["/api/v1/health/ready"]["get"]["responses"]
        assert "200" in responses
        assert "503" in responses

    def test_error_envelope_is_part_of_the_contract(self, document: dict[str, object]) -> None:
        components = document["components"]
        assert isinstance(components, dict)

        schemas = components["schemas"]
        assert "ApiErrorResponse" in schemas
        assert "LivenessResponse" in schemas
        assert "ReadinessResponse" in schemas

    def test_states_that_no_machine_learning_is_involved(self, document: dict[str, object]) -> None:
        # The document is what an integrator reads before writing a client. If it
        # is silent about this, "AI" in the product name is the only signal they
        # have, and it points the wrong way.
        info = document["info"]
        assert isinstance(info, dict)

        description = info["description"]
        assert isinstance(description, str)
        assert "no machine learning" in description.lower()
        assert "ml_predictions_used" in description

    def test_states_that_missing_data_is_not_evidence_of_accessibility(
        self, document: dict[str, object]
    ) -> None:
        info = document["info"]
        assert isinstance(info, dict)
        description = info["description"]
        assert isinstance(description, str)

        assert "unknown" in description.lower()

    def test_the_route_response_carries_the_no_predictions_flag(
        self, document: dict[str, object]
    ) -> None:
        components = document["components"]
        assert isinstance(components, dict)

        response = components["schemas"]["RouteCompareResponse"]
        assert "ml_predictions_used" in response["properties"]
        # Typed as a constant false, so a client cannot compile against a true.
        assert response["properties"]["ml_predictions_used"]["const"] is False

    def test_contract_version_matches_the_package(self, document: dict[str, object]) -> None:
        info = document["info"]
        assert isinstance(info, dict)

        assert info["version"] == "0.1.0"


class TestWriting:
    def test_writes_the_document_to_disk(self, tmp_path: Path) -> None:
        destination = tmp_path / "nested" / "openapi.json"

        written = write_openapi(destination)

        assert written == destination
        assert json.loads(destination.read_text(encoding="utf-8"))["openapi"].startswith("3.")

    def test_cli_defaults_to_openapi_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        destination = tmp_path / "contract.json"

        assert main([str(destination)]) == 0
        assert destination.exists()
        assert "OpenAPI written to" in capsys.readouterr().out
