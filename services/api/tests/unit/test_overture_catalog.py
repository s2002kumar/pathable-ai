"""Release identity comes from Overture's catalog, and surprises stop the run.

The expensive failure here is silent: a manifest that names a release it did
not actually read, or a schema nobody checked.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests

from pathable_api.geo.overture.catalog import (
    LATEST,
    CatalogItem,
    CatalogUnreachableError,
    IncompatibleReleaseError,
    ReleaseError,
    ReleaseUnavailableError,
    http_json_fetcher,
    resolve_release,
    select_items,
)

ROOT = "https://stac.example/catalog.json"


def catalog(
    *, latest: str = "2026-09-23.0", schema: str = "2.0.0", observed: str | None = None
) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {
        ROOT: {
            "latest": latest,
            "links": [
                {"rel": "root", "href": ROOT},
                {"rel": "child", "href": "https://stac.example/2026-08-19.0/catalog.json"},
                {"rel": "child", "href": "https://stac.example/2026-09-23.0/catalog.json"},
            ],
        },
        "https://stac.example/2026-08-19.0/catalog.json": {
            "release:version": "2026-08-19.0",
            "schema:version": "1.18.0",
        },
        "https://stac.example/2026-09-23.0/catalog.json": {
            "release:version": observed or "2026-09-23.0",
            "schema:version": schema,
            "schema:tag": f"https://github.com/OvertureMaps/schema/releases/tag/v{schema}",
        },
    }
    return documents


def fetcher(documents: dict[str, dict[str, Any]]) -> Any:
    return documents.__getitem__


def test_a_pinned_release_is_resolved_with_its_schema() -> None:
    identity = resolve_release("2026-08-19.0", fetcher(catalog()), root_url=ROOT)

    assert identity.requested == "2026-08-19.0"
    assert identity.observed == "2026-08-19.0"
    assert identity.schema_version == "1.18.0"
    assert identity.available_releases == ("2026-08-19.0", "2026-09-23.0")
    assert identity.warnings == ()


def test_latest_is_resolved_and_both_names_are_kept() -> None:
    identity = resolve_release(LATEST, fetcher(catalog()), root_url=ROOT)

    assert identity.requested == "latest"
    assert identity.observed == "2026-09-23.0"
    assert identity.latest_at_resolution == "2026-09-23.0"


def test_an_aged_out_release_fails_and_says_why() -> None:
    with pytest.raises(ReleaseUnavailableError, match="60 days"):
        resolve_release("2026-07-22.0", fetcher(catalog()), root_url=ROOT)


def test_something_that_is_not_a_release_id_is_refused_before_any_request() -> None:
    def never(_url: str) -> dict[str, Any]:
        raise AssertionError("no request should be made")

    with pytest.raises(ReleaseError, match="not an Overture release"):
        resolve_release("september", never, root_url=ROOT)


def test_a_catalog_that_describes_a_different_release_is_not_trusted() -> None:
    documents = catalog(observed="2026-09-24.0")

    with pytest.raises(IncompatibleReleaseError, match="describes release"):
        resolve_release("2026-09-23.0", fetcher(documents), root_url=ROOT)


def test_an_unsupported_schema_major_version_stops_the_run() -> None:
    with pytest.raises(IncompatibleReleaseError, match=r"schema 3\.0\.0"):
        resolve_release("2026-09-23.0", fetcher(catalog(schema="3.0.0")), root_url=ROOT)


def test_an_untested_minor_version_is_accepted_but_flagged() -> None:
    identity = resolve_release("2026-09-23.0", fetcher(catalog(schema="2.1.0")), root_url=ROOT)

    assert identity.schema_version == "2.1.0"
    assert any("2.1.0" in warning for warning in identity.warnings)


def test_only_files_whose_catalog_box_meets_the_region_are_selected() -> None:
    region = (-80.59, 43.42, -80.46, 43.52)
    items = [
        CatalogItem("00030", "a", None, (-86.54, 42.51, -59.88, 44.25), 1, 1),  # contains it
        CatalogItem("00029", "b", None, (-87.25, 40.70, -75.82, 42.94), 1, 1),  # just south
        CatalogItem("00031", "c", None, (-80.46, 43.52, -70.0, 50.0), 1, 1),  # touches a corner
    ]

    assert [item.item_id for item in select_items(items, region)] == ["00030", "00031"]


class TestLiveFetcher:
    """The real fetcher's failure path, with the network replaced by a raising stub."""

    def test_a_network_failure_becomes_a_named_error_with_the_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(_self: object, url: str, **_kwargs: object) -> None:
            raise requests.ConnectionError("connection refused")

        monkeypatch.setattr(requests.Session, "get", refuse)
        fetch = http_json_fetcher()

        with pytest.raises(CatalogUnreachableError, match=r"catalog\.json.*connection refused"):
            fetch("https://stac.example/catalog.json")

    def test_a_document_that_is_not_a_json_object_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Listing:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> list[str]:
                return ["not", "an", "object"]

        monkeypatch.setattr(requests.Session, "get", lambda *_args, **_kwargs: Listing())

        with pytest.raises(CatalogUnreachableError, match="not return a JSON object"):
            http_json_fetcher()("https://stac.example/catalog.json")
