"""The geocoding endpoint, with no provider configured.

Covers the default deployment: search is off, and the response has to say so
rather than looking like a search that found nothing.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from pathable_api.main import create_app
from tests.conftest import build_settings

SEARCH = "/api/v1/geocode/search"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(build_settings())) as test_client:
        yield test_client


class TestDisabledProvider:
    def test_it_reports_that_nothing_was_searched(self, client: TestClient) -> None:
        response = client.post(SEARCH, json={"region": "waterloo", "query": "Waterloo Park"})

        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is False
        assert body["provider"] == "disabled"
        assert body["matches"] == []

    def test_an_empty_result_is_distinguishable_from_a_disabled_search(
        self, client: TestClient
    ) -> None:
        # "We found nothing" and "we did not look" lead a user to do different
        # things, so the response cannot collapse them into an empty list.
        body = client.post(SEARCH, json={"query": "anything"}).json()
        assert "enabled" in body


class TestValidation:
    def test_an_empty_query_is_rejected(self, client: TestClient) -> None:
        response = client.post(SEARCH, json={"region": "waterloo", "query": ""})
        assert response.status_code == 422

    def test_an_overlong_query_is_rejected(self, client: TestClient) -> None:
        response = client.post(SEARCH, json={"region": "waterloo", "query": "x" * 500})
        assert response.status_code == 422

    def test_a_malformed_region_slug_is_rejected(self, client: TestClient) -> None:
        response = client.post(SEARCH, json={"region": "Waterloo!", "query": "park"})
        assert response.status_code == 422

    def test_an_unknown_region_is_a_404(self, client: TestClient) -> None:
        response = client.post(SEARCH, json={"region": "atlantis", "query": "park"})

        assert response.status_code == 404
        assert response.json()["code"] == "unknown_region"

    def test_an_oversized_limit_is_rejected(self, client: TestClient) -> None:
        response = client.post(SEARCH, json={"query": "park", "limit": 5000})
        assert response.status_code == 422


class TestConfiguration:
    def test_nominatim_requires_a_contact_address(self) -> None:
        # Configuring the provider without one would mean being blocked by
        # Nominatim rather than throttled, so it fails at startup instead.
        with pytest.raises(ValueError, match="GEOCODING_CONTACT"):
            build_settings(geocoding_provider="nominatim")

    def test_nominatim_is_accepted_with_a_contact(self) -> None:
        settings = build_settings(
            geocoding_provider="nominatim", geocoding_contact="pathable@example.org"
        )
        assert settings.geocoding_provider == "nominatim"

    def test_search_is_disabled_by_default(self) -> None:
        assert build_settings().geocoding_provider == "none"
