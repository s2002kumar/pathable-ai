"""Put the profile, the study geography and the lineage sample into one evidence file.

Inputs are a frozen snapshot, its normalized GeoParquet file, and PathAble's
own dataset for the pilot region, read in a ``READ ONLY`` transaction. The
output is ``kitchener-active-transport-profile.json`` and the GeoJSON sample
for PA-GEO-04. Nothing is written to PathAble, and nothing here can change a
route: the Kitchener records are never joined to an edge.
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import shapely
from shapely.geometry.base import BaseGeometry

from pathable_api.geo.kitchener.adoption import adoption_matrix, exit_gate
from pathable_api.geo.kitchener.geography import (
    OFFSET_SAMPLE_SPACING_M,
    PathAbleEdges,
    RecordGeography,
    band,
    band_order,
    describe_records,
    graph_along_inventory,
    study_area,
)
from pathable_api.geo.kitchener.normalize import load_normalized
from pathable_api.geo.kitchener.profile import Profiler, build_profile
from pathable_api.geo.kitchener.sample import (
    MINIMUM_PER_STRATUM,
    SEED,
    TARGET,
    Candidate,
    draw_sample,
)
from pathable_api.geo.kitchener.semantics import schemas_from_layer
from pathable_api.geo.kitchener.snapshot import load_manifest
from pathable_api.geo.kitchener.source import ACTIVE_TRANSPORTATION, LICENCE_NAME
from pathable_api.geo.overture.evidence import content_sha256, write_json
from pathable_api.geo.regions import RegionDefinition

PROFILE_FORMAT_VERSION = 1

#: Metres around a record's midpoint within which other records count towards density.
DENSITY_RADIUS_M = 100.0
#: Records at or above this quantile of in-area sidewalk density are "dense".
DENSE_QUANTILE = 0.9

ATTRIBUTION = (
    "Contains information licensed under the Open Government Licence - The Corporation of the "
    "City of Kitchener. Proximity figures also use PathAble's graph: © OpenStreetMap "
    "contributors, ODbL 1.0."
)

_RECORDS_QUERY = """
SELECT activetransportid, identity_state, physical_class, network_role, lifecycle, category,
    subcategory, feature_type, structure, surface_material, width_m, railing, curbcut,
    surface_condition, source_class, source_year, length_m, part_count, roadsegmentid,
    roadsegment_side, in_active_transportation, in_walkability, geometry_issue,
    state_surface_material, state_width_m, state_curbcut, state_railing, state_surface_condition,
    geometry, geometry_native
FROM read_parquet(?)
"""


class AuditError(RuntimeError):
    """The inputs do not belong together, or cannot be read."""


@dataclass(frozen=True, slots=True)
class KitchenerRecord:
    activetransportid: int | None
    identity_state: str
    physical_class: str
    network_role: str
    lifecycle: str
    category: str | None
    subcategory: str | None
    feature_type: str | None
    structure: str | None
    surface_material: str | None
    width_m: float | None
    railing: str | None
    curbcut: str | None
    surface_condition: str | None
    source_class: str
    source_year: int | None
    length_m: float | None
    part_count: int | None
    roadsegmentid: int | None
    roadsegment_side: str | None
    in_active_transportation: bool
    in_walkability: bool
    geometry_issue: str | None
    state_surface_material: str
    state_width_m: str
    state_curbcut: str
    state_railing: str
    state_surface_condition: str
    primary: BaseGeometry | None
    native: BaseGeometry | None


@dataclass(slots=True)
class AuditResult:
    profile: dict[str, Any]
    sample: dict[str, Any]


def run_audit(
    snapshot: Path,
    normalized: Path,
    region: RegionDefinition,
    edges: PathAbleEdges,
    *,
    measure: Callable[[], dict[str, Any]] | None = None,
    progress: Callable[[str], None] | None = None,
) -> AuditResult:
    say = progress or (lambda _message: None)
    started = time.perf_counter()
    manifest = load_manifest(snapshot)
    parquet, normalized_manifest = load_normalized(normalized)
    if normalized_manifest["snapshot_id"] != manifest["snapshot_id"]:
        msg = (
            f"{normalized} was built from snapshot {normalized_manifest['snapshot_id'][:12]}, "
            f"not {manifest['snapshot_id'][:12]}."
        )
        raise AuditError(msg)
    retrieved_year = int(str(manifest["retrieved_at"])[:4])
    layer = json.loads(
        (snapshot / "metadata" / f"{ACTIVE_TRANSPORTATION.key}.layer.json").read_text("utf-8")
    )

    say("profile: querying the normalized file...")
    timer = time.perf_counter()
    profiler = Profiler(parquet)
    try:
        profile = build_profile(profiler, schemas_from_layer(layer), retrieved_year=retrieved_year)
    finally:
        profiler.close()
    profile_seconds = time.perf_counter() - timer

    say("geography: relating records to the study area and PathAble's graph...")
    timer = time.perf_counter()
    records = load_records(parquet)
    area = region.boundary()
    geography = describe_records(
        [r.primary for r in records], [r.native for r in records], area, edges
    )
    geography_seconds = time.perf_counter() - timer
    overlap = _overlap(records, geography, region, edges)

    say("sample: drawing the PA-GEO-04 lineage sample...")
    candidates = _candidates(records, geography)
    sampled, strata = draw_sample(candidates, manifest["snapshot_id"])
    by_id = {r.activetransportid: (r, g) for r, g in zip(records, geography, strict=True)}
    sample = _sample_geojson(sampled, strata, by_id, manifest["snapshot_id"])

    document: dict[str, Any] = {
        "kitchener_profile_version": PROFILE_FORMAT_VERSION,
        "attribution": ATTRIBUTION,
        "what_this_shows": (
            "What the City of Kitchener's published Active Transportation inventory contains, "
            "measured on one frozen snapshot: population, defaults, provenance, physical versus "
            "virtual records, and where it overlaps PathAble's Waterloo pilot."
        ),
        "what_this_does_not_show": [
            "That any Kitchener record describes the same thing as any OSM way or PathAble edge; "
            "proximity is descriptive and nothing is matched.",
            "That any attribute is true on the ground; nothing has been field-checked.",
            "That Kitchener evidence is independent of OpenStreetMap; the City permits its data "
            "in OSM and lineage has not been studied.",
            "Any effect on routing; no Kitchener field is used by PathAble.",
        ],
        "snapshot": _snapshot_summary(manifest),
        "normalized": {
            "file_sha256": normalized_manifest["output"]["sha256"],
            "bytes": normalized_manifest["output"]["bytes"],
            "rows": normalized_manifest["output"]["rows"],
            "geoparquet_version": normalized_manifest["geoparquet"]["version"],
            "crs": normalized_manifest["crs"],
            "joins": normalized_manifest["joins"],
            "content_sha256": normalized_manifest["content_sha256"],
        },
        **profile,
        "geography": overlap,
        "sample": {
            "file": "kitchener-geo04-sample.geojson",
            "method": sample["metadata"]["method"],
            "seed": SEED,
            "target": TARGET,
            "minimum_per_stratum": MINIMUM_PER_STRATUM,
            "records": len(sampled),
            "strata": strata,
            "content_sha256": content_sha256(sample),
        },
    }
    document["adoption"] = adoption_matrix(document)
    document["exit_gate"] = exit_gate(document)
    document["measurement"] = {
        "profile_seconds": round(profile_seconds, 2),
        "geography_seconds": round(geography_seconds, 2),
        "total_seconds": round(time.perf_counter() - started, 2),
        **(measure() if measure is not None else {}),
    }
    document["content_sha256"] = content_sha256(document)
    return AuditResult(profile=document, sample=sample)


def load_records(parquet: Path) -> list[KitchenerRecord]:
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("SET autoinstall_known_extensions = false")
        connection.execute("SET autoload_known_extensions = false")
        rows = connection.execute(_RECORDS_QUERY, [parquet.as_posix()]).fetchall()
    finally:
        connection.close()
    # The two geometry columns come last in the query, as in the dataclass.
    primary = shapely.from_wkb([bytes(row[-2]) if row[-2] is not None else None for row in rows])
    native = shapely.from_wkb([bytes(row[-1]) if row[-1] is not None else None for row in rows])
    names = [item.name for item in fields(KitchenerRecord)][:-2]
    return [
        KitchenerRecord(**dict(zip(names, row[:-2], strict=True)), primary=p, native=n)
        for row, p, n in zip(rows, primary, native, strict=True)
    ]


def write_outputs(result: AuditResult, profile_path: Path, sample_path: Path) -> None:
    write_json(profile_path, result.profile)
    write_json(sample_path, result.sample)


# ---------------------------------------------------------------------------
# Snapshot summary
# ---------------------------------------------------------------------------


def _snapshot_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    publications = {}
    for key, record in manifest["publications"].items():
        publications[key] = {
            "role": record["role"],
            "item_id": record["item"]["id"],
            "item_title": record["item"]["title"],
            "item_owner": record["item"]["owner"],
            "item_modified": record["item"]["modified"],
            "layer_url": record["layer"]["url"],
            "layer_name": record["layer"]["name"],
            "spatial_reference": record["layer"]["spatial_reference"],
            "edit_info": record["layer"]["edit_info"],
            "fields_published": len(record["layer"]["fields"]),
            "contract": record["layer"]["contract"],
            "features": record["features"]["records"],
            "features_sha256": record["features"]["sha256"],
            "municipal_content_sha256": record["features"]["municipal_content_sha256"],
            "requests": record["completeness"]["pages"],
        }
    licence = manifest["licence"]
    return {
        "snapshot_id": manifest["snapshot_id"],
        "retrieved_at": manifest["retrieved_at"],
        "publisher": manifest["publisher"],
        "publications": publications,
        "licence": {
            "name": LICENCE_NAME,
            "version": licence["version_recorded"],
            "matches_recorded_terms": licence["matches_recorded_terms"],
            "terms": {term["term"]: term["reading"] for term in licence["terms"]},
            "licence_info_sha256": licence["licence_info_sha256"],
        },
        "documents": [
            {
                "key": doc["key"],
                "url": doc["url"],
                "http_status": doc["http_status"],
                "sha256": doc.get("sha256"),
                "last_modified": doc.get("last_modified"),
                **({"revision": doc["revision"]} if "revision" in doc else {}),
            }
            for doc in manifest["documents"]
        ],
    }


# ---------------------------------------------------------------------------
# Overlap
# ---------------------------------------------------------------------------


def _overlap(
    records: Sequence[KitchenerRecord],
    geography: Sequence[RecordGeography],
    region: RegionDefinition,
    edges: PathAbleEdges,
) -> dict[str, Any]:
    inside = [(r, g) for r, g in zip(records, geography, strict=True) if g.intersects_study_area]
    pedestrian = [(r, g) for r, g in inside if _is_physical_pedestrian(r)]

    def km(items: Sequence[tuple[KitchenerRecord, RecordGeography]]) -> float:
        return round(sum(r.length_m or 0.0 for r, _g in items) / 1000, 3)

    def bands(
        items: Sequence[tuple[KitchenerRecord, RecordGeography]], attr: str
    ) -> dict[str, int]:
        found: Counter[str] = Counter(band(getattr(g, attr)) for _r, g in items)
        return {label: found.get(label, 0) for label in band_order()}

    corridor_mask = [
        g.intersects_study_area and _is_physical_pedestrian(r)
        for r, g in zip(records, geography, strict=True)
    ]
    return {
        "study_area": study_area(region, edges),
        "label": (
            "Overlap feasibility only. A record intersecting the study area, or lying near a "
            "PathAble edge, is not a match."
        ),
        "records_total": len(records),
        "records_intersecting_study_area": len(inside),
        "records_within_study_area": sum(1 for _r, g in inside if g.within_study_area),
        "km_total": round(sum(r.length_m or 0.0 for r in records) / 1000, 3),
        "km_intersecting_study_area": km(inside),
        "intersecting_by_physical_class": _count(r.physical_class for r, _g in inside),
        "intersecting_by_network_role": _count(r.network_role for r, _g in inside),
        "intersecting_by_subcategory": _count(r.subcategory for r, _g in inside),
        "intersecting_by_structure": _count(r.structure for r, _g in inside if r.structure),
        "intersecting_by_publication": _count(
            "both"
            if r.in_active_transportation and r.in_walkability
            else (
                "active_transportation_only" if r.in_active_transportation else "walkability_only"
            )
            for r, _g in inside
        ),
        "intersecting_curbcut_y": sum(1 for r, _g in inside if r.curbcut == "Y"),
        "physical_active_pedestrian_intersecting": len(pedestrian),
        "physical_active_pedestrian_km_intersecting": km(pedestrian),
        "evidence_on_pedestrian_records": {
            "scope": (
                "active physical pedestrian ways and crossings; a value counts only when it "
                "departs from the template default (a width of 0 is not counted)"
            ),
            "all": evidence_counts([r for r in records if _is_physical_pedestrian(r)]),
            "in_study_area": evidence_counts([r for r, _g in pedestrian]),
        },
        "proximity_label": (
            "Distance from each intersecting record to the nearest PathAble edge, in the "
            "source's native metres. Descriptive; the transformation between the two datums "
            "is a null shift with a stated accuracy of a few metres, so the first bands are "
            "within that uncertainty."
        ),
        "proximity_to_any_edge": bands(inside, "nearest_edge_m"),
        "proximity_of_pedestrian_records_to_any_edge": bands(pedestrian, "nearest_edge_m"),
        "proximity_of_pedestrian_records_to_osm_footway_or_path": bands(
            pedestrian, "nearest_separate_pedestrian_edge_m"
        ),
        "offset_label": (
            "Worst-point offset: every record line is sampled at least every "
            f"{OFFSET_SAMPLE_SPACING_M:g} m and the largest distance from a sample point to "
            "the nearest OSM footway, path, pedestrian way or steps edge is reported (a directed "
            "Hausdorff distance). A small value means the whole line runs along OSM pedestrian "
            "geometry. It is consistent with shared lineage, and proves neither lineage nor a "
            "match."
        ),
        "offset_of_pedestrian_records_from_osm_pedestrian_ways": bands(
            pedestrian, "max_offset_to_osm_pedestrian_m"
        ),
        "offset_by_subcategory": {
            subcategory: {
                "records": len(group),
                "median_m": _median(g.max_offset_to_osm_pedestrian_m for _r, g in group),
                "bands": bands(group, "max_offset_to_osm_pedestrian_m"),
            }
            for subcategory, group in _grouped(pedestrian, lambda r: r.subcategory)
        },
        "offset_of_curbcut_y_records": bands(
            [(r, g) for r, g in inside if r.curbcut == "Y"], "max_offset_to_osm_pedestrian_m"
        ),
        "graph_along_inventory": graph_along_inventory(
            [r.native for r in records], corridor_mask, edges
        ),
    }


def _is_physical_pedestrian(record: KitchenerRecord) -> bool:
    return record.physical_class == "physical_active" and record.network_role in (
        "pedestrian_way",
        "pedestrian_crossing",
    )


def evidence_counts(records: Sequence[KitchenerRecord]) -> dict[str, int]:
    """How many records carry each kind of non-default accessibility value.

    Template defaults, unknown codes and nulls are not evidence and are never
    counted here; neither is a 0 m width, which the City uses for crossings.
    """

    def count(predicate: Callable[[KitchenerRecord], bool]) -> int:
        return sum(1 for record in records if predicate(record))

    facts: dict[str, Callable[[KitchenerRecord], bool]] = {
        "stairs": lambda r: r.structure == "STAIRS",
        "other_structure": lambda r: r.structure is not None and r.structure != "STAIRS",
        "surface_non_default": lambda r: r.state_surface_material == "non_default",
        "width_non_default_non_zero": lambda r: (
            r.state_width_m == "non_default" and (r.width_m or 0) != 0
        ),
        "curbcut_y": lambda r: r.curbcut == "Y",
        "railing_y": lambda r: r.railing == "Y",
        "condition_fair_poor_unusable": lambda r: r.state_surface_condition == "non_default",
    }
    result = {"records": len(records)}
    result.update({name: count(test) for name, test in facts.items()})
    result["with_any_of_these"] = count(lambda r: any(test(r) for test in facts.values()))
    result["surface_template_default"] = count(
        lambda r: r.state_surface_material == "template_default"
    )
    result["width_template_default"] = count(lambda r: r.state_width_m == "template_default")
    result["condition_unknown"] = count(lambda r: r.state_surface_condition == "unknown")
    return result


def _count(values: Any) -> dict[str, int]:
    found: Counter[str] = Counter("null" if v is None else str(v) for v in values)
    return dict(sorted(found.items(), key=lambda kv: (-kv[1], kv[0])))


def _grouped(
    items: Sequence[tuple[KitchenerRecord, RecordGeography]],
    key: Callable[[KitchenerRecord], str | None],
) -> list[tuple[str, list[tuple[KitchenerRecord, RecordGeography]]]]:
    groups: dict[str, list[tuple[KitchenerRecord, RecordGeography]]] = defaultdict(list)
    for record, geography in items:
        groups[key(record) or "null"].append((record, geography))
    return sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def _median(values: Any) -> float | None:
    present = sorted(v for v in values if v is not None)
    if not present:
        return None
    return round(float(np.median(present)), 3)


# ---------------------------------------------------------------------------
# Sample
# ---------------------------------------------------------------------------


def _candidates(
    records: Sequence[KitchenerRecord], geography: Sequence[RecordGeography]
) -> list[Candidate]:
    inside = [
        (r, g)
        for r, g in zip(records, geography, strict=True)
        if g.intersects_study_area and r.identity_state == "unique" and r.native is not None
    ]
    dense = _dense(inside)
    parallel = _parallel_sidewalks(inside)
    return [
        Candidate(
            activetransportid=int(r.activetransportid),  # type: ignore[arg-type]
            physical_class=r.physical_class,
            network_role=r.network_role,
            subcategory=r.subcategory,
            structure=r.structure,
            curbcut=r.curbcut,
            length_m=r.length_m,
            part_count=r.part_count,
            max_offset_to_osm_pedestrian_m=g.max_offset_to_osm_pedestrian_m,
            nearest_road_highway=g.nearest_road_highway,
            dense=index in dense,
            parallel_pair=r.activetransportid in parallel,
        )
        for index, (r, g) in enumerate(inside)
    ]


def _dense(inside: Sequence[tuple[KitchenerRecord, RecordGeography]]) -> set[int]:
    """Indices of in-area sidewalks whose neighbourhood is in the top tenth by record count."""
    if not inside:
        return set()
    geometries = np.array([r.native for r, _g in inside], dtype=object)
    midpoints = shapely.line_interpolate_point(geometries, 0.5, normalized=True)
    tree = shapely.STRtree(geometries)
    hits = tree.query(midpoints, predicate="dwithin", distance=DENSITY_RADIUS_M)
    neighbours = np.bincount(hits[0], minlength=len(inside))
    sidewalks = [i for i, (r, _g) in enumerate(inside) if r.subcategory == "SIDEWALK"]
    if not sidewalks:
        return set()
    threshold = float(np.quantile(neighbours[sidewalks], DENSE_QUANTILE, method="lower"))
    return {i for i in sidewalks if neighbours[i] >= threshold}


def _parallel_sidewalks(inside: Sequence[tuple[KitchenerRecord, RecordGeography]]) -> set[int]:
    sides: dict[int, set[str]] = defaultdict(set)
    for r, _g in inside:
        if r.subcategory == "SIDEWALK" and r.roadsegmentid is not None and r.roadsegment_side:
            sides[r.roadsegmentid].add(r.roadsegment_side)
    both = {segment for segment, seen in sides.items() if {"LEFT", "RIGHT"} <= seen}
    return {
        int(r.activetransportid)
        for r, _g in inside
        if r.subcategory == "SIDEWALK"
        and r.roadsegmentid in both
        and r.activetransportid is not None
    }


def _sample_geojson(
    sampled: Sequence[Any],
    strata: Mapping[str, Mapping[str, Any]],
    by_id: Mapping[int | None, tuple[KitchenerRecord, RecordGeography]],
    snapshot_id: str,
) -> dict[str, Any]:
    features = []
    for item in sampled:
        record, geography = by_id[item.candidate.activetransportid]
        features.append(
            {
                "type": "Feature",
                "id": record.activetransportid,
                "properties": {
                    "activetransportid": record.activetransportid,
                    "stratum": item.stratum,
                    "rank_in_stratum": item.rank,
                    "physical_class": record.physical_class,
                    "network_role": record.network_role,
                    "lifecycle": record.lifecycle,
                    "category": record.category,
                    "subcategory": record.subcategory,
                    "feature_type": record.feature_type,
                    "surface_material": record.surface_material,
                    "width_m": record.width_m,
                    "curbcut": record.curbcut,
                    "railing": record.railing,
                    "surface_condition": record.surface_condition,
                    "source_class": record.source_class,
                    "source_year": record.source_year,
                    "roadsegmentid": record.roadsegmentid,
                    "roadsegment_side": record.roadsegment_side,
                    "length_m": round(record.length_m, 2) if record.length_m is not None else None,
                    "nearest_pathable_edge_m": geography.nearest_edge_m,
                    "nearest_pathable_edge_highway": geography.nearest_edge_highway,
                    "nearest_osm_footway_or_path_m": geography.nearest_separate_pedestrian_edge_m,
                    "max_offset_to_osm_pedestrian_way_m": geography.max_offset_to_osm_pedestrian_m,
                    "nearest_osm_road_highway": geography.nearest_road_highway,
                    "published_in": [
                        name
                        for name, present in (
                            ("active_transportation", record.in_active_transportation),
                            ("walkability", record.in_walkability),
                        )
                        if present
                    ],
                },
                "geometry": _rounded(record.primary),
            }
        )
    return {
        "type": "FeatureCollection",
        "metadata": {
            "purpose": "PA-GEO-04 manual geometry and OSM-lineage inspection sample",
            "snapshot_id": snapshot_id,
            "seed": SEED,
            "method": (
                "Records intersecting the study area, one stratum each by first matching rule; "
                f"at least {MINIMUM_PER_STRATUM} per non-empty stratum, the rest of {TARGET} "
                "by largest remainder in proportion to stratum size; within a stratum, "
                "ascending sha256(seed:snapshot_id:ACTIVETRANSPORTID)."
            ),
            "strata": dict(strata),
            "coordinates": "OGC:CRS84, rounded to 7 decimal places (about 1 cm) for inspection",
            "attribution": ATTRIBUTION,
        },
        "features": features,
    }


def _rounded(geometry: BaseGeometry | None) -> dict[str, Any] | None:
    if geometry is None:
        return None
    mapped: dict[str, Any] = shapely.geometry.mapping(geometry)

    def round_coords(value: Any) -> Any:
        if isinstance(value, tuple | list):
            if value and isinstance(value[0], float | int):
                return [round(float(v), 7) for v in value]
            return [round_coords(v) for v in value]
        return value

    return {"type": mapped["type"], "coordinates": round_coords(mapped["coordinates"])}
