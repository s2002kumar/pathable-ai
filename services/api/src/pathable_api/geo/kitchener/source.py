"""The exact Kitchener source this audit freezes, and what it must look like.

The City publishes one internal layer, ``GIS_DATA.ACTIVE_TRANSPORTATION``, as
several hosted ArcGIS Online feature services. Two matter here, and neither is
complete on its own (measured 2026-09-26):

- **Active_Transportation** carries all 63 attributes, but only records whose
  ``STATUS`` is ``ACTIVE``, and none of the ``NETWORK LINKS`` category.
- **Walkability** carries the pedestrian network *including* the network links
  (virtual street crossings and unofficial connections), but only 12 fields —
  no ``STATUS``, no ``CURBCUT``, no condition or inspection fields.

Both are frozen together and joined on ``ACTIVETRANSPORTID``, which the City's
field documentation names as the permanent record identity. ``OBJECTID`` is
not: the same documentation says it changes on export or import.

The column contracts below list only the fields this audit reads. Anything else
the service publishes is carried into the snapshot untouched and reported as an
addition, so a new municipal field is recorded rather than refused.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

PORTAL = "https://www.arcgis.com"
ORG_ID = "qAo1OsXi67t7XgmS"
SERVICES_ROOT = f"https://services1.arcgis.com/{ORG_ID}/arcgis/rest/services"

PUBLISHER = "The Corporation of the City of Kitchener"

#: The permanent record identity, per the City's field documentation.
IDENTITY_FIELD = "ACTIVETRANSPORTID"
OBJECT_ID_FIELD = "OBJECTID"

#: The service's own coordinate system: NAD83 / UTM zone 17N.
NATIVE_WKID = 26917

ESRI_OID = "esriFieldTypeOID"
ESRI_INTEGER = "esriFieldTypeInteger"
ESRI_STRING = "esriFieldTypeString"
ESRI_DOUBLE = "esriFieldTypeDouble"
ESRI_DATE = "esriFieldTypeDate"

#: Integer-like types ArcGIS may report for the same column across versions.
COMPATIBLE_TYPES: dict[str, frozenset[str]] = {
    ESRI_OID: frozenset({ESRI_OID}),
    ESRI_INTEGER: frozenset({ESRI_INTEGER, "esriFieldTypeSmallInteger", "esriFieldTypeBigInteger"}),
    ESRI_STRING: frozenset({ESRI_STRING}),
    ESRI_DOUBLE: frozenset({ESRI_DOUBLE, "esriFieldTypeSingle"}),
    ESRI_DATE: frozenset({ESRI_DATE}),
}


@dataclass(frozen=True, slots=True)
class Publication:
    """One hosted feature layer, identified the way ArcGIS identifies it."""

    key: str
    item_id: str
    service_name: str
    layer_id: int
    #: What this publication contributes, in one line, for the manifest.
    role: str
    #: Field name → Esri field type this audit depends on.
    contract: dict[str, str] = field(default_factory=dict)

    @property
    def service_url(self) -> str:
        return f"{SERVICES_ROOT}/{self.service_name}/FeatureServer"

    @property
    def layer_url(self) -> str:
        return f"{self.service_url}/{self.layer_id}"

    @property
    def item_url(self) -> str:
        return f"{PORTAL}/sharing/rest/content/items/{self.item_id}"


ACTIVE_TRANSPORTATION = Publication(
    key="active_transportation",
    item_id="9fcaa379310643d1a72094972ee55833",
    service_name="Active_Transportation",
    layer_id=0,
    role="every published attribute; ACTIVE records only; no NETWORK LINKS category",
    contract={
        "OBJECTID": ESRI_OID,
        "ACTIVETRANSPORTID": ESRI_INTEGER,
        "STATUS": ESRI_STRING,
        "STATUS_DATE": ESRI_DATE,
        "CATEGORY": ESRI_STRING,
        "SUBCATEGORY": ESRI_STRING,
        "FEATURE_TYPE": ESRI_STRING,
        "SURFACE_MATERIAL": ESRI_STRING,
        "WIDTH_M": ESRI_DOUBLE,
        "GRADE": ESRI_STRING,
        "RAILING": ESRI_STRING,
        "CURBCUT": ESRI_STRING,
        "STREET": ESRI_STRING,
        "ROADSEGMENTID": ESRI_INTEGER,
        "ROADSEGMENT_SIDE": ESRI_STRING,
        "SOURCE": ESRI_STRING,
        "SOURCE_DATE": ESRI_DATE,
        "NOTES": ESRI_STRING,
        "INSTALLATION_YEAR": ESRI_INTEGER,
        "LAST_INSPECTION_YEAR": ESRI_STRING,
        "SURFACE_CONDITION": ESRI_STRING,
        "CONDITION_DATE": ESRI_DATE,
        "CONDITION_SCORE": ESRI_INTEGER,
        "CREATE_DATE": ESRI_DATE,
        "UPDATE_BY": ESRI_STRING,
        "UPDATE_DATE": ESRI_DATE,
        "SIDEWALKER_PROGRAM": ESRI_STRING,
        "SLOPE_GRADIENT_PERCENT": ESRI_INTEGER,
        "SLOPE_GRADIENT_CLASS": ESRI_STRING,
        "SLOPE_GRADIENT_SOURCE": ESRI_STRING,
        "SLOPE_GRADIENT_MAX": ESRI_INTEGER,
        "SLOPE_GRADIENT_MIN": ESRI_INTEGER,
        "SLOPE_GRADIENT_AVG": ESRI_INTEGER,
        "GRADE_CATEGORY_MAX": ESRI_STRING,
        "Shape__Length": ESRI_DOUBLE,
    },
)

WALKABILITY = Publication(
    key="walkability",
    item_id="64710818a7e044f4aad99b5d6dff4a3f",
    service_name="Walkability",
    layer_id=0,
    role="pedestrian network including NETWORK LINKS; 12 fields; no STATUS",
    contract={
        "OBJECTID": ESRI_OID,
        "ACTIVETRANSPORTID": ESRI_INTEGER,
        "ROADSEGMENTID": ESRI_INTEGER,
        "CATEGORY": ESRI_STRING,
        "SUBCATEGORY": ESRI_STRING,
        "FEATURE_TYPE": ESRI_STRING,
        "SURFACE_MATERIAL": ESRI_STRING,
        "WIDTH_M": ESRI_DOUBLE,
        "GRADE": ESRI_STRING,
        "SOURCE": ESRI_STRING,
        "SOURCE_DATE": ESRI_DATE,
        "Shape__Length": ESRI_DOUBLE,
    },
)

#: Frozen together, in this order. The first one's attributes win when a field
#: exists in both — and every such field is also compared, so a disagreement is
#: counted rather than silently resolved.
PUBLICATIONS: tuple[Publication, ...] = (ACTIVE_TRANSPORTATION, WALKABILITY)


@dataclass(frozen=True, slots=True)
class Document:
    """A human-readable reference archived alongside the data."""

    key: str
    url: str
    why: str


METADATA_REPORTS = "https://app2.kitchener.ca/appdocs/GISImages/GIS_Web_External/GIS_Metadata_Open_Data/IndividualReports"
OSM_WIKI = "https://wiki.openstreetmap.org/w"
KITCHENER_AUTHORIZATION_PAGE = "Waterloo_region/Kitchener_authorization"

DOCUMENTS: tuple[Document, ...] = (
    Document(
        key="metadata_active_transportation",
        url=f"{METADATA_REPORTS}/Active_Transportation.pdf",
        why="The City's layer metadata: source layer, accuracy, history, maintenance.",
    ),
    Document(
        key="metadata_walkability",
        url=f"{METADATA_REPORTS}/Walkability.pdf",
        why="The City's field documentation, defaults and domains (same source layer).",
    ),
    Document(
        key="licence_page",
        url="https://www.kitchener.ca/council-and-city-administration/data-and-maps/open-data-licence/",
        why="The City's published licence page. The item's own licenceInfo is the text of record.",
    ),
    Document(
        key="osm_kitchener_authorization_revision",
        url=(
            f"{OSM_WIKI}/api.php?action=query&prop=revisions&rvprop=ids%7Ctimestamp"
            f"&format=json&titles={KITCHENER_AUTHORIZATION_PAGE}"
        ),
        why="Which revision of the OpenStreetMap permission record was read.",
    ),
    Document(
        key="osm_kitchener_authorization",
        url=f"{OSM_WIKI}/index.php?title={KITCHENER_AUTHORIZATION_PAGE}&action=raw",
        why=(
            "The City's recorded permission to use its data in OpenStreetMap — the reason "
            "agreement between the two is not independent confirmation."
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class LicenceTerm:
    term: str
    #: A sentence the licence text must contain for the term to hold as recorded.
    phrase: str
    reading: str


LICENCE_NAME = "Open Government Licence - The Corporation of the City of Kitchener"
LICENCE_VERSION = "1.0"

#: What the earlier research concluded, pinned to the sentences that support it.
#: If any sentence is missing from the licence text served with a snapshot, the
#: licence has changed and the snapshot stops for review. This is an engineering
#: reading of the text, not legal advice.
LICENCE_TERMS: tuple[LicenceTerm, ...] = (
    LicenceTerm(
        "commercial_use",
        "worldwide, royalty-free, perpetual, non-exclusive licence to use the information, "
        "including for commercial purposes",
        "permitted",
    ),
    LicenceTerm(
        "copy_modify_adapt_distribute",
        "Copy, modify, publish, translate, adapt, distribute or otherwise use the Information "
        "in any medium, mode or format for any lawful purpose",
        "permitted",
    ),
    LicenceTerm("attribution", "No credit is required", "optional"),
    LicenceTerm(
        "attribution_text",
        "Contains information licensed under the Open Government Licence - The Corporation "
        "of the City of Kitchener",
        "the credit to use when crediting voluntarily",
    ),
    LicenceTerm(
        "personal_information_excluded",
        "This licence does not grant you any right to use: Personal information",
        "personal information is outside the licence",
    ),
    LicenceTerm(
        "version",
        "This is version 1.0 of the Open Government Licence - The Corporation of the City "
        "of Kitchener",
        LICENCE_VERSION,
    ),
)


def licence_plain_text(licence_html: str) -> str:
    """The licence as words: tags removed, entities decoded, whitespace collapsed."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", licence_html))
    return re.sub(r"\s+", " ", text).strip()


def licence_terms_found(licence_html: str) -> dict[str, bool]:
    text = licence_plain_text(licence_html).casefold()
    return {
        term.term: re.sub(r"\s+", " ", term.phrase).casefold() in text for term in LICENCE_TERMS
    }
