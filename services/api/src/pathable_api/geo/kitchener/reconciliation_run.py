"""PA-GEO-06 over the full pilot: inputs bound to PA-GEO-05, the research artifact, the evidence.

The run reads PA-GEO-05's artifact, never its matcher: the decisions are
those the benchmark measured, checked file by file against the manifest that
recorded them, and bound to the same Kitchener snapshot and OSM extract. It
writes four tables under the ignored data folder and a summary that can be
committed.

The artifact is a combined database of City and OSM values. It stays out of
git and out of anything routing reads: combining the two for production or
redistribution is behind the founder licensing gate
(``docs/licensing/DATA_SOURCES.md`` §11). The committed summary holds counts,
the observed value pairs and every conflict, as earlier cards' evidence did.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import shapely
from shapely import ops
from shapely.geometry.base import BaseGeometry

from pathable_api.geo.kitchener.assertions import (
    ASSERTION_SCHEMA_VERSION,
    NOT_ROUTING_ELIGIBLE,
    OSM_NODE,
    RESEARCH_CANDIDATE,
    TWO_SIDED,
    Assertion,
    Reconciliation,
    Relationship,
    Source,
    Topic,
)
from pathable_api.geo.kitchener.canonical import _geo_metadata, write_table
from pathable_api.geo.kitchener.conflation import (
    CANDIDATE_CONTRACT_VERSION,
    ConflationInputs,
    Decision,
    load_inputs,
    study_area,
)
from pathable_api.geo.kitchener.conflation import Target as MatchTarget
from pathable_api.geo.kitchener.correspondence import KitchenerIndex, OsmIndex, to_native
from pathable_api.geo.kitchener.reconciliation import (
    ACCEPTED_MATCHER,
    INPUT_CONTRACT_VERSION,
    KITCHENER_SOURCE,
    OSM_SOURCE,
    POLICY_VERSION,
    CityFields,
    Reconciled,
    attach_history,
    class_accounting,
    invariant_violations,
    reconcile,
)
from pathable_api.geo.kitchener.reconciliation_vocabulary import VOCABULARY_VERSION
from pathable_api.geo.kitchener.study import ATTRIBUTION, History
from pathable_api.geo.overture.evidence import content_sha256, file_sha256

ARTIFACT_VERSION = "kitchener-geo06-artifact-v1"
EVIDENCE_VERSION = 1

#: Where the City publishes the licence its portal item cites (checked
#: 2026-09-26; ``docs/licensing/DATA_SOURCES.md`` §11).
KITCHENER_LICENCE_URL = (
    "https://www.kitchener.ca/council-and-city-administration/data-and-maps/open-data-licence/"
)
ODBL_URL = "https://opendatacommons.org/licenses/odbl/1-0/"

VERSIONS = {
    "assertion_schema": ASSERTION_SCHEMA_VERSION,
    "vocabulary": VOCABULARY_VERSION,
    "reconciliation_policy": POLICY_VERSION,
    "accepted_input_contract": INPUT_CONTRACT_VERSION,
    "artifact": ARTIFACT_VERSION,
}

Progress = Callable[[str], None]


class ReconciliationError(RuntimeError):
    """The inputs are not the ones PA-GEO-05's artifact was made from, or are damaged."""


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Geo05Artifact:
    decisions: dict[int, Decision]
    manifest: dict[str, Any]
    manifest_sha256: str


_MATCHES_QUERY = """
SELECT source_record_id, match_state, rule, relationship, representation, targets,
    matcher_version, signals
FROM read_parquet(?) ORDER BY source_record_id
"""


def load_geo05_artifact(folder: Path) -> Geo05Artifact:
    """PA-GEO-05's decisions, refused unless every file matches its manifest."""
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    if manifest.get("policy", {}).get("version") != ACCEPTED_MATCHER:
        msg = f"the artifact is not {ACCEPTED_MATCHER}'s; this contract accepts nothing else."
        raise ReconciliationError(msg)
    for name, entry in sorted(manifest["files"].items()):
        path = folder / entry["file"]
        if not path.is_file() or file_sha256(path) != entry["sha256"]:
            msg = f"PA-GEO-05's {name} table does not match the hash its manifest recorded."
            raise ReconciliationError(msg)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("SET autoinstall_known_extensions = false")
        connection.execute("SET autoload_known_extensions = false")
        rows = connection.execute(
            _MATCHES_QUERY, [(folder / "matches.parquet").as_posix()]
        ).fetchall()
    finally:
        connection.close()
    decisions: dict[int, Decision] = {}
    for record_id, state, rule, relationship, representation, targets, version, signals in rows:
        if version != ACCEPTED_MATCHER:
            msg = f"record {record_id} was decided by {version}, not {ACCEPTED_MATCHER}."
            raise ReconciliationError(msg)
        decisions[int(record_id)] = Decision(
            int(record_id),
            str(state),
            str(rule),
            tuple(
                MatchTarget(t["element"], t["role"], t["from_m"], t["to_m"]) for t in targets or ()
            ),
            relationship,
            str(representation),
            json.loads(signals),
        )
    return Geo05Artifact(decisions, manifest, file_sha256(manifest_path))


_CITY_QUERY = """
SELECT activetransportid,
    strftime(create_date, '%Y-%m-%dT%H:%M:%SZ'),
    strftime(update_date, '%Y-%m-%dT%H:%M:%SZ'),
    state_feature_type,
    coalesce(curbcut = 'Y' AND state_curbcut = 'non_default'
        AND physical_class <> 'virtual_link', false)
FROM read_parquet(?) WHERE activetransportid IS NOT NULL ORDER BY activetransportid
"""


def city_record_fields(parquet: Path) -> tuple[dict[int, CityFields], set[int]]:
    """Every record's database dates and FEATURE_TYPE state, and the physical
    records carrying CURBCUT = Y."""
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("SET autoinstall_known_extensions = false")
        connection.execute("SET autoload_known_extensions = false")
        rows = connection.execute(_CITY_QUERY, [parquet.as_posix()]).fetchall()
    finally:
        connection.close()
    fields = {
        int(i): CityFields(created, modified, state) for i, created, modified, state, _cut in rows
    }
    return fields, {int(i) for i, *_rest, cut in rows if cut}


@dataclass(slots=True)
class RunInputs:
    conflation: ConflationInputs
    geo05: Geo05Artifact
    city_fields: dict[int, CityFields]
    city_curb_cuts: KitchenerIndex
    area: BaseGeometry
    sources: list[Source]
    identity: dict[str, Any]


def load_run_inputs(
    normalized_dir: Path,
    extract_path: Path,
    extract_manifest_path: Path,
    geo05_dir: Path,
    snapshot_evidence: Path,
    *,
    progress: Progress | None = None,
) -> RunInputs:
    """The frozen inputs, bound to the artifact PA-GEO-05 wrote from them."""
    geo05 = load_geo05_artifact(geo05_dir)
    inputs = load_inputs(normalized_dir, extract_path, extract_manifest_path, progress=progress)
    recorded = geo05.manifest["inputs"]
    for side, key in (("kitchener", "normalized_sha256"), ("osm_frozen", "extract_sha256")):
        if inputs.identity[side][key] != recorded[side][key]:
            msg = f"the {side} input is not the one PA-GEO-05's artifact was made from."
            raise ReconciliationError(msg)
    if set(geo05.decisions) != {r.activetransportid for r in inputs.population.records}:
        msg = "PA-GEO-05's decisions do not cover exactly the eligible records."
        raise ReconciliationError(msg)
    city_fields, curb_cut_ids = city_record_fields(inputs.parquet)
    physical = inputs.population.physical
    curb_cuts = KitchenerIndex.build(f for i, f in physical.features.items() if i in curb_cut_ids)
    extract_manifest = json.loads(extract_manifest_path.read_text("utf-8"))
    area = study_area(tuple(extract_manifest["dataset"]["source_bbox"]), to_native())
    snapshot = json.loads(snapshot_evidence.read_text("utf-8"))
    snapshot_id = inputs.identity["kitchener"]["snapshot_id"]
    if snapshot.get("snapshot_id") != snapshot_id:
        msg = "the snapshot evidence describes a different Kitchener snapshot."
        raise ReconciliationError(msg)
    sources = source_registry(snapshot, extract_manifest)
    identity = {
        "kitchener": inputs.identity["kitchener"],
        "osm_frozen": {
            "extract_sha256": inputs.identity["osm_frozen"]["extract_sha256"],
            "dataset_id": extract_manifest["dataset"]["dataset_id"],
            "dataset_checksum": extract_manifest["dataset"]["checksum"],
            "source_file_sha256": extract_manifest["dataset"]["source_file_sha256"],
            "source_timestamp": extract_manifest["dataset"]["source_timestamp"],
        },
        "geo05_artifact": {
            "manifest_sha256": geo05.manifest_sha256,
            "matcher_version": geo05.manifest["policy"]["version"],
            "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
            "decisions_sha256": geo05.manifest["decisions_sha256"],
            "decisions": len(geo05.decisions),
            "files": {k: v["sha256"] for k, v in sorted(geo05.manifest["files"].items())},
            "produced_at_commit": geo05.manifest["run"]["environment"].get("git_commit"),
        },
    }
    return RunInputs(inputs, geo05, city_fields, curb_cuts, area, sources, identity)


def source_registry(
    snapshot: Mapping[str, Any], extract_manifest: Mapping[str, Any]
) -> list[Source]:
    publications = snapshot["publications"]
    licence = snapshot["licence"]
    dataset = extract_manifest["dataset"]
    return [
        Source(
            source_id=KITCHENER_SOURCE,
            provider=str(snapshot["publisher"]),
            dataset="GIS_DATA.ACTIVE_TRANSPORTATION",
            publications=tuple(
                f"{p['item']['title']} (ArcGIS Online item {p['item']['id']})"
                for _name, p in sorted(publications.items())
            ),
            snapshot=str(snapshot["snapshot_id"]),
            as_of=str(snapshot["retrieved_at"]),
            licence=f"{licence['name']}, version {licence['version_recorded']}",
            licence_url=KITCHENER_LICENCE_URL,
            attribution=ATTRIBUTION["kitchener"],
            role="municipal assertions: research only, behind the founder licensing gate",
        ),
        Source(
            source_id=OSM_SOURCE,
            provider="OpenStreetMap contributors",
            dataset=str(dataset["source_name"]),
            publications=(f"{dataset['source_provider']}: {dataset['source_file_name']}",),
            snapshot=str(extract_manifest["output"]["sha256"]),
            as_of=str(dataset["source_timestamp"]),
            licence="Open Data Commons Open Database License (ODbL) 1.0",
            licence_url=ODBL_URL,
            attribution="© OpenStreetMap contributors",
            role="the frozen extract PathAble's active routing dataset was built from",
        ),
    ]


def run_reconciliation(
    run_inputs: RunInputs, history: History | None, *, progress: Progress | None = None
) -> Reconciled:
    say = progress or (lambda _message: None)
    inputs = run_inputs.conflation
    records = {r.activetransportid: r for r in inputs.population.records}
    reconciled = reconcile(
        records,
        run_inputs.geo05.decisions,
        inputs.osm,
        area=run_inputs.area,
        city_physical=inputs.population.physical,
        city_curb_cuts=run_inputs.city_curb_cuts,
        city_fields=run_inputs.city_fields,
    )
    say(
        f"reconciled: {len(reconciled.reconciliations)} rows, {len(reconciled.assertions)} assertions"
    )
    if history is not None:
        attach_history(reconciled, records, history, run_inputs.city_fields, inputs.osm)
        say("lineage: attached from OSM's edit history")
    problems = invariant_violations(reconciled, inputs.osm)
    if problems:
        msg = f"{len(problems)} reconciliations break the model's invariants, e.g. {problems[:3]}"
        raise ReconciliationError(msg)
    return reconciled


# ---------------------------------------------------------------------------
# The artifact
# ---------------------------------------------------------------------------

_SOURCE_COLUMNS = (
    ("source_id", "VARCHAR"),
    ("provider", "VARCHAR"),
    ("dataset", "VARCHAR"),
    ("publications", "VARCHAR[]"),
    ("snapshot", "VARCHAR"),
    ("as_of", "VARCHAR"),
    ("licence", "VARCHAR"),
    ("licence_url", "VARCHAR"),
    ("attribution", "VARCHAR"),
    ("role", "VARCHAR"),
)
_ASSERTION_COLUMNS = (
    ("assertion_id", "VARCHAR"),
    ("source_id", "VARCHAR"),
    ("source_record", "VARCHAR"),
    ("source_record_version", "BIGINT"),
    ("topic", "VARCHAR"),
    ("property", "VARCHAR"),
    ("raw_attribute", "VARCHAR"),
    ("raw_value", "VARCHAR"),
    ("normalized_value", "VARCHAR"),
    ("value_state", "VARCHAR"),
    ("usable", "BOOLEAN"),
    ("evidence_origin", "VARCHAR"),
    ("scope", "VARCHAR"),
    ("capture_source", "VARCHAR"),
    ("source_capture_date", "VARCHAR"),
    ("observation_date", "VARCHAR"),
    ("observation_date_basis", "VARCHAR"),
    ("inspection_year", "BIGINT"),
    ("record_created_at", "VARCHAR"),
    ("record_modified_at", "VARCHAR"),
    ("osm_edit_timestamp", "VARCHAR"),
    ("osm_value_since", "VARCHAR"),
    ("freshness_basis", "VARCHAR"),
    ("history_assessed", "BOOLEAN"),
    ("introducing_changeset", "BIGINT"),
    ("stated_sources", "VARCHAR[]"),
    ("note", "VARCHAR"),
    ("schema_version", "VARCHAR"),
)
_CORRESPONDENCE_COLUMNS = (
    ("source_record_id", "BIGINT"),
    ("match_state", "VARCHAR"),
    ("rule", "VARCHAR"),
    ("relationship", "VARCHAR"),
    ("representation", "VARCHAR"),
    (
        "targets",
        "STRUCT(element VARCHAR, osm_version BIGINT, role VARCHAR, target_type VARCHAR, "
        "from_m DOUBLE, to_m DOUBLE)[]",
    ),
    ("matcher_version", "VARCHAR"),
    ("candidate_contract_version", "VARCHAR"),
    ("accepted_topics", "VARCHAR[]"),
    ("exclusions", "STRUCT(topic VARCHAR, reason VARCHAR)[]"),
    ("kerb_node_relationship", "VARCHAR"),
    ("input_contract_version", "VARCHAR"),
)
_RECONCILIATION_COLUMNS = (
    ("reconciliation_id", "VARCHAR"),
    ("topic", "VARCHAR"),
    ("property", "VARCHAR"),
    ("target_element", "VARCHAR"),
    ("target_osm_version", "BIGINT"),
    ("target_type", "VARCHAR"),
    ("from_m", "DOUBLE"),
    ("to_m", "DOUBLE"),
    ("source_records", "BIGINT[]"),
    ("correspondence_rules", "VARCHAR[]"),
    ("correspondence_relationship", "VARCHAR"),
    ("kitchener_assertions", "VARCHAR[]"),
    ("kitchener_withheld", "VARCHAR[]"),
    ("osm_assertions", "VARCHAR[]"),
    ("kitchener_values", "VARCHAR[]"),
    ("osm_values", "VARCHAR[]"),
    ("semantic_relationship", "VARCHAR"),
    ("specificity", "VARCHAR"),
    ("rule", "VARCHAR"),
    ("lineage_relationship", "VARCHAR"),
    ("lineage_basis", "VARCHAR"),
    ("lineage_reasons", "VARCHAR[]"),
    ("target_geometry_lineage", "VARCHAR"),
    ("evidence_state", "VARCHAR"),
    ("conflict", "VARCHAR"),
    ("routing_property", "BOOLEAN"),
    ("routing_eligibility", "VARCHAR"),
    ("blockers", "VARCHAR[]"),
    ("research_status", "VARCHAR"),
    ("policy_version", "VARCHAR"),
    ("geometry", "BLOB"),
)


def assertion_row(a: Assertion) -> dict[str, Any]:
    d = a.dates
    return {
        "assertion_id": a.assertion_id,
        "source_id": a.source_id,
        "source_record": a.source_record,
        "source_record_version": a.source_record_version,
        "topic": str(a.topic),
        "property": a.prop,
        "raw_attribute": a.raw_attribute,
        "raw_value": a.raw_value,
        "normalized_value": a.normalized_value,
        "value_state": a.value_state,
        "usable": a.usable,
        "evidence_origin": a.evidence_origin,
        "scope": a.scope,
        "capture_source": a.capture_source,
        "source_capture_date": d.source_capture_date,
        "observation_date": d.observation_date,
        "observation_date_basis": d.observation_date_basis,
        "inspection_year": d.inspection_year,
        "record_created_at": d.record_created_at,
        "record_modified_at": d.record_modified_at,
        "osm_edit_timestamp": d.osm_edit_timestamp,
        "osm_value_since": d.osm_value_since,
        "freshness_basis": d.freshness_basis,
        "history_assessed": a.history.assessed,
        "introducing_changeset": a.history.introducing_changeset,
        "stated_sources": list(a.history.stated_sources),
        "note": a.note,
        "schema_version": ASSERTION_SCHEMA_VERSION,
    }


def reconciliation_row(row: Reconciliation, osm: OsmIndex) -> dict[str, Any]:
    t = row.target
    return {
        "reconciliation_id": row.reconciliation_id,
        "topic": str(row.topic),
        "property": row.prop,
        "target_element": t.element,
        "target_osm_version": t.osm_version,
        "target_type": t.target_type,
        "from_m": t.from_m,
        "to_m": t.to_m,
        "source_records": list(row.source_records),
        "correspondence_rules": list(row.correspondence_rules),
        "correspondence_relationship": row.correspondence_relationship,
        "kitchener_assertions": list(row.kitchener_assertions),
        "kitchener_withheld": list(row.kitchener_withheld),
        "osm_assertions": list(row.osm_assertions),
        "kitchener_values": list(row.kitchener_values),
        "osm_values": list(row.osm_values),
        "semantic_relationship": str(row.relationship),
        "specificity": str(row.specificity),
        "rule": row.rule,
        "lineage_relationship": str(row.lineage),
        "lineage_basis": row.lineage_basis,
        "lineage_reasons": list(row.lineage_reasons),
        "target_geometry_lineage": row.target_geometry_lineage,
        "evidence_state": str(row.evidence_state),
        "conflict": row.conflict,
        "routing_property": row.routing_property,
        "routing_eligibility": row.routing_eligibility,
        "blockers": list(row.blockers),
        "research_status": RESEARCH_CANDIDATE,
        "policy_version": POLICY_VERSION,
        "geometry": shapely.to_wkb(target_geometry(row, osm)),
    }


def target_geometry(row: Reconciliation, osm: OsmIndex) -> BaseGeometry:
    """The local target, in native metres: the node, or the metres of the way the record covers."""
    number = int(row.target.element.split("/")[1])
    if row.target.target_type == OSM_NODE:
        point = osm.fact_points.get(number)
        return point if point is not None else shapely.Point()
    line = osm.lines[number]
    start = row.target.from_m if row.target.from_m is not None else 0.0
    end = row.target.to_m if row.target.to_m is not None else line.length
    found: BaseGeometry = ops.substring(line, start, end)
    return found


def correspondence_rows(
    reconciled: Reconciled, geo05: Geo05Artifact, osm: OsmIndex
) -> list[dict[str, Any]]:
    node_counts = {node: len(ids) for node, ids in reconciled.kerb_claims.items()}
    rows = []
    for record_id, found in reconciled.gates.items():
        decision = geo05.decisions[record_id]
        kerbs = list(found.kerb_nodes)
        rows.append(
            {
                "source_record_id": record_id,
                "match_state": decision.state,
                "rule": decision.rule,
                "relationship": decision.relationship,
                "representation": decision.representation,
                "targets": [
                    {
                        "element": t.element,
                        "osm_version": _version(osm, t.element),
                        "role": t.role,
                        "target_type": "osm_node"
                        if t.element.startswith("node/")
                        else "osm_way_extent",
                        "from_m": t.from_m,
                        "to_m": t.to_m,
                    }
                    for t in decision.targets
                ],
                "matcher_version": ACCEPTED_MATCHER,
                "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
                "accepted_topics": [str(t) for t in found.accepted],
                "exclusions": [
                    {"topic": str(topic), "reason": str(reason)}
                    for topic, reason in sorted(found.exclusions.items())
                ],
                "kerb_node_relationship": (
                    None
                    if not kerbs
                    else "many_to_one"
                    if any(node_counts.get(n, 0) > 1 for n in kerbs)
                    else "one_to_one"
                ),
                "input_contract_version": INPUT_CONTRACT_VERSION,
            }
        )
    return rows


def _version(osm: OsmIndex, element: str) -> int | None:
    kind, _, number = element.partition("/")
    item = (
        osm.extract.nodes.get(int(number)) if kind == "node" else osm.extract.ways.get(int(number))
    )
    return None if item is None else item.version


def write_reconciliation_artifact(
    folder: Path, run_inputs: RunInputs, reconciled: Reconciled
) -> dict[str, dict[str, Any]]:
    """Every table, written deterministically; the files' identity for the manifest."""
    osm = run_inputs.conflation.osm
    rows = [reconciliation_row(r, osm) for r in reconciled.reconciliations]
    geometries = [shapely.from_wkb(r["geometry"]) for r in rows]
    sources = [
        {name: list(v) if isinstance(v, tuple) else v for name, v in _fields(s).items()}
        for s in run_inputs.sources
    ]
    return {
        "sources": write_table(folder / "sources.parquet", _SOURCE_COLUMNS, sources),
        "assertions": write_table(
            folder / "assertions.parquet",
            _ASSERTION_COLUMNS,
            [assertion_row(reconciled.assertions[k]) for k in sorted(reconciled.assertions)],
        ),
        "correspondences": write_table(
            folder / "correspondences.parquet",
            _CORRESPONDENCE_COLUMNS,
            correspondence_rows(reconciled, run_inputs.geo05, osm),
        ),
        "reconciliations": write_table(
            folder / "reconciliations.parquet",
            _RECONCILIATION_COLUMNS,
            rows,
            _geo_metadata(geometries),
        ),
    }


def _fields(item: Any) -> dict[str, Any]:
    return {name: getattr(item, name) for name in type(item).__dataclass_fields__}


def compare_runs(first: Mapping[str, Mapping[str, Any]], folder: Path) -> dict[str, Any]:
    """Whether a second run's files are byte-identical to the first's."""
    earlier = json.loads((folder / "manifest.json").read_text("utf-8"))["files"]
    same = {
        name: earlier.get(name, {}).get("sha256") == entry["sha256"]
        for name, entry in sorted(first.items())
    }
    return {"compared_with": folder.name, "files_identical": same, "identical": all(same.values())}


# ---------------------------------------------------------------------------
# The evidence summary
# ---------------------------------------------------------------------------


def _count(values: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _metres(row: Reconciliation) -> float:
    t = row.target
    if t.from_m is None or t.to_m is None:
        return 0.0
    return max(t.to_m - t.from_m, 0.0)


def outcomes(rows: Sequence[Reconciliation]) -> dict[str, Any]:
    """Per topic and property: relationships, specificity and, for surfaces, metres."""
    result: dict[str, Any] = {}
    for topic in Topic:
        mine = [r for r in rows if r.topic is topic]
        block: dict[str, Any] = {
            "rows": len(mine),
            "semantic_relationship": _count(str(r.relationship) for r in mine),
            "specificity_of_compatible": _count(
                str(r.specificity) for r in mine if r.relationship is Relationship.COMPATIBLE
            ),
        }
        properties = sorted({r.prop for r in mine})
        if len(properties) > 1:
            block["by_property"] = {
                p: _count(str(r.relationship) for r in mine if r.prop == p) for p in properties
            }
        if topic is Topic.SURFACE:
            metres: dict[str, float] = defaultdict(float)
            for r in mine:
                metres[str(r.relationship)] += _metres(r)
            block["local_extent_metres"] = {k: round(v, 1) for k, v in sorted(metres.items())}
        result[str(topic)] = block
    return result


_OSM_SIDE = frozenset({*TWO_SIDED, Relationship.SOURCE_ONLY_OSM})


def coverage(rows: Sequence[Reconciliation], topic: Topic) -> dict[str, Any]:
    """Potential evidence coverage if eligible City assertions were included. Research only."""
    mine = [r for r in rows if r.topic is topic]
    by = Counter(r.relationship for r in mine)
    baseline = sum(by[r] for r in _OSM_SIDE)
    only = by[Relationship.SOURCE_ONLY_KITCHENER]
    return {
        "denominator": len(mine),
        "baseline_osm": baseline,
        "kitchener_only": only,
        "union": baseline + only,
        "unresolved_conflicts": by[Relationship.CONFLICT],
        "incomparable": by[Relationship.INCOMPARABLE],
        "unknown": by[Relationship.UNKNOWN],
    }


def lineage_summary(reconciled: Reconciled) -> dict[str, Any]:
    two_sided = [r for r in reconciled.reconciliations if r.relationship in TWO_SIDED]
    by_topic: dict[str, Any] = {}
    for topic in Topic:
        mine = [r for r in two_sided if r.topic is topic]
        if not mine:
            continue
        by_topic[str(topic)] = {
            "by_relationship": {
                str(rel): _count(str(r.lineage) for r in mine if r.relationship is rel)
                for rel in sorted({r.relationship for r in mine})
            },
            "apparently_independent_basis": _count(
                str(r.lineage_basis) for r in mine if r.lineage_basis
            ),
            "attribute_lineage_by_target_geometry_lineage": {
                geometry: _count(
                    str(r.lineage) for r in mine if r.target_geometry_lineage == geometry
                )
                for geometry in sorted({r.target_geometry_lineage for r in mine})
            },
        }
    assessed = [
        reconciled.assertions[a]
        for r in two_sided
        for a in r.osm_assertions
        if reconciled.assertions[a].history.assessed
    ]
    unique = {a.assertion_id: a for a in assessed}
    stated: Counter[str] = Counter()
    for a in unique.values():
        for signal in a.history.stated_sources or ("none_stated",):
            stated[f"{a.topic}: {signal}"] += 1
    return {
        "what_it_is": (
            "Whether OSM's value may share an origin with the City's, from what OSM's edit "
            "history states under PA-GEO-04's rules, unchanged. apparently_independent is what "
            "the metadata states, not proven independence. Assessed only where both sources "
            "assert something."
        ),
        "by_topic": by_topic,
        "osm_values_by_stated_source_of_their_introducing_edit": dict(sorted(stated.items())),
    }


#: What each date dates, as the evidence states it.
DATE_MEANINGS = {
    "source_capture_date": "City SOURCE_DATE: when the record was captured; for orthoimagery, "
    "the photographs' date. Not an observation of any attribute.",
    "observation_date": "When the value was observed: an OSM check_date or survey:date tag, or "
    "the edit of a survey app that entered it. The City supplies none.",
    "inspection_year": "City LAST_INSPECTION_YEAR: the year of an inspection, not what it found.",
    "record_created_at": "City CREATE_DATE: database maintenance.",
    "record_modified_at": "City UPDATE_DATE: database maintenance, mostly one bulk day. Never "
    "freshness.",
    "osm_edit_timestamp": "When the OSM element last changed in any way: an edit, not an "
    "observation.",
    "osm_value_since": "When OSM's current value entered OSM, from the element's history.",
}
#: Dates whose years are worth showing: the ones that say how old evidence is.
_YEARS = ("source_capture_date", "observation_date", "inspection_year", "osm_value_since")


def freshness_summary(reconciled: Reconciled) -> dict[str, Any]:
    """Which dates each source's usable assertions carry, and how old they are."""
    result: dict[str, Any] = {"date_meanings": DATE_MEANINGS}
    for source in (KITCHENER_SOURCE, OSM_SOURCE):
        mine = [a for a in reconciled.assertions.values() if a.source_id == source and a.usable]
        years: dict[str, dict[str, int]] = {}
        for name in _YEARS:
            values = [getattr(a.dates, name) for a in mine]
            present = [str(v)[:4] for v in values if v is not None]
            if present:
                years[name] = _count(present)
        result[source] = {
            "usable_assertions": len(mine),
            "with_date": {
                name: sum(1 for a in mine if getattr(a.dates, name) is not None)
                for name in DATE_MEANINGS
            },
            "freshness_basis": _count(a.dates.freshness_basis for a in mine),
            "observation_date_basis": _count(
                str(a.dates.observation_date_basis) for a in mine if a.dates.observation_date
            ),
            "years": years,
        }
    return result


def value_pairs(rows: Sequence[Reconciliation]) -> list[dict[str, Any]]:
    """Every distinct pair of values the vocabulary classified, with its count."""
    counts: Counter[tuple[str, str, str, str, str, str, str]] = Counter()
    for r in rows:
        counts[
            (
                str(r.topic),
                r.prop,
                "; ".join(r.kitchener_values) or "-",
                "; ".join(r.osm_values) or "-",
                str(r.relationship),
                str(r.specificity),
                r.rule,
            )
        ] += 1
    return [
        {
            "topic": topic,
            "property": prop,
            "kitchener": city,
            "osm": osm,
            "relationship": rel,
            "specificity": spec,
            "rule": rule,
            "rows": n,
        }
        for (topic, prop, city, osm, rel, spec, rule), n in sorted(
            counts.items(), key=lambda kv: (kv[0][0], kv[0][1], -kv[1], kv[0])
        )
    ]


def _assertion_case(a: Assertion) -> dict[str, Any]:
    row = assertion_row(a)
    keep = (
        "assertion_id",
        "raw_attribute",
        "raw_value",
        "normalized_value",
        "value_state",
        "evidence_origin",
        "capture_source",
        "source_record_version",
        "source_capture_date",
        "observation_date",
        "observation_date_basis",
        "inspection_year",
        "record_created_at",
        "record_modified_at",
        "osm_edit_timestamp",
        "osm_value_since",
        "introducing_changeset",
        "stated_sources",
    )
    return {k: row[k] for k in keep if row[k] not in (None, [])}


def casebook(reconciled: Reconciled, relationship: Relationship) -> dict[str, Any]:
    """Every row with this relationship, both sides' assertions in full. Nothing resolved."""
    rows = [r for r in reconciled.reconciliations if r.relationship is relationship]
    constant: dict[str, Any] = {"matcher": ACCEPTED_MATCHER}
    if rows:
        constant.update(
            {
                "evidence_state": str(rows[0].evidence_state),
                "conflict": rows[0].conflict,
                "routing_eligibility": rows[0].routing_eligibility,
            }
        )
    cases = [
        {
            "reconciliation_id": r.reconciliation_id,
            "target": {
                "element": r.target.element,
                "osm_version": r.target.osm_version,
                "from_m": r.target.from_m,
                "to_m": r.target.to_m,
            },
            "kitchener_records": list(r.source_records),
            "correspondence": {
                "rules": list(r.correspondence_rules),
                "relationship": r.correspondence_relationship,
            },
            "kitchener": [
                _assertion_case(reconciled.assertions[a]) for a in r.kitchener_assertions
            ],
            "osm": [_assertion_case(reconciled.assertions[a]) for a in r.osm_assertions],
            "specificity": str(r.specificity),
            "rule": r.rule,
            "lineage": str(r.lineage),
            "lineage_basis": r.lineage_basis,
            "target_geometry_lineage": r.target_geometry_lineage,
            "blockers": list(r.blockers),
        }
        for r in rows
    ]
    return {"every_case": constant, "cases": cases}


def reconciliation_evidence(
    run_inputs: RunInputs,
    reconciled: Reconciled,
    files: Mapping[str, Mapping[str, Any]],
    history_identity: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The committed summary of one run. Counts and cases, never the whole combined table."""
    rows = reconciled.reconciliations
    records = {r.activetransportid: r for r in run_inputs.conflation.population.records}
    locations = Counter(str(v) for v in reconciled.kerb_locations.values())
    decisions = run_inputs.geo05.decisions
    accepted_any = sum(1 for g in reconciled.gates.values() if g.accepted)
    return {
        "kitchener_geo06_reconciliation_version": EVIDENCE_VERSION,
        "what_it_is": (
            "PA-GEO-06 research: what OpenStreetMap and the City of Kitchener each assert about "
            "surfaces, curb ramps and structures where PA-GEO-05's frozen matcher made a "
            "correspondence this card accepts. Both sides are kept; nothing is resolved, "
            "nothing is routed on, and no figure here is a validated accuracy."
        ),
        "versions": VERSIONS,
        "inputs": {
            **run_inputs.identity,
            "osm_history": history_identity,
        },
        "sources": [
            {k: list(v) if isinstance(v, tuple) else v for k, v in _fields(s).items()}
            for s in run_inputs.sources
        ],
        "accepted_inputs": {
            "decisions": len(decisions),
            "decisions_by_state": _count(d.state for d in decisions.values()),
            "decisions_with_any_accepted_topic": accepted_any,
            "by_class": class_accounting(records, decisions, reconciled.gates),
            "kerb_nodes_named_by_accepted_curb_cuts": len(reconciled.kerb_claims),
            "kerb_nodes_named_by_several_curb_cuts": sum(
                1 for ids in reconciled.kerb_claims.values() if len(ids) > 1
            ),
            "osm_kerb_locations": dict(sorted(locations.items())),
        },
        "outcomes": outcomes(rows),
        "coverage": {
            "what_it_is": (
                "Potential evidence coverage if eligible municipal assertions were included, "
                "over this card's targets only. Not validated coverage, production coverage or "
                "routing coverage. A City-only assertion is an additional source assertion not "
                "represented in the compared OSM field, not a correction."
            ),
            "surface": {
                **coverage(rows, Topic.SURFACE),
                "unit": "a City record's local extent on one OSM way",
            },
            "curb_ramp": {
                **coverage(rows, Topic.CURB_RAMP),
                "unit": "an OSM kerb node: accepted City curb cuts, and nodes where the City has "
                "a facility within 10 m and no curb cut within 3 m",
            },
            "structure": {
                **coverage(rows, Topic.STRUCTURE),
                "unit": "a City record's local extent on one OSM way, per structure family, "
                "where either source asserts a structure",
            },
        },
        "lineage": lineage_summary(reconciled),
        "freshness": freshness_summary(reconciled),
        "value_pairs": value_pairs(rows),
        "conflict_casebook": {
            "what_it_is": (
                "Every conflict, with both assertions, their dates and provenance, the "
                "correspondence and the lineage. Nothing is resolved: a conflict does not say "
                "which source is wrong, and either may be."
            ),
            **casebook(reconciled, Relationship.CONFLICT),
        },
        "incomparable_cases": casebook(reconciled, Relationship.INCOMPARABLE),
        "routing": {
            "routing_eligibility": _count(r.routing_eligibility for r in rows),
            "blockers": _count(b for r in rows for b in r.blockers),
            "eligible_rows": sum(1 for r in rows if r.routing_eligibility != NOT_ROUTING_ELIGIBLE),
        },
        "artifact": {
            "version": ARTIFACT_VERSION,
            "files": {k: dict(v) for k, v in sorted(files.items())},
            "bytes": sum(int(v["bytes"]) for v in files.values()),
            "stored": "the ignored data folder only; never committed and never read by routing",
        },
        "attribution": ATTRIBUTION,
        "licensing": (
            "The founder licensing gate stays closed: the City permits this research use; it "
            "separately permits its data in OSM; OSMF LWG approval of its licence is not "
            "confirmed. No Kitchener assertion reaches routing, explanations or a published "
            "derived database."
        ),
    }


def reconciliation_manifest(
    run_inputs: RunInputs,
    files: Mapping[str, Mapping[str, Any]],
    history_identity: Mapping[str, Any] | None,
    run_measurements: Mapping[str, Any],
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "artifact_version": ARTIFACT_VERSION,
        "purpose": "PA-GEO-06 research artifact: never read by routing",
        "versions": VERSIONS,
        "inputs": {**run_inputs.identity, "osm_history": history_identity},
        "files": {k: dict(v) for k, v in sorted(files.items())},
        "attribution": ATTRIBUTION,
    }
    document["content_sha256"] = content_sha256(document)
    document["run"] = dict(run_measurements)
    return document
