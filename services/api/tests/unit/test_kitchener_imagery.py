"""Esri imagery metadata: which photographs its finest layer showed, and since when.

Canned answers in Esri's shape; no network.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from pathable_api.geo.kitchener.arcgis import HttpResponse
from pathable_api.geo.kitchener.imagery import (
    ESRI_METADATA,
    ImageryError,
    choose_releases,
    finest_source,
    survey_imagery,
)


def _tile(credit: str, source: str, date: str, resolution: str) -> dict[str, Any]:
    return {
        "layerName": "metadata",
        "attributes": {
            "NICE_DESC": credit,
            "SRC_DESC": source,
            "SRC_DATE": date,
            "SRC_RES": resolution,
            "MinMapLevel": "18",
            "MaxMapLevel": "21",
        },
    }


COMMERCIAL = _tile("DigitalGlobe", "QB02", "20080529", "0.6")
CITY = _tile("Kitchener", "City of Kitchener 2012", "20160223", "0.12")
REGION = _tile("Region of Waterloo", "Waterloo Imagery2022", "20220428", "0.1")
RELEASES = {
    "World_Imagery_Metadata_2015_r01": [COMMERCIAL],
    "World_Imagery_Metadata_2015_r09": [COMMERCIAL],
    "World_Imagery_Metadata_2016_r02": [COMMERCIAL],
    "World_Imagery_Metadata_2016_r22": [COMMERCIAL, CITY],
}


class FakeEsri:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str, params: Mapping[str, str]) -> HttpResponse:
        self.urls.append(url)
        if url == ESRI_METADATA:
            services = [{"name": n, "type": "MapServer"} for n in RELEASES]
            body: dict[str, Any] = {"services": [*services, {"name": "USA_NAIP_Metadata"}]}
        elif "World_Imagery_Metadata_" in url:
            name = url.split("/services/")[1].split("/")[0]
            body = {"results": RELEASES[name]}
        elif "Clarity" in url:
            body = {"results": [CITY]}
        else:
            body = {"results": [{"layerName": "Citations", "attributes": {}}, REGION]}
        return HttpResponse(200, json.dumps(body).encode(), {})

    def post(self, url: str, data: Mapping[str, str]) -> HttpResponse:
        raise AssertionError("metadata is only ever read")


def test_the_finest_source_is_kept_and_a_municipal_credit_recognised() -> None:
    source = finest_source({"results": [COMMERCIAL, REGION]})

    assert source is not None
    assert source.credit == "Region of Waterloo"
    assert source.date == "2022-04-28"
    assert source.municipal is True
    commercial = finest_source({"results": [COMMERCIAL]})
    assert commercial is not None
    assert commercial.municipal is False
    assert finest_source({"results": []}) is None


def test_releases_are_the_first_and_last_of_each_year() -> None:
    names = [
        "World_Imagery_Metadata_2016_r22",
        "World_Imagery_Metadata_2015_r09",
        "World_Imagery_Metadata_2016_r02",
        "World_Imagery_Metadata_2016_r10",
        "World_Imagery_Metadata_2015_r01",
        "World_Imagery_Clarity_Metadata",
    ]

    assert choose_releases(names) == [
        "World_Imagery_Metadata_2015_r01",
        "World_Imagery_Metadata_2015_r09",
        "World_Imagery_Metadata_2016_r02",
        "World_Imagery_Metadata_2016_r22",
    ]


def test_the_survey_dates_when_municipal_photography_became_the_finest_layer() -> None:
    esri = FakeEsri()

    document = survey_imagery(esri, points={"a point": (-80.49, 43.45)})

    assert document["municipal_imagery"] == {
        "first_release_showing_it": "World_Imagery_Metadata_2016_r22",
        "last_release_before_it": "World_Imagery_Metadata_2016_r02",
        "releases_since_without_it": [],
        "earliest_source_date": "2016-02-23",
    }
    point = document["points"]["a point"]
    assert point["current"]["credit"] == "Region of Waterloo"
    assert point["clarity"]["source"] == "City of Kitchener 2012"
    # Metadata only: the catalog and identify answers, never a tile or an export.
    assert all(url == ESRI_METADATA or url.endswith("/identify") for url in esri.urls)


def test_an_error_answer_is_refused() -> None:
    class Refusing(FakeEsri):
        def get(self, url: str, params: Mapping[str, str]) -> HttpResponse:
            return HttpResponse(200, b'{"error": {"code": 404}}', {})

    with pytest.raises(ImageryError, match="404"):
        survey_imagery(Refusing(), points={"a point": (-80.49, 43.45)})
