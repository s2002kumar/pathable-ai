"""Which photographs Esri World Imagery shows over Kitchener, now and in past releases.

OpenStreetMap editors record the imagery layer on screen (``imagery_used``),
and whether "Esri World Imagery" is unrelated to the City's own photography
depends on what Esri served there at the time. Esri publishes that as metadata:
each tile's source, date and resolution, for the current map and for every
archived release since 2014. This reads that metadata at a few points across
the City — never imagery — and records the finest source per release.

It answers one question for the lineage rules: since when the finest Esri
layer over Kitchener has been the City's or the Region's own orthophotos.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pathable_api.geo.kitchener.arcgis import Transport, TransportError
from pathable_api.geo.overture.evidence import content_sha256

IMAGERY_FORMAT_VERSION = 1

ESRI_WORLD_IMAGERY = (
    "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer"
)
ESRI_METADATA = "https://metadata.maptiles.arcgis.com/arcgis/rest/services"
CLARITY_METADATA = "World_Imagery_Clarity_Metadata"
_RELEASE = re.compile(r"^World_Imagery_Metadata_(\d{4})_r(\d+)$")

#: Points across the City, in longitude and latitude.
POINTS: dict[str, tuple[float, float]] = {
    "downtown Kitchener": (-80.4925, 43.4516),
    "south Kitchener (Forest Heights)": (-80.5210, 43.4330),
    "east Kitchener (Victoria Hills)": (-80.5020, 43.4420),
}
#: How Esri credits the City's and the Region's own photography.
_MUNICIPAL = re.compile(r"kitchener|region of waterloo", re.IGNORECASE)

Progress = Callable[[str], None]


class ImageryError(RuntimeError):
    """The metadata could not be read."""


@dataclass(frozen=True, slots=True)
class ImagerySource:
    """One tile source as Esri's metadata describes it."""

    credit: str | None
    source: str | None
    date: str | None
    resolution_m: float | None
    levels: str | None

    @property
    def municipal(self) -> bool:
        return bool(_MUNICIPAL.search(f"{self.credit or ''} {self.source or ''}"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "credit": self.credit,
            "source": self.source,
            "date": self.date,
            "resolution_m": self.resolution_m,
            "levels": self.levels,
            "municipal": self.municipal,
        }


def _date(value: Any) -> str | None:
    text = str(value or "")
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}" if re.fullmatch(r"\d{8}", text) else None


def _resolution(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def finest_source(answer: Mapping[str, Any]) -> ImagerySource | None:
    """The finest-resolution source in an ``identify`` answer; ties keep Esri's order."""
    sources = []
    for result in answer.get("results", []):
        attributes = result.get("attributes") or {}
        if "SRC_DESC" not in attributes and "NICE_DESC" not in attributes:
            continue
        sources.append(
            ImagerySource(
                credit=attributes.get("NICE_DESC"),
                source=attributes.get("SRC_DESC"),
                date=_date(attributes.get("SRC_DATE")),
                resolution_m=_resolution(attributes.get("SRC_RES")),
                levels=f"{attributes.get('MinMapLevel')}-{attributes.get('MaxMapLevel')}",
            )
        )
    if not sources:
        return None
    return min(sources, key=lambda s: s.resolution_m if s.resolution_m is not None else 1e9)


def choose_releases(names: Sequence[str]) -> list[str]:
    """The first and the last archived release of each year, in time order."""
    by_year: dict[int, list[tuple[int, str]]] = {}
    for name in names:
        match = _RELEASE.match(name)
        if match:
            by_year.setdefault(int(match[1]), []).append((int(match[2]), name))
    chosen: list[str] = []
    for year in sorted(by_year):
        releases = sorted(by_year[year])
        chosen.append(releases[0][1])
        if len(releases) > 1:
            chosen.append(releases[-1][1])
    return chosen


def _get(transport: Transport, url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
    try:
        response = transport.get(url, params)
    except TransportError as error:
        msg = f"{url}: {error}"
        raise ImageryError(msg) from error
    if response.status != 200:
        msg = f"{url}: HTTP {response.status}"
        raise ImageryError(msg)
    document = json.loads(response.body)
    if "error" in document:
        msg = f"{url}: {document['error']}"
        raise ImageryError(msg)
    return document  # type: ignore[no-any-return]


def identify(transport: Transport, service: str, lon: float, lat: float) -> ImagerySource | None:
    """The finest source a metadata service records at one point."""
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "sr": "4326",
        "layers": "all",
        "tolerance": "0",
        "mapExtent": f"{lon - 0.01},{lat - 0.01},{lon + 0.01},{lat + 0.01}",
        "imageDisplay": "400,400,96",
        "returnGeometry": "false",
        "f": "json",
    }
    return finest_source(_get(transport, f"{service}/identify", params))


def municipal_imagery(points: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """When the City's or the Region's photography became Esri's finest layer.

    ``earliest_source_date`` is the oldest date Esri gives any such source, a
    conservative bound: the photographs cannot have been served before it.
    """
    releases: dict[str, bool] = {}
    dates: list[str] = []
    for entry in points.values():
        for name, source in entry["releases"].items():
            municipal = bool(source and source["municipal"])
            releases[name] = releases.get(name, False) or municipal
            if municipal and source["date"]:
                dates.append(source["date"])
    ordered = choose_releases(list(releases))
    first = next((i for i, name in enumerate(ordered) if releases[name]), None)
    return {
        "first_release_showing_it": ordered[first] if first is not None else None,
        "last_release_before_it": ordered[first - 1] if first else None,
        "releases_since_without_it": (
            [name for name in ordered[first + 1 :] if not releases[name]]
            if first is not None
            else []
        ),
        "earliest_source_date": min(dates) if dates else None,
    }


def survey_imagery(
    transport: Transport,
    *,
    points: Mapping[str, tuple[float, float]] = POINTS,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Esri's imagery metadata at each point: current, Clarity, and archived releases."""
    catalog = _get(transport, ESRI_METADATA, {"f": "json"})
    releases = choose_releases([service["name"] for service in catalog.get("services", [])])
    if not releases:
        msg = "Esri's metadata catalog lists no archived World Imagery releases."
        raise ImageryError(msg)
    found: dict[str, Any] = {}
    for label, (lon, lat) in points.items():
        if progress:
            progress(f"{label}: current, Clarity and {len(releases)} archived releases")
        current = identify(transport, ESRI_WORLD_IMAGERY, lon, lat)
        clarity = identify(transport, f"{ESRI_METADATA}/{CLARITY_METADATA}/MapServer", lon, lat)
        archived = {
            name: identify(transport, f"{ESRI_METADATA}/{name}/MapServer", lon, lat)
            for name in releases
        }
        found[label] = {
            "lon": lon,
            "lat": lat,
            "current": current.as_dict() if current else None,
            "clarity": clarity.as_dict() if clarity else None,
            "releases": {name: s.as_dict() if s else None for name, s in archived.items()},
        }
    document: dict[str, Any] = {
        "kitchener_geo04_imagery_version": IMAGERY_FORMAT_VERSION,
        "what_this_is": (
            "Esri World Imagery metadata over Kitchener: the finest source Esri records at each "
            "point, now and in the first and last archived release of each year. Metadata only; "
            "no imagery was retrieved. It says which photographs an OpenStreetMap editor showing "
            "'Esri World Imagery' at high zoom was most likely looking at, not which zoom a "
            "mapper used."
        ),
        "services": {"current": ESRI_WORLD_IMAGERY, "archive": ESRI_METADATA},
        "acquired_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "releases_queried": releases,
        "points": found,
        "municipal_imagery": municipal_imagery(found),
    }
    document["content_sha256"] = content_sha256(document)
    return document
