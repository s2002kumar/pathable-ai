"""A miniature Kitchener ArcGIS service, served from memory, so no test touches the network.

It has the real shapes — portal items with the City's licence text, a feature
service, a layer description with template defaults and coded domains (and a
second publication that strips them, as Walkability does), count and id
queries, and feature pages by object id — plus switches for every way a real
read can go wrong: truncated pages, a republish mid-read, transient errors.

The records sit on the central meridian of UTM zone 17N, far from Kitchener,
and every attribute is invented. Each record's purpose is in the table below;
tests assert those purposes, not whatever the code happens to produce.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyproj

from pathable_api.geo.kitchener.arcgis import ArcGISClient, HttpResponse
from pathable_api.geo.kitchener.snapshot import SnapshotPlan, SnapshotResult, take_snapshot
from pathable_api.geo.kitchener.source import (
    ACTIVE_TRANSPORTATION,
    DOCUMENTS,
    NATIVE_WKID,
    WALKABILITY,
    Publication,
)
from pathable_api.geo.regions import RegionDefinition

#: The City's licence text as served in the item's licenseInfo, trimmed to the
#: sentences the audit checks plus some of the surrounding HTML.
LICENCE_HTML = (
    "<p><strong>Using information under this licence means:</strong> You accept the terms "
    "below. The information provider grants you a worldwide, royalty-free, perpetual, "
    "non-exclusive licence to use the information, including for commercial purposes, subject "
    "to the terms below. You are free to Copy, modify, publish, translate, adapt, distribute or "
    "otherwise use the Information in any medium, mode or format for any lawful purpose. No "
    "credit is required where you do any of the above. <em><strong>Contains information "
    "licensed under the Open Government Licence - The Corporation of the City of "
    "Kitchener.</strong></em></p><p><br /><strong>Exemptions:</strong> This licence does not "
    "grant you any right to use: Personal information or records not accessible under the "
    "Municipal Freedom of Information and Protection of Privacy Act</p><p><strong>Versioning:"
    "</strong> This is version 1.0 of the Open Government Licence - The Corporation of the City "
    "of Kitchener. The information provider may make changes.</p>"
)

EDIT_DATE = 1_790_151_405_878  # 2026-09-23T08:16:45.878Z
BULK_DAY = 1_787_573_025_000  # 2026-08-24T12:03:45Z
LATER_DAY = 1_788_998_400_000  # 2026-09-10T00:00:00Z
ORTHO_2012 = 1_336_003_200_000  # 2012-05-03
ORTHO_2019 = 1_556_668_800_000  # 2019-05-01
CREATED = 1_404_136_412_000  # 2014-06-30

X0, Y0 = 500_000.0, 5_000_000.0

#: The coded domains and template defaults the City's layer publishes, for the
#: fields the audit classifies. Values mirror the real layer description.
DOMAINS: dict[str, tuple[Any, list[Any]]] = {
    "STATUS": ("ACTIVE", ["ACTIVE", "PLANNED", "CLOSED", "UNDESIGNATED", "POTENTIAL"]),
    "CATEGORY": (
        "SIDEWALKS AND WALKWAYS",
        ["CYCLING", "SIDEWALKS AND WALKWAYS", "PATHWAYS", "NETWORK LINKS", "MAINTENANCE ACCESS"],
    ),
    "FEATURE_TYPE": (
        "SURFACE",
        [
            "BOARDWALK",
            "BRIDGE",
            "OVERPASS",
            "STAIRS",
            "SURFACE",
            "UNDERPASS",
            "NA (VIRTUAL LINK)",
            "UNKNOWN",
        ],
    ),
    "SURFACE_MATERIAL": (
        "CONCRETE",
        ["ASPHALT", "ASPHALT (PAINTED)", "CONCRETE", "STONEDUST", "UNKNOWN", "NA (VIRTUAL LINK)"],
    ),
    "WIDTH_M": (1.5, [0, 0.5, 1, 1.5, 1.75, 2, 3, 3.5]),
    "GRADE": ("UNKNOWN", ["NONE", "FLAT", "MODERATE", "STEEP", "EXTREME", "UNKNOWN"]),
    "RAILING": ("N", ["Y", "N"]),
    "CURBCUT": ("N", ["Y", "N", "U"]),
    "SURFACE_CONDITION": ("GOOD", ["GOOD", "FAIR", "POOR", "UNUSABLE", "UNKNOWN"]),
    "ROADSEGMENT_SIDE": ("NA", ["LEFT", "RIGHT", "UNKNOWN", "NA"]),
}


def line(x0: float, y0: float, x1: float, y1: float) -> dict[str, Any]:
    return {"paths": [[[X0 + x0, Y0 + y0], [X0 + x1, Y0 + y1]]]}


def _length(geometry: Mapping[str, Any]) -> float:
    (a, b) = geometry["paths"][0]
    return float(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5)


def _at(atid: int, **values: Any) -> dict[str, Any]:
    """An Active_Transportation record: realistic defaults, overridden per case."""
    geometry = values.pop("geometry")
    attributes: dict[str, Any] = {
        "ACTIVETRANSPORTID": atid,
        "STATUS": "ACTIVE",
        "STATUS_DATE": CREATED,
        "CATEGORY": "SIDEWALKS AND WALKWAYS",
        "SUBCATEGORY": "SIDEWALK",
        "FEATURE_TYPE": "SURFACE",
        "SURFACE_MATERIAL": "CONCRETE",
        "WIDTH_M": 1.5,
        "GRADE": "UNKNOWN",
        "RAILING": "N",
        "CURBCUT": "N",
        "STREET": "FIXTURE STREET",
        "ROADSEGMENTID": 70,
        "ROADSEGMENT_SIDE": "LEFT",
        "SOURCE": "ORTHO 2012",
        "SOURCE_DATE": ORTHO_2012,
        "NOTES": "CHECK",
        "INSTALLATION_YEAR": 1997,
        "LAST_INSPECTION_YEAR": "2026",
        "SURFACE_CONDITION": "UNKNOWN",
        "CONDITION_DATE": None,
        "CONDITION_SCORE": None,
        "CREATE_BY": "SOMEONE",
        "CREATE_DATE": CREATED,
        "UPDATE_BY": "GIS_DATA",
        "UPDATE_DATE": BULK_DAY,
        "SIDEWALKER_PROGRAM": "Y",
        "SLOPE_GRADIENT_PERCENT": 1,
        "SLOPE_GRADIENT_CLASS": "Level (0 - 1.5%)",
        "SLOPE_GRADIENT_SOURCE": "FME - FIXTURE/CalculateTrailGradient.fmw",
        "SLOPE_GRADIENT_MAX": 1,
        "SLOPE_GRADIENT_MIN": 0,
        "SLOPE_GRADIENT_AVG": 1,
        "GRADE_CATEGORY_MAX": "<2% Flat",
        "WAYFINDING": "N",
    }
    attributes.update(values)
    attributes["Shape__Length"] = _length(geometry)
    return {"attributes": attributes, "geometry": geometry}


#: (purpose, record). OBJECTIDs are assigned in order, starting at 1.
AT_RECORDS: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "every accessibility field at its template default",
        _at(1001, geometry=line(0, 0, 100, 0), SURFACE_CONDITION="GOOD"),
    ),
    ("a 2 m curb-cut segment", _at(1002, geometry=line(100, 0, 102, 0), CURBCUT="Y")),
    (
        "a painted crosswalk coded 0 m wide",
        _at(
            1003,
            geometry=line(102, 0, 102, 15),
            SUBCATEGORY="CROSSWALK",
            SURFACE_MATERIAL="ASPHALT (PAINTED)",
            WIDTH_M=0,
            SOURCE="ORTHO 2019",
            SOURCE_DATE=ORTHO_2019,
        ),
    ),
    (
        "stairs with a railing, sourced from a plan",
        _at(
            1004,
            geometry=line(0, 50, 8, 50),
            SUBCATEGORY="WALKWAY",
            FEATURE_TYPE="STAIRS",
            RAILING="Y",
            SOURCE="PLAN AND PROFILE",
        ),
    ),
    (
        "a stonedust trail in poor condition from the 2015 inventory, slope fields disagreeing",
        _at(
            1005,
            geometry=line(0, 200, 250, 200),
            CATEGORY="PATHWAYS",
            SUBCATEGORY="MUT",
            SURFACE_MATERIAL="STONEDUST",
            WIDTH_M=3.5,
            SURFACE_CONDITION="POOR",
            SOURCE="2015 TRAIL INVENTORY PROJECT",
            SLOPE_GRADIENT_MAX=12,
            GRADE_CATEGORY_MAX=">5 to <10% Steep",
        ),
    ),
    (
        "null surface and width, unknown curb cut, a personal-observation source, a named updater",
        _at(
            1006,
            geometry=line(0, -50, 60, -50),
            SURFACE_MATERIAL=None,
            WIDTH_M=None,
            CURBCUT="U",
            SURFACE_CONDITION="GOOD",
            SOURCE="PERSONAL OBSERVATION -XY",
            SOURCE_DATE=None,
            UPDATE_BY="JDOE",
            UPDATE_DATE=LATER_DAY,
        ),
    ),
    (
        "a crosswalk carrying the virtual-link code: unresolved, never physical",
        _at(
            1007,
            geometry=line(-5, 0, -5, 15),
            SUBCATEGORY="CROSSWALK",
            FEATURE_TYPE="NA (VIRTUAL LINK)",
            SURFACE_MATERIAL="NA (VIRTUAL LINK)",
            WIDTH_M=0,
        ),
    ),
    (
        "a bicycle lane: physical, not pedestrian",
        _at(
            1008,
            geometry=line(0, 100, 120, 100),
            CATEGORY="CYCLING",
            SUBCATEGORY="BICYCLE LANE",
            SURFACE_MATERIAL="ASPHALT",
            SURFACE_CONDITION="GOOD",
        ),
    ),
    (
        "impossible values: side outside the domain, inspection year 0, slope 131%",
        _at(
            1009,
            geometry=line(0, 300, 40, 300),
            ROADSEGMENT_SIDE="UNDEFINED",
            ROADSEGMENTID=71,
            LAST_INSPECTION_YEAR="0",
            SLOPE_GRADIENT_MAX=131,
            GRADE_CATEGORY_MAX=">=10% Extreme",
        ),
    ),
    (
        "a blank surface, a 2 m width, the other side of road 70, a score without a date",
        _at(
            1010,
            geometry=line(0, 20, 100, 20),
            SURFACE_MATERIAL=" ",
            WIDTH_M=2,
            ROADSEGMENT_SIDE="RIGHT",
            CONDITION_SCORE=1,
            NOTES="DONE",
        ),
    ),
)

_SHARED = ("CATEGORY", "SUBCATEGORY", "FEATURE_TYPE", "SURFACE_MATERIAL", "WIDTH_M", "GRADE",
           "SOURCE", "SOURCE_DATE", "ROADSEGMENTID", "Shape__Length")  # fmt: skip


def _walk(record: Mapping[str, Any]) -> dict[str, Any]:
    attributes = {name: record["attributes"][name] for name in ("ACTIVETRANSPORTID", *_SHARED)}
    return {"attributes": attributes, "geometry": record["geometry"]}


def _link(atid: int, subcategory: str, geometry: dict[str, Any], **values: Any) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "ACTIVETRANSPORTID": atid,
        "ROADSEGMENTID": None,
        "CATEGORY": "NETWORK LINKS",
        "SUBCATEGORY": subcategory,
        "FEATURE_TYPE": "NA (VIRTUAL LINK)",
        "SURFACE_MATERIAL": "NA (VIRTUAL LINK)",
        "WIDTH_M": 0,
        "GRADE": "UNKNOWN",
        "SOURCE": "ORTHO 2019",
        "SOURCE_DATE": ORTHO_2019,
    }
    attributes.update(values)
    attributes["Shape__Length"] = _length(geometry)
    return {"attributes": attributes, "geometry": geometry}


#: Walkability: four records shared with Active_Transportation, and three only here.
WALK_RECORDS: tuple[tuple[str, dict[str, Any]], ...] = (
    *(("shared", _walk(record)) for _p, record in AT_RECORDS if record["attributes"]["ACTIVETRANSPORTID"] in (1001, 1002, 1003, 1005)),
    ("a virtual street crossing", _link(2001, "LINK (PEDESTRIAN)", line(110, 0, 110, 15))),
    ("an unofficial driveway connection coded virtual", _link(2002, "DRIVEWAY CONNECTION", line(120, 0, 120, 10))),
    (
        "a CONCRETE crosswalk filed under NETWORK LINKS: unresolved, and CONCRETE is still the "
        "layer's template default although this publication strips defaults",
        _link(2003, "CROSSWALK", line(130, 0, 130, 15), FEATURE_TYPE="SURFACE", SURFACE_MATERIAL="CONCRETE", WIDTH_M=1.5),
    ),
)  # fmt: skip

WALK_OBJECT_ID_START = 901


def _esri_type(publication: Publication, name: str) -> str:
    return publication.contract.get(name, "esriFieldTypeString")


def layer_description(
    publication: Publication,
    *,
    edit_date: int = EDIT_DATE,
    max_record_count: int = 2000,
    with_domains: bool,
    extra_fields: Sequence[str] = (),
    drop_fields: Sequence[str] = (),
    geometry_type: str = "esriGeometryPolyline",
    wkid: int = NATIVE_WKID,
) -> dict[str, Any]:
    fields = []
    for name in (*publication.contract, *extra_fields):
        if name in drop_fields:
            continue
        item: dict[str, Any] = {"name": name, "type": _esri_type(publication, name), "alias": name}
        if with_domains and name in DOMAINS:
            default, codes = DOMAINS[name]
            item["defaultValue"] = default
            item["domain"] = {
                "type": "codedValue",
                "name": f"Fixture{name}",
                "codedValues": [{"name": str(code), "code": code} for code in codes],
            }
        else:
            item["defaultValue"] = None
            item["domain"] = None
        fields.append(item)
    return {
        "id": publication.layer_id,
        "name": publication.service_name.replace("_", " "),
        "type": "Feature Layer",
        "geometryType": geometry_type,
        "extent": {
            "xmin": X0,
            "ymin": Y0,
            "xmax": X0 + 300,
            "ymax": Y0 + 300,
            "spatialReference": {"wkid": wkid, "latestWkid": wkid},
        },
        "objectIdField": "OBJECTID",
        "globalIdField": "",
        "typeIdField": "CATEGORY",
        "maxRecordCount": max_record_count,
        "maxIdsCount": 1_000_000,
        "hasZ": False,
        "hasM": False,
        "dateFieldsTimeReference": {"timeZone": "UTC"},
        "editingInfo": {
            "lastEditDate": edit_date,
            "schemaLastEditDate": edit_date,
            "dataLastEditDate": edit_date,
        },
        "fields": fields,
        "types": [
            {
                "id": "SIDEWALKS AND WALKWAYS",
                "templates": [
                    {
                        "name": "SIDEWALKS AND WALKWAYS",
                        "prototype": {
                            "attributes": {"SURFACE_MATERIAL": "CONCRETE", "WIDTH_M": 1.5}
                        },
                    }
                ],
            }
        ]
        if with_domains
        else [],
    }


@dataclass
class FakeLayer:
    publication: Publication
    description: dict[str, Any]
    features: list[dict[str, Any]]
    #: Serve at most this many features per page, and say the limit was exceeded.
    truncate_pages_to: int | None = None
    #: Bump the layer's edit date after this many feature pages, on every attempt
    #: up to ``republish_attempts``.
    republish_after_pages: int | None = None
    republish_attempts: int = 0
    #: Report this count instead of the real one.
    count_override: int | None = None
    #: Drop these object ids from pages after the id list has been served.
    deleted_after_listing: set[int] = field(default_factory=set)
    pages_served: int = 0
    republished: int = 0

    def edit_date(self) -> int:
        return int(self.description["editingInfo"]["lastEditDate"])


class FakeArcGIS:
    """Routes ArcGIS REST requests to in-memory layers, items and documents."""

    def __init__(
        self,
        layers: Sequence[FakeLayer],
        *,
        licence_html: str = LICENCE_HTML,
        documents: Mapping[str, tuple[int, bytes, str]] | None = None,
    ) -> None:
        self.layers = {layer.publication.layer_url: layer for layer in layers}
        self.licence_html = licence_html
        self.documents = dict(documents if documents is not None else default_documents())
        #: Responses served before the real one, per (method, url).
        self.failures: dict[tuple[str, str], list[HttpResponse]] = {}
        self.log: list[tuple[str, str, dict[str, str]]] = []

    # Transport -------------------------------------------------------------

    def get(self, url: str, params: Mapping[str, str]) -> HttpResponse:
        return self._serve("GET", url, dict(params))

    def post(self, url: str, data: Mapping[str, str]) -> HttpResponse:
        return self._serve("POST", url, dict(data))

    # Routing ---------------------------------------------------------------

    def _serve(self, method: str, url: str, params: dict[str, str]) -> HttpResponse:
        self.log.append((method, url, params))
        queued = self.failures.get((method, url))
        if queued:
            return queued.pop(0)
        if url in self.documents:
            status, body, content_type = self.documents[url]
            return HttpResponse(status, body, {"Content-Type": content_type})
        for layer in self.layers.values():
            publication = layer.publication
            if url == publication.item_url:
                return _json(self._item(publication))
            if url == publication.service_url:
                return _json(self._service(publication))
            if url == publication.layer_url:
                return _json(layer.description)
            if url == f"{publication.layer_url}/query":
                return _json(self._query(layer, params))
        return HttpResponse(404, b"not found", {})

    def _item(self, publication: Publication) -> dict[str, Any]:
        return {
            "id": publication.item_id,
            "owner": "KitchenerGIS",
            "orgId": "fixture",
            "title": publication.service_name,
            "type": "Feature Service",
            "url": publication.service_url,
            "created": 1_553_884_620_000,
            "modified": 1_790_323_665_000,
            "accessInformation": "Fixture - not the City of Kitchener",
            "snippet": "Fixture",
            "contentStatus": "public_authoritative",
            "licenseInfo": self.licence_html,
            "numViews": 1,
            "size": 1,
        }

    def _service(self, publication: Publication) -> dict[str, Any]:
        return {
            "serviceItemId": publication.item_id,
            "maxRecordCount": 2000,
            "capabilities": "Query,Extract",
            "spatialReference": {"wkid": NATIVE_WKID},
            "layers": [{"id": publication.layer_id, "name": publication.service_name}],
        }

    def _query(self, layer: FakeLayer, params: Mapping[str, str]) -> dict[str, Any]:
        oid = "OBJECTID"
        if params.get("returnCountOnly") == "true":
            count = (
                layer.count_override if layer.count_override is not None else len(layer.features)
            )
            return {"count": count}
        if params.get("returnIdsOnly") == "true":
            return {
                "objectIdFieldName": oid,
                "objectIds": [f["attributes"][oid] for f in layer.features],
            }
        requested = [int(i) for i in params["objectIds"].split(",")]
        wanted = set(requested) - layer.deleted_after_listing
        page = [f for f in layer.features if f["attributes"][oid] in wanted]
        layer.pages_served += 1
        if (
            layer.republish_after_pages is not None
            and layer.pages_served == layer.republish_after_pages
            and layer.republished < layer.republish_attempts
        ):
            layer.republished += 1
            layer.pages_served = 0
            layer.description["editingInfo"]["lastEditDate"] += 1
        document: dict[str, Any] = {"objectIdFieldName": oid, "features": page}
        if layer.truncate_pages_to is not None and len(page) > layer.truncate_pages_to:
            document["features"] = page[: layer.truncate_pages_to]
            document["exceededTransferLimit"] = True
        return document


def _json(document: Mapping[str, Any]) -> HttpResponse:
    return HttpResponse(
        200, json.dumps(document).encode("utf-8"), {"Content-Type": "application/json"}
    )


def error_response(code: int, message: str = "fixture error") -> HttpResponse:
    """ArcGIS's habit: an HTTP 200 whose body is an error."""
    return _json({"error": {"code": code, "message": message}})


def default_documents() -> dict[str, tuple[int, bytes, str]]:
    documents: dict[str, tuple[int, bytes, str]] = {}
    for document in DOCUMENTS:
        if document.key.startswith("metadata_"):
            documents[document.url] = (200, b"%PDF-1.4 fixture\n", "application/pdf")
        elif document.key == "licence_page":
            documents[document.url] = (
                200,
                (
                    b"<html><body><h2>Versioning</h2><p>This is version 1.0 of the Open Government "
                    b"Licence - The Corporation of the City of Kitchener.</p></body></html>"
                ),
                "text/html; charset=utf-8",
            )
        elif document.key == "osm_kitchener_authorization_revision":
            documents[document.url] = (
                200,
                json.dumps(
                    {
                        "query": {
                            "pages": {
                                "1": {
                                    "revisions": [
                                        {"revid": 42, "timestamp": "2024-07-03T04:39:36Z"}
                                    ]
                                }
                            }
                        }
                    }
                ).encode(),
                "application/json; charset=utf-8",
            )
        else:
            documents[document.url] = (
                200,
                b"Fixture permission text.",
                "text/x-wiki; charset=UTF-8",
            )
    return documents


def build_layers(
    *,
    at_records: Sequence[dict[str, Any]] | None = None,
    walk_records: Sequence[dict[str, Any]] | None = None,
    at_object_id_start: int = 1,
    **at_options: Any,
) -> list[FakeLayer]:
    """The two publications, with OBJECTIDs assigned in record order."""

    def numbered(records: Sequence[dict[str, Any]], start: int) -> list[dict[str, Any]]:
        out = []
        for offset, record in enumerate(records):
            copy = json.loads(json.dumps(record))
            copy["attributes"] = {"OBJECTID": start + offset, **copy["attributes"]}
            out.append(copy)
        return out

    description_options = {
        key: at_options.pop(key)
        for key in (
            "max_record_count",
            "extra_fields",
            "drop_fields",
            "geometry_type",
            "wkid",
            "edit_date",
        )
        if key in at_options
    }
    at = FakeLayer(
        ACTIVE_TRANSPORTATION,
        layer_description(
            ACTIVE_TRANSPORTATION,
            with_domains=True,
            # CREATE_BY holds staff user names in the real layer; WAYFINDING is a
            # field the audit does not rely on and must record as an addition.
            **{"extra_fields": ("CREATE_BY", "WAYFINDING"), **description_options},
        ),
        numbered(
            at_records if at_records is not None else [r for _p, r in AT_RECORDS],
            at_object_id_start,
        ),
        **at_options,
    )
    walk = FakeLayer(
        WALKABILITY,
        layer_description(WALKABILITY, with_domains=False),
        numbered(
            walk_records if walk_records is not None else [r for _p, r in WALK_RECORDS],
            WALK_OBJECT_ID_START,
        ),
    )
    return [at, walk]


def snapshot(
    root: Path,
    server: FakeArcGIS | None = None,
    *,
    chunk_size: int = 3,
) -> SnapshotResult:
    """A complete snapshot of the fixture, taken the way the command takes one."""
    client = ArcGISClient(server or FakeArcGIS(build_layers()), sleep=lambda _s: None)
    return take_snapshot(client, root, plan=SnapshotPlan(chunk_size=chunk_size))


def fixture_region() -> RegionDefinition:
    """A study area around the fixture, in longitude/latitude, from its native box."""
    to_lonlat = pyproj.Transformer.from_crs(f"EPSG:{NATIVE_WKID}", "OGC:CRS84", always_xy=True)
    west, south = to_lonlat.transform(X0 - 50, Y0 - 100)
    east, north = to_lonlat.transform(X0 + 400, Y0 + 400)
    return RegionDefinition(
        slug="kitchener-fixture",
        display_name="Kitchener audit fixture (invented data)",
        bounds=(west, south, east, north),
        centre=((west + east) / 2, (south + north) / 2),
        default_zoom=16.0,
        local_projected_crs="EPSG:32617",
        enabled=False,
    )
