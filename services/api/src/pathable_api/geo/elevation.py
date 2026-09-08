"""Elevation, and the grade derived from it.

Grade is a first-order accessibility fact — a 10% ramp is the difference between
a route somebody can use and one they cannot — and OpenStreetMap almost never
records it. `incline` is present on a tiny fraction of ways, so without a terrain
model the product is silent about slope across nearly the whole network.

Three rules govern everything here, and they are the reason this is a separate
module rather than a column somebody fills in.

**Derived is not observed.** An `incline` tag is a person's assertion about a
specific path. A grade computed from a terrain model is our inference from data
that knows nothing about the path — it cannot see a ramp, a bridge, or a
staircase cut into a hillside. The two are stored separately and never overwrite
one another; where they disagree, the disagreement is surfaced rather than
resolved.

**Missing is missing.** A sample the provider could not give us leaves elevation
null. Zero-filling would turn "nobody measured this" into "flat", which is the
exact failure this project exists to avoid.

**Provenance travels with the number.** Source, dataset, resolution and
acquisition time are stored per node, because a grade derived from a 30 m model
and one derived from a 1 m LiDAR surface deserve different confidence, and a
user shown "4% climb" has no way to tell them apart otherwise.

Choosing a source
-----------------

Six candidates were tested live against a measured reference point in Waterloo
(43.4668, -80.5164). The question that settled it was not "which is available"
but "is 30 m data good enough to say anything about a sidewalk", and the answer
is no. Grade error was measured against 1 m LiDAR over 400 randomly placed
segments per length:

===================  ==================  ====================
Segment length       30 m bare earth     Copernicus GLO-30
===================  ==================  ====================
20 m                 RMSE 3.01 pp        RMSE 5.91 pp
50 m                 RMSE 1.63 pp        RMSE 4.06 pp
100 m                RMSE 0.75 pp        RMSE 2.23 pp
===================  ==================  ====================

The true median grade in this area is 1.78% over 50 m. **A 30 m global model's
error is larger than the signal it is measuring.** Against the 5% running-slope
threshold that ADA and AODA use, GLO-30 misclassified 14% of 50 m segments,
including 18 genuinely too-steep segments called acceptable — the direction of
error this product must not make.

So the primary source is NRCan's HRDEM: 1 m LiDAR bare-earth, Open Government
Licence - Canada (commercial use and redistribution permitted, attribution
required), no account and no key, published as cloud-optimised GeoTIFFs on
public S3 with byte-range reads. Coverage over the Waterloo pilot bbox measured
100% valid, from a 2025 survey. OpenTopoData is kept as a fallback for areas
HRDEM does not cover, with its resolution stated plainly wherever its numbers
are shown.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import math
import os
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

import requests
from sqlalchemy import select

from pathable_api.core.logging import get_logger
from pathable_api.geo.models import GraphNode

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

#: Bumped when a change here would move a derived grade.
#: 1 — first implementation: endpoint-to-endpoint grade from a sampled DEM.
ELEVATION_POLICY_VERSION = 1

#: Public OpenTopoData. Free, no account, and rate-limited to be polite.
OPENTOPODATA_URL = "https://api.opentopodata.org/v1"

#: One call per second, and at most this many points per call — the published
#: limits for the public instance. Exceeding them gets an application blocked,
#: not throttled, so the limit is enforced by a lock rather than a comment.
_MAX_POINTS_PER_CALL = 100
_MIN_REQUEST_INTERVAL_SECONDS = 1.0
_REQUEST_TIMEOUT_SECONDS = 30.0

#: NRCan's HRDEM mosaic. The tile covering southern Ontario; the whole file is
#: 898 GB and is never downloaded — GDAL range-reads only the blocks it needs.
HRDEM_MOSAIC_URL = (
    "https://canelevation-dem.s3.ca-central-1.amazonaws.com/hrdem-mosaic-1m/8_2-mosaic-1m-dtm.tif"
)

#: Required wherever this data is shown. The en dash is part of the licence's
#: official name, so it is reproduced exactly rather than normalised.
HRDEM_ATTRIBUTION = "Contains information licensed under the Open Government Licence – Canada."  # noqa: RUF001

#: Beyond this, a derived grade is almost certainly a model artefact — a bridge
#: read as a cliff, or a sample that landed on a building. Reported as a
#: diagnostic rather than trusted as a grade.
MAX_PLAUSIBLE_DERIVED_GRADE_PERCENT = 25.0

#: How many cell widths a segment must span before a grade computed across it
#: means anything. Two samples closer together than the model can resolve differ
#: mostly by noise, and the measurements above show that noise exceeding the
#: real signal is the normal case for a coarse model, not the exceptional one.
_MIN_LENGTH_IN_CELLS = 5.0

#: Floor for the above, so a 1 m model does not start reporting grades across
#: segments shorter than a stride.
_ABSOLUTE_MIN_SEGMENT_LENGTH_M = 8.0


def min_segment_length_for_grade(resolution_m: float | None) -> float:
    """Shortest segment this model may be asked about.

    Tied to resolution rather than fixed, because the honest answer differs by
    two orders of magnitude between a 1 m LiDAR surface and a 30 m global model,
    and a single constant would either silence the good source or licence the
    bad one.
    """
    if resolution_m is None:
        return _ABSOLUTE_MIN_SEGMENT_LENGTH_M
    return max(_ABSOLUTE_MIN_SEGMENT_LENGTH_M, resolution_m * _MIN_LENGTH_IN_CELLS)


@dataclass(frozen=True, slots=True)
class ElevationSample:
    """One elevation reading, with enough provenance to judge it."""

    longitude: float
    latitude: float
    #: Metres above the datum, or None when the provider had no value here.
    elevation_m: float | None
    source: str
    dataset: str
    #: Native resolution of the underlying model, in metres. This is the number
    #: that decides whether a derived grade means anything.
    resolution_m: float | None

    @property
    def is_known(self) -> bool:
        return self.elevation_m is not None


class ElevationProvider(Protocol):
    """What PathAble needs from any elevation source."""

    name: str
    dataset: str
    resolution_m: float | None
    enabled: bool
    attribution: str

    async def sample(self, points: Sequence[tuple[float, float]]) -> list[ElevationSample]:
        """Elevation for each ``(longitude, latitude)``, in the same order."""
        ...


class DisabledElevation:
    """No elevation at all.

    The default, and a legitimate deployment: the product works without grade,
    it simply reports grade as unknown wherever OSM is silent — which is honest,
    and better than a number nobody can justify.
    """

    name: str = "disabled"
    dataset: str = "none"
    resolution_m: float | None = None
    enabled: bool = False
    attribution: str = ""

    async def sample(self, points: Sequence[tuple[float, float]]) -> list[ElevationSample]:
        return [
            ElevationSample(longitude, latitude, None, self.name, self.dataset, None)
            for longitude, latitude in points
        ]


class HrdemProvider:
    """NRCan HRDEM, read directly from the published cloud-optimised GeoTIFF.

    The mosaic is 898 GB and is never downloaded. It is a COG on public S3 with
    byte-range support, so GDAL fetches only the 512 px blocks covering the
    points asked for. Opening the file measured 0.22 s and the first sample
    0.28 s from this machine.

    ``GDAL_DISABLE_READDIR_ON_OPEN`` is not optional: without it GDAL lists the
    entire bucket prefix before reading a byte, and the open never returns in
    any reasonable time. That single setting is the difference between this
    source being usable and appearing to hang.
    """

    name: str = "nrcan-hrdem"
    enabled: bool = True
    attribution: str = HRDEM_ATTRIBUTION

    def __init__(
        self,
        *,
        url: str = HRDEM_MOSAIC_URL,
        dataset: str = "hrdem-mosaic-1m-dtm",
        resolution_m: float | None = 1.0,
    ) -> None:
        self.dataset = dataset
        self.resolution_m = resolution_m
        self._url = url
        self._dataset_handle: Any = None

    async def sample(self, points: Sequence[tuple[float, float]]) -> list[ElevationSample]:
        if not points:
            return []
        try:
            values = await asyncio.to_thread(self._sample_sync, list(points))
        except Exception:
            # A terrain model being unreachable is a gap in evidence, not a
            # reason to stop. Every point comes back unknown and stays unknown.
            logger.warning("HRDEM sampling failed", extra={"points": len(points)}, exc_info=True)
            values = [None] * len(points)

        return [
            ElevationSample(
                longitude=longitude,
                latitude=latitude,
                elevation_m=value,
                source=self.name,
                dataset=self.dataset,
                resolution_m=self.resolution_m,
            )
            for (longitude, latitude), value in zip(points, values, strict=True)
        ]

    def _open(self) -> Any:
        """The COG, opened once and kept open.

        Re-opening per batch would throw away GDAL's block cache, which is the
        only thing making six-figure point counts practical: the blocks covering
        a city are fetched once and then answered from memory.
        """
        if self._dataset_handle is None:
            import rasterio

            _configure_gdal()
            self._dataset_handle = rasterio.open(f"/vsicurl/{self._url}")
        return self._dataset_handle

    def close(self) -> None:
        """Release the remote handle. Safe to call more than once."""
        if self._dataset_handle is not None:
            self._dataset_handle.close()
            self._dataset_handle = None

    def _sample_sync(self, points: list[tuple[float, float]]) -> list[float | None]:
        from rasterio.warp import transform

        handle = self._open()
        xs, ys = transform(
            "EPSG:4326",
            handle.crs,
            [point[0] for point in points],
            [point[1] for point in points],
        )
        projected = list(zip(xs, ys, strict=True))

        # Sample in spatial order, then put each answer back where it belongs.
        # Random access over a remote raster re-fetches the same blocks again and
        # again; walking them in order touches each one about once.
        order = sorted(
            range(len(projected)),
            key=lambda index: (projected[index][1], projected[index][0]),
        )
        nodata = handle.nodata

        # Default is None, so anything the model cannot answer stays unknown
        # rather than becoming a number.
        values: list[float | None] = [None] * len(projected)
        for index, row in zip(
            order,
            handle.sample([projected[index] for index in order]),
            strict=True,
        ):
            raw = float(row[0])
            # nodata is the model saying it has no coverage here. Writing it
            # through would put a -32767 m sidewalk in the database and a
            # nonsense grade on every segment touching it.
            if nodata is not None and math.isclose(raw, float(nodata)):
                continue
            if math.isfinite(raw):
                values[index] = raw
        return values


def _configure_gdal() -> None:
    """Settings that make a remote COG read fast instead of pathological."""
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
    os.environ.setdefault("GDAL_HTTP_MULTIPLEX", "YES")
    os.environ.setdefault("VSI_CACHE", "TRUE")
    os.environ.setdefault("GDAL_CACHEMAX", "512")


class OpenTopoDataProvider:
    """Public OpenTopoData — the fallback, for areas HRDEM does not cover.

    Free and needs no account. It is also somebody else's donated server, so the
    throttle below is not optional politeness.

    Its best coverage for Ontario is 30 m class, which the measurements in this
    module's docstring show is too coarse to trust for a single footpath. It is
    kept because partial evidence with its limits stated beats no evidence, and
    :func:`resolution_caveat` makes sure the limitation reaches the user.
    """

    enabled: bool = True
    attribution: str = "Elevation from OpenTopoData (SRTM/ASTER, public domain)."

    def __init__(
        self,
        *,
        dataset: str = "aster30m",
        resolution_m: float | None = 30.0,
        url: str = OPENTOPODATA_URL,
        session: requests.Session | None = None,
        user_agent: str = "PathAble/0.1",
    ) -> None:
        self.name = "opentopodata"
        self.dataset = dataset
        self.resolution_m = resolution_m
        self._url = url.rstrip("/")
        self._session = session or requests.Session()
        self._user_agent = user_agent
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def sample(self, points: Sequence[tuple[float, float]]) -> list[ElevationSample]:
        results: list[ElevationSample] = []
        ordered = list(points)
        for start in range(0, len(ordered), _MAX_POINTS_PER_CALL):
            batch = ordered[start : start + _MAX_POINTS_PER_CALL]
            results.extend(await self._sample_batch(batch))
        return results

    async def _sample_batch(self, batch: list[tuple[float, float]]) -> list[ElevationSample]:
        locations = "|".join(f"{latitude},{longitude}" for longitude, latitude in batch)

        async with self._lock:
            await self._wait_for_slot()
            try:
                response = await asyncio.to_thread(self._get, locations)
            except requests.RequestException:
                logger.warning("Elevation request failed", extra={"provider": self.name})
                return self._unknown(batch)
            finally:
                self._last_request_at = time.monotonic()

        if not response.ok:
            logger.warning(
                "Elevation provider refused",
                extra={"provider": self.name, "status": response.status_code},
            )
            return self._unknown(batch)

        try:
            payload = response.json()
            entries = payload.get("results") or []
        except ValueError:
            return self._unknown(batch)

        samples: list[ElevationSample] = []
        for (longitude, latitude), entry in zip(batch, entries, strict=False):
            raw = entry.get("elevation") if isinstance(entry, dict) else None
            samples.append(
                ElevationSample(
                    longitude=longitude,
                    latitude=latitude,
                    # `null` is the provider saying it has no coverage here.
                    # That is unknown, not sea level.
                    elevation_m=float(raw) if isinstance(raw, int | float) else None,
                    source=self.name,
                    dataset=self.dataset,
                    resolution_m=self.resolution_m,
                )
            )
        # A short response means missing answers, not answers for other points.
        while len(samples) < len(batch):
            longitude, latitude = batch[len(samples)]
            samples.append(
                ElevationSample(
                    longitude, latitude, None, self.name, self.dataset, self.resolution_m
                )
            )
        return samples

    def _get(self, locations: str) -> requests.Response:
        return self._session.get(
            f"{self._url}/{self.dataset}",
            params={"locations": locations},
            timeout=_REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": self._user_agent, "Accept": "application/json"},
        )

    def _unknown(self, batch: list[tuple[float, float]]) -> list[ElevationSample]:
        return [
            ElevationSample(longitude, latitude, None, self.name, self.dataset, self.resolution_m)
            for longitude, latitude in batch
        ]

    async def _wait_for_slot(self) -> None:
        remaining = _MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            await asyncio.sleep(remaining)


@dataclass(frozen=True, slots=True)
class DerivedGrade:
    """A slope computed from two elevations, with its own caveats."""

    grade_percent: float | None
    rise_m: float | None
    run_m: float
    #: True when the segment was too short for the model's resolution to say
    #: anything useful, so no grade was produced.
    too_short: bool = False
    #: True when the raw computation exceeded what a footpath can plausibly be,
    #: which usually means a bridge, a tunnel, or a sample on a rooftop.
    implausible: bool = False


def derive_grade(
    start: ElevationSample | None,
    end: ElevationSample | None,
    length_m: float,
    *,
    min_length_m: float | None = None,
) -> DerivedGrade:
    """Grade along a segment, signed from ``start`` to ``end``.

    Positive is uphill in the direction of travel, matching OSM's own convention
    for `incline`, so the two are directly comparable and reverse traversal flips
    the sign of both in the same way.

    Returns no grade at all rather than a bad one. Two samples closer together
    than the model can resolve can produce a double-digit slope out of nothing,
    and a confident wrong number is worse here than an admitted gap.
    """
    if start is None or end is None or not start.is_known or not end.is_known:
        return DerivedGrade(None, None, length_m)

    threshold = (
        min_segment_length_for_grade(start.resolution_m) if min_length_m is None else min_length_m
    )
    if length_m < threshold:
        return DerivedGrade(None, None, length_m, too_short=True)

    assert start.elevation_m is not None  # noqa: S101 - narrowed by is_known above
    assert end.elevation_m is not None  # noqa: S101
    rise = end.elevation_m - start.elevation_m
    grade = (rise / length_m) * 100.0

    if not math.isfinite(grade):
        return DerivedGrade(None, None, length_m)
    if abs(grade) > MAX_PLAUSIBLE_DERIVED_GRADE_PERCENT:
        # Kept as a diagnostic, not used as a grade.
        return DerivedGrade(None, rise, length_m, implausible=True)

    return DerivedGrade(round(grade, 2), rise, length_m)


def build_provider(
    name: str,
    *,
    dataset: str | None = None,
    resolution_m: float | None = None,
    user_agent: str = "PathAble/0.1",
) -> ElevationProvider:
    """Construct the configured provider.

    An unknown name is a configuration error, not a silent fallback: a
    deployment that meant to enable elevation and typed the name wrong should
    hear about it at startup rather than wonder why every grade is unknown.
    """
    normalised = name.strip().lower()
    if normalised in {"", "none", "disabled"}:
        return DisabledElevation()
    if normalised == "hrdem":
        return HrdemProvider(
            dataset=dataset or "hrdem-mosaic-1m-dtm",
            resolution_m=1.0 if resolution_m is None else resolution_m,
        )
    if normalised == "opentopodata":
        return OpenTopoDataProvider(
            dataset=dataset or "aster30m",
            resolution_m=30.0 if resolution_m is None else resolution_m,
            user_agent=user_agent,
        )

    msg = f"Unknown elevation provider {name!r}. Supported: none, hrdem, opentopodata."
    raise ValueError(msg)


def resolution_caveat(resolution_m: float | None, dataset: str) -> str | None:
    """A plain sentence about what this model can and cannot see.

    Shown to users wherever a derived grade is. A coarse model averages slope
    over a distance longer than most sidewalk segments, so it will miss a short
    steep ramp entirely and can invent one across a retaining wall.
    """
    if resolution_m is None:
        return None
    if resolution_m >= 20.0:
        return (
            f"Gradient is estimated from a {resolution_m:.0f} m elevation model "
            f"({dataset}), which averages slope over a distance longer than many "
            f"footpath segments. It can miss a short steep ramp and can overstate "
            f"slope near walls and bridges. Where OpenStreetMap records an incline, "
            f"that is used instead."
        )
    return (
        f"Gradient is estimated from a {resolution_m:g} m elevation model "
        f"({dataset}) rather than surveyed on the path itself. It describes the "
        f"ground, not the path surface, so it cannot see a ramp or a step."
    )


def acquisition_metadata(
    provider: ElevationProvider, acquired_at: dt.datetime
) -> dict[str, object]:
    """Provenance for a sampling run, stored alongside the numbers it produced."""
    return {
        "provider": provider.name,
        "dataset": provider.dataset,
        "resolution_m": provider.resolution_m,
        "acquired_at": acquired_at.isoformat(),
        "policy_version": ELEVATION_POLICY_VERSION,
        "attribution": provider.attribution,
        "min_segment_length_m": min_segment_length_for_grade(provider.resolution_m),
    }


#: Attribution owed for each elevation source that can appear on a stored node.
#: Keyed by the provider's ``name`` because that is what ``elevation_source``
#: records; a route response looks the dataset's sources up here so the credit
#: travels with every grade it produced. A provider missing from this table is a
#: bug, and a unit test checks every constructible provider is present.
ELEVATION_ATTRIBUTION_BY_SOURCE: Final[dict[str, str]] = {
    "nrcan-hrdem": HRDEM_ATTRIBUTION,
    "opentopodata": OpenTopoDataProvider.attribution,
}


#: Datasets are immutable once active and the routing graph built from one is
#: cached for the life of the process, so the credit owed for its elevation is
#: resolved once per dataset per process and cached alongside. A dataset that
#: gains elevation after the process started needs a restart for its grades to
#: appear at all, and the same restart refreshes this.
_ELEVATION_CREDIT_CACHE: dict[uuid.UUID, str | None] = {}
_ELEVATION_CREDIT_CACHE_LIMIT = 64


def clear_elevation_attribution_cache() -> None:
    _ELEVATION_CREDIT_CACHE.clear()


async def elevation_attribution(session: AsyncSession, dataset_id: uuid.UUID) -> str | None:
    """The credit owed for the elevation behind a dataset's derived grades.

    ``None`` when no node in the dataset carries an elevation, which is the
    honest answer for a dataset that was never sampled. Resolved from the
    distinct ``elevation_source`` values stored on the dataset's nodes — the
    provenance written at sampling time — and cached per process, because
    walking a city's nodes on every route request is not a price a credit line
    should cost.
    """
    if dataset_id in _ELEVATION_CREDIT_CACHE:
        return _ELEVATION_CREDIT_CACHE[dataset_id]

    sources = (
        await session.execute(
            select(GraphNode.elevation_source)
            .where(
                GraphNode.dataset_version_id == dataset_id,
                GraphNode.elevation_source.is_not(None),
            )
            .distinct()
        )
    ).scalars()
    owed: list[str] = []
    for source in sorted(str(value) for value in sources):
        credit = ELEVATION_ATTRIBUTION_BY_SOURCE.get(source)
        if credit is None:
            logger.warning(
                "Elevation source has no registered attribution",
                extra={"elevation_source": source, "dataset_id": str(dataset_id)},
            )
            continue
        owed.append(credit)
    result = " ".join(owed) if owed else None

    if len(_ELEVATION_CREDIT_CACHE) >= _ELEVATION_CREDIT_CACHE_LIMIT:
        _ELEVATION_CREDIT_CACHE.clear()
    _ELEVATION_CREDIT_CACHE[dataset_id] = result
    return result
