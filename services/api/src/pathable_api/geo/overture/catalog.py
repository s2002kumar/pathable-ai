"""Overture release identity and file discovery, from Overture's own STAC catalog.

Which release, and which schema, is read from ``stac.overturemaps.org`` — the
catalog Overture publishes alongside the data — rather than from a
documentation page. The two have disagreed: on 2026-09-25 the release calendar
listed ``2026-09-23.0`` with schema ``v1.18.0`` while the catalog and the
release notes both said ``2.0.0``. The catalog is the one that ships with the
files, so it is the one trusted, and the requested and observed identities are
both recorded so a disagreement is visible rather than silently resolved.

Releases are public for about 60 days (two monthly releases). Asking for one
that has aged out fails with that explanation instead of quietly using another.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import requests

#: The root of Overture's release catalog.
STAC_ROOT = "https://stac.overturemaps.org/catalog.json"

#: Ask for whatever the catalog currently calls latest. The resolved release is
#: always recorded, so "latest" never survives into a manifest.
LATEST = "latest"

_RELEASE = re.compile(r"\d{4}-\d{2}-\d{2}\.\d+")
_SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_RELEASE_IN_HREF = re.compile(r"/(\d{4}-\d{2}-\d{2}\.\d+)/catalog\.json$")

#: Schema versions this pipeline has actually been run against. Anything else
#: in a supported major version is accepted with a warning; the column contract
#: in :mod:`pathable_api.geo.overture.contract` is what decides compatibility.
TESTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"1.18.0", "2.0.0"})

#: Major versions whose transportation columns match the contract. A new major
#: version is a deliberate code change, not something to discover in a run.
SUPPORTED_SCHEMA_MAJORS: frozenset[int] = frozenset({1, 2})

#: Fetches a URL and returns the decoded JSON object.
JsonFetcher = Callable[[str], dict[str, Any]]


class ReleaseError(RuntimeError):
    """The requested release cannot be used."""


class ReleaseUnavailableError(ReleaseError):
    """The release is not (or is no longer) published."""


class IncompatibleReleaseError(ReleaseError):
    """The release exists but its metadata is not something this code understands."""


class CatalogUnreachableError(ReleaseError):
    """The catalog could not be read. There is deliberately no cached fallback."""


def http_json_fetcher(*, timeout_seconds: float = 30.0) -> JsonFetcher:
    """Fetch catalog documents over HTTPS, failing loudly.

    A run that cannot reach the catalog stops with the reason. Quietly reusing
    an older copy would produce a manifest that names a release it never
    actually checked.
    """
    session = requests.Session()
    session.headers["User-Agent"] = (
        "pathable-overture-intake (+https://github.com/s2002kumar/pathable-ai)"
    )

    def fetch(url: str) -> dict[str, Any]:
        try:
            response = session.get(url, timeout=timeout_seconds)
            response.raise_for_status()
            document = response.json()
        except (requests.RequestException, ValueError) as error:
            msg = f"Could not read {url}: {error}"
            raise CatalogUnreachableError(msg) from error
        if not isinstance(document, dict):
            msg = f"{url} did not return a JSON object."
            raise CatalogUnreachableError(msg)
        return document

    return fetch


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    requested: str
    observed: str
    schema_version: str
    schema_tag: str | None
    catalog_url: str
    #: What the root catalog called latest when this was resolved.
    latest_at_resolution: str | None
    available_releases: tuple[str, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "observed": self.observed,
            "schema_version": self.schema_version,
            "schema_tag": self.schema_tag,
            "catalog_url": self.catalog_url,
            "latest_at_resolution": self.latest_at_resolution,
            "available_releases": list(self.available_releases),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class CatalogItem:
    """One Parquet file of a release, as the catalog describes it."""

    item_id: str
    href: str
    s3_href: str | None
    bbox: tuple[float, float, float, float]
    size_bytes: int | None
    num_rows: int | None

    def intersects(self, bounds: tuple[float, float, float, float]) -> bool:
        min_lon, min_lat, max_lon, max_lat = bounds
        item_min_lon, item_min_lat, item_max_lon, item_max_lat = self.bbox
        return not (
            item_max_lon < min_lon
            or item_min_lon > max_lon
            or item_max_lat < min_lat
            or item_min_lat > max_lat
        )


def resolve_release(
    requested: str, fetch_json: JsonFetcher, *, root_url: str = STAC_ROOT
) -> ReleaseIdentity:
    """Turn a requested release into an observed, validated identity."""
    if requested != LATEST and _RELEASE.fullmatch(requested) is None:
        msg = f"{requested!r} is not an Overture release identifier (e.g. 2026-09-23.0)."
        raise ReleaseError(msg)

    root = fetch_json(root_url)
    available: dict[str, str] = {}
    for link in root.get("links", []):
        if link.get("rel") != "child":
            continue
        href = str(link.get("href", ""))
        match = _RELEASE_IN_HREF.search(href)
        if match is not None:
            available[match.group(1)] = href
    latest = root.get("latest")
    latest_release = str(latest) if isinstance(latest, str) else None

    target = latest_release if requested == LATEST else requested
    if target is None:
        msg = "The Overture catalog does not name a latest release."
        raise IncompatibleReleaseError(msg)
    if target not in available:
        listed = ", ".join(sorted(available)) or "none"
        msg = (
            f"Overture release {target} is not in the catalog. Overture keeps releases "
            f"public for about 60 days; the catalog lists: {listed}."
        )
        raise ReleaseUnavailableError(msg)

    catalog_url = available[target]
    catalog = fetch_json(catalog_url)
    observed = catalog.get("release:version")
    if observed != target:
        msg = f"Catalog {catalog_url} describes release {observed!r}, not {target!r}."
        raise IncompatibleReleaseError(msg)

    schema_version = catalog.get("schema:version")
    if not isinstance(schema_version, str) or _SEMVER.fullmatch(schema_version) is None:
        msg = f"Release {target} has no readable schema version ({schema_version!r})."
        raise IncompatibleReleaseError(msg)
    major = int(schema_version.split(".", 1)[0])
    if major not in SUPPORTED_SCHEMA_MAJORS:
        msg = (
            f"Release {target} uses schema {schema_version}; this pipeline supports major "
            f"versions {sorted(SUPPORTED_SCHEMA_MAJORS)}. Review the schema before widening it."
        )
        raise IncompatibleReleaseError(msg)

    warnings: list[str] = []
    if schema_version not in TESTED_SCHEMA_VERSIONS:
        warnings.append(
            f"Schema {schema_version} has not been run through this pipeline before; "
            "the column contract still applies."
        )

    schema_tag = catalog.get("schema:tag")
    return ReleaseIdentity(
        requested=requested,
        observed=target,
        schema_version=schema_version,
        schema_tag=schema_tag if isinstance(schema_tag, str) else None,
        catalog_url=catalog_url,
        latest_at_resolution=latest_release,
        available_releases=tuple(sorted(available)),
        warnings=tuple(warnings),
    )


def collection_url(release: ReleaseIdentity, theme: str, feature_type: str) -> str:
    """The catalog collection for one theme/type of a release."""
    base = release.catalog_url.rsplit("/", 1)[0]
    return f"{base}/{theme}/{feature_type}/collection.json"


def list_collection_items(
    collection: str, fetch_json: JsonFetcher, *, workers: int = 8
) -> list[CatalogItem]:
    """Every Parquet file in a collection, with the extent the catalog gives it.

    The catalog publishes one item per file with that file's bounding box, which
    is what lets a regional read skip every file that cannot contain the region
    without opening it.
    """
    document = fetch_json(collection)
    hrefs = [str(link["href"]) for link in document.get("links", []) if link.get("rel") == "item"]
    if not hrefs:
        msg = f"Collection {collection} lists no items."
        raise IncompatibleReleaseError(msg)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        items = list(pool.map(fetch_json, hrefs))
    return sorted((_catalog_item(item) for item in items), key=lambda item: item.item_id)


def select_items(
    items: Sequence[CatalogItem], bounds: tuple[float, float, float, float]
) -> list[CatalogItem]:
    return [item for item in items if item.intersects(bounds)]


def _catalog_item(document: dict[str, Any]) -> CatalogItem:
    item_id = str(document.get("id"))
    bbox = document.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        msg = f"Catalog item {item_id} has no usable bbox."
        raise IncompatibleReleaseError(msg)
    assets = document.get("assets", {})
    aws = assets.get("aws")
    if not isinstance(aws, dict) or not aws.get("href"):
        msg = f"Catalog item {item_id} has no AWS asset."
        raise IncompatibleReleaseError(msg)
    alternate = aws.get("alternate", {}).get("s3", {})
    size = aws.get("file:size")
    rows = document.get("properties", {}).get("num_rows")
    return CatalogItem(
        item_id=item_id,
        href=str(aws["href"]),
        s3_href=str(alternate["href"])
        if isinstance(alternate, dict) and "href" in alternate
        else None,
        bbox=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
        size_bytes=int(size) if isinstance(size, int) else None,
        num_rows=int(rows) if isinstance(rows, int) else None,
    )
