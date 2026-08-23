"""Request-size limiting.

Every endpoint takes a small fixed structure. Without a cap, an unauthenticated
caller can make the server buffer an arbitrarily large body before validation
runs, at almost no cost to themselves.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from pathable_api.core.middleware import MAX_REQUEST_BODY_BYTES


class TestBodySizeLimit:
    def test_an_oversized_body_is_refused(self, client: TestClient) -> None:
        payload = {
            "region": "waterloo",
            "query": "x",
            "padding": "y" * (MAX_REQUEST_BODY_BYTES + 1),
        }

        response = client.post("/api/v1/geocode/search", json=payload)

        assert response.status_code == 413
        assert response.json()["code"] == "request_too_large"

    def test_the_refusal_says_what_the_limit_is(self, client: TestClient) -> None:
        payload = {"padding": "y" * (MAX_REQUEST_BODY_BYTES + 1)}

        response = client.post("/api/v1/geocode/search", json=payload)

        assert "64 KiB" in response.json()["message"]

    def test_an_ordinary_request_is_unaffected(self, client: TestClient) -> None:
        response = client.post("/api/v1/geocode/search", json={"query": "Waterloo Park"})

        assert response.status_code == 200

    def test_the_limit_is_generous_for_a_real_request(self) -> None:
        # A real compare request is a few hundred bytes; the cap is three orders
        # of magnitude above it, so it can only ever catch abuse.
        realistic = json.dumps(
            {
                "region": "waterloo",
                "origin": {"longitude": -80.5449, "latitude": 43.4643},
                "destination": {"longitude": -80.5204, "latitude": 43.4723},
                "profile": "wheelchair",
            }
        )
        assert len(realistic) * 100 < MAX_REQUEST_BODY_BYTES

    def test_a_get_request_is_unaffected(self, client: TestClient) -> None:
        assert client.get("/api/v1/health/live").status_code == 200

    def test_the_refusal_carries_a_request_id(self, client: TestClient) -> None:
        # A refusal the caller cannot quote in a bug report is worse than one
        # they can; correlation therefore runs outside this middleware.
        response = client.post(
            "/api/v1/geocode/search", json={"padding": "y" * (MAX_REQUEST_BODY_BYTES + 1)}
        )

        assert response.status_code == 413
        assert response.json()["request_id"]
