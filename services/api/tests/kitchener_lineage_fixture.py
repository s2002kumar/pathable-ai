"""An invented OSM side for the Kitchener fixture, for the lineage-study tests.

The Kitchener fixture (``tests.kitchener_fixture``) places records in NAD83 /
UTM 17N metres around (500 000, 5 000 000). This module puts OSM ways and
nodes beside them — converted to longitude/latitude the way the study converts
back — and writes the three files the study reads: a frozen extract with its
manifest, and a sample drawn from the fixture's records.

Every placement is deliberate:

- way 501, a sidewalk 1 m beside sidewalk 1001;
- way 502, "Fixture Street", between sidewalks 1001 and 1010;
- way 503, a crossing 0.5 m beside crosswalk 1003;
- way 504, steps with a handrail beside stairs 1004;
- way 505, a gravel path in bad smoothness beside the stonedust trail 1005;
- way 506, a crossing along the City's virtual link 2001;
- node 9001, a lowered kerb 0.5 m from curb cut 1002;
- node 9002, a lowered kerb beside sidewalk 1001, 50 m from any City curb cut.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyproj

from pathable_api.geo.kitchener.osm_extract import (
    OsmNode,
    OsmWay,
    StudyExtract,
    write_study_extract,
)
from pathable_api.geo.kitchener.source import NATIVE_WKID
from pathable_api.geo.overture.evidence import content_sha256, file_sha256
from tests.kitchener_fixture import X0, Y0

STAMP = "2021-06-01T12:00:00Z"

#: Local metres for every OSM node, relative to the fixture origin.
NODES: dict[int, tuple[float, float]] = {
    1: (0.0, 1.0),
    2: (100.0, 1.0),
    3: (0.0, 10.0),
    4: (150.0, 10.0),
    5: (102.5, 0.0),
    6: (102.5, 15.0),
    7: (0.0, 50.5),
    8: (8.0, 50.5),
    9: (0.0, 201.0),
    10: (250.0, 201.0),
    11: (110.5, 0.0),
    12: (110.5, 15.0),
    9001: (101.5, 0.5),
    9002: (50.0, 0.5),
}
#: The tagged nodes: two lowered kerbs.
KERBS = frozenset({9001, 9002})
WAYS: dict[int, tuple[tuple[int, ...], dict[str, str]]] = {
    501: ((1, 2), {"highway": "footway", "footway": "sidewalk", "surface": "concrete"}),
    502: ((3, 4), {"highway": "residential", "name": "Fixture Street"}),
    503: ((5, 6), {"highway": "footway", "footway": "crossing", "crossing": "marked"}),
    504: ((7, 8), {"highway": "steps", "handrail": "yes"}),
    505: ((9, 10), {"highway": "path", "surface": "gravel", "smoothness": "bad"}),
    506: ((11, 12), {"highway": "footway", "footway": "crossing"}),
}
#: The sampled records and the strata they stand for.
SAMPLE: tuple[tuple[int, str], ...] = (
    (2001, "virtual_link"),
    (1007, "unresolved_semantics"),
    (1004, "stairs"),
    (1002, "curb_cut_coded"),
    (1003, "crossing"),
    (1005, "trail"),
    (1010, "parallel_sidewalk_pair"),
    (1001, "ordinary_sidewalk"),
)


def lonlat(x: float, y: float) -> tuple[float, float]:
    transformer = pyproj.Transformer.from_crs(f"EPSG:{NATIVE_WKID}", "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(X0 + x, Y0 + y)
    return float(lon), float(lat)


def extract() -> StudyExtract:
    nodes = {}
    for node_id, (x, y) in NODES.items():
        lon, lat = lonlat(x, y)
        tags = {"barrier": "kerb", "kerb": "lowered"} if node_id in KERBS else {}
        version, stamp = (3, STAMP) if tags else (None, None)
        nodes[node_id] = OsmNode(node_id, lon, lat, version, stamp, tags)
    ways = {
        way_id: OsmWay(way_id, 2, STAMP, dict(tags), refs) for way_id, (refs, tags) in WAYS.items()
    }
    return StudyExtract(nodes=nodes, ways=ways)


def write_extract(folder: Path) -> tuple[Path, Path]:
    """The frozen extract and its manifest, as `kitchener lineage-extract` writes them."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "study-extract.jsonl.gz"
    sha256 = write_study_extract(extract(), path)
    manifest: dict[str, Any] = {
        "kitchener_osm_extract_version": 1,
        "dataset": {
            "dataset_id": "00000000-0000-0000-0000-000000000001",
            "source_timestamp": "2021-07-01T00:00:00+00:00",
            "source_file_sha256": "f" * 64,
            "source_bbox": [-81.1, 45.0, -80.9, 45.2],
        },
        "selection": "fixture",
        "counts": {"ways": len(WAYS), "nodes": len(NODES)},
        "output": {"file": path.name, "bytes": path.stat().st_size, "sha256": sha256},
    }
    manifest["content_sha256"] = content_sha256(manifest)
    manifest_path = folder / "study-extract-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), "utf-8")
    return path, manifest_path


def write_sample(path: Path, snapshot_id: str) -> tuple[Path, str]:
    """A sample file in the PA-GEO-03 shape; returns it and its SHA-256."""
    strata: dict[str, dict[str, Any]] = {}
    features = []
    for record_id, stratum in SAMPLE:
        strata.setdefault(stratum, {"rule": "fixture", "population": 1, "sampled": 0})
        strata[stratum]["sampled"] += 1
        features.append(
            {
                "type": "Feature",
                "id": record_id,
                "properties": {
                    "activetransportid": record_id,
                    "stratum": stratum,
                    "rank_in_stratum": strata[stratum]["sampled"],
                },
                "geometry": None,
            }
        )
    document = {
        "type": "FeatureCollection",
        "metadata": {"snapshot_id": snapshot_id, "seed": "fixture", "strata": strata},
        "features": features,
    }
    path.write_text(json.dumps(document, indent=2), "utf-8")
    return path, file_sha256(path)


def label(
    record_id: int,
    correspondence: str,
    osm: list[str],
    *,
    representation: str = "separate_way",
    relationship: str | None = None,
    geometry: str | None = None,
    topology: str = "not_assessed",
) -> dict[str, Any]:
    return {
        "activetransportid": record_id,
        "correspondence": correspondence,
        "osm": osm,
        "representation": representation,
        "relationship": relationship,
        "geometry": geometry,
        "topology": topology,
        "note": "fixture",
    }


def labels() -> dict[str, Any]:
    """One label per sampled record, fitting the geometry placed above."""
    obvious = {
        "relationship": "one_to_one",
        "geometry": "closely_aligned",
        "topology": "topology_agreement",
    }
    return {
        "kitchener_geo04_labels_version": 1,
        "pass": "primary",
        "records": [
            label(2001, "obvious_correspondence", ["way/506"], **obvious),
            label(1007, "not_comparable", [], representation="none"),
            label(1004, "obvious_correspondence", ["way/504"], **obvious),
            label(
                1002,
                "ambiguous_correspondence",
                ["node/9001"],
                representation="node",
                topology="topology_agreement",
            ),
            label(1003, "obvious_correspondence", ["way/503"], **obvious),
            label(1005, "obvious_correspondence", ["way/505"], **obvious),
            label(1010, "no_correspondence", [], representation="none"),
            label(1001, "obvious_correspondence", ["way/501"], **obvious),
        ],
    }
