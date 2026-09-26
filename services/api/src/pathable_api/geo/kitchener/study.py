"""PA-GEO-04: how the Kitchener sample relates to OpenStreetMap, and where OSM's data came from.

Inputs, each verified by hash before use:

- the PA-GEO-03 sample (``kitchener-geo04-sample.geojson``) — the 80 records,
  never re-drawn;
- the normalized Kitchener GeoParquet it was drawn from, for every other
  record (neighbours, and the N:1 question);
- the frozen OSM study extract, cut from the exact file PathAble's routing
  dataset was built from;
- optionally, the OSM history gathered by ``kitchener lineage-history``, and
  the reviewer's label files.

Without labels the study writes candidates and a review page to label from.
With them it writes the evidence: labels, topology facts, lineage from
history, attribute comparisons, repeat-label consistency and what the labels
say about matching signals. Nothing is written to PathAble and nothing here can
change a route: no Kitchener value is joined to an edge.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import shapely

from pathable_api.geo.kitchener.correspondence import (
    CANDIDATE_RADIUS_M,
    NODE_NEAR_M,
    KitchenerFeature,
    KitchenerIndex,
    OsmIndex,
    candidates_for,
    ends,
    kitchener_end_neighbours,
    kitchener_family,
    nodes_near,
    osm_class,
    osm_end_junctions,
    road_context,
    to_native,
)
from pathable_api.geo.kitchener.lineage import (
    DEFINITION_REFINEMENTS,
    DEFINITIONS,
    DEFINITIONS_VERSION,
    RESTRICTED,
    Correspondence,
    ElementHistory,
    Lineage,
    RecordLabel,
    attribute_lineage,
    combine,
    geometry_lineage,
    parse_labels,
    raw_agreement,
)
from pathable_api.geo.kitchener.normalize import load_normalized
from pathable_api.geo.kitchener.osm_extract import StudyExtract, load_study_extract
from pathable_api.geo.kitchener.osm_history import Changeset, Contribution, iter_elements
from pathable_api.geo.kitchener.semantics import PUBLISHABLE_SOURCE_CLASSES, SourceClass
from pathable_api.geo.overture.evidence import content_sha256, file_sha256

STUDY_FORMAT_VERSION = 1

#: Candidates at most this far from a record get their history read.
HISTORY_NEAR_M = 10.0
#: The deterministic repeat-review subset: one record per stratum, then by hash to this size.
REPEAT_SEED = "pathable-pa-geo-04-repeat-v1"
REPEAT_TARGET = 40
#: When a candidate's vertices count as sitting on the City's (a lineage signal,
#: fixed before any history was read): at least this many pairs, this share of
#: the OSM vertices near the record, and this little spread about one shift.
VERTEX_MIN_PAIRS = 3
VERTEX_MIN_SHARE = 0.75
VERTEX_MAX_SPREAD_M = 0.3
#: A kerb node counts as the curb cut's when it is on a corresponding way or this near the record.
KERB_ASSOCIATION_M = 3.0

ATTRIBUTION = {
    "kitchener": (
        "Contains information licensed under the Open Government Licence - The Corporation of "
        "the City of Kitchener."
    ),
    "openstreetmap": (
        "© OpenStreetMap contributors, ODbL 1.0: the frozen extract PathAble's routing dataset "
        "was built from, element history through the ohsome API (HeiGIT), and changeset "
        "metadata from the OSM planet changeset dump."
    ),
}

_DETAIL_QUERY = """
SELECT activetransportid, category, subcategory, feature_type, structure, surface_material,
    state_surface_material, width_m, state_width_m, railing, state_railing, curbcut,
    state_curbcut, surface_condition, state_surface_condition, street, roadsegment_side,
    source, source_class, source_year, strftime(create_date, '%Y-%m-%d'),
    strftime(source_date, '%Y-%m-%d'), installation_year, last_inspection_year,
    strftime(condition_date, '%Y-%m-%d'), lifecycle, physical_class, network_role, role_note,
    length_m, part_count
FROM read_parquet(?) WHERE activetransportid IN (SELECT unnest(?))
"""
_DETAIL_FIELDS = (
    "activetransportid",
    "category",
    "subcategory",
    "feature_type",
    "structure",
    "surface_material",
    "state_surface_material",
    "width_m",
    "state_width_m",
    "railing",
    "state_railing",
    "curbcut",
    "state_curbcut",
    "surface_condition",
    "state_surface_condition",
    "street",
    "roadsegment_side",
    "source",
    "source_class",
    "source_year",
    "create_date",
    "source_date",
    "installation_year",
    "last_inspection_year",
    "condition_date",
    "lifecycle",
    "physical_class",
    "network_role",
    "role_note",
    "length_m",
    "part_count",
)
_FEATURE_QUERY = """
SELECT activetransportid, physical_class, network_role, subcategory, geometry_native
FROM read_parquet(?) WHERE activetransportid IS NOT NULL AND geometry_native IS NOT NULL
"""

Progress = Callable[[str], None]


class StudyError(RuntimeError):
    """The study's inputs do not belong together."""


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SampleFeature:
    activetransportid: int
    stratum: str
    rank: int
    properties: dict[str, Any]


@dataclass(slots=True)
class StudyInputs:
    sample: list[SampleFeature]
    identity: dict[str, Any]
    kitchener: KitchenerIndex
    details: dict[int, dict[str, Any]]
    osm: OsmIndex
    parquet: Path | None = None
    #: The study box, in longitude and latitude, as the OSM dataset recorded it.
    bounds: tuple[float, float, float, float] | None = None


def load_sample(
    path: Path, *, expected_sha256: str | None
) -> tuple[list[SampleFeature], dict[str, Any]]:
    actual = file_sha256(path)
    if expected_sha256 is not None and actual != expected_sha256:
        msg = f"{path.name} hashes to {actual}, not the recorded {expected_sha256}."
        raise StudyError(msg)
    document = json.loads(path.read_text("utf-8"))
    features = [
        SampleFeature(
            activetransportid=int(item["properties"]["activetransportid"]),
            stratum=str(item["properties"]["stratum"]),
            rank=int(item["properties"]["rank_in_stratum"]),
            properties=dict(item["properties"]),
        )
        for item in document["features"]
    ]
    metadata = document.get("metadata") or {}
    identity = {
        "file": path.name,
        "sha256": actual,
        "content_sha256": content_sha256(document),
        "records": len(features),
        "snapshot_id": metadata.get("snapshot_id"),
        "seed": metadata.get("seed"),
        "strata": {name: item["sampled"] for name, item in (metadata.get("strata") or {}).items()},
    }
    return features, identity


def load_inputs(
    sample_path: Path,
    normalized_dir: Path,
    extract_path: Path,
    extract_manifest_path: Path,
    *,
    expected_sample_sha256: str | None = None,
    progress: Progress | None = None,
) -> StudyInputs:
    say = progress or (lambda _message: None)
    sample, sample_identity = load_sample(sample_path, expected_sha256=expected_sample_sha256)
    parquet, normalized = load_normalized(normalized_dir)
    snapshot_id = normalized.get("snapshot_id") or normalized.get("snapshot", {}).get("snapshot_id")
    if sample_identity["snapshot_id"] != snapshot_id:
        msg = (
            f"the sample was drawn from snapshot {sample_identity['snapshot_id']}, the normalized "
            f"file is from {snapshot_id}."
        )
        raise StudyError(msg)
    manifest = json.loads(extract_manifest_path.read_text("utf-8"))
    recorded = manifest["output"]["sha256"]
    say("osm: loading the frozen extract...")
    extract = load_study_extract(extract_path, expected_sha256=recorded)
    transformer = to_native()
    osm = OsmIndex.build(extract, transformer)
    say(f"osm: {len(extract.ways)} ways, {len(osm.fact_ids)} tagged nodes indexed.")
    features, details = _kitchener(parquet, [f.activetransportid for f in sample])
    kitchener = KitchenerIndex.build(features)
    missing = [f.activetransportid for f in sample if f.activetransportid not in kitchener.features]
    if missing:
        msg = f"sample records without a geometry in the normalized file: {missing}"
        raise StudyError(msg)
    say(f"kitchener: {len(kitchener.ids)} records indexed.")
    identity = {
        "kitchener": {
            "snapshot_id": snapshot_id,
            "normalized_file": parquet.name,
            "normalized_sha256": normalized["output"]["sha256"],
            "sample": sample_identity,
        },
        "osm_frozen": {
            "role": (
                "the geometry and tags every comparison is made against: PathAble's own source "
                "extract, not live OSM"
            ),
            "dataset": manifest["dataset"],
            "extract_file": manifest["output"]["file"],
            "extract_sha256": recorded,
            "extract_counts": manifest.get("counts"),
            "selection": manifest.get("selection"),
        },
    }
    box = manifest["dataset"].get("source_bbox")
    bounds = (float(box[0]), float(box[1]), float(box[2]), float(box[3])) if box else None
    return StudyInputs(sample, identity, kitchener, details, osm, parquet, bounds)


def _kitchener(
    parquet: Path, sample_ids: Sequence[int]
) -> tuple[list[KitchenerFeature], dict[int, dict[str, Any]]]:
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("SET autoinstall_known_extensions = false")
        connection.execute("SET autoload_known_extensions = false")
        rows = connection.execute(_FEATURE_QUERY, [parquet.as_posix()]).fetchall()
        detail_rows = connection.execute(
            _DETAIL_QUERY, [parquet.as_posix(), list(sample_ids)]
        ).fetchall()
    finally:
        connection.close()
    geometries = shapely.from_wkb([bytes(row[4]) for row in rows])
    features = [
        KitchenerFeature(int(row[0]), str(row[1]), str(row[2]), row[3], geometry)
        for row, geometry in zip(rows, geometries, strict=True)
    ]
    details = {}
    for row in detail_rows:
        item = dict(zip(_DETAIL_FIELDS, row, strict=True))
        # SOURCE may name a member of staff: publish it only for classes known not to.
        if item["source_class"] not in {str(kind) for kind in PUBLISHABLE_SOURCE_CLASSES}:
            item["source"] = None
        details[int(item["activetransportid"])] = item
    return features, details


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


def municipal_since(detail: Mapping[str, Any]) -> str | None:
    """The earliest date the City's record can have existed: its creation or source date."""
    dates = [d for d in (detail.get("create_date"), detail.get("source_date")) if d]
    return min(dates) if dates else None


def analyse(inputs: StudyInputs, *, progress: Progress | None = None) -> dict[str, Any]:
    """Candidates and context for every sampled record. Deterministic."""
    say = progress or (lambda _message: None)
    records: list[dict[str, Any]] = []
    elements: dict[str, dict[str, Any]] = {}
    for feature in inputs.sample:
        record_id = feature.activetransportid
        geometry = inputs.kitchener.features[record_id].geometry
        detail = inputs.details[record_id]
        family = kitchener_family(
            detail["subcategory"], detail["feature_type"], detail["network_role"]
        )
        road = road_context(geometry, detail["street"], inputs.osm)
        candidates = candidates_for(geometry, family, road, inputs.osm, inputs.kitchener)
        near_nodes = nodes_near(geometry, inputs.osm)
        for candidate in candidates:
            _remember_way(elements, candidate.osm_id, inputs.osm)
        if road.osm_id is not None:
            _remember_way(elements, road.osm_id, inputs.osm)
        records.append(
            {
                "activetransportid": record_id,
                "stratum": feature.stratum,
                "rank_in_stratum": feature.rank,
                "family": family,
                "kitchener": _kitchener_view(detail),
                "municipal_since": municipal_since(detail),
                "road": road.as_dict(),
                "candidate_count": len(candidates),
                "candidates": [c.as_dict() for c in candidates],
                "nodes_near": near_nodes,
                "kitchener_end_neighbours": kitchener_end_neighbours(
                    record_id, geometry, inputs.kitchener
                ),
            }
        )
    say(f"candidates: {sum(r['candidate_count'] for r in records)} for {len(records)} records.")
    return {"records": records, "osm_elements": dict(sorted(elements.items()))}


def _remember_way(elements: dict[str, dict[str, Any]], way_id: int, osm: OsmIndex) -> None:
    key = f"way/{way_id}"
    if key in elements:
        return
    way = osm.extract.ways[way_id]
    elements[key] = {
        "version": way.version,
        "timestamp": way.timestamp,
        "tags": dict(sorted(way.tags.items())),
        "osm_class": osm_class(way.tags),
        "length_m": round(float(osm.lines[way_id].length), 2),
        "end_junctions": osm_end_junctions(way_id, osm),
    }


def _kitchener_view(detail: Mapping[str, Any]) -> dict[str, Any]:
    view = {key: detail[key] for key in _DETAIL_FIELDS if key != "activetransportid"}
    if isinstance(view.get("width_m"), float):
        view["width_m"] = round(view["width_m"], 2)
    if isinstance(view.get("length_m"), float):
        view["length_m"] = round(view["length_m"], 2)
    view["restricted_lineage"] = (
        RESTRICTED if detail.get("source_class") == str(SourceClass.STREET_LEVEL_IMAGERY) else None
    )
    return view


def history_elements(analysis: Mapping[str, Any], *, near_m: float = HISTORY_NEAR_M) -> list[str]:
    """The OSM elements whose history the study reads: near candidates and tagged nodes."""
    wanted: set[str] = set()
    for record in analysis["records"]:
        for candidate in record["candidates"]:
            # Evidence files keep only identity and distance for far candidates.
            metrics = candidate.get("metrics") or candidate
            if metrics["min_distance_m"] <= near_m:
                wanted.add(candidate["osm"])
        for node in record["nodes_near"]:
            wanted.add(node["osm"])
    return sorted(wanted, key=lambda e: (e.split("/")[0], int(e.split("/")[1])))


def repeat_subset(sample: Sequence[SampleFeature], *, target: int = REPEAT_TARGET) -> list[int]:
    """One record from every stratum, then the rest by hash, to ``target`` records."""

    def key(record_id: int) -> str:
        return hashlib.sha256(f"{REPEAT_SEED}:{record_id}".encode()).hexdigest()

    chosen: list[int] = []
    for stratum in dict.fromkeys(f.stratum for f in sample):
        members = sorted((f.activetransportid for f in sample if f.stratum == stratum), key=key)
        chosen.append(members[0])
    rest = sorted(
        (f.activetransportid for f in sample if f.activetransportid not in chosen), key=key
    )
    chosen.extend(rest[: max(target - len(chosen), 0)])
    return sorted(chosen)


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class History:
    elements: dict[str, ElementHistory]
    changesets: dict[int, Changeset]
    identity: dict[str, Any]


def load_history(path: Path) -> History:
    document = json.loads(path.read_text("utf-8"))
    elements = {}
    for element, item in document["elements"].items():
        contributions = tuple(
            Contribution(
                element=element,
                timestamp=c["timestamp"],
                version=c["version"],
                changeset=int(c["changeset"]),
                creation=bool(c["creation"]),
                deletion=bool(c["deletion"]),
                geometry_change=bool(c["geometry_change"]),
                tag_change=bool(c["tag_change"]),
                tags=dict(c["tags"]),
            )
            for c in item["contributions"]
        )
        elements[element] = ElementHistory(
            element, contributions, bool(item["reaches_frozen_state"]), item.get("note")
        )
    changesets = {int(k): Changeset.from_dict(v) for k, v in document["changesets"].items()}
    return History(elements, changesets, document["identity"])


def completeness(
    element: str, contributions: Sequence[Contribution], extract: StudyExtract
) -> tuple[bool, str | None]:
    """Whether the history reaches the state frozen in the extract."""
    kind, _, number = element.partition("/")
    if not contributions:
        return False, "no contributions within the history's extent"
    last = contributions[-1]
    if kind == "way":
        way = extract.ways.get(int(number))
        if way is None:
            return False, "not in the frozen extract"
        frozen_version = way.version
        frozen = [(extract.nodes[r].lon, extract.nodes[r].lat) for r in way.refs]
    else:
        node = extract.nodes.get(int(number))
        if node is None:
            return False, "not in the frozen extract"
        frozen_version = node.version
        frozen = [(node.lon, node.lat)]
    if frozen_version is not None and (last.version or 0) < frozen_version:
        return False, (
            f"the frozen extract holds version {frozen_version}; the history ends at "
            f"version {last.version}"
        )
    if last.coordinates is not None and not _same_coordinates(last.coordinates, frozen):
        return False, "the frozen geometry differs from the history's last state"
    return True, None


def _same_coordinates(
    first: Sequence[tuple[float, float]], second: Sequence[tuple[float, float]]
) -> bool:
    if len(first) != len(second):
        return False
    return all(
        abs(a[0] - b[0]) <= 2e-7 and abs(a[1] - b[1]) <= 2e-7
        for a, b in zip(first, second, strict=True)
    )


def history_document(
    contributions: Iterable[Contribution],
    changesets: Mapping[int, Changeset],
    extract: StudyExtract,
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    """The history cache: contributions per element, completeness, changesets."""
    elements = {}
    for element, items in iter_elements(contributions):
        reaches, note = completeness(element, items, extract)
        elements[element] = {
            "contributions": [c.as_dict() for c in items],
            "reaches_frozen_state": reaches,
            "note": note,
        }
    return {
        "kitchener_geo04_history_version": 1,
        "identity": dict(identity),
        "elements": elements,
        "changesets": {str(k): changesets[k].as_dict() for k in sorted(changesets)},
    }


# ---------------------------------------------------------------------------
# Labels, topology, lineage and attributes
# ---------------------------------------------------------------------------


def _candidates_by_osm(record: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["osm"]: c for c in record["candidates"]}


def vertex_coincidence(candidate: Mapping[str, Any]) -> bool:
    vertices = candidate["vertices"]
    near = vertices["osm_vertices_within_3m"]
    paired = vertices["paired_with_kitchener_vertex_within_2m"]
    spread = vertices["displacement_spread_m"]
    return (
        paired >= VERTEX_MIN_PAIRS
        and near > 0
        and paired / near >= VERTEX_MIN_SHARE
        and spread is not None
        and spread <= VERTEX_MAX_SPREAD_M
    )


def topology_facts(
    record: Mapping[str, Any], label: RecordLabel, inputs: StudyInputs
) -> dict[str, Any] | None:
    """Deterministic facts behind the reviewer's topology label."""
    ways = [int(osm.split("/")[1]) for osm in label.osm if osm.startswith("way/")]
    if not ways:
        return None
    geometry = inputs.kitchener.features[record["activetransportid"]].geometry
    osm = inputs.osm
    end_nodes = {
        ref: osm.node_ways.get(ref, [])
        for way in ways
        for ref in (osm.extract.ways[way].refs[0], osm.extract.ways[way].refs[-1])
    }
    transformer = to_native()
    points = {}
    for ref in end_nodes:
        node = osm.extract.nodes[ref]
        x, y = transformer.transform(node.lon, node.lat)
        points[ref] = shapely.Point(x, y)
    record_ends = []
    features = inputs.kitchener.features
    for end, neighbours in zip(ends(geometry), record["kitchener_end_neighbours"], strict=True):
        nearest = min(points, key=lambda ref: (points[ref].distance(end), ref))
        others = [w for w in end_nodes[nearest] if w not in ways]
        virtual = [n for n in neighbours if features[n].physical_class == "virtual_link"]
        record_ends.append(
            {
                "nearest_osm_end_node": f"node/{nearest}",
                "distance_m": round(float(points[nearest].distance(end)), 2),
                "kitchener_physical_records_touching": len(neighbours) - len(virtual),
                "kitchener_virtual_links_touching": len(virtual),
                "osm_ways_at_node": len(others),
                "osm_classes_at_node": sorted(
                    {osm_class(osm.extract.ways[w].tags) for w in others}
                ),
            }
        )
    by_osm = _candidates_by_osm(record)
    chosen = [by_osm[f"way/{w}"] for w in ways]
    return {
        "record_ends": record_ends,
        "same_road": _all_or_none(c["same_road_as_record"] for c in chosen),
        "same_side_of_road": _all_or_none(c["same_side_as_record"] for c in chosen),
        "record_crosses_road": record["road"]["record_crosses_road"],
        "osm_crosses_same_road": _all_or_none(c["crosses_record_road"] for c in chosen),
        "street_matches_kitchener_street": record["road"]["street_matches_kitchener_street"],
    }


def _all_or_none(values: Iterable[bool | None]) -> bool | None:
    known = [v for v in values if v is not None]
    if not known:
        return None
    return all(known)


def record_lineage(
    record: Mapping[str, Any], label: RecordLabel, history: History | None
) -> dict[str, Any] | None:
    ways = [osm for osm in label.osm if osm.startswith("way/")]
    if not ways:
        return None
    if history is None:
        return {"geometry": None, "ways": {}}
    by_osm = _candidates_by_osm(record)
    per_way: dict[str, Any] = {}
    labels: list[Lineage] = []
    for way in ways:
        element = history.elements.get(way)
        if element is None:
            per_way[way] = {"label": str(Lineage.UNKNOWN), "reasons": ["no history read"]}
            labels.append(Lineage.UNKNOWN)
            continue
        finding = geometry_lineage(
            element,
            history.changesets,
            municipal_since=record["municipal_since"],
            vertex_coincidence=vertex_coincidence(by_osm[way]),
        )
        per_way[way] = finding.as_dict()
        labels.append(finding.label)
    combined = combine(labels)
    return {"geometry": str(combined) if combined else None, "ways": per_way}


# Kitchener material → OSM surface values that name the same material.
SURFACE_SAME: dict[str, frozenset[str]] = {
    "ASPHALT": frozenset({"asphalt"}),
    "ASPHALT (PAINTED)": frozenset({"asphalt"}),
    "CONCRETE": frozenset({"concrete", "concrete:plates", "concrete:lanes"}),
    "BRICK": frozenset({"paving_stones", "bricks", "brick"}),
    "COBBLESTONE": frozenset({"sett", "cobblestone", "unhewn_cobblestone"}),
    "STONE": frozenset({"stone", "paving_stones", "sett"}),
    "STONEDUST": frozenset({"fine_gravel", "compacted"}),
    "GRAVEL": frozenset({"gravel", "pebblestone"}),
    "NATURAL": frozenset({"ground", "dirt", "earth", "grass", "mud", "sand"}),
    "WOOD": frozenset({"wood"}),
    "STEEL": frozenset({"metal", "metal_grid"}),
    "TAR AND CHIP": frozenset({"chipseal"}),
}
UNPAVED_MATERIALS = frozenset({"STONEDUST", "GRAVEL", "NATURAL"})


def compare_surface(material: str, osm_surface: str | None) -> str:
    """``same``, ``same_coarser`` (OSM says only paved/unpaved), ``conflict`` or ``kitchener_only``."""
    if osm_surface is None:
        return "kitchener_only"
    value = osm_surface.strip().lower()
    if value in SURFACE_SAME.get(material, frozenset()):
        return "same"
    paved = material not in UNPAVED_MATERIALS
    if (value == "paved" and paved) or (value == "unpaved" and not paved):
        return "same_coarser"
    return "conflict"


#: The narrowest fact CURBCUT = Y supports is the City's own definition: the
#: facility is "a curbcut down to street level". OSM kerb values consistent with
#: that, and values that contradict it. Anything else says something different.
KERB_CONSISTENT = frozenset({"lowered", "flush"})
KERB_CONFLICT = frozenset({"raised"})

STRUCTURE_TAGS = {
    "STAIRS": ("highway", frozenset({"steps"})),
    "BRIDGE": ("bridge", None),
    "OVERPASS": ("bridge", None),
    "UNDERPASS": ("tunnel", None),
    "BOARDWALK": ("bridge", frozenset({"boardwalk"})),
}


def attribute_comparisons(
    record: Mapping[str, Any],
    label: RecordLabel | None,
    elements: Mapping[str, Mapping[str, Any]],
    history: History | None,
) -> dict[str, Any]:
    """What OSM says about each high-value Kitchener attribute of one record."""
    kitchener = record["kitchener"]
    if kitchener.get("restricted_lineage"):
        # A record the City sourced from street-level imagery: its assertions
        # are not evidence, so nothing is compared.
        return {"restricted": str(kitchener["restricted_lineage"])}
    ways = [o for o in (label.osm if label else ()) if o.startswith("way/")]
    corresponded = label is not None and label.correspondence in (
        Correspondence.OBVIOUS,
        Correspondence.AMBIGUOUS,
    )
    since = record["municipal_since"]
    results: dict[str, Any] = {}

    def lineage_of(element: str, key: str) -> dict[str, Any] | None:
        if history is None or element not in history.elements:
            return None
        finding = attribute_lineage(
            history.elements[element], history.changesets, key, municipal_since=since
        )
        return finding.as_dict() if finding else None

    if kitchener["curbcut"] == "Y" and kitchener["state_curbcut"] == "non_default":
        associated = [
            node
            for node in record["nodes_near"]
            if "kerb" in node["osm_tags"]
            and (node["distance_m"] <= KERB_ASSOCIATION_M or set(node["on_ways"]) & set(ways))
        ]
        values = sorted({node["osm_tags"]["kerb"] for node in associated})
        crossing_near = any(
            node["osm_tags"].get("highway") == "crossing" or "crossing" in node["osm_tags"]
            for node in record["nodes_near"]
        ) or any(
            elements[c["osm"]]["osm_class"] == "crossing"
            for c in record["candidates"]
            if c["metrics"]["min_distance_m"] <= NODE_NEAR_M
        )
        if not values:
            comparison = "kitchener_only"
        elif set(values) & KERB_CONSISTENT and not set(values) & KERB_CONFLICT:
            comparison = "same"
        elif set(values) <= KERB_CONFLICT:
            comparison = "conflict"
        else:
            comparison = "semantics_mismatch"
        results["curb_cut"] = {
            "kitchener": "CURBCUT = Y: 'a curbcut down to street level' (the City's definition)",
            "osm_correspondence": str(label.correspondence) if label else None,
            "osm_crossing_near": crossing_near,
            "osm_kerb_nodes": [
                {
                    "osm": n["osm"],
                    "kerb": n["osm_tags"]["kerb"],
                    "distance_m": n["distance_m"],
                    "lineage": lineage_of(n["osm"], "kerb"),
                }
                for n in associated
            ],
            "osm_kerb_values": values,
            "comparison": comparison,
        }

    structure = kitchener["structure"]
    if structure in STRUCTURE_TAGS:
        key, accepted = STRUCTURE_TAGS[structure]
        found = []
        for way in ways:
            tags = elements[way]["tags"]
            value = tags.get(key)
            if value is not None and value != "no" and (accepted is None or value in accepted):
                found.append({"osm": way, "tag": f"{key}={value}", "lineage": lineage_of(way, key)})
        results["structure"] = {
            "kitchener": f"FEATURE_TYPE = {structure}",
            "osm_correspondence": str(label.correspondence) if label else None,
            "osm_structure": found,
            "osm_tags_on_corresponding_ways": {
                w: _structure_tags(elements[w]["tags"]) for w in ways
            },
            "comparison": (
                "not_comparable" if not corresponded else "same" if found else "kitchener_only"
            ),
        }

    if kitchener["railing"] == "Y" and kitchener["state_railing"] == "non_default":
        handrails = {
            way: {k: v for k, v in elements[way]["tags"].items() if k.startswith("handrail")}
            for way in ways
        }
        handrail_values = {v for tags in handrails.values() for v in tags.values()}
        results["railing"] = {
            "kitchener": "RAILING = Y",
            "osm_handrail_tags": handrails,
            "comparison": (
                "not_comparable"
                if not corresponded
                else "kitchener_only"
                if not handrail_values
                else "conflict"
                if handrail_values == {"no"}
                else "same"
            ),
        }

    material = kitchener["surface_material"]
    if kitchener["state_surface_material"] == "non_default" and material:
        per_way = {way: elements[way]["tags"].get("surface") for way in ways}
        outcomes = {way: compare_surface(material, value) for way, value in per_way.items()}
        results["surface"] = {
            "kitchener": f"SURFACE_MATERIAL = {material}",
            "osm_surface": per_way,
            "per_way": outcomes,
            "comparison": _surface_outcome(outcomes.values())
            if corresponded and ways
            else "not_comparable",
            "lineage": {
                way: lineage_of(way, "surface")
                for way, value in per_way.items()
                if value is not None
            },
        }

    condition = kitchener["surface_condition"]
    if (
        condition in ("FAIR", "POOR", "UNUSABLE")
        and kitchener["state_surface_condition"] == "non_default"
    ):
        osm_condition = {
            way: {
                k: v
                for k, v in elements[way]["tags"].items()
                if k in ("smoothness", "surface:condition", "condition")
            }
            for way in ways
        }
        present = any(osm_condition.values())
        results["condition"] = {
            "kitchener": (
                f"SURFACE_CONDITION = {condition}, documented as found by the 2015 Trail "
                "inventory project: historical, not a current condition"
            ),
            "osm_condition_tags": osm_condition,
            "comparison": (
                "not_comparable"
                if not corresponded
                else "both_present"
                if present
                else "kitchener_only"
            ),
        }

    if record["family"] == "virtual_link":
        crossing_ways = [
            c["osm"]
            for c in record["candidates"]
            if elements[c["osm"]]["osm_class"] == "crossing"
            and c["metrics"]["min_distance_m"] <= 5.0
        ]
        crossing_nodes = [
            n["osm"]
            for n in record["nodes_near"]
            if n["osm_tags"].get("highway") == "crossing" or "crossing" in n["osm_tags"]
        ]
        results["virtual_link"] = {
            "kitchener": "a virtual street crossing: topology only, never a physical facility",
            "osm_crossing_ways_within_5m": crossing_ways,
            "osm_crossing_nodes_within_8m": crossing_nodes,
            "osm_correspondence": str(label.correspondence) if label else None,
        }
    osm_only = _osm_only(kitchener, ways, elements)
    if corresponded and osm_only:
        results["osm_only"] = osm_only
    return results


def _osm_only(
    kitchener: Mapping[str, Any], ways: Sequence[str], elements: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """What OSM says about the corresponding ways where the City asserts nothing.

    A City template default or unknown is not an assertion, so this is never a
    conflict: it is information only OSM has.
    """
    found: dict[str, Any] = {}
    if kitchener["state_surface_material"] != "non_default":
        surfaces = {
            w: elements[w]["tags"]["surface"] for w in ways if "surface" in elements[w]["tags"]
        }
        if surfaces:
            found["surface"] = surfaces
    if kitchener["structure"] is None:
        structures = {
            w: _structure_tags(elements[w]["tags"])
            for w in ways
            if elements[w]["tags"].get("highway") == "steps"
            or elements[w]["tags"].get("bridge", "no") != "no"
            or elements[w]["tags"].get("tunnel", "no") != "no"
        }
        if structures:
            found["structure"] = structures
    if kitchener["railing"] != "Y":
        handrails = {
            w: {k: v for k, v in elements[w]["tags"].items() if k.startswith("handrail")}
            for w in ways
            if any(k.startswith("handrail") for k in elements[w]["tags"])
        }
        if handrails:
            found["railing"] = handrails
    return found


def _structure_tags(tags: Mapping[str, str]) -> dict[str, str]:
    keys = (
        "highway",
        "bridge",
        "tunnel",
        "layer",
        "step_count",
        "ramp",
        "incline",
        "handrail",
        "covered",
    )
    return {k: v for k, v in tags.items() if k in keys or k.startswith(("handrail", "ramp"))}


def _surface_outcome(outcomes: Iterable[str]) -> str:
    values = set(outcomes)
    for outcome in ("conflict", "same", "same_coarser", "kitchener_only"):
        if outcome in values:
            if outcome == "conflict" and values & {"same", "same_coarser"}:
                return "mixed"
            return outcome
    return "not_comparable"


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


def summarise(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts over the labelled sample, physical and virtual records kept apart."""

    def group(record: Mapping[str, Any]) -> str:
        return (
            "virtual_or_connection"
            if record["family"] in ("virtual_link", "connection")
            else "physical_or_unresolved"
        )

    summary: dict[str, Any] = {}
    for name in ("all", "physical_or_unresolved", "virtual_or_connection"):
        chosen = [r for r in records if name == "all" or group(r) == name]
        labels = [r["labels"] for r in chosen if r.get("labels")]
        summary[name] = {
            "records": len(chosen),
            "correspondence": _count(label["correspondence"] for label in labels),
            "relationship": _count(
                label["relationship"] for label in labels if label["relationship"]
            ),
            "geometry": _count(label["geometry"] for label in labels if label["geometry"]),
            "topology": _count(label["topology"] for label in labels),
            "representation": _count(label["representation"] for label in labels),
            "geometry_lineage": _count(
                (r.get("lineage") or {}).get("geometry") or "not_assessed" for r in chosen
            ),
        }
    by_stratum: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        if record.get("labels"):
            by_stratum[record["stratum"]][record["labels"]["correspondence"]] += 1
    summary["correspondence_by_stratum"] = {
        k: dict(sorted(v.items())) for k, v in by_stratum.items()
    }
    return summary


def _count(values: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def matcher_signals(
    records: Sequence[Mapping[str, Any]], elements: Mapping[str, Any]
) -> dict[str, Any]:
    """What the labelled obvious correspondences say about candidate signals.

    For each record with an obvious correspondence, the reviewer's ways are
    "labelled", every other candidate "other". Reported: where the labelled
    way ranks under each signal alone, and the signal's values for labelled
    and other candidates. Descriptive only — no weights, no threshold.
    """
    signals: dict[str, Callable[[Mapping[str, Any]], float | None]] = {
        "min_distance_m": lambda c: c["metrics"]["min_distance_m"],
        "max_offset_m": lambda c: c["metrics"]["max_offset_m"],
        "median_offset_m": lambda c: c["metrics"]["median_offset_m"],
        "overlap_5m": lambda c: -c["metrics"]["overlap_5m"],
        "overlap_2m": lambda c: -c["metrics"]["overlap_2m"],
        "osm_share_within_5m": lambda c: -c["metrics"]["osm_share_within_5m"],
        "orientation_deg": lambda c: c["metrics"]["orientation_deg"],
        "nearest_endpoint_pair_m": lambda c: c["metrics"]["nearest_endpoint_pair_m"],
    }
    ranks: dict[str, Counter[str]] = {name: Counter() for name in signals}
    values: dict[str, dict[str, list[float]]] = {
        name: {"labelled": [], "other": []} for name in signals
    }
    categorical: dict[str, dict[str, Counter[str]]] = {
        name: {"labelled": Counter(), "other": Counter()}
        for name in ("class_compatibility", "same_side_as_record", "same_road_as_record")
    }
    failures: list[dict[str, Any]] = []
    considered = 0
    for record in records:
        label = record.get("labels")
        if not label or label["correspondence"] != str(Correspondence.OBVIOUS):
            continue
        chosen = {o for o in label["osm"] if o.startswith("way/")}
        if not chosen:
            continue
        considered += 1
        candidates = record["candidates"]
        for name, signal in signals.items():
            scored = [(signal(c), c["osm"]) for c in candidates if signal(c) is not None]
            scored.sort()
            best = [osm for _value, osm in scored[:1]]
            rank = "first" if best and best[0] in chosen else "not_first"
            ranks[name][rank] += 1
            if rank == "not_first" and name in ("min_distance_m", "overlap_5m", "max_offset_m"):
                failures.append(
                    {
                        "activetransportid": record["activetransportid"],
                        "signal": name,
                        "first": best[0] if best else None,
                        "labelled": sorted(chosen),
                    }
                )
            for c in candidates:
                value = signal(c)
                if value is not None:
                    group = "labelled" if c["osm"] in chosen else "other"
                    values[name][group].append(
                        abs(value) if name.startswith(("overlap", "osm_share")) else value
                    )
        for c in candidates:
            group = "labelled" if c["osm"] in chosen else "other"
            categorical["class_compatibility"][group][c["class_compatibility"]] += 1
            categorical["same_side_as_record"][group][str(c["same_side_as_record"])] += 1
            categorical["same_road_as_record"][group][str(c["same_road_as_record"])] += 1
    return {
        "records_with_obvious_way_correspondence": considered,
        "labelled_way_ranks_first": {k: dict(v) for k, v in ranks.items()},
        "distributions": {
            name: {group: _describe(items) for group, items in groups.items()}
            for name, groups in values.items()
        },
        "categorical": {
            name: {group: dict(sorted(counter.items())) for group, counter in groups.items()}
            for name, groups in categorical.items()
        },
        "rank_failures": failures,
    }


def _describe(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    array = np.asarray(values, dtype=float)
    return {
        "n": len(values),
        "min": round(float(array.min()), 2),
        "p25": round(float(np.percentile(array, 25)), 2),
        "median": round(float(np.median(array)), 2),
        "p75": round(float(np.percentile(array, 75)), 2),
        "max": round(float(array.max()), 2),
    }


def attribute_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """B14: for each attribute the City asserts, what OSM says, over the labelled sample."""
    summary: dict[str, Any] = {}
    for key in ("curb_cut", "structure", "railing", "surface", "condition", "virtual_link"):
        items = [r for r in records if key in (r.get("attributes") or {})]
        comparisons: Counter[str] = Counter()
        lineage: Counter[str] = Counter()
        examples: dict[str, list[int]] = defaultdict(list)
        corresponded = 0
        for record in items:
            block = record["attributes"][key]
            label = record.get("labels") or {}
            if label.get("correspondence") in (
                str(Correspondence.OBVIOUS),
                str(Correspondence.AMBIGUOUS),
            ):
                corresponded += 1
            outcome = block.get("comparison") or (
                "osm_crossing_way"
                if block.get("osm_crossing_ways_within_5m")
                else "osm_crossing_node_only"
                if block.get("osm_crossing_nodes_within_8m")
                else "no_osm_crossing"
            )
            comparisons[outcome] += 1
            examples[outcome].append(record["activetransportid"])
            for finding in _attribute_findings(block):
                lineage[finding] += 1
        summary[key] = {
            "sample_records": len(items),
            "corresponded": corresponded,
            "comparison": dict(sorted(comparisons.items())),
            "osm_value_lineage": dict(sorted(lineage.items())),
            "examples": {k: v[:6] for k, v in sorted(examples.items())},
        }
    osm_only: dict[str, list[int]] = defaultdict(list)
    for record in records:
        for key in (record.get("attributes") or {}).get("osm_only", {}):
            osm_only[key].append(record["activetransportid"])
    summary["osm_only"] = {
        key: {"records": len(ids), "examples": ids[:6]} for key, ids in sorted(osm_only.items())
    }
    return summary


def _attribute_findings(block: Mapping[str, Any]) -> list[str]:
    findings = [n["lineage"]["label"] for n in block.get("osm_kerb_nodes", []) if n.get("lineage")]
    findings += [s["lineage"]["label"] for s in block.get("osm_structure", []) if s.get("lineage")]
    findings += [f["label"] for f in (block.get("lineage") or {}).values() if f]
    return findings


def population_context(inputs: StudyInputs) -> dict[str, Any] | None:
    """Proximity, not correspondence: OSM kerb and steps near every in-area City record.

    Over every CURBCUT = Y record and every STAIRS record intersecting the
    study box — not the sample — how many have an OSM kerb node, or OSM steps,
    within :data:`KERB_ASSOCIATION_M`. Nothing here is a match; it says how much
    of the City's evidence has OSM information of the same kind beside it.
    """
    if inputs.parquet is None or inputs.bounds is None:
        return None
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("SET autoinstall_known_extensions = false")
        connection.execute("SET autoload_known_extensions = false")
        rows = connection.execute(
            "SELECT activetransportid, curbcut, state_curbcut, feature_type, geometry, "
            "geometry_native FROM read_parquet(?) WHERE geometry IS NOT NULL AND "
            "((curbcut = 'Y' AND state_curbcut = 'non_default') OR feature_type = 'STAIRS') "
            # Street-level-imagery-sourced records are never evidence.
            "AND source_class <> 'street_level_imagery'",
            [inputs.parquet.as_posix()],
        ).fetchall()
    finally:
        connection.close()
    box = shapely.box(*inputs.bounds)
    osm = inputs.osm
    steps = [w for w in osm.way_ids if osm.extract.ways[w].tags.get("highway") == "steps"]
    steps_tree = shapely.STRtree([osm.lines[w] for w in steps]) if steps else None
    curb: Counter[str] = Counter()
    stairs: Counter[str] = Counter()
    for _record_id, curbcut, _state, feature_type, geometry, native in rows:
        if not shapely.from_wkb(bytes(geometry)).intersects(box):
            continue
        line = shapely.from_wkb(bytes(native))
        if curbcut == "Y":
            hits = osm.fact_tree.query(line, predicate="dwithin", distance=KERB_ASSOCIATION_M)
            values = {
                osm.extract.nodes[osm.fact_ids[int(h)]].tags["kerb"]
                for h in hits
                if "kerb" in osm.extract.nodes[osm.fact_ids[int(h)]].tags
            }
            if not values:
                curb["no_osm_kerb_node_within_3m"] += 1
            elif values & KERB_CONSISTENT and not values & KERB_CONFLICT:
                curb["lowered_or_flush"] += 1
            elif values <= KERB_CONFLICT:
                curb["raised"] += 1
            else:
                curb["other_or_mixed"] += 1
        if feature_type == "STAIRS":
            near = (
                len(steps_tree.query(line, predicate="dwithin", distance=KERB_ASSOCIATION_M))
                if steps_tree is not None
                else 0
            )
            stairs["osm_steps_within_3m" if near else "no_osm_steps_within_3m"] += 1
    return {
        "what_this_is": (
            "Proximity over every in-area record, not correspondence: an OSM kerb node or steps "
            "within 3 m. A nearby value may belong to a different corner or stair."
        ),
        "curb_cut_records": sum(curb.values()),
        "curb_cut": dict(sorted(curb.items())),
        "stairs_records": sum(stairs.values()),
        "stairs": dict(sorted(stairs.items())),
    }


#: Candidates this near a record, or cited by a label, keep every metric in the
#: evidence; the rest keep their identity, class and distance.
EVIDENCE_NEAR_M = HISTORY_NEAR_M


def slim(document: dict[str, Any]) -> dict[str, Any]:
    """The committed evidence: every candidate listed, full metrics where they matter."""
    referenced: set[str] = set()
    records = []
    for record in document["records"]:
        cited = set((record.get("labels") or {}).get("osm", [])) | set(
            (record.get("repeat_labels") or {}).get("osm", [])
        )
        candidates = []
        for candidate in record["candidates"]:
            if (
                candidate["metrics"]["min_distance_m"] <= EVIDENCE_NEAR_M
                or candidate["osm"] in cited
            ):
                candidates.append(candidate)
                referenced.add(candidate["osm"])
            else:
                candidates.append(
                    {
                        "osm": candidate["osm"],
                        "osm_class": candidate["osm_class"],
                        "min_distance_m": candidate["metrics"]["min_distance_m"],
                    }
                )
        if record["road"]["osm"]:
            referenced.add(record["road"]["osm"])
        records.append({**record, "candidates": candidates})
    elements = {k: v for k, v in document["osm_elements"].items() if k in referenced}
    return {**document, "records": records, "osm_elements": elements}


# ---------------------------------------------------------------------------
# The whole study
# ---------------------------------------------------------------------------


def run_study(
    inputs: StudyInputs,
    *,
    history: History | None = None,
    labels: Mapping[str, Any] | None = None,
    repeat: Mapping[str, Any] | None = None,
    first_pass: Mapping[str, Any] | None = None,
    repeat_refined: Mapping[str, Any] | None = None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """The study. ``labels`` are the ones the results use.

    Consistency is measured between ``first_pass`` (default: ``labels``) and
    ``repeat``, both as labelled. When definitions were refined after comparing
    them, ``repeat_refined`` is the repeat pass re-reviewed under the refined
    definitions, compared with ``labels``: agreement after a refinement the
    disagreements prompted, which is not an independent measurement.
    """
    started = time.perf_counter()
    analysis = analyse(inputs, progress=progress)
    # A label may cite the candidate ways or the tagged nodes near the record.
    candidates = {
        r["activetransportid"]: [c["osm"] for c in r["candidates"]]
        + [n["osm"] for n in r["nodes_near"]]
        for r in analysis["records"]
    }
    primary = parse_labels(labels, candidates) if labels else {}
    second = parse_labels(repeat, candidates) if repeat else {}
    first = parse_labels(first_pass, candidates) if first_pass else primary
    refined = parse_labels(repeat_refined, candidates) if repeat_refined else {}
    elements = analysis["osm_elements"]
    records = []
    for record in analysis["records"]:
        record_id = record["activetransportid"]
        label = primary.get(record_id)
        item = dict(record)
        item["labels"] = label.as_dict() if label else None
        item["first_pass_labels"] = (
            first[record_id].as_dict() if first_pass and record_id in first else None
        )
        item["repeat_labels"] = second[record_id].as_dict() if record_id in second else None
        item["repeat_labels_refined"] = (
            refined[record_id].as_dict() if record_id in refined else None
        )
        item["topology_facts"] = topology_facts(record, label, inputs) if label else None
        item["lineage"] = record_lineage(record, label, history) if label else None
        item["attributes"] = attribute_comparisons(record, label, elements, history)
        records.append(item)
    document: dict[str, Any] = {
        "kitchener_geo04_lineage_version": STUDY_FORMAT_VERSION,
        "attribution": ATTRIBUTION,
        "inputs": {**inputs.identity, "osm_history": history.identity if history else None},
        "definitions": {
            "version": DEFINITIONS_VERSION,
            **{k: {str(n): text for n, text in v.items()} for k, v in DEFINITIONS.items()},
            "lineage": LINEAGE_DEFINITIONS,
        },
        "method": {
            "candidate_radius_m": CANDIDATE_RADIUS_M,
            "node_near_m": NODE_NEAR_M,
            "history_near_m": HISTORY_NEAR_M,
            "kerb_association_m": KERB_ASSOCIATION_M,
            "vertex_coincidence": {
                "min_pairs": VERTEX_MIN_PAIRS,
                "min_share": VERTEX_MIN_SHARE,
                "max_spread_m": VERTEX_MAX_SPREAD_M,
            },
            "repeat_subset": {
                "seed": REPEAT_SEED,
                "target": REPEAT_TARGET,
                "records": repeat_subset(inputs.sample),
            },
        },
        "records": records,
        "osm_elements": elements,
    }
    if primary:
        document["summary"] = summarise(records)
        document["attribute_results"] = attribute_summary(records)
        document["matcher_signals"] = matcher_signals(records, elements)
        document["population_context"] = population_context(inputs)
    if first and second:
        document["repeat_review"] = {
            "as_labelled": repeat_review(first, second),
            "after_refinement": repeat_review(primary, refined) if refined else None,
            "definition_refinements": list(DEFINITION_REFINEMENTS),
            "revisions": list((labels or {}).get("revisions", [])),
        }
    document["measurement"] = {"seconds": round(time.perf_counter() - started, 2)}
    document["content_sha256"] = content_sha256(document)
    return document


def repeat_review(
    primary: Mapping[int, RecordLabel], second: Mapping[int, RecordLabel]
) -> dict[str, Any]:
    both = sorted(set(primary) & set(second))
    obvious_both = [
        r
        for r in both
        if primary[r].correspondence is Correspondence.OBVIOUS
        and second[r].correspondence is Correspondence.OBVIOUS
    ]

    def collapsed(label: RecordLabel) -> str:
        return {
            Correspondence.OBVIOUS: "obvious",
            Correspondence.AMBIGUOUS: "ambiguous",
        }.get(label.correspondence, "unmatched_or_not_comparable")

    same_ways = sum(set(primary[r].osm) == set(second[r].osm) for r in obvious_both)
    return {
        "records": len(both),
        "kind": (
            "repeat-label consistency: the same labelling procedure repeated without sight of the "
            "first labels; not inter-rater reliability, so no chance-corrected statistic"
        ),
        "correspondence": raw_agreement(
            {r: str(primary[r].correspondence) for r in both},
            {r: str(second[r].correspondence) for r in both},
        ),
        "correspondence_collapsed": raw_agreement(
            {r: collapsed(primary[r]) for r in both}, {r: collapsed(second[r]) for r in both}
        ),
        "relationship_where_both_obvious": raw_agreement(
            {r: str(primary[r].relationship) for r in obvious_both},
            {r: str(second[r].relationship) for r in obvious_both},
        ),
        "same_osm_ways_where_both_obvious": {"records": len(obvious_both), "same": same_ways},
        "geometry_where_both_labelled": raw_agreement(
            {
                r: str(primary[r].geometry)
                for r in both
                if primary[r].geometry and second[r].geometry
            },
            {
                r: str(second[r].geometry)
                for r in both
                if primary[r].geometry and second[r].geometry
            },
        ),
        "topology": raw_agreement(
            {r: str(primary[r].topology) for r in both}, {r: str(second[r].topology) for r in both}
        ),
    }


LINEAGE_DEFINITIONS = {
    str(Lineage.KNOWN): (
        "A contribution that shaped the geometry (or set the attribute) states City of Kitchener "
        "data as its source: in the changeset's source, imagery or comment, or in the element's "
        "own source tags written by that contribution. A place name alone is not a source."
    ),
    str(Lineage.POSSIBLE): (
        "No statement of Kitchener data, but a statement of municipal orthoimagery, other "
        "government data or an unnamed import, or the OSM vertices coincide with the City's "
        "under one common displacement."
    ),
    str(Lineage.INDEPENDENT): (
        "Positive evidence only: every contribution that shaped it states survey, street-level "
        "imagery or unrelated imagery (an editor's own imagery record counts for geometry and for "
        "attributes visible from above, not for kerb heights), or it was last shaped before the "
        "City's record can have existed; and the history reaches the frozen state."
    ),
    str(Lineage.UNKNOWN): (
        "Anything else, including contributions that state no source at all: absence of a "
        "municipal source tag is not evidence of independence."
    ),
    RESTRICTED: (
        "A Kitchener record whose own SOURCE names street-level imagery. Its assertions are not "
        "used as evidence."
    ),
}
