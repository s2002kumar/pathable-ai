"""Correlation-id generation, adoption and propagation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pathable_api.core.request_context import (
    REQUEST_ID_HEADER,
    get_request_id,
    is_valid_request_id,
    new_request_id,
    reset_request_id,
    resolve_request_id,
    set_request_id,
)

LIVE_URL = "/api/v1/health/live"


class TestIdValidation:
    @pytest.mark.parametrize(
        "value",
        [
            "9f1c2b7a4e5d4f0aa1b2c3d4e5f60718",
            "trace-1234",
            "a" * 128,
            "abcdefgh",
            "A.b_c-1234",
        ],
    )
    def test_well_formed_ids_are_accepted(self, value: str) -> None:
        assert is_valid_request_id(value) is True

    @pytest.mark.parametrize(
        ("value", "reason"),
        [
            ("short", "below the minimum length"),
            ("a" * 129, "above the maximum length"),
            ("has spaces here", "whitespace"),
            ("drop\ntable", "newline injection into logs"),
            ("<script>alert(1)</script>", "markup"),
            ("id;rm -rf /", "shell metacharacters"),
            ("", "empty"),
        ],
    )
    def test_malformed_ids_are_rejected(self, value: str, reason: str) -> None:
        assert is_valid_request_id(value) is False, reason


class TestResolution:
    def test_generates_an_id_when_none_supplied(self) -> None:
        assert is_valid_request_id(resolve_request_id(None))

    def test_adopts_a_well_formed_inbound_id(self) -> None:
        assert resolve_request_id("upstream-trace-01") == "upstream-trace-01"

    def test_trims_surrounding_whitespace_before_adopting(self) -> None:
        assert resolve_request_id("  upstream-trace-01  ") == "upstream-trace-01"

    def test_replaces_a_malformed_inbound_id_rather_than_failing(self) -> None:
        # A bad correlation header is not the caller's fault to fix mid-request;
        # dropping it silently is better than rejecting an otherwise valid request.
        resolved = resolve_request_id("bad id\nwith newline")

        assert resolved != "bad id\nwith newline"
        assert is_valid_request_id(resolved)

    def test_generated_ids_are_unique(self) -> None:
        assert len({new_request_id() for _ in range(500)}) == 500


class TestContextVar:
    def test_defaults_to_none(self) -> None:
        assert get_request_id() is None

    def test_set_and_reset_round_trip(self) -> None:
        token = set_request_id("trace-abcdef")
        try:
            assert get_request_id() == "trace-abcdef"
        finally:
            reset_request_id(token)

        assert get_request_id() is None


class TestOverHttp:
    def test_response_carries_a_generated_id(self, client: TestClient) -> None:
        value = client.get(LIVE_URL).headers[REQUEST_ID_HEADER]

        assert is_valid_request_id(value)

    def test_valid_inbound_id_is_preserved(self, client: TestClient) -> None:
        response = client.get(LIVE_URL, headers={REQUEST_ID_HEADER: "client-trace-77"})

        assert response.headers[REQUEST_ID_HEADER] == "client-trace-77"

    def test_invalid_inbound_id_is_replaced(self, client: TestClient) -> None:
        response = client.get(LIVE_URL, headers={REQUEST_ID_HEADER: "no"})

        returned = response.headers[REQUEST_ID_HEADER]
        assert returned != "no"
        assert is_valid_request_id(returned)

    def test_each_request_gets_a_distinct_id(self, client: TestClient) -> None:
        first = client.get(LIVE_URL).headers[REQUEST_ID_HEADER]
        second = client.get(LIVE_URL).headers[REQUEST_ID_HEADER]

        assert first != second

    def test_context_does_not_leak_between_requests(self, client: TestClient) -> None:
        client.get(LIVE_URL, headers={REQUEST_ID_HEADER: "client-trace-77"})

        assert get_request_id() is None
