"""What each Kitchener field may be used for, decided from the measured profile.

The dispositions are reviewed engineering judgements made on one snapshot. The
numbers they rest on are not typed in here: each entry names a function that
reads them out of the profile document, so the matrix always shows the
figures of the run it is part of. If a later snapshot moves a number, the
figure changes with it and the judgement can be re-examined against it.

No field is approved for routing by this matrix. The strongest disposition,
"eligible for normalized evidence", means a later card may translate the value
into PathAble's vocabulary as a source claim, kept apart from OpenStreetMap
facts — not that any route may use it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Disposition(StrEnum):
    IDENTITY_PROVENANCE = "identity/provenance"
    RAW_EVIDENCE = "eligible as raw evidence"
    NORMALIZED_EVIDENCE = "eligible for normalized evidence"
    MATCHING_INPUT = "matching/conflation input only"
    COMPARISON_ONLY = "comparison only"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"


Document = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Adoption:
    subject: str
    fields: tuple[str, ...]
    disposition: Disposition
    #: Which values the disposition covers, when it is narrower than the field.
    scope: str
    rationale: str
    basis: Callable[[Document], dict[str, Any]]


def _field(d: Document, name: str) -> Mapping[str, Any]:
    field: Mapping[str, Any] = d["fields"][name]
    return field


def _states(d: Document, name: str) -> Mapping[str, int]:
    states: Mapping[str, int] = _field(d, name)["states"]
    return states


def _geo(d: Document) -> Mapping[str, Any]:
    geography: Mapping[str, Any] = d["geography"]
    return geography


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _identity(d: Document) -> dict[str, Any]:
    identity = d["overall"]["identity"]
    return {
        "records": d["overall"]["records"],
        "null_identity": identity["null_identity"],
        "duplicate_identity_records": identity["duplicate_identity_records"],
        "joined_across_publications": d["overall"]["publications"].get("both", 0),
        "fields_differing_between_publications": d["normalized"]["joins"][
            "fields_differing_between_publications"
        ],
    }


def _object_id(d: Document) -> dict[str, Any]:
    return {
        "objectid_differs_between_publications": d["overall"]["identity"][
            "objectid_differs_between_publications"
        ],
        "records_in_both_publications": d["overall"]["publications"].get("both", 0),
    }


def _source(d: Document) -> dict[str, Any]:
    provenance = d["provenance"]
    source_date = _states(d, "SOURCE_DATE")
    return {
        "source_classes": provenance["source_classes"],
        "source_date_populated": source_date["non_default"],
        "source_date_null": source_date["null"],
        "orthoimagery_year_vs_source_date": provenance["orthoimagery_year_vs_source_date"],
    }


def _record_dates(d: Document) -> dict[str, Any]:
    return {
        name: {"populated": _states(d, name)["non_default"], "null": _states(d, name)["null"]}
        for name in ("CREATE_DATE", "STATUS_DATE")
    }


def _update_date(d: Document) -> dict[str, Any]:
    update: dict[str, Any] = dict(d["provenance"]["update_date"])
    return update


def _status(d: Document) -> dict[str, Any]:
    return {
        "lifecycle": d["overall"]["lifecycle"],
        "lifecycle_by_publication": d["physical_virtual"]["lifecycle_by_publication"],
    }


def _classification(d: Document) -> dict[str, Any]:
    return {
        "network_role": d["overall"]["network_role"],
        "unresolved_or_noted": d["physical_virtual"]["unresolved_or_noted"],
    }


def _structures(d: Document) -> dict[str, Any]:
    states = _states(d, "FEATURE_TYPE")
    return {
        "structures": d["overall"]["structure"],
        "structures_in_study_area": _geo(d)["intersecting_by_structure"],
        "template_default_SURFACE": states["template_default"],
        "non_default": states["non_default"],
        "not_applicable_virtual": states["not_applicable"],
        "railing_on_stairs": d["defaults"]["railing"]["stairs"],
    }


def _geometry(d: Document) -> dict[str, Any]:
    geography = _geo(d)
    return {
        "geometry_issues": d["overall"]["geometry"]["issues"],
        "documented_feature_accuracy": "+/- 0.5 m (City layer metadata)",
        "crs_transformation": d["normalized"]["crs"]["transformation"],
        "crs_transformation_accuracy_m": d["normalized"]["crs"]["transformation_accuracy_m"],
        "offset_of_pedestrian_records_from_osm_pedestrian_ways": geography[
            "offset_of_pedestrian_records_from_osm_pedestrian_ways"
        ],
    }


def _width(d: Document) -> dict[str, Any]:
    width = d["defaults"]["width_m"]
    sidewalk = width["by_subcategory_at_1_5"].get("SIDEWALK", {})
    return {
        "equal_to_template_default_1_5": width["equal_to_template_default_1_5"],
        "equal_to_documented_default_1_8": width["equal_to_documented_default_1_8"],
        "sidewalks_at_1_5": sidewalk,
        "zero": width["zero"],
        "zero_by_subcategory": width["zero_by_subcategory"],
        "non_default_non_zero": width["non_default_non_zero"],
        "domain_size": _field(d, "WIDTH_M")["domain_size"],
    }


def _surface(d: Document) -> dict[str, Any]:
    surface = d["defaults"]["surface_material"]
    return {
        "concrete": surface["concrete"],
        "sidewalks_concrete": surface["by_subcategory_concrete"].get("SIDEWALK", {}),
        "non_concrete_distribution": surface["non_concrete_distribution"],
        "evidence_for_non_default": surface["evidence_for_non_default"],
    }


def _condition(d: Document) -> dict[str, Any]:
    condition = d["defaults"]["surface_condition"]
    return {
        "distribution": condition["distribution"],
        "good": condition["good"],
        "fair_poor_unusable": condition["fair_poor_unusable"],
    }


def _curbcut(d: Document) -> dict[str, Any]:
    curbcut = d["defaults"]["curbcut"]
    geography = _geo(d)
    return {
        "distribution": curbcut["distribution"],
        "segment_length_m": curbcut["segment_length_m"],
        "y_in_study_area": geography["intersecting_curbcut_y"],
        "offset_of_y_records_from_osm_pedestrian_ways": geography["offset_of_curbcut_y_records"],
        "osm_crossing_edges_along_inventory": geography["graph_along_inventory"][
            "osm_baseline_on_those_edges"
        ],
    }


def _railing(d: Document) -> dict[str, Any]:
    railing: dict[str, Any] = dict(d["defaults"]["railing"])
    return railing


def _grade(d: Document) -> dict[str, Any]:
    grade: Mapping[str, int] = d["derived_slope_consistency"]["grade"]
    total = sum(grade.values())
    return {"distribution": dict(grade), "unknown_share": _share(grade.get("UNKNOWN", 0), total)}


def _slope(d: Document) -> dict[str, Any]:
    slope = d["derived_slope_consistency"]
    return {
        "slope_gradient_source": slope["slope_gradient_source"],
        "slope_gradient_class": slope["slope_gradient_class"],
        "over_100_percent": d["plausibility"]["slope_max_over_100_percent"]["records"],
    }


def _grade_category(d: Document) -> dict[str, Any]:
    slope = d["derived_slope_consistency"]
    compared = slope["records_with_slope_max_and_grade_category"]
    agree = slope["grade_category_agrees_with_slope_max"]
    return {
        "compared": compared,
        "agrees_with_slope_max": agree,
        "agreement_share": _share(agree, compared),
        "string_None": slope["grade_category_is_the_string_None"],
    }


def _condition_score(d: Document) -> dict[str, Any]:
    plausibility = d["plausibility"]
    return {
        "values": plausibility["condition_score_values"],
        "score_without_date": plausibility["condition_score_without_condition_date"]["records"],
        "date_without_score": plausibility["condition_date_without_condition_score"]["records"],
        "condition_date_years": _field(d, "CONDITION_DATE")["years"],
    }


def _inspection(d: Document) -> dict[str, Any]:
    return {
        "last_inspection_year": d["provenance"]["last_inspection_year"],
        "implausible": d["plausibility"]["last_inspection_year_not_a_plausible_year"]["records"],
    }


def _installation(d: Document) -> dict[str, Any]:
    return {
        "modal": d["provenance"]["installation_year_modal"],
        "implausible": d["plausibility"]["installation_year_outside_1900_to_retrieval"]["records"],
    }


def _virtual(d: Document) -> dict[str, Any]:
    return {
        "records": d["overall"]["physical_class"].get("virtual_link", 0),
        "in_study_area": _geo(d)["intersecting_by_physical_class"].get("virtual_link", 0),
        "published_only_in_walkability": d["overall"]["publications"].get("walkability_only", 0),
    }


def _connections(d: Document) -> dict[str, Any]:
    return {
        "records": d["overall"]["physical_class"].get("unofficial_connection", 0),
        "in_study_area": _geo(d)["intersecting_by_physical_class"].get("unofficial_connection", 0),
    }


def _road_side(d: Document) -> dict[str, Any]:
    return {
        "roadsegment_side_values": d["plausibility"]["roadsegment_side_values"],
        "out_of_domain": d["plausibility"]["roadsegment_side_out_of_domain"]["records"],
    }


def _notes(d: Document) -> dict[str, Any]:
    notes = _field(d, "NOTES")
    return {
        "values": notes.get("values"),
        "unlisted_free_text_records": notes.get("unlisted_free_text_records"),
    }


ADOPTIONS: tuple[Adoption, ...] = (
    Adoption(
        "identity",
        ("ACTIVETRANSPORTID",),
        Disposition.IDENTITY_PROVENANCE,
        "all values",
        "The City documents it as the permanent record id. It is present and unique on every "
        "record of both publications and joins them with no field disagreeing.",
        _identity,
    ),
    Adoption(
        "service row number",
        ("OBJECTID",),
        Disposition.REJECTED,
        "as an identity",
        "The City documents that OBJECTID changes on export and import; it differs between "
        "the two publications for the same record. It is used only to check each request "
        "returned the rows it asked for.",
        _object_id,
    ),
    Adoption(
        "source and source date",
        ("SOURCE", "SOURCE_DATE"),
        Disposition.IDENTITY_PROVENANCE,
        "all values; SOURCE published by vocabulary class",
        "Record-level provenance: mostly the orthoimagery year a record was digitised from, "
        "with SOURCE_DATE matching that year. It dates the capture of the record, not any "
        "attribute on it.",
        _source,
    ),
    Adoption(
        "record dates",
        ("CREATE_DATE", "STATUS_DATE"),
        Disposition.IDENTITY_PROVENANCE,
        "all values",
        "Database-maintained timestamps of record creation and of the last status change. "
        "Useful for lineage; not observations of the facility.",
        _record_dates,
    ),
    Adoption(
        "update date",
        ("UPDATE_DATE",),
        Disposition.REJECTED,
        "as freshness evidence",
        "Nearly every record carries the same update day, written by the database account: "
        "it records a maintenance run, not an observation.",
        _update_date,
    ),
    Adoption(
        "status",
        ("STATUS",),
        Disposition.RAW_EVIDENCE,
        "ACTIVE, as an administrative assertion that the facility is in service",
        "Every published record is ACTIVE because only active records are published; "
        "planned, potential and closed records cannot be studied from the open data, and the "
        "network links carry no status at all.",
        _status,
    ),
    Adoption(
        "classification",
        ("CATEGORY", "SUBCATEGORY"),
        Disposition.MATCHING_INPUT,
        "all values",
        "Separates sidewalks, crossings, trails, links and connections, which is what a "
        "matcher needs to pair a record with the right kind of OSM way. It is not an "
        "accessibility fact.",
        _classification,
    ),
    Adoption(
        "stairs and structures",
        ("FEATURE_TYPE",),
        Disposition.NORMALIZED_EVIDENCE,
        "STAIRS, BRIDGE, OVERPASS, UNDERPASS, BOARDWALK only",
        "These are deliberate departures from the template value SURFACE and translate "
        "directly into steps, bridge and tunnel evidence. SURFACE is the template default and "
        "is never read as 'no stairs'.",
        _structures,
    ),
    Adoption(
        "geometry",
        ("SHAPE",),
        Disposition.MATCHING_INPUT,
        "all records",
        "Centrelines digitised from orthoimagery. In the study area almost every pedestrian "
        "record runs within a couple of metres of an OSM pedestrian way along its whole "
        "length, which is consistent with shared lineage: the geometry is input to matching "
        "and a lineage question, not independent evidence of where a path is.",
        _geometry,
    ),
    Adoption(
        "width",
        ("WIDTH_M",),
        Disposition.COMPARISON_ONLY,
        "non-default, non-zero values; 1.5 and 0 never",
        "A value from a coded list, not a measurement. 1.5 is the template default and sits "
        "on almost every sidewalk; the documented 1.8 m default never occurs; 0 stands in for "
        "crossings and links. Other widths may be compared with OSM widths; none is adopted.",
        _width,
    ),
    Adoption(
        "surface material",
        ("SURFACE_MATERIAL",),
        Disposition.NORMALIZED_EVIDENCE,
        "non-default values only; CONCRETE never",
        "Asphalt, stonedust, gravel, natural, brick, wood and the rest are deliberate "
        "departures from the template and translate into surface classes. CONCRETE is the "
        "template default and cannot be told from an unedited record.",
        _surface,
    ),
    Adoption(
        "surface condition",
        ("SURFACE_CONDITION",),
        Disposition.RAW_EVIDENCE,
        "FAIR, POOR and UNUSABLE, as a claim dated 2015 by the City's documentation",
        "Documented as found in the 2015 trail inventory. A 2015 condition is not a current "
        "fact, so it may be kept only as a dated source claim. GOOD is the template default; "
        "UNKNOWN is explicit and most common, and stays unknown.",
        _condition,
    ),
    Adoption(
        "curb cut",
        ("CURBCUT",),
        Disposition.NORMALIZED_EVIDENCE,
        "Y only; N is never 'no curb cut', U is unknown",
        "Y marks short segments that are 'a curbcut down to street level' — a deliberate, "
        "located claim that translates into kerb-ramp evidence. Whether the ramp is lowered or "
        "flush is not stated. N is the template default.",
        _curbcut,
    ),
    Adoption(
        "railing",
        ("RAILING",),
        Disposition.RAW_EVIDENCE,
        "Y only",
        "Y is deliberate and N is the template default. PathAble's cost model has no railing "
        "input, so it can only be kept as a source claim.",
        _railing,
    ),
    Adoption(
        "grade",
        ("GRADE",),
        Disposition.REJECTED,
        "all values",
        "Documented as script-calculated, and almost every record says UNKNOWN.",
        _grade,
    ),
    Adoption(
        "slope",
        (
            "SLOPE_GRADIENT_PERCENT",
            "SLOPE_GRADIENT_CLASS",
            "SLOPE_GRADIENT_MAX",
            "SLOPE_GRADIENT_MIN",
            "SLOPE_GRADIENT_AVG",
        ),
        Disposition.COMPARISON_ONLY,
        "against PathAble's own derived grade",
        "Derived by the City's FME script from an unstated surface model, with some values "
        "over 100%. PathAble derives grade from 1 m LiDAR itself; a derived value may be "
        "compared with it, never adopted over it.",
        _slope,
    ),
    Adoption(
        "grade category",
        ("GRADE_CATEGORY_MAX",),
        Disposition.REJECTED,
        "all values",
        "Undocumented, and it disagrees with the City's own SLOPE_GRADIENT_MAX on about half "
        "of the records where both are present.",
        _grade_category,
    ),
    Adoption(
        "condition score and date",
        ("CONDITION_SCORE", "CONDITION_DATE"),
        Disposition.REJECTED,
        "all values",
        "Documented as a calculated Cityworks score, but only 0 and 1 occur, and a score and "
        "its date almost never appear on the same record.",
        _condition_score,
    ),
    Adoption(
        "inspection year",
        ("LAST_INSPECTION_YEAR",),
        Disposition.RAW_EVIDENCE,
        "plausible years, as the date a record was last inspected",
        "Documented as the last year the segment was inspected by the City's programmes. It "
        "says the facility was looked at, not what was found: it may date a record's "
        "existence, never an attribute.",
        _inspection,
    ),
    Adoption(
        "installation year",
        ("INSTALLATION_YEAR",),
        Disposition.UNRESOLVED,
        "all values",
        "A single year covers a large share of populated values, which looks like a bulk load "
        "rather than installation dates; the documentation says only 'usually a database "
        "maintained field'.",
        _installation,
    ),
    Adoption(
        "virtual links",
        ("NETWORK LINKS / LINK (PEDESTRIAN)", "NETWORK LINKS / LINK (MUT)"),
        Disposition.MATCHING_INPUT,
        "topology and crossing location only",
        "The City's virtual street crossings say where its network connects. They are never a "
        "physical routable segment, and never evidence that a crossing facility exists.",
        _virtual,
    ),
    Adoption(
        "unofficial connections",
        ("NETWORK LINKS / DRIVEWAY CONNECTION", "NETWORK LINKS / ON-ROAD CONNECTION"),
        Disposition.COMPARISON_ONLY,
        "connectivity context only",
        "Unofficial routes along roads or driveways, documented as such; not pedestrian "
        "infrastructure.",
        _connections,
    ),
    Adoption(
        "road relationship",
        ("ROADSEGMENTID", "ROADSEGMENT_SIDE"),
        Disposition.MATCHING_INPUT,
        "LEFT and RIGHT",
        "Which road and which side a sidewalk belongs to — what a matcher needs to pair it "
        "with OSM's sidewalk on that side. UNDEFINED is outside the City's own domain.",
        _road_side,
    ),
    Adoption(
        "notes",
        ("NOTES",),
        Disposition.REJECTED,
        "all values",
        "Documented as free text, but the snapshot holds only two workflow words whose "
        "meaning is not documented.",
        _notes,
    ),
)


def adoption_matrix(document: Document) -> dict[str, Any]:
    return {
        "routing_use": "none — no Kitchener field is approved for routing by PA-GEO-03",
        "decided_on": "one snapshot, from the figures in each entry's basis",
        "entries": [
            {
                "subject": entry.subject,
                "fields": list(entry.fields),
                "disposition": str(entry.disposition),
                "scope": entry.scope,
                "rationale": entry.rationale,
                "basis": entry.basis(document),
            }
            for entry in ADOPTIONS
        ],
    }


def exit_gate(document: Document) -> dict[str, Any]:
    """The seven exit questions, answered with the run's own numbers.

    The decision itself (GO / LIMITED GO / NO-GO) is a judgement and is recorded
    in the methodology document, next to these figures, not generated here.
    """
    overall = document["overall"]
    geography = _geo(document)
    along = geography["graph_along_inventory"]
    pedestrian = document["physical_virtual"]["physical_active_pedestrian"]

    def non_default(name: str) -> int:
        return int(_states(document, name)["non_default"])

    width = document["defaults"]["width_m"]
    return {
        "q1_geographic_overlap": {
            "records_intersecting_study_area": geography["records_intersecting_study_area"],
            "share_of_records": _share(
                geography["records_intersecting_study_area"], geography["records_total"]
            ),
            "km_intersecting_study_area": geography["km_intersecting_study_area"],
            "km_total": geography["km_total"],
            "pathable_edges_along_inventory": along["edges_along_inventory"],
            "share_of_pathable_edges": _share(along["edges_along_inventory"], along["edges_total"]),
        },
        "q2_active_physical_pedestrian_records": {
            "total": pedestrian["records"],
            "km_total": pedestrian["km"],
            "in_study_area": geography["physical_active_pedestrian_intersecting"],
            "km_in_study_area": geography["physical_active_pedestrian_km_intersecting"],
        },
        "q3_populated_beyond_template_defaults": {
            "FEATURE_TYPE_structures": non_default("FEATURE_TYPE"),
            "SURFACE_MATERIAL_non_default": non_default("SURFACE_MATERIAL"),
            "WIDTH_M_non_default_non_zero": width["non_default_non_zero"],
            "CURBCUT_Y": non_default("CURBCUT"),
            "RAILING_Y": non_default("RAILING"),
            "SURFACE_CONDITION_fair_poor_unusable": non_default("SURFACE_CONDITION"),
            "SURFACE_CONDITION_unknown": _states(document, "SURFACE_CONDITION")["unknown"],
            "GRADE_known": non_default("GRADE"),
            "records_with_every_accessibility_field_at_default": document["defaults"][
                "template_signature"
            ]["records_by_fields_at_default"].get("6", 0),
        },
        "q4_provenance_and_freshness": {
            "records_with_source_date": _states(document, "SOURCE_DATE")["non_default"],
            "records_with_last_inspection_year": non_default("LAST_INSPECTION_YEAR"),
            "last_inspection_year": document["provenance"]["last_inspection_year"],
            "update_date_share_on_bulk_day": document["provenance"]["update_date"][
                "share_on_bulk_update_day"
            ],
            "non_default_values_with_source_date": {
                name: _field(document, name)["coverage_when_non_default"]
                for name in ("SURFACE_MATERIAL", "CURBCUT", "SURFACE_CONDITION", "FEATURE_TYPE")
            },
        },
        "q5_stairs_crossings_curb": {
            "stairs": overall["structure"].get("STAIRS", 0),
            "stairs_in_study_area": geography["intersecting_by_structure"].get("STAIRS", 0),
            "pedestrian_crossings": overall["network_role"].get("pedestrian_crossing", 0),
            "pedestrian_crossings_in_study_area": geography["intersecting_by_network_role"].get(
                "pedestrian_crossing", 0
            ),
            "curbcut_y": non_default("CURBCUT"),
            "curbcut_y_in_study_area": geography["intersecting_curbcut_y"],
        },
        "q6_virtual_or_non_physical": {
            "virtual_link": overall["physical_class"].get("virtual_link", 0),
            "unofficial_connection": overall["physical_class"].get("unofficial_connection", 0),
            "unresolved": overall["physical_class"].get("unresolved", 0),
            "in_study_area": {
                key: geography["intersecting_by_physical_class"].get(key, 0)
                for key in ("virtual_link", "unofficial_connection", "unresolved")
            },
        },
        "q7_inputs": {
            "pedestrian_records_whose_whole_line_is_within_2m_of_osm_pedestrian_ways": sum(
                count
                for label, count in geography[
                    "offset_of_pedestrian_records_from_osm_pedestrian_ways"
                ].items()
                if label in ("0-1m", "1-2m")
            ),
            "pedestrian_records_in_study_area": geography[
                "physical_active_pedestrian_intersecting"
            ],
            "osm_baseline_along_inventory": along["osm_baseline_on_those_edges"],
        },
    }
