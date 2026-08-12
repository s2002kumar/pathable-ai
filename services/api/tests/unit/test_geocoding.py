"""Geocoding provider behaviour.

Nominatim runs on donated infrastructure and enforces its usage policy by
blocking applications that ignore it. These tests cover the parts of that policy
this code is responsible for — identification, rate limiting, bounding — against
a fake session, so the real service is never touched.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
import requests

from pathable_api.geo.geocoding import (
    MAX_QUERY_LENGTH,
    DisabledGeocoder,
    GeocodingError,
    NominatimGeocoder,
    build_geocoder,
)

WATERLOO_BOUNDS = (-80.59, 43.42, -80.46, 43.52)

SAMPLE = [
    {
        "display_name": "Waterloo Public Square, King Street South, Waterloo, Ontario",
        "lat": "43.4658",
        "lon": "-80.5230",
        "addresstype": "square",
    },
    {
        "display_name": "Waterloo Park, Waterloo, Ontario",
        "lat": "43.4690",
        "lon": "-80.5330",
        "type": "park",
    },
]


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300

    def json(self) -> Any:
        if isinstance(self._payload, str):
            return json.loads(self._payload)
        return self._payload


class FakeSession:
    """Records what was asked of the provider, and answers however a test wants."""

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response = response if response is not None else FakeResponse(SAMPLE)
        self._error = error

    def get(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, **kwargs})
        if self._error is not None:
            raise self._error
        return self._response


def nominatim(session: FakeSession) -> NominatimGeocoder:
    return NominatimGeocoder(
        contact="pathable@example.org",
        user_agent="pathable-api/0.1.0",
        session=session,  # type: ignore[arg-type]
    )


class TestDisabledByDefault:
    def test_the_default_provider_does_not_search(self) -> None:
        provider = build_geocoder("none", contact="", user_agent="pathable-api/0.1.0")

        assert provider.enabled is False
        assert provider.name == "disabled"

    def test_a_blank_provider_name_disables_search(self) -> None:
        assert build_geocoder("", contact="", user_agent="x").enabled is False

    async def test_it_returns_nothing_rather_than_pretending(self) -> None:
        results = await DisabledGeocoder().search("anywhere", bounds=WATERLOO_BOUNDS)
        assert results == []

    def test_an_unknown_provider_is_a_configuration_error(self) -> None:
        # A silent fallback would let a deployment that meant to enable search
        # discover an empty result list in production instead.
        with pytest.raises(GeocodingError, match="Unknown geocoding provider"):
            build_geocoder("googol-maps", contact="a@b.c", user_agent="x")


class TestNominatimPolicy:
    def test_it_refuses_to_start_without_a_contact(self) -> None:
        # Nominatim's policy requires a way to reach whoever is responsible for
        # the traffic. Starting without one means being blocked, not throttled.
        with pytest.raises(GeocodingError, match="contact address"):
            NominatimGeocoder(contact="", user_agent="pathable-api/0.1.0")

    async def test_it_identifies_itself_and_its_contact(self) -> None:
        session = FakeSession()
        await nominatim(session).search("Waterloo Park", bounds=WATERLOO_BOUNDS)

        agent = session.calls[0]["headers"]["User-Agent"]
        assert "pathable-api/0.1.0" in agent
        assert "pathable@example.org" in agent

    async def test_it_bounds_the_search_to_the_region(self) -> None:
        session = FakeSession()
        await nominatim(session).search("King Street", bounds=WATERLOO_BOUNDS)

        params = session.calls[0]["params"]
        assert params["bounded"] == "1"
        assert params["viewbox"] == "-80.59,43.52,-80.46,43.42"

    async def test_it_caps_the_number_of_results_requested(self) -> None:
        session = FakeSession()
        await nominatim(session).search("Waterloo", bounds=WATERLOO_BOUNDS, limit=500)

        assert int(session.calls[0]["params"]["limit"]) <= 5

    async def test_it_waits_between_requests(self) -> None:
        # One request per second, enforced rather than documented.
        session = FakeSession()
        provider = nominatim(session)

        started = asyncio.get_running_loop().time()
        await provider.search("first", bounds=WATERLOO_BOUNDS)
        await provider.search("second", bounds=WATERLOO_BOUNDS)
        elapsed = asyncio.get_running_loop().time() - started

        assert len(session.calls) == 2
        assert elapsed >= 0.9

    async def test_it_sets_a_request_timeout(self) -> None:
        session = FakeSession()
        await nominatim(session).search("Waterloo", bounds=WATERLOO_BOUNDS)

        assert session.calls[0]["timeout"] > 0


class TestNominatimResults:
    async def test_it_parses_matches(self) -> None:
        results = await nominatim(FakeSession()).search("Waterloo", bounds=WATERLOO_BOUNDS)

        assert len(results) == 2
        assert results[0].label.startswith("Waterloo Public Square")
        assert results[0].latitude == pytest.approx(43.4658)
        assert results[0].longitude == pytest.approx(-80.5230)
        assert results[0].category == "square"

    async def test_an_empty_query_is_not_sent_at_all(self) -> None:
        # Politeness *and* correctness: an empty search has no answer worth a
        # request to somebody else's server.
        session = FakeSession()
        assert await nominatim(session).search("   ", bounds=WATERLOO_BOUNDS) == []
        assert session.calls == []

    async def test_an_overlong_query_is_rejected_locally(self) -> None:
        session = FakeSession()
        with pytest.raises(GeocodingError, match="longer than"):
            await nominatim(session).search("x" * (MAX_QUERY_LENGTH + 1), bounds=WATERLOO_BOUNDS)
        assert session.calls == []

    async def test_malformed_entries_are_skipped_rather_than_crashing(self) -> None:
        session = FakeSession(
            FakeResponse(
                [
                    {"display_name": "No coordinates here"},
                    {"lat": "not-a-number", "lon": "-80.5", "display_name": "Bad"},
                    {"lat": "43.47", "lon": "-80.52", "display_name": "Good"},
                ]
            )
        )

        results = await nominatim(session).search("anything", bounds=WATERLOO_BOUNDS)

        assert [result.label for result in results] == ["Good"]

    async def test_an_unexpected_payload_shape_yields_no_matches(self) -> None:
        session = FakeSession(FakeResponse({"error": "unavailable"}))
        assert await nominatim(session).search("x", bounds=WATERLOO_BOUNDS) == []


class TestNominatimFailures:
    async def test_rate_limiting_is_reported_as_such(self) -> None:
        session = FakeSession(FakeResponse([], status_code=429))

        with pytest.raises(GeocodingError, match="rate-limiting"):
            await nominatim(session).search("Waterloo", bounds=WATERLOO_BOUNDS)

    async def test_a_server_error_names_the_status(self) -> None:
        session = FakeSession(FakeResponse([], status_code=503))

        with pytest.raises(GeocodingError, match="503"):
            await nominatim(session).search("Waterloo", bounds=WATERLOO_BOUNDS)

    async def test_a_network_failure_does_not_leak_the_underlying_error(self) -> None:
        session = FakeSession(error=requests.ConnectionError("dns exploded at 10.0.0.1"))

        with pytest.raises(GeocodingError) as failure:
            await nominatim(session).search("Waterloo", bounds=WATERLOO_BOUNDS)

        assert "10.0.0.1" not in str(failure.value)

    async def test_an_unreadable_body_is_reported_clearly(self) -> None:
        session = FakeSession(FakeResponse("not json at all"))

        with pytest.raises(GeocodingError, match="could not be read"):
            await nominatim(session).search("Waterloo", bounds=WATERLOO_BOUNDS)
