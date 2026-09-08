"""Talking to an elevation service, without talking to one.

The HTTP provider is exercised through a stub session. Reaching the real
OpenTopoData from a test suite would make failures depend on somebody else's
donated server and, because it blocks rather than throttles, could get this
application banned by its own CI.

What is tested is the part that decides whether a number is trustworthy: how a
null, a short response, a refusal and an outage are each turned into "unknown"
rather than into a height.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
import requests

from pathable_api.geo.elevation import (
    ELEVATION_ATTRIBUTION_BY_SOURCE,
    HRDEM_ATTRIBUTION,
    HrdemProvider,
    OpenTopoDataProvider,
    build_provider,
)

POINTS = [(-80.5164, 43.4668), (-80.52, 43.47)]


class StubResponse:
    def __init__(self, payload: Any, *, ok: bool = True, status: int = 200) -> None:
        self._payload = payload
        self.ok = ok
        self.status_code = status

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class StubSession:
    """Records what was asked for, and answers with whatever it was given."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, **kwargs})
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def provider(response: Any) -> tuple[OpenTopoDataProvider, StubSession]:
    session = StubSession(response)
    # A structural stand-in for requests.Session: the provider only ever calls
    # `.get`, and a real session here would mean a real request.
    source = OpenTopoDataProvider(
        session=cast("requests.Session", session), dataset="aster30m", resolution_m=30.0
    )
    return source, session


class TestReadingAnAnswer:
    async def test_a_height_comes_back_with_its_provenance(self) -> None:
        source, _ = provider(
            StubResponse({"results": [{"elevation": 323.0}, {"elevation": 324.0}]})
        )

        samples = await source.sample(POINTS)

        assert [entry.elevation_m for entry in samples] == [323.0, 324.0]
        assert samples[0].source == "opentopodata"
        assert samples[0].dataset == "aster30m"
        assert samples[0].resolution_m == 30.0

    async def test_the_order_of_the_answers_matches_the_order_asked(self) -> None:
        # Silently reordering would attach a height to the wrong node, which is
        # worse than having none: the grade would be confidently wrong.
        source, _ = provider(StubResponse({"results": [{"elevation": 1.0}, {"elevation": 2.0}]}))

        samples = await source.sample(POINTS)

        assert (samples[0].longitude, samples[0].latitude) == POINTS[0]
        assert (samples[1].longitude, samples[1].latitude) == POINTS[1]

    async def test_it_asks_the_dataset_it_was_configured_with(self) -> None:
        source, session = provider(StubResponse({"results": [{"elevation": 1.0}] * 2}))

        await source.sample(POINTS)

        assert session.calls[0]["url"].endswith("/aster30m")
        assert "43.4668,-80.5164" in session.calls[0]["params"]["locations"]


class TestWhenThereIsNoAnswer:
    async def test_a_null_elevation_is_unknown_not_sea_level(self) -> None:
        # The provider saying "I have no coverage here" must not become 0 m.
        source, _ = provider(StubResponse({"results": [{"elevation": None}, {"elevation": 5.0}]}))

        samples = await source.sample(POINTS)

        assert samples[0].elevation_m is None
        assert samples[0].is_known is False
        assert samples[1].elevation_m == 5.0

    async def test_a_short_response_leaves_the_rest_unknown(self) -> None:
        # Not "answers for the other points shifted up by one".
        source, _ = provider(StubResponse({"results": [{"elevation": 300.0}]}))

        samples = await source.sample(POINTS)

        assert len(samples) == 2
        assert samples[0].elevation_m == 300.0
        assert samples[1].elevation_m is None

    async def test_a_refusal_yields_unknowns_rather_than_raising(self) -> None:
        # A rate-limit response should cost us the data, not the import.
        source, _ = provider(StubResponse({}, ok=False, status=429))

        samples = await source.sample(POINTS)

        assert all(not entry.is_known for entry in samples)

    async def test_an_unreachable_service_yields_unknowns(self) -> None:
        source, _ = provider(requests.ConnectionError("no route to host"))

        samples = await source.sample(POINTS)

        assert len(samples) == 2
        assert all(entry.elevation_m is None for entry in samples)

    async def test_a_response_that_is_not_json_yields_unknowns(self) -> None:
        source, _ = provider(StubResponse(ValueError("not json")))

        samples = await source.sample(POINTS)

        assert all(not entry.is_known for entry in samples)

    async def test_asking_about_nothing_returns_nothing(self) -> None:
        source, session = provider(StubResponse({"results": []}))

        assert await source.sample([]) == []
        assert session.calls == []


class TestBatching:
    async def test_a_large_request_is_split(self) -> None:
        # The public service caps a call at 100 points and blocks applications
        # that exceed its limits.
        source, session = provider(StubResponse({"results": [{"elevation": 1.0}] * 100}))

        samples = await source.sample([(-80.5, 43.4)] * 250)

        assert len(samples) == 250
        assert len(session.calls) == 3


class TestTheLidarProvider:
    def test_it_reports_the_licence_it_must_be_credited_under(self) -> None:
        source = HrdemProvider()

        assert source.attribution == HRDEM_ATTRIBUTION
        assert "Open Government Licence" in source.attribution

    def test_it_reports_a_metre_of_resolution(self) -> None:
        assert HrdemProvider().resolution_m == 1.0

    def test_closing_it_twice_is_harmless(self) -> None:
        source = HrdemProvider()
        source.close()
        source.close()

    async def test_a_provider_that_cannot_reach_its_raster_returns_unknowns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A terrain model being unreachable is a gap in evidence, not a reason to
        # stop the import. The failure is injected rather than provoked with a
        # bad URL, which would make this test wait on a real DNS lookup.
        source = HrdemProvider()
        monkeypatch.setattr(
            HrdemProvider, "_sample_sync", lambda *_: (_ for _ in ()).throw(OSError("no raster"))
        )

        samples = await source.sample(POINTS)

        assert len(samples) == 2
        assert all(entry.elevation_m is None for entry in samples)

    async def test_it_asks_for_nothing_when_given_nothing(self) -> None:
        assert await HrdemProvider().sample([]) == []


class TestChoosingAProvider:
    @pytest.mark.parametrize("name", ["hrdem", "opentopodata", "none", ""])
    def test_every_supported_name_builds(self, name: str) -> None:
        assert build_provider(name) is not None

    def test_a_dataset_and_resolution_can_be_overridden(self) -> None:
        source = build_provider("opentopodata", dataset="srtm30m", resolution_m=90.0)

        assert source.dataset == "srtm30m"
        assert source.resolution_m == 90.0


class TestAttributionRegistry:
    @pytest.mark.parametrize("name", ["hrdem", "opentopodata"])
    def test_every_constructible_provider_has_a_registered_credit(self, name: str) -> None:
        # A provider that writes grades but has no entry here would produce
        # gradients the API cannot credit. That is a licensing failure, not a
        # cosmetic one, so it is pinned per provider.
        provider = build_provider(name)

        assert ELEVATION_ATTRIBUTION_BY_SOURCE[provider.name] == provider.attribution
        assert provider.attribution

    def test_the_disabled_provider_owes_nothing(self) -> None:
        assert build_provider("none").name not in ELEVATION_ATTRIBUTION_BY_SOURCE
