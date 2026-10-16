"""Per-client rate limits on route comparison and place search (KI-13).

The limiter is the only thing between one script and every other visitor's
routes, so these tests pin what it counts, who it counts, what a refused
caller receives, and what it must never refuse.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pathable_api.core.rate_limit import (
    DEFAULT_MAX_CLIENTS,
    RateLimitMiddleware,
    TokenBucketLimiter,
    client_key,
)
from pathable_api.main import create_app
from tests.conftest import build_settings, settings_from

COMPARE = "/api/v1/routes/compare"
SEARCH = "/api/v1/geocode/search"
ROUTE_BODY: dict[str, Any] = {
    "region": "waterloo",
    "origin": {"longitude": -80.5420, "latitude": 43.4724},
    "destination": {"longitude": -80.5452, "latitude": 43.4720},
    "profile": "wheelchair",
}
SEARCH_BODY = {"region": "waterloo", "query": "Davis Centre"}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def limited_client(**overrides: Any) -> TestClient:
    return TestClient(create_app(build_settings(**overrides)), raise_server_exceptions=False)


@pytest.fixture
def two_routes_a_minute() -> Iterator[TestClient]:
    with limited_client(rate_limit_routes_per_minute=2, rate_limit_searches_per_minute=2) as client:
        yield client


class TestTokenBucket:
    def test_a_full_bucket_allows_a_burst_then_says_when_the_next_token_arrives(self) -> None:
        limiter = TokenBucketLimiter(capacity=3, per_minute=3, clock=FakeClock())

        assert [limiter.acquire("a") for _ in range(3)] == [None, None, None]
        # Three a minute is one every 20 s, and the bucket is empty.
        assert limiter.acquire("a") == pytest.approx(20.0)

    def test_tokens_return_with_time_and_a_refusal_spends_nothing(self) -> None:
        clock = FakeClock()
        limiter = TokenBucketLimiter(capacity=3, per_minute=3, clock=clock)
        for _ in range(3):
            limiter.acquire("a")
        assert limiter.acquire("a") is not None

        clock.now += 15.0
        # Three-quarters of a token: still refused, and the refusal must not
        # push the wait back — 5 s left, not 20.
        assert limiter.acquire("a") == pytest.approx(5.0)
        clock.now += 5.0
        assert limiter.acquire("a") is None
        assert limiter.acquire("a") is not None

    def test_an_idle_client_never_banks_more_than_one_burst(self) -> None:
        clock = FakeClock()
        limiter = TokenBucketLimiter(capacity=3, per_minute=3, clock=clock)
        limiter.acquire("a")

        clock.now += 3_600.0
        assert [limiter.acquire("a") for _ in range(3)] == [None, None, None]
        assert limiter.acquire("a") is not None

    def test_clients_are_counted_separately(self) -> None:
        limiter = TokenBucketLimiter(capacity=1, per_minute=1, clock=FakeClock())

        assert limiter.acquire("a") is None
        assert limiter.acquire("a") is not None
        assert limiter.acquire("b") is None

    def test_memory_is_bounded_by_dropping_the_least_recently_seen_client(self) -> None:
        limiter = TokenBucketLimiter(capacity=1, per_minute=1, max_clients=2, clock=FakeClock())
        limiter.acquire("a")
        limiter.acquire("b")
        limiter.acquire("a")  # a is now the most recently seen
        limiter.acquire("c")  # evicts b

        assert len(limiter) == 2
        # a, still tracked, stays empty; b comes back with a full bucket — the
        # bound errs towards letting a request through.
        assert limiter.acquire("a") is not None
        assert limiter.acquire("b") is None
        assert len(limiter) == 2

    def test_the_default_bound_is_finite(self) -> None:
        limiter = TokenBucketLimiter(capacity=1, per_minute=1, clock=FakeClock())
        for index in range(DEFAULT_MAX_CLIENTS + 50):
            limiter.acquire(f"client-{index}")
        assert len(limiter) == DEFAULT_MAX_CLIENTS

    @pytest.mark.parametrize(
        ("capacity", "per_minute", "max_clients"), [(0, 1, 1), (1, 0, 1), (1, 1, 0)]
    )
    def test_a_limiter_that_could_never_admit_anyone_is_refused(
        self, capacity: int, per_minute: int, max_clients: int
    ) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            TokenBucketLimiter(capacity=capacity, per_minute=per_minute, max_clients=max_clients)


class TestClientKey:
    def test_without_a_trusted_proxy_the_header_is_ignored(self) -> None:
        assert client_key("198.51.100.7", "203.0.113.9", trusted_proxy_hops=0) == "198.51.100.7"

    def test_behind_one_proxy_only_the_entry_it_appended_is_believed(self) -> None:
        # The caller sent "6.6.6.6" itself; the proxy appended what it saw.
        assert client_key("172.18.0.5", "6.6.6.6, 203.0.113.9", 1) == "203.0.113.9"
        assert client_key("172.18.0.5", "203.0.113.9", 1) == "203.0.113.9"

    def test_a_request_that_skipped_the_proxy_is_counted_by_its_peer(self) -> None:
        assert client_key("172.18.0.3", None, 1) == "172.18.0.3"
        assert client_key("172.18.0.3", " , ", 1) == "172.18.0.3"
        assert client_key("172.18.0.3", "203.0.113.9", 2) == "172.18.0.3"

    def test_two_proxies_take_the_second_entry_from_the_right(self) -> None:
        assert client_key("10.0.0.2", "6.6.6.6, 203.0.113.9, 10.0.0.9", 2) == "203.0.113.9"

    def test_ipv6_clients_share_a_bucket_per_64(self) -> None:
        first = client_key(None, "2001:db8:1:2:aaaa::1", 1)
        second = client_key(None, "2001:db8:1:2:ffff::9", 1)
        other = client_key(None, "2001:db8:1:3::1", 1)

        assert first == second == "2001:db8:1:2::/64"
        assert other != first

    def test_an_ipv4_mapped_address_is_the_ipv4_client(self) -> None:
        assert client_key("::ffff:203.0.113.9", None, 0) == "203.0.113.9"

    def test_a_non_address_is_kept_but_bounded(self) -> None:
        assert client_key("testclient", None, 0) == "testclient"
        assert len(client_key(None, "x" * 500, 1)) == 64
        assert client_key(None, None, 0) == "unknown"


class TestLimitedEndpoints:
    def test_route_requests_beyond_the_limit_get_a_standard_refusal(
        self, two_routes_a_minute: TestClient
    ) -> None:
        allowed = [two_routes_a_minute.post(COMPARE, json=ROUTE_BODY) for _ in range(2)]
        refused = two_routes_a_minute.post(COMPARE, json=ROUTE_BODY)

        assert all(response.status_code != 429 for response in allowed)
        assert refused.status_code == 429
        retry_after = int(refused.headers["Retry-After"])
        assert 1 <= retry_after <= 30
        body = refused.json()
        assert body["code"] == "rate_limited"
        assert "at most 2 a minute" in body["message"]
        assert f"Try again in {retry_after} seconds" in body["message"]
        # The ordinary error envelope, so a report can quote the request id.
        assert body["request_id"] == refused.headers["X-Request-ID"]

    def test_a_refusal_is_decided_before_the_body_is_read(
        self, two_routes_a_minute: TestClient
    ) -> None:
        for _ in range(2):
            two_routes_a_minute.post(COMPARE, json=ROUTE_BODY)

        refused = two_routes_a_minute.post(
            COMPARE, content=b"not json", headers={"Content-Type": "application/json"}
        )
        assert refused.status_code == 429

    def test_search_and_routing_are_limited_separately(
        self, two_routes_a_minute: TestClient
    ) -> None:
        for _ in range(3):
            two_routes_a_minute.post(COMPARE, json=ROUTE_BODY)

        assert two_routes_a_minute.post(SEARCH, json=SEARCH_BODY).status_code == 200
        assert two_routes_a_minute.post(SEARCH, json=SEARCH_BODY).status_code == 200
        assert two_routes_a_minute.post(SEARCH, json=SEARCH_BODY).status_code == 429

    def test_probes_and_the_profile_list_are_never_limited(self) -> None:
        with limited_client(
            rate_limit_routes_per_minute=1, rate_limit_searches_per_minute=1
        ) as client:
            client.post(COMPARE, json=ROUTE_BODY)
            client.post(SEARCH, json=SEARCH_BODY)
            statuses = {
                client.get(path).status_code
                for path in ("/api/v1/health/live", "/api/v1/routes/profiles") * 50
            }
            ready = client.get("/api/v1/health/ready")

        assert statuses == {200}
        assert ready.status_code != 429

    def test_a_refused_browser_request_still_carries_cors_and_can_read_the_wait(self) -> None:
        origin = "http://localhost:3000"
        with limited_client(rate_limit_routes_per_minute=1) as client:
            preflight = client.options(
                COMPARE,
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            # The preflight spent nothing: the one allowed request is still there.
            first = client.post(COMPARE, json=ROUTE_BODY, headers={"Origin": origin})
            refused = client.post(COMPARE, json=ROUTE_BODY, headers={"Origin": origin})

        assert preflight.status_code == 200
        assert first.status_code != 429
        assert refused.status_code == 429
        assert refused.headers["access-control-allow-origin"] == origin
        assert "retry-after" in refused.headers["access-control-expose-headers"].lower()

    def test_behind_a_trusted_proxy_each_visitor_has_their_own_bucket(self) -> None:
        with limited_client(rate_limit_routes_per_minute=1, trusted_proxy_hops=1) as client:
            first = client.post(
                COMPARE, json=ROUTE_BODY, headers={"X-Forwarded-For": "203.0.113.1"}
            )
            second = client.post(
                COMPARE, json=ROUTE_BODY, headers={"X-Forwarded-For": "203.0.113.2"}
            )
            # Same visitor, a different made-up address on the left: still them.
            spoofed = client.post(
                COMPARE, json=ROUTE_BODY, headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.1"}
            )

        assert first.status_code != 429
        assert second.status_code != 429
        assert spoofed.status_code == 429

    def test_without_a_trusted_proxy_a_forged_header_buys_nothing(self) -> None:
        with limited_client(rate_limit_routes_per_minute=1) as client:
            client.post(COMPARE, json=ROUTE_BODY, headers={"X-Forwarded-For": "203.0.113.1"})
            forged = client.post(
                COMPARE, json=ROUTE_BODY, headers={"X-Forwarded-For": "203.0.113.2"}
            )

        assert forged.status_code == 429

    def test_turning_it_off_removes_the_middleware(self) -> None:
        app = create_app(build_settings(rate_limit_enabled=False, rate_limit_routes_per_minute=1))

        installed = {getattr(entry.cls, "__name__", "") for entry in app.user_middleware}
        assert RateLimitMiddleware.__name__ not in installed
        with TestClient(app) as client:
            statuses = {client.post(COMPARE, json=ROUTE_BODY).status_code for _ in range(5)}
        assert 429 not in statuses


@pytest.mark.usefixtures("clean_env")
class TestConfiguration:
    def test_defaults_are_on_and_sized_for_people(self) -> None:
        settings = settings_from({})

        assert settings.rate_limit_enabled is True
        assert settings.rate_limit_routes_per_minute == 30
        assert settings.rate_limit_searches_per_minute == 60
        assert settings.trusted_proxy_hops == 0

    def test_values_come_from_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RATE_LIMIT_ROUTES_PER_MINUTE", "45")
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
        settings = settings_from({})

        assert settings.rate_limit_routes_per_minute == 45
        assert settings.trusted_proxy_hops == 1
        assert settings.rate_limit_enabled is False

    @pytest.mark.parametrize(
        "values",
        [
            {"rate_limit_routes_per_minute": 0},
            {"rate_limit_searches_per_minute": -5},
            {"rate_limit_routes_per_minute": 6001},
            {"trusted_proxy_hops": -1},
            {"trusted_proxy_hops": 4},
        ],
    )
    def test_nonsense_is_refused_at_startup(self, values: dict[str, int]) -> None:
        with pytest.raises(ValidationError):
            settings_from(values)
