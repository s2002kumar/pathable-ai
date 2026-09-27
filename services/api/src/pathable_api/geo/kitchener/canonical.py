"""The canonical research representation PA-GEO-05 writes — and nothing routing reads.

Only what the observed sources require, as four tables in one run folder:

- ``source_features`` — each matched City record: provider, dataset, the
  publications it was read from, snapshot, record id, physical and network
  class, feature type, and its native geometry (GeoParquet).
- ``matches`` — each record's decision: state, the target OSM elements with
  the *local scope* each covers (metres along a way, or a node), relationship,
  representation, matcher and candidate-contract versions, and the rule and
  signals that decided it.
- ``assertions`` — what the City asserts, for the fields PA-GEO-03 approved and
  only where the value is not a template default: the raw value, its value
  state, a normalized value where one is allowed, the evidence origin, the
  record's dates, and a lineage state. CURBCUT = Y normalizes to "a curb cut is
  present" — never to a kerb height.
- ``comparisons`` — for a matched record, the City's assertion beside OSM's for
  the same attribute on the matched elements, and how they compare. Nothing is
  resolved: both are kept, and deciding between them is PA-GEO-06's question.

The files live under the ignored data folder. A manifest records every file's
SHA-256, the inputs' identity and the versions, so a run can be named without
committing it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb
import pyproj
import shapely

from pathable_api.geo.kitchener.conflation import (
    CANDIDATE_CONTRACT_VERSION,
    MATCHED,
    Decision,
    Record,
)
from pathable_api.geo.kitchener.correspondence import OsmIndex
from pathable_api.geo.kitchener.source import NATIVE_WKID
from pathable_api.geo.kitchener.study import (
    KERB_CONFLICT,
    KERB_CONSISTENT,
    STRUCTURE_TAGS,
    compare_surface,
)

ARTIFACT_VERSION = "kitchener-geo05-artifact-v1"
PROVIDER = "city-of-kitchener"
DATASET = "GIS_DATA.ACTIVE_TRANSPORTATION"
UNRESOLVED = "unresolved: reconciliation is PA-GEO-06's, behind the founder licensing gate"

#: City structure types, as the OSM feature they describe.
STRUCTURE_FEATURES = {
    "STAIRS": "steps",
    "BRIDGE": "bridge",
    "OVERPASS": "bridge",
    "UNDERPASS": "tunnel",
    "BOARDWALK": "boardwalk",
}
#: The 2015 trail inventory's condition values: historical, never current.
HISTORICAL_CONDITIONS = frozenset({"FAIR", "POOR", "UNUSABLE"})


def assertions(record: Record) -> list[dict[str, Any]]:
    """What the City asserts about one record, in the approved fields only."""
    a = record.attributes
    dates = {
        "record_source_date": a.get("source_date"),
        "last_inspection_year": a.get("last_inspection_year"),
    }
    found: list[dict[str, Any]] = []

    def add(
        attribute: str, raw: Any, state: Any, normalized: Any, origin: Any, **extra: Any
    ) -> None:
        found.append(
            {
                "source_record_id": record.activetransportid,
                "attribute": attribute,
                "raw_value": None if raw is None else str(raw),
                "value_state": state,
                "normalized_value": normalized,
                "evidence_origin": origin,
                "observed": extra.pop("observed", None),
                **dates,
                "lineage_state": "not_assessed",
                "note": extra.pop("note", None),
            }
        )

    if record.curb_cut:
        add(
            "curb_cut",
            a.get("curbcut"),
            a.get("state_curbcut"),
            "curb_cut_present",
            a.get("origin_curbcut"),
            note="The City defines CURBCUT = Y as 'a curbcut down to street level'; it implies "
            "no kerb height.",
        )
    if record.structure is not None:
        add(
            "structure",
            record.structure,
            "non_default",
            STRUCTURE_FEATURES[record.structure],
            a.get("origin_feature_type"),
        )
    if a.get("railing") == "Y" and a.get("state_railing") == "non_default":
        add("railing", "Y", "non_default", "railing_present", a.get("origin_railing"))
    if record.surface_material is not None:
        add(
            "surface_material",
            record.surface_material,
            "non_default",
            record.surface_material.split(" (")[0].lower(),
            a.get("origin_surface_material"),
        )
    condition = a.get("surface_condition")
    if condition in HISTORICAL_CONDITIONS and a.get("state_surface_condition") == "non_default":
        add(
            "surface_condition",
            condition,
            "non_default",
            str(condition).lower(),
            a.get("origin_surface_condition"),
            observed="2015",
            note="Documented as found by the 2015 Trail inventory project: historical, not a "
            "current condition.",
        )
    return found


def _way_ids(decision: Decision) -> list[int]:
    return [int(t.element.split("/")[1]) for t in decision.targets if t.element.startswith("way/")]


def comparisons(record: Record, decision: Decision, index: OsmIndex) -> list[dict[str, Any]]:
    """The City's assertions beside OSM's on the matched elements. Nothing is resolved."""
    if decision.state != MATCHED:
        return []
    ways = _way_ids(decision)
    tags = {w: index.extract.ways[w].tags for w in ways}
    kerbs = [
        int(t.element.split("/")[1])
        for t in decision.targets
        if t.element.startswith("node/") and t.role == "kerb"
    ]
    rows: list[dict[str, Any]] = []

    def add(
        attribute: str,
        city: Any,
        elements: Sequence[str],
        key: str,
        values: Sequence[str],
        outcome: str,
    ) -> None:
        rows.append(
            {
                "source_record_id": record.activetransportid,
                "attribute": attribute,
                "kitchener_value": city,
                "osm_elements": list(elements),
                "osm_key": key,
                "osm_values": sorted(set(values)),
                "comparison": outcome,
                "resolution": UNRESOLVED,
            }
        )

    for assertion in assertions(record):
        attribute = assertion["attribute"]
        city = assertion["normalized_value"]
        if attribute == "curb_cut":
            values = [index.extract.nodes[k].tags.get("kerb", "") for k in kerbs]
            present = {v for v in values if v}
            if not present:
                outcome = "kitchener_only"
            elif present & KERB_CONSISTENT and not present & KERB_CONFLICT:
                outcome = "consistent"
            elif present <= KERB_CONFLICT:
                outcome = "conflict"
            else:
                outcome = "semantics_mismatch"
            add(attribute, city, [f"node/{k}" for k in kerbs], "kerb", sorted(present), outcome)
        elif attribute == "structure":
            # PA-GEO-04's reading: the tag OSM uses for the structure, and for
            # stairs and boardwalks the value it must carry.
            key, accepted = STRUCTURE_TAGS[str(record.structure)]
            hit = [
                v
                for w in ways
                if (v := tags[w].get(key)) is not None
                and v != "no"
                and (accepted is None or v in accepted)
            ]
            add(
                attribute,
                city,
                [f"way/{w}" for w in ways],
                key,
                hit,
                "same" if hit else "kitchener_only",
            )
        elif attribute == "railing":
            values = [v for w in ways for k, v in tags[w].items() if k.startswith("handrail")]
            outcome = (
                "kitchener_only"
                if not values
                else "osm_no_handrail"
                if set(values) == {"no"}
                else "consistent"
            )
            add(attribute, city, [f"way/{w}" for w in ways], "handrail", values, outcome)
        elif attribute == "surface_material":
            material = str(record.surface_material)
            outcomes = [compare_surface(material, tags[w].get("surface")) for w in ways]
            values = [tags[w]["surface"] for w in ways if "surface" in tags[w]]
            if "conflict" in outcomes and ({"same", "same_coarser"} & set(outcomes)):
                outcome = "mixed"
            elif "conflict" in outcomes:
                outcome = "conflict"
            elif "same" in outcomes:
                outcome = "same"
            elif "same_coarser" in outcomes:
                outcome = "same_coarser"
            else:
                outcome = "kitchener_only"
            add(attribute, city, [f"way/{w}" for w in ways], "surface", values, outcome)
        elif attribute == "surface_condition":
            values = [
                v
                for w in ways
                for k, v in tags[w].items()
                if k in ("smoothness", "surface:condition")
            ]
            add(
                attribute,
                city,
                [f"way/{w}" for w in ways],
                "smoothness",
                values,
                "both_present" if values else "kitchener_only",
            )
    if record.surface_material is None:
        values = [tags[w]["surface"] for w in ways if "surface" in tags[w]]
        if values:
            add("surface_material", None, [f"way/{w}" for w in ways], "surface", values, "osm_only")
    return rows


# ---------------------------------------------------------------------------
# Writing the tables
# ---------------------------------------------------------------------------

_SOURCE_COLUMNS = (
    ("provider", "VARCHAR"),
    ("dataset", "VARCHAR"),
    ("publications", "VARCHAR[]"),
    ("snapshot_id", "VARCHAR"),
    ("source_record_id", "BIGINT"),
    ("physical_class", "VARCHAR"),
    ("network_role", "VARCHAR"),
    ("family", "VARCHAR"),
    ("feature_type", "VARCHAR"),
    ("evidence_classes", "VARCHAR[]"),
    ("length_m", "DOUBLE"),
    ("geometry", "BLOB"),
)
_MATCH_COLUMNS = (
    ("source_record_id", "BIGINT"),
    ("match_state", "VARCHAR"),
    ("rule", "VARCHAR"),
    ("relationship", "VARCHAR"),
    ("representation", "VARCHAR"),
    (
        "targets",
        "STRUCT(element VARCHAR, osm_version BIGINT, role VARCHAR, from_m DOUBLE, to_m DOUBLE)[]",
    ),
    ("matcher_version", "VARCHAR"),
    ("candidate_contract_version", "VARCHAR"),
    ("signals", "VARCHAR"),
)
_ASSERTION_COLUMNS = (
    ("source_record_id", "BIGINT"),
    ("attribute", "VARCHAR"),
    ("raw_value", "VARCHAR"),
    ("value_state", "VARCHAR"),
    ("normalized_value", "VARCHAR"),
    ("evidence_origin", "VARCHAR"),
    ("observed", "VARCHAR"),
    ("record_source_date", "VARCHAR"),
    ("last_inspection_year", "BIGINT"),
    ("lineage_state", "VARCHAR"),
    ("note", "VARCHAR"),
)
_COMPARISON_COLUMNS = (
    ("source_record_id", "BIGINT"),
    ("attribute", "VARCHAR"),
    ("kitchener_value", "VARCHAR"),
    ("osm_elements", "VARCHAR[]"),
    ("osm_key", "VARCHAR"),
    ("osm_values", "VARCHAR[]"),
    ("comparison", "VARCHAR"),
    ("resolution", "VARCHAR"),
)


def _geo_metadata(geometries: Iterable[Any]) -> dict[str, Any]:
    types = sorted({g.geom_type for g in geometries})
    return {
        "version": "1.1.0",
        "primary_column": "geometry",
        "columns": {
            "geometry": {
                "encoding": "WKB",
                "geometry_types": types,
                "crs": pyproj.CRS.from_epsg(NATIVE_WKID).to_json_dict(),
            }
        },
    }


def _sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def write_table(
    path: Path,
    columns: Sequence[tuple[str, str]],
    rows: Sequence[Mapping[str, Any]],
    geo: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One Parquet file, written by DuckDB on one thread so its bytes are reproducible."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.ndjson")
    with staging.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            record = {
                name: (
                    bytes(row[name]).hex()
                    if kind == "BLOB" and row[name] is not None
                    else row[name]
                )
                for name, kind in columns
            }
            handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("SET threads = 1")
        connection.execute("SET TimeZone = 'UTC'")
        connection.execute("SET autoinstall_known_extensions = false")
        connection.execute("SET autoload_known_extensions = false")
        staged = ", ".join(
            f"'{name}': '{'VARCHAR' if kind == 'BLOB' else kind}'" for name, kind in columns
        )
        selected = ", ".join(
            f'from_hex("{name}") AS "{name}"' if kind == "BLOB" else f'"{name}"'
            for name, kind in columns
        )
        # Column names and types come from this module; the path is quoted.
        connection.execute(
            f"CREATE TABLE output AS SELECT {selected} FROM read_json("  # noqa: S608
            f"'{_sql_path(staging)}', format = 'newline_delimited', columns = {{{staged}}})"
        )
        options = "FORMAT parquet, COMPRESSION zstd"
        if geo is not None:
            literal = json.dumps(geo, sort_keys=True, separators=(",", ":")).replace("'", "''")
            options += f", KV_METADATA {{geo: '{literal}'}}"
        connection.execute(f"COPY output TO '{_sql_path(path)}' ({options})")
    finally:
        connection.close()
        staging.unlink(missing_ok=True)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"file": path.name, "rows": len(rows), "bytes": path.stat().st_size, "sha256": digest}


def write_artifact(
    folder: Path,
    records: Sequence[Record],
    decisions: Mapping[int, Decision],
    index: OsmIndex,
    snapshot_id: str,
    policy_version: str,
) -> dict[str, Any]:
    """Every table for a run, and the files' identity for the manifest."""
    ordered = sorted(records, key=lambda r: r.activetransportid)
    sources = [
        {
            "provider": PROVIDER,
            "dataset": DATASET,
            "publications": list(r.attributes.get("publications") or []),
            "snapshot_id": snapshot_id,
            "source_record_id": r.activetransportid,
            "physical_class": "physical_active",
            "network_role": r.network_role,
            "family": r.family,
            "feature_type": r.attributes.get("feature_type"),
            "evidence_classes": list(r.classes),
            "length_m": round(r.length_m, 3),
            "geometry": shapely.to_wkb(r.geometry),
        }
        for r in ordered
    ]
    matches = []
    for r in ordered:
        d = decisions[r.activetransportid]
        matches.append(
            {
                "source_record_id": r.activetransportid,
                "match_state": d.state,
                "rule": d.rule,
                "relationship": d.relationship,
                "representation": d.representation,
                "targets": [
                    {
                        "element": t.element,
                        "osm_version": _version(t.element, index),
                        "role": t.role,
                        "from_m": None if t.from_m is None else round(t.from_m, 3),
                        "to_m": None if t.to_m is None else round(t.to_m, 3),
                    }
                    for t in d.targets
                ],
                "matcher_version": policy_version,
                "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
                "signals": json.dumps(d.signals, sort_keys=True, separators=(",", ":")),
            }
        )
    assertion_rows = [a for r in ordered for a in assertions(r)]
    comparison_rows = [
        c for r in ordered for c in comparisons(r, decisions[r.activetransportid], index)
    ]
    return {
        "version": ARTIFACT_VERSION,
        "files": {
            "source_features": write_table(
                folder / "source_features.parquet",
                _SOURCE_COLUMNS,
                sources,
                _geo_metadata(r.geometry for r in ordered),
            ),
            "matches": write_table(folder / "matches.parquet", _MATCH_COLUMNS, matches),
            "assertions": write_table(
                folder / "assertions.parquet", _ASSERTION_COLUMNS, assertion_rows
            ),
            "comparisons": write_table(
                folder / "comparisons.parquet", _COMPARISON_COLUMNS, comparison_rows
            ),
        },
    }


def _version(element: str, index: OsmIndex) -> int | None:
    kind, _, number = element.partition("/")
    item = (
        index.extract.ways.get(int(number))
        if kind == "way"
        else index.extract.nodes.get(int(number))
    )
    return None if item is None else item.version
