"""Turning a place name into coordinates.

A provider abstraction rather than a direct call, for two reasons. Geocoding is
the part of this system most likely to need a different supplier — every option
has different licensing, coverage and cost — and PathAble must be able to run
with no geocoder at all, because the map-click flow does not need one.

The default provider is therefore :class:`DisabledGeocoder`, which returns
nothing and says why. Nominatim is opt-in, and when it is on, its usage policy is
enforced here rather than trusted to callers:

* **One request per second, process-wide.** Enforced by a lock, not a comment.
* **Submit-only.** There is no as-you-type endpoint, because autocomplete against
  Nominatim means one request per keystroke and is explicitly forbidden.
* **Identified.** Every request carries a User-Agent naming the project and a
  contact address, so an operator can reach us instead of blocking us.
* **Bounded.** Searches are restricted to the pilot region's viewbox, which keeps
  results relevant and the query cheap.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from pathable_api.core.logging import get_logger

logger = get_logger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

#: Nominatim's published limit is one request per second per application.
_MIN_REQUEST_INTERVAL_SECONDS = 1.0

#: Long enough for a cold Nominatim query, short enough that a stuck request does
#: not hold a client connection open indefinitely.
_REQUEST_TIMEOUT_SECONDS = 10.0

#: More than this is a list nobody reads, and each extra result costs the
#: provider the same as the first.
MAX_RESULTS = 5

#: Beyond this a query is not a place name.
MAX_QUERY_LENGTH = 160


@dataclass(frozen=True, slots=True)
class GeocodeResult:
    """One candidate location."""

    label: str
    longitude: float
    latitude: float
    #: What the provider called this — a road, a building, a suburb. Untouched,
    #: because normalising it across providers would lose more than it gained.
    category: str | None = None


class GeocodingError(RuntimeError):
    """Raised when a lookup could not be completed."""


class GeocodingProvider(Protocol):
    """What PathAble needs from any geocoder."""

    name: str
    enabled: bool

    async def search(
        self,
        query: str,
        *,
        bounds: tuple[float, float, float, float],
        limit: int = MAX_RESULTS,
    ) -> list[GeocodeResult]:
        """Find candidate locations for a place name inside ``bounds``."""
        ...


class DisabledGeocoder:
    """The default: no geocoding at all.

    Chosen as the default deliberately. Search is a convenience on top of the
    map-click flow, and a deployment should have to opt into calling somebody
    else's donated service rather than doing it by accident.
    """

    name = "disabled"
    enabled = False

    async def search(
        self,
        query: str,
        *,
        bounds: tuple[float, float, float, float],
        limit: int = MAX_RESULTS,
    ) -> list[GeocodeResult]:
        del query, bounds, limit
        return []


class NominatimGeocoder:
    """OpenStreetMap's own geocoder, used within its usage policy.

    Free and requires no account, which is why it is the one provider
    implemented. It is also strictly rate-limited and run on donated
    infrastructure, so the throttle below is not optional politeness — exceeding
    it gets an application blocked.
    """

    name = "nominatim"
    enabled = True

    def __init__(
        self,
        *,
        contact: str,
        user_agent: str,
        url: str = NOMINATIM_URL,
        session: requests.Session | None = None,
    ) -> None:
        if not contact:
            msg = (
                "Nominatim requires a contact address so operators can reach the "
                "application's maintainer. Set GEOCODING_CONTACT."
            )
            raise GeocodingError(msg)

        self._contact = contact
        self._user_agent = user_agent
        self._url = url
        self._session = session or requests.Session()
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def search(
        self,
        query: str,
        *,
        bounds: tuple[float, float, float, float],
        limit: int = MAX_RESULTS,
    ) -> list[GeocodeResult]:
        text = query.strip()
        if not text:
            return []
        if len(text) > MAX_QUERY_LENGTH:
            msg = f"Search text is longer than {MAX_QUERY_LENGTH} characters."
            raise GeocodingError(msg)

        min_lon, min_lat, max_lon, max_lat = bounds
        params = {
            "q": text,
            "format": "jsonv2",
            "limit": str(max(1, min(limit, MAX_RESULTS))),
            # left,top,right,bottom
            "viewbox": f"{min_lon},{max_lat},{max_lon},{min_lat}",
            "bounded": "1",
            "addressdetails": "0",
        }

        async with self._lock:
            await self._wait_for_slot()
            try:
                # `requests` is synchronous; running it on the event loop thread
                # would block every other request for the duration.
                response = await asyncio.to_thread(self._get, params)
            except requests.RequestException as error:
                logger.warning("Geocoding request failed", extra={"provider": self.name})
                msg = "The geocoding service could not be reached."
                raise GeocodingError(msg) from error
            finally:
                self._last_request_at = time.monotonic()

        if response.status_code == 429:
            msg = "The geocoding service is rate-limiting this application. Try again shortly."
            raise GeocodingError(msg)
        if not response.ok:
            msg = f"The geocoding service returned HTTP {response.status_code}."
            raise GeocodingError(msg)

        try:
            payload = response.json()
        except ValueError as error:
            msg = "The geocoding service returned a response that could not be read."
            raise GeocodingError(msg) from error

        return _parse_nominatim(payload)

    def _get(self, params: dict[str, str]) -> requests.Response:
        return self._session.get(
            self._url,
            params=params,
            timeout=_REQUEST_TIMEOUT_SECONDS,
            headers={
                # Nominatim's policy requires an identifying User-Agent with a
                # way to contact whoever is responsible for the traffic.
                "User-Agent": f"{self._user_agent} ({self._contact})",
                "Accept": "application/json",
                "Accept-Language": "en",
            },
        )

    async def _wait_for_slot(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = _MIN_REQUEST_INTERVAL_SECONDS - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)


def _parse_nominatim(payload: Any) -> list[GeocodeResult]:
    if not isinstance(payload, list):
        return []

    results: list[GeocodeResult] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        try:
            longitude = float(entry["lon"])
            latitude = float(entry["lat"])
        except (KeyError, TypeError, ValueError):
            continue

        label = str(entry.get("display_name") or "").strip()
        if not label:
            continue

        category = entry.get("addresstype") or entry.get("type")
        results.append(
            GeocodeResult(
                label=label,
                longitude=longitude,
                latitude=latitude,
                category=str(category) if category else None,
            )
        )
    return results


def build_geocoder(
    provider: str,
    *,
    contact: str,
    user_agent: str,
) -> GeocodingProvider:
    """Construct the configured provider.

    Unknown names are a configuration error rather than a silent fallback: a
    deployment that meant to enable search and typed the name wrong should hear
    about it at startup, not discover an empty result list in production.
    """
    normalised = provider.strip().lower()
    if normalised in {"", "none", "disabled"}:
        return DisabledGeocoder()
    if normalised == "nominatim":
        return NominatimGeocoder(contact=contact, user_agent=user_agent)

    msg = f"Unknown geocoding provider {provider!r}. Supported: none, nominatim."
    raise GeocodingError(msg)
