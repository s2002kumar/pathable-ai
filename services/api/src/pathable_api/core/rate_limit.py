"""Per-client rate limits on the two endpoints that cost real work.

A route comparison is about 130 ms of CPU on the pilot's host, computed on the
event loop of a single process, so one script sending them as fast as it can
holds routing busy for everybody else (KI-13). Place search is cheaper but is
the other public endpoint that touches the database. Each gets a token bucket
per client: a burst of ``per_minute`` requests, refilled at ``per_minute`` a
minute. Health, readiness and the profile list are never limited — an
orchestrator's probe must not be refused, and they cost nothing.

**Why in-process.** The pilot runs one API process (ADR 0009), so a dictionary
in that process is the exact count, with no extra service to deploy, secure or
back up. With N workers each would keep its own buckets and a client would get
N times the limit; that is the point at which a shared store earns its place,
not before.

**Who the client is.** Behind a reverse proxy the socket peer is the proxy, so
every visitor would share one bucket. ``trusted_proxy_hops`` says how many
proxies the deployment puts in front of the API; with one, the client is the
right-most ``X-Forwarded-For`` entry — the address the proxy itself appended,
which a caller cannot choose. Anything to its left is whatever the caller sent
and is ignored. With zero, the default, the header is ignored entirely and the
socket peer is the client. Setting it above zero is only correct where the API
cannot be reached except through those proxies.

IPv6 clients are counted per /64, because a single subscriber is routinely
given a whole /64 and could otherwise rotate through it.

**Bounded.** At most ``max_clients`` buckets are kept per endpoint, least
recently seen dropped first. A dropped bucket comes back full, which errs
towards letting a request through rather than refusing a legitimate one.
"""

from __future__ import annotations

import ipaddress
import math
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Final

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from pathable_api.core.errors import build_error_response

#: Header a limited response carries, in whole seconds (RFC 9110 §10.2.3).
RETRY_AFTER_HEADER: Final = "Retry-After"

#: Buckets kept per endpoint before the least recently seen is dropped. Each is a
#: few dozen bytes, so this bounds the limiter at well under a few megabytes
#: whatever the traffic looks like.
DEFAULT_MAX_CLIENTS: Final = 10_000

#: IPv6 addresses are grouped by this prefix length.
IPV6_CLIENT_PREFIX: Final = 64


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """One limited endpoint: which requests it covers and how many a minute."""

    name: str
    method: str
    path: str
    per_minute: int
    #: Plural noun for the refusal message: "route requests", "searches".
    noun: str

    def matches(self, method: str, path: str) -> bool:
        return method == self.method and path == self.path


class TokenBucketLimiter:
    """Token buckets keyed by client, with a fixed bound on how many are kept.

    Each bucket holds up to ``capacity`` tokens and gains ``capacity`` per
    minute; a request spends one. The clock is injected so tests can move time
    without sleeping.
    """

    def __init__(
        self,
        *,
        capacity: int,
        per_minute: int,
        max_clients: int = DEFAULT_MAX_CLIENTS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity < 1 or per_minute < 1 or max_clients < 1:
            msg = "capacity, per_minute and max_clients must all be at least 1"
            raise ValueError(msg)
        self._capacity = float(capacity)
        self._per_second = per_minute / 60.0
        self._max_clients = max_clients
        self._clock = clock
        # client -> (tokens, time they were counted)
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._buckets)

    def acquire(self, client: str) -> float | None:
        """Spend one token for ``client``.

        Returns ``None`` when the request may proceed, otherwise the seconds
        until a token will be available.
        """
        now = self._clock()
        tokens, counted_at = self._buckets.pop(client, (self._capacity, now))
        tokens = min(self._capacity, tokens + (now - counted_at) * self._per_second)

        allowed = tokens >= 1.0
        if allowed:
            tokens -= 1.0
        self._buckets[client] = (tokens, now)
        while len(self._buckets) > self._max_clients:
            self._buckets.popitem(last=False)

        if allowed:
            return None
        return (1.0 - tokens) / self._per_second


def client_key(peer: str | None, forwarded_for: str | None, trusted_proxy_hops: int) -> str:
    """The address a request is counted against.

    ``peer`` is the socket peer, ``forwarded_for`` the raw ``X-Forwarded-For``
    header. See the module docstring for why only the right-most
    ``trusted_proxy_hops``-th entry is believed.
    """
    candidate = peer or "unknown"
    if trusted_proxy_hops > 0 and forwarded_for:
        hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
        # Fewer entries than proxies means the request did not come through all
        # of them — a direct call from inside the network, say — so nothing in
        # the header can be trusted and the peer is used instead.
        if len(hops) >= trusted_proxy_hops:
            candidate = hops[-trusted_proxy_hops]
    return _normalise(candidate)


def _normalise(address: str) -> str:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        # Not an address (the test client calls itself "testclient"). Bounded so
        # a hostile header cannot make a key arbitrarily large.
        return address[:64]
    if isinstance(parsed, ipaddress.IPv6Address):
        if parsed.ipv4_mapped is not None:
            return str(parsed.ipv4_mapped)
        return str(ipaddress.ip_network(f"{parsed}/{IPV6_CLIENT_PREFIX}", strict=False))
    return str(parsed)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Refuse a client's request to a limited endpoint once its bucket is empty.

    Runs before the body is read or the route is resolved, so a refusal costs a
    dictionary lookup. The refusal is the API's ordinary error body with code
    ``rate_limited`` and a ``Retry-After`` header. It is registered inside the
    CORS middleware, so a browser on an allowed origin can read the refusal.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        policies: Iterable[RateLimitPolicy],
        trusted_proxy_hops: int = 0,
        max_clients: int = DEFAULT_MAX_CLIENTS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(app)
        self._trusted_proxy_hops = trusted_proxy_hops
        self._limits = [
            (
                policy,
                TokenBucketLimiter(
                    capacity=policy.per_minute,
                    per_minute=policy.per_minute,
                    max_clients=max_clients,
                    clock=clock,
                ),
            )
            for policy in policies
        ]

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        for policy, limiter in self._limits:
            if not policy.matches(request.method, request.url.path):
                continue
            client = client_key(
                request.client.host if request.client else None,
                request.headers.get("x-forwarded-for"),
                self._trusted_proxy_hops,
            )
            retry_after = limiter.acquire(client)
            if retry_after is None:
                break
            seconds = max(1, math.ceil(retry_after))
            response = build_error_response(
                status_code=HTTPStatus.TOO_MANY_REQUESTS,
                code="rate_limited",
                message=(
                    f"Too many {policy.noun} from this connection: at most "
                    f"{policy.per_minute} a minute. Try again in {seconds} "
                    f"second{'' if seconds == 1 else 's'}."
                ),
            )
            response.headers[RETRY_AFTER_HEADER] = str(seconds)
            return response

        return await call_next(request)
