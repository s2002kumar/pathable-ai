"""An empirical profile of one normalized Kitchener snapshot, computed by DuckDB.

Every number in the profile is a query over the normalized GeoParquet file,
and every query is a constant string in this module, so a reader can see
exactly what a figure counts. Distributions are ordered by count and then by
value, so two runs over the same file produce the same document.

Personal data does not leave the snapshot. ``CREATE_BY`` and ``UPDATE_BY`` are
not in the normalized file at all; ``SOURCE`` values are published only for the
vocabulary classes that cannot name a person; free-text ``NOTES`` values are
published only when they are single upper-case workflow words.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb

from pathable_api.geo.kitchener.normalize import ORIGIN_FIELDS, STATE_FIELDS
from pathable_api.geo.kitchener.semantics import (
    DOCUMENTED_ORIGINS,
    PUBLISHABLE_SOURCE_CLASSES,
    FieldSchema,
    FieldState,
)

#: How many values a distribution lists before it only counts the rest.
TOP_VALUES = 40

#: Template-defaulted fields that describe the facility itself.
ACCESSIBILITY_DEFAULTED = (
    "FEATURE_TYPE",
    "SURFACE_MATERIAL",
    "WIDTH_M",
    "RAILING",
    "CURBCUT",
    "SURFACE_CONDITION",
)

#: Fields whose raw values are never listed: identifiers, free text, timestamps.
_NO_VALUE_LISTING = frozenset(
    {
        "STREET",
        "ROADSEGMENTID",
        "STATUS_DATE",
        "SOURCE_DATE",
        "CREATE_DATE",
        "UPDATE_DATE",
        "CONDITION_DATE",
    }
)
_DATE_FIELDS = frozenset(
    {"STATUS_DATE", "SOURCE_DATE", "CREATE_DATE", "UPDATE_DATE", "CONDITION_DATE"}
)
_WORKFLOW_WORD = re.compile(r"^[A-Z]{2,12}$")

#: The documented default the City's field description gives for WIDTH_M.
DOCUMENTED_WIDTH_DEFAULT_M = 1.8

#: The label a script-derived GRADE_CATEGORY_MAX would carry for a whole-percent
#: maximum slope, taken from the label text itself ("<2% Flat", ">2 to <5% ...").
_GRADE_LABELS = (
    (2, "<2% Flat"),
    (5, ">2 to <5% Moderate"),
    (10, ">5 to <10% Steep"),
)
_GRADE_EXTREME = ">=10% Extreme"


class Profiler:
    """Constant queries over one normalized file, in a network-free DuckDB."""

    def __init__(self, parquet: Path) -> None:
        self._connection = duckdb.connect(database=":memory:")
        self._connection.execute("SET autoinstall_known_extensions = false")
        self._connection.execute("SET autoload_known_extensions = false")
        self._connection.execute("SET TimeZone = 'UTC'")
        path = parquet.as_posix().replace("'", "''")
        self._connection.execute(
            "CREATE VIEW n AS SELECT * EXCLUDE (geometry, geometry_native) "
            f"FROM read_parquet('{path}')"
        )

    def close(self) -> None:
        self._connection.close()

    def rows(self, sql: str, parameters: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        return [tuple(row) for row in self._connection.execute(sql, list(parameters)).fetchall()]

    def scalar(self, sql: str, parameters: Sequence[Any] = ()) -> Any:
        row = self._connection.execute(sql, list(parameters)).fetchone()
        return row[0] if row is not None else None

    def counts(
        self, expression: str, where: str = "TRUE", parameters: Sequence[Any] = ()
    ) -> dict[str, int]:
        """``expression`` → count, most frequent first, ties by value."""
        result = self.rows(
            f"SELECT {expression} AS v, count(*) FROM n WHERE {where} GROUP BY v", parameters
        )
        return _ordered({_key(value): int(count) for value, count in result})

    def year_histogram(self, column: str, where: str = "TRUE") -> dict[str, int]:
        result = self.rows(
            f"SELECT year({column}) AS y, count(*) FROM n WHERE {where} GROUP BY y ORDER BY y"
        )
        return {_key(year): int(count) for year, count in result}


def _key(value: Any) -> str:
    return "null" if value is None else str(value)


def _ordered(values: Mapping[str, int]) -> dict[str, int]:
    return dict(sorted(values.items(), key=lambda kv: (-kv[1], kv[0])))


def _top(values: Mapping[str, int], limit: int = TOP_VALUES) -> dict[str, Any]:
    ordered = _ordered(values)
    listed = dict(list(ordered.items())[:limit])
    rest = sum(ordered.values()) - sum(listed.values())
    return {"values": listed, "unlisted_records": rest, "distinct_values": len(ordered)}


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


def build_profile(
    profiler: Profiler,
    schemas: Mapping[str, FieldSchema],
    *,
    retrieved_year: int,
) -> dict[str, Any]:
    modal_update_day = profiler.scalar(
        "SELECT strftime(update_date, '%Y-%m-%d') AS d FROM n WHERE update_date IS NOT NULL "
        "GROUP BY d ORDER BY count(*) DESC, d LIMIT 1"
    )
    return {
        "overall": _overall(profiler),
        "fields": {
            name: _field(profiler, name, schemas.get(name), modal_update_day)
            for name in STATE_FIELDS
        },
        "defaults": _defaults(profiler),
        "provenance": _provenance(profiler, modal_update_day),
        "evidence_origin": _origins(profiler),
        "plausibility": _plausibility(profiler, retrieved_year),
        "derived_slope_consistency": _slope_consistency(profiler),
        "physical_virtual": _physical_virtual(profiler),
    }


def _overall(p: Profiler) -> dict[str, Any]:
    total = int(p.scalar("SELECT count(*) FROM n"))
    lengths = p.rows(
        "SELECT round(sum(length_m) / 1000, 3), round(min(length_m), 3), "
        "round(quantile_cont(length_m, 0.5), 3), round(max(length_m), 3) "
        "FROM n WHERE geometry_issue IS NULL"
    )[0]
    vertices = p.rows(
        "SELECT min(vertex_count), quantile_disc(vertex_count, 0.5), max(vertex_count), "
        "count(*) FILTER (WHERE vertex_count = 2) FROM n WHERE geometry_issue IS NULL"
    )[0]
    return {
        "records": total,
        "publications": p.counts(
            "CASE WHEN in_active_transportation AND in_walkability THEN 'both' "
            "WHEN in_active_transportation THEN 'active_transportation_only' "
            "ELSE 'walkability_only' END"
        ),
        "identity": {
            "states": p.counts("identity_state"),
            "null_identity": int(
                p.scalar("SELECT count(*) FROM n WHERE activetransportid IS NULL")
            ),
            "duplicate_identity_records": int(
                p.scalar("SELECT count(*) FROM n WHERE identity_state = 'duplicate'")
            ),
            "objectid_differs_between_publications": int(
                p.scalar(
                    "SELECT count(*) FROM n WHERE in_active_transportation AND in_walkability "
                    "AND objectid_active_transportation <> objectid_walkability"
                )
            ),
        },
        "geometry": {
            "issues": p.counts("coalesce(geometry_issue, 'valid')"),
            "parts": p.counts("part_count"),
            "vertices": {
                "min": vertices[0],
                "median": vertices[1],
                "max": vertices[2],
                "two_vertex_lines": vertices[3],
            },
            "length_m": {
                "total_km": lengths[0],
                "min": lengths[1],
                "median": lengths[2],
                "max": lengths[3],
            },
            "max_difference_from_service_length_m": p.scalar(
                "SELECT round(max(abs(length_m - shape_length_m)), 3) FROM n "
                "WHERE shape_length_m IS NOT NULL AND geometry_issue IS NULL"
            ),
        },
        "lifecycle": p.counts("lifecycle"),
        "category": p.counts("category"),
        "subcategory": p.counts("subcategory"),
        "category_subcategory": p.counts("concat_ws(' / ', category, subcategory)"),
        "feature_type": p.counts("feature_type"),
        "network_role": p.counts("network_role"),
        "physical_class": p.counts("physical_class"),
        "structure": p.counts("structure", "structure IS NOT NULL"),
    }


def _field(
    p: Profiler, name: str, schema: FieldSchema | None, modal_update_day: str | None
) -> dict[str, Any]:
    column = "shape_length_m" if name == "Shape__Length" else name.lower()
    state = f"state_{name.lower()}"
    states = p.counts(state)
    published = sum(count for key, count in states.items() if key != FieldState.NOT_PUBLISHED)
    document: dict[str, Any] = {
        "records_where_published": published,
        "states": {s.value: states.get(s.value, 0) for s in FieldState},
        "schema_default": schema.default if schema is not None else None,
        "domain_size": len(schema.domain) if schema is not None and schema.domain else None,
    }
    if name in _DATE_FIELDS:
        document["years"] = p.year_histogram(column, f"{column} IS NOT NULL")
    elif name == "SOURCE":
        document["values"] = "see provenance.source_values (published by vocabulary class)"
    elif name == "NOTES":
        values = p.counts(column, f"{column} IS NOT NULL")
        listed = {k: v for k, v in values.items() if _WORKFLOW_WORD.match(k)}
        document["values"] = listed
        document["unlisted_free_text_records"] = sum(values.values()) - sum(listed.values())
    elif name not in _NO_VALUE_LISTING:
        document.update(_top(p.counts(column, f"{state} <> 'not_published'")))
    else:
        document["distinct_values"] = int(
            p.scalar(f"SELECT count(DISTINCT {column}) FROM n WHERE {column} IS NOT NULL")
        )
    document["coverage_when_populated"] = _coverage(
        p, f"{state} NOT IN ('not_published', 'null', 'blank')", modal_update_day
    )
    document["coverage_when_non_default"] = _coverage(
        p, f"{state} = 'non_default'", modal_update_day
    )
    return document


def _coverage(p: Profiler, where: str, modal_update_day: str | None) -> dict[str, Any]:
    """How many of the selected records carry provenance or freshness metadata."""
    row = p.rows(
        "SELECT count(*), "
        "count(*) FILTER (WHERE state_source NOT IN ('null', 'blank', 'not_published')), "
        "count(*) FILTER (WHERE source_date IS NOT NULL), "
        "count(*) FILTER (WHERE update_date IS NOT NULL), "
        "count(*) FILTER (WHERE update_date IS NOT NULL "
        "  AND strftime(update_date, '%Y-%m-%d') <> coalesce(?, '')), "
        "count(*) FILTER (WHERE state_last_inspection_year = 'non_default') "
        f"FROM n WHERE {where}",
        [modal_update_day],
    )[0]
    return {
        "records": int(row[0]),
        "with_source": int(row[1]),
        "with_source_date": int(row[2]),
        "with_update_date": int(row[3]),
        "with_update_date_off_the_bulk_update_day": int(row[4]),
        "with_last_inspection_year": int(row[5]),
    }


def _defaults(p: Profiler) -> dict[str, Any]:
    """The default-value investigation: what each attractive value actually rests on."""
    at = "in_active_transportation"
    pedestrian = "network_role IN ('pedestrian_way', 'pedestrian_crossing')"

    width = {
        "records_where_published": int(
            p.scalar("SELECT count(*) FROM n WHERE state_width_m <> 'not_published'")
        ),
        "equal_to_template_default_1_5": int(
            p.scalar("SELECT count(*) FROM n WHERE width_m = 1.5")
        ),
        "equal_to_documented_default_1_8": int(
            p.scalar("SELECT count(*) FROM n WHERE width_m = ?", [DOCUMENTED_WIDTH_DEFAULT_M])
        ),
        "zero": int(p.scalar("SELECT count(*) FROM n WHERE width_m = 0")),
        "null": int(p.scalar("SELECT count(*) FROM n WHERE state_width_m = 'null'")),
        "distribution": p.counts("width_m", "state_width_m <> 'not_published'"),
        "by_subcategory_at_1_5": _by_subcategory(p, "width_m = 1.5", "width_m IS NOT NULL"),
        "non_default_non_zero": int(
            p.scalar("SELECT count(*) FROM n WHERE state_width_m = 'non_default' AND width_m <> 0")
        ),
        "non_default_non_zero_on_pedestrian_ways_and_crossings": int(
            p.scalar(
                "SELECT count(*) FROM n WHERE state_width_m = 'non_default' AND width_m <> 0 "
                f"AND {pedestrian}"
            )
        ),
        "zero_by_subcategory": p.counts("subcategory", "width_m = 0"),
        "evidence_for_1_5": _evidence_for(p, "width_m = 1.5"),
        "evidence_for_non_default_non_zero": _evidence_for(
            p, "state_width_m = 'non_default' AND width_m <> 0"
        ),
    }
    surface = {
        "records_where_published": int(
            p.scalar("SELECT count(*) FROM n WHERE state_surface_material <> 'not_published'")
        ),
        "concrete": int(p.scalar("SELECT count(*) FROM n WHERE surface_material = 'CONCRETE'")),
        "non_concrete_distribution": p.counts(
            "surface_material",
            "state_surface_material NOT IN ('not_published', 'template_default')",
        ),
        "by_subcategory_concrete": _by_subcategory(
            p, "surface_material = 'CONCRETE'", "surface_material IS NOT NULL"
        ),
        "evidence_for_concrete": _evidence_for(p, "surface_material = 'CONCRETE'"),
        "evidence_for_non_default": _evidence_for(p, "state_surface_material = 'non_default'"),
    }
    condition = {
        "records_where_published": int(
            p.scalar(
                f"SELECT count(*) FROM n WHERE {at} AND state_surface_condition <> 'not_published'"
            )
        ),
        "distribution": p.counts("surface_condition", f"{at}"),
        "by_category": p.counts(
            "concat_ws(' / ', category, coalesce(surface_condition, 'null'))", at
        ),
        "good": _condition_evidence(p, "surface_condition = 'GOOD'"),
        "fair_poor_unusable": _condition_evidence(
            p, "surface_condition IN ('FAIR', 'POOR', 'UNUSABLE')"
        ),
    }
    curbcut = {
        "distribution": p.counts("curbcut", at),
        "by_subcategory": p.counts("concat_ws(' / ', subcategory, coalesce(curbcut, 'null'))", at),
        "by_feature_type": p.counts(
            "concat_ws(' / ', coalesce(feature_type, 'null'), coalesce(curbcut, 'null'))", at
        ),
        "segment_length_m": {
            value: _length_summary(p, f"{at} AND curbcut = '{value}' AND geometry_issue IS NULL")
            for value in ("Y", "N")
        },
        "evidence_for_y": _evidence_for(p, "curbcut = 'Y'"),
    }
    railing = {
        "distribution": p.counts("railing", at),
        "y_by_feature_type": p.counts("coalesce(feature_type, 'null')", "railing = 'Y'"),
        "stairs": p.counts("railing", "feature_type = 'STAIRS'"),
    }
    signature = " + ".join(
        f"CASE WHEN state_{name.lower()} = 'template_default' THEN 1 ELSE 0 END"
        for name in ACCESSIBILITY_DEFAULTED
    )
    template = {
        "fields": list(ACCESSIBILITY_DEFAULTED),
        "records_by_fields_at_default": p.counts(f"({signature})", at),
        "all_at_default_by_subcategory": p.counts(
            "subcategory", f"{at} AND ({signature}) = {len(ACCESSIBILITY_DEFAULTED)}"
        ),
    }
    return {
        "width_m": width,
        "surface_material": surface,
        "surface_condition": condition,
        "curbcut": curbcut,
        "railing": railing,
        "template_signature": template,
    }


def _by_subcategory(p: Profiler, matching: str, among: str) -> dict[str, dict[str, Any]]:
    rows = p.rows(
        f"SELECT subcategory, count(*) FILTER (WHERE {matching}), count(*) FROM n "
        f"WHERE {among} GROUP BY subcategory"
    )
    ordered = sorted(rows, key=lambda row: (-int(row[2]), _key(row[0])))
    return {
        _key(sub): {
            "matching": int(hit),
            "records": int(total),
            "share": _share(int(hit), int(total)),
        }
        for sub, hit, total in ordered
    }


def _evidence_for(p: Profiler, where: str) -> dict[str, int]:
    row = p.rows(
        "SELECT count(*), "
        "count(*) FILTER (WHERE source_date IS NOT NULL), "
        "count(*) FILTER (WHERE source_class = 'orthoimagery'), "
        "count(*) FILTER (WHERE source_class IN ('trail_inventory_2015', 'personal_observation', "
        "  'engineering_plan', 'project_or_programme', 'staff_assertion')), "
        "count(*) FILTER (WHERE state_last_inspection_year = 'non_default'), "
        "count(*) FILTER (WHERE condition_date IS NOT NULL) "
        f"FROM n WHERE {where}"
    )[0]
    return {
        "records": int(row[0]),
        "with_source_date": int(row[1]),
        "with_orthoimagery_source": int(row[2]),
        "with_document_survey_or_staff_source": int(row[3]),
        "with_last_inspection_year": int(row[4]),
        "with_condition_date": int(row[5]),
    }


def _condition_evidence(p: Profiler, where: str) -> dict[str, int]:
    row = p.rows(
        "SELECT count(*), "
        "count(*) FILTER (WHERE state_last_inspection_year = 'non_default'), "
        "count(*) FILTER (WHERE condition_date IS NOT NULL), "
        "count(*) FILTER (WHERE condition_score IS NOT NULL), "
        "count(*) FILTER (WHERE source_date IS NOT NULL), "
        "count(*) FILTER (WHERE source_class = 'trail_inventory_2015') "
        f"FROM n WHERE {where}"
    )[0]
    return {
        "records": int(row[0]),
        "with_last_inspection_year": int(row[1]),
        "with_condition_date": int(row[2]),
        "with_condition_score": int(row[3]),
        "with_source_date": int(row[4]),
        "source_is_2015_trail_inventory": int(row[5]),
    }


def _length_summary(p: Profiler, where: str) -> dict[str, Any]:
    row = p.rows(
        "SELECT count(*), round(quantile_cont(length_m, 0.1), 2), "
        "round(quantile_cont(length_m, 0.5), 2), round(quantile_cont(length_m, 0.9), 2) "
        f"FROM n WHERE {where}"
    )[0]
    return {"records": int(row[0]), "p10": row[1], "median": row[2], "p90": row[3]}


def _provenance(p: Profiler, modal_update_day: str | None) -> dict[str, Any]:
    classes = p.counts("source_class")
    publishable = [str(kind) for kind in sorted(PUBLISHABLE_SOURCE_CLASSES)]
    placeholders = ", ".join("?" for _ in publishable)
    values = p.rows(
        f"SELECT source_class, source, count(*) FROM n WHERE source_class IN ({placeholders}) "
        "GROUP BY source_class, source",
        publishable,
    )
    by_class: dict[str, dict[str, int]] = {}
    for kind, value, count in values:
        by_class.setdefault(str(kind), {})[_key(value)] = int(count)
    total_updates = int(p.scalar("SELECT count(*) FROM n WHERE update_date IS NOT NULL"))
    on_modal = int(
        p.scalar(
            "SELECT count(*) FROM n WHERE strftime(update_date, '%Y-%m-%d') = ?",
            [modal_update_day],
        )
    )
    ortho_vs_date = p.counts(
        "CASE WHEN source_date IS NULL THEN 'no_source_date' "
        "WHEN year(source_date) = source_year THEN 'same_year' ELSE 'different_year' END",
        "source_class = 'orthoimagery' AND source_year IS NOT NULL",
    )
    return {
        "source_classes": classes,
        "source_values": {kind: _ordered(v) for kind, v in sorted(by_class.items())},
        "source_values_withheld": {
            kind: count
            for kind, count in classes.items()
            if kind not in PUBLISHABLE_SOURCE_CLASSES and kind != "null"
        },
        "orthoimagery_years": p.counts("source_year", "source_year IS NOT NULL"),
        "orthoimagery_year_vs_source_date": ortho_vs_date,
        "update_date": {
            "records_with_update_date": total_updates,
            "bulk_update_day": modal_update_day,
            "records_on_bulk_update_day": on_modal,
            "share_on_bulk_update_day": _share(on_modal, total_updates),
            "accounts_on_bulk_update_day": p.counts(
                "coalesce(update_account, 'null')",
                "strftime(update_date, '%Y-%m-%d') = ?",
                [modal_update_day],
            ),
            "update_accounts": p.counts(
                "coalesce(update_account, 'null')", "in_active_transportation"
            ),
        },
        "last_inspection_year": p.counts(
            "last_inspection_year", "state_last_inspection_year <> 'not_published'"
        ),
        "sidewalker_program_by_last_inspection_year": p.counts(
            "concat_ws(' / ', coalesce(sidewalker_program, 'null'), "
            "coalesce(last_inspection_year, 'null'))",
            "in_active_transportation",
        ),
        "installation_year_modal": _modal(p, "installation_year"),
    }


def _modal(p: Profiler, column: str) -> dict[str, Any]:
    row = p.rows(
        f"SELECT {column}, count(*) AS c FROM n WHERE {column} IS NOT NULL "
        f"GROUP BY {column} ORDER BY c DESC, {column} LIMIT 1"
    )
    populated = int(p.scalar(f"SELECT count(*) FROM n WHERE {column} IS NOT NULL"))
    if not row:
        return {"value": None, "records": 0, "share_of_populated": None}
    return {
        "value": row[0][0],
        "records": int(row[0][1]),
        "share_of_populated": _share(int(row[0][1]), populated),
    }


def _origins(p: Profiler) -> dict[str, Any]:
    return {
        name: {
            "documented_origin": (
                str(DOCUMENTED_ORIGINS[name].origin) if name in DOCUMENTED_ORIGINS else None
            ),
            "basis": DOCUMENTED_ORIGINS[name].basis if name in DOCUMENTED_ORIGINS else None,
            "records_by_origin": p.counts(f"origin_{name.lower()}"),
        }
        for name in ORIGIN_FIELDS
    }


def _plausibility(p: Profiler, retrieved_year: int) -> dict[str, Any]:
    """Values that cannot be right as stated. Each rule is its own query."""
    rules = {
        "width_zero_on_physical_record": (
            "width_m = 0 AND physical_class = 'physical_active'",
            "A physical facility cannot be 0 m wide; 0 is in the City's coded domain.",
        ),
        "width_at_least_10m": ("width_m >= 10", "Wider than any pedestrian facility here."),
        "installation_year_outside_1900_to_retrieval": (
            f"installation_year IS NOT NULL AND installation_year NOT BETWEEN 1900 AND {retrieved_year}",
            "Not a possible installation year.",
        ),
        "last_inspection_year_not_a_plausible_year": (
            "last_inspection_year IS NOT NULL AND NOT regexp_full_match(last_inspection_year, "
            f"'(19|20)[0-9]{{2}}') OR TRY_CAST(last_inspection_year AS INTEGER) > {retrieved_year}",
            "Not a four-digit year up to the retrieval year.",
        ),
        "slope_max_over_100_percent": (
            "slope_gradient_max > 100",
            "Steeper than 45 degrees along a walking or cycling facility.",
        ),
        "date_after_retrieval": (
            " OR ".join(
                f"year({c}) > {retrieved_year}"
                for c in (
                    "status_date",
                    "source_date",
                    "create_date",
                    "update_date",
                    "condition_date",
                )
            ),
            "A record date later than the snapshot.",
        ),
        "condition_score_without_condition_date": (
            "condition_score IS NOT NULL AND condition_date IS NULL",
            "A calculated score without the date the City documents for it.",
        ),
        "condition_date_without_condition_score": (
            "condition_date IS NOT NULL AND condition_score IS NULL",
            "A calculation date without the score.",
        ),
        "roadsegment_side_out_of_domain": (
            "state_roadsegment_side = 'out_of_domain'",
            "A side value outside the City's LEFT/RIGHT/UNKNOWN/NA domain.",
        ),
    }
    return {
        name: {
            "records": int(p.scalar(f"SELECT count(*) FROM n WHERE {where}")),
            "rule": reason,
        }
        for name, (where, reason) in rules.items()
    } | {
        "condition_score_values": p.counts("condition_score", "condition_score IS NOT NULL"),
        "roadsegment_side_values": p.counts("roadsegment_side", "in_active_transportation"),
    }


def _slope_consistency(p: Profiler) -> dict[str, Any]:
    """Do the City's own derived slope fields agree with each other?"""
    cases = " ".join(
        f"WHEN slope_gradient_max < {limit} THEN '{label}'" for limit, label in _GRADE_LABELS
    )
    expected = f"CASE {cases} ELSE '{_GRADE_EXTREME}' END"
    return {
        "records_with_slope_max_and_grade_category": int(
            p.scalar(
                "SELECT count(*) FROM n WHERE slope_gradient_max IS NOT NULL "
                "AND grade_category_max IS NOT NULL AND grade_category_max <> 'None'"
            )
        ),
        "grade_category_agrees_with_slope_max": int(
            p.scalar(
                f"SELECT count(*) FROM n WHERE slope_gradient_max IS NOT NULL "
                f"AND grade_category_max IS NOT NULL AND grade_category_max <> 'None' "
                f"AND grade_category_max = {expected}"
            )
        ),
        "grade_category_is_the_string_None": int(
            p.scalar("SELECT count(*) FROM n WHERE grade_category_max = 'None'")
        ),
        "rule": (
            "GRADE_CATEGORY_MAX compared with the label its own text implies for "
            "SLOPE_GRADIENT_MAX (<2, 2-5, 5-10, >=10 percent); integer percents at a boundary "
            "are assigned to the higher band."
        ),
        "slope_gradient_source": p.counts(
            "slope_gradient_source", "slope_gradient_source IS NOT NULL"
        ),
        "slope_gradient_class": p.counts(
            "slope_gradient_class", "state_slope_gradient_class <> 'not_published'"
        ),
        "grade": p.counts("grade", "state_grade <> 'not_published'"),
    }


def _physical_virtual(p: Profiler) -> dict[str, Any]:
    pedestrian = p.rows(
        "SELECT count(*), round(coalesce(sum(length_m), 0) / 1000, 3) FROM n "
        "WHERE physical_class = 'physical_active' "
        "AND network_role IN ('pedestrian_way', 'pedestrian_crossing')"
    )[0]
    return {
        "physical_class": p.counts("physical_class"),
        "physical_active_pedestrian": {"records": int(pedestrian[0]), "km": pedestrian[1]},
        "by_class_and_subcategory": p.counts(
            "concat_ws(' / ', physical_class, category, subcategory)"
        ),
        "unresolved_or_noted": p.counts("role_note", "role_note IS NOT NULL"),
        "virtual_or_unofficial_in_active_transportation": int(
            p.scalar(
                "SELECT count(*) FROM n WHERE in_active_transportation "
                "AND physical_class IN ('virtual_link', 'unofficial_connection')"
            )
        ),
        "lifecycle_by_publication": p.counts(
            "concat_ws(' / ', CASE WHEN in_active_transportation THEN 'active_transportation' "
            "ELSE 'walkability_only' END, lifecycle)"
        ),
    }
