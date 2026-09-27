"""The held-out benchmark sample for PA-GEO-05.

PA-GEO-04's 80 records are the development set: rules and thresholds are
designed and tuned on them. The benchmark that measures the result must be
records the design never saw. This module draws them:

- from every eligible City record (:func:`conflation.load_population`) that is
  **not** one of the development records;
- into strata, first matching rule wins, chosen to exercise the evidence
  classes (curb cuts, stairs and structures, non-default surfaces) and the
  geometry that makes matching hard (no counterpart, offset, parallel ways,
  short pieces, splits and merges, dense junctions, crowded candidates);
- a fixed number per stratum (:data:`STRATA`), or all of a smaller one;
- within a stratum in the order of ``sha256(seed:id)``, where the seed names
  the Kitchener snapshot, the OSM extract and :data:`SAMPLE_VERSION`.

The signals below describe where the two datasets sit relative to each other,
to put hard cases into the sample. None of them is the matcher, and nothing
here decides a match.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import shapely
import shapely.geometry

from pathable_api.geo.kitchener.conflation import (
    PEDESTRIAN_CLASSES,
    SHORT_PIECE_M,
    CandidateSet,
    ConflationInputs,
    Record,
    candidate_set,
)
from pathable_api.geo.kitchener.correspondence import KitchenerIndex, parts
from pathable_api.geo.overture.evidence import file_sha256

SAMPLE_VERSION = "pathable-pa-geo-05-holdout-v1"

#: Descriptive bands, in metres.
OFFSET_BAND_M = (3.0, 20.0)
PARALLEL_WITHIN_M = 5.0
PARALLEL_MAX_DEG = 20.0
SPLIT_WITHIN_M = 3.0
SPLIT_MIN_SHARE = 0.2
LONG_M = 150.0
NEIGHBOUR_M = 10.0
KERB_NEAR_M = 3.0
#: "Dense" and "candidate-heavy" are the top tenth of the eligible population.
TOP_SHARE = 0.9


@dataclass(frozen=True, slots=True)
class Signals:
    """Where a record sits relative to OSM and to the City's other records."""

    candidate_ways: int
    #: Share of the record within 5 m of some OSM pedestrian way.
    pedestrian_within_5m_share: float
    #: The best single pedestrian way's worst-point distance; ``None`` if none is near.
    best_worst_point_m: float | None
    #: Pedestrian ways running beside the record: half of it within 5 m, near-parallel.
    parallel_ways: int
    #: Pedestrian ways each nearest and within 3 m for a fifth of the record.
    splitting_ways: int
    city_neighbours: int
    osm_kerb_within_3m: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_ways": self.candidate_ways,
            "pedestrian_within_5m_share": round(self.pedestrian_within_5m_share, 3),
            "best_worst_point_m": None
            if self.best_worst_point_m is None
            else round(self.best_worst_point_m, 2),
            "parallel_ways": self.parallel_ways,
            "splitting_ways": self.splitting_ways,
            "city_neighbours": self.city_neighbours,
            "osm_kerb_within_3m": self.osm_kerb_within_3m,
        }


def signals(candidates: CandidateSet, eligible: KitchenerIndex) -> Signals:
    record = candidates.record
    pedestrian = [w for w in candidates.ways if w.osm_class in PEDESTRIAN_CLASSES]
    if pedestrian:
        distances = np.vstack([w.distances for w in pedestrian])
        within5 = float((distances.min(axis=0) <= PARALLEL_WITHIN_M).mean())
        best_worst: float | None = min(w.max_offset_m for w in pedestrian)
        nearest = np.argmin(distances, axis=0)
        close = distances.min(axis=0) <= SPLIT_WITHIN_M
        splitting = sum(
            1 for i in range(len(pedestrian)) if ((nearest == i) & close).mean() >= SPLIT_MIN_SHARE
        )
    else:
        within5, best_worst, splitting = 0.0, None, 0
    parallel = 0
    for way in pedestrian:
        near = way.distances <= PARALLEL_WITHIN_M
        if near.mean() >= 0.5 and float(np.median(way.angles[near])) <= PARALLEL_MAX_DEG:
            parallel += 1
    neighbours = [
        other
        for other in eligible.near(record.geometry, NEIGHBOUR_M)
        if other != record.activetransportid
    ]
    return Signals(
        candidate_ways=len(candidates.ways),
        pedestrian_within_5m_share=within5,
        best_worst_point_m=best_worst,
        parallel_ways=parallel,
        splitting_ways=splitting,
        city_neighbours=len(neighbours),
        osm_kerb_within_3m=any(
            n.kind == "kerb" and n.distance_m <= KERB_NEAR_M for n in candidates.nodes
        ),
    )


@dataclass(frozen=True, slots=True)
class Thresholds:
    dense_city_neighbours: int
    heavy_candidate_ways: int


Rule = Callable[[Record, Signals, Thresholds], bool]


def _offset(s: Signals) -> bool:
    worst = s.best_worst_point_m
    return worst is not None and OFFSET_BAND_M[0] <= worst < OFFSET_BAND_M[1]


#: (name, rule, what it is for, target). Order is priority: first match wins.
STRATA: tuple[tuple[str, Rule, str, int], ...] = (
    ("stairs", lambda r, s, t: r.structure == "STAIRS", "FEATURE_TYPE STAIRS", 20),
    (
        "other_structure",
        lambda r, s, t: r.structure is not None,
        "bridges, overpasses, underpasses and boardwalks",
        20,
    ),
    (
        "curb_cut_osm_kerb_near",
        lambda r, s, t: r.curb_cut and s.osm_kerb_within_3m,
        f"CURBCUT = Y with an OSM kerb node within {KERB_NEAR_M:g} m",
        28,
    ),
    (
        "curb_cut_no_osm_kerb",
        lambda r, s, t: r.curb_cut,
        f"CURBCUT = Y with no OSM kerb node within {KERB_NEAR_M:g} m",
        28,
    ),
    (
        "non_default_surface",
        lambda r, s, t: r.surface_material is not None,
        "a non-default SURFACE_MATERIAL",
        28,
    ),
    (
        "no_osm_pedestrian_way",
        lambda r, s, t: s.pedestrian_within_5m_share == 0.0,
        f"no OSM footway, path, crossing or steps within {PARALLEL_WITHIN_M:g} m of any point",
        10,
    ),
    (
        "offset_geometry",
        lambda r, s, t: _offset(s),
        f"the best OSM pedestrian way's worst point {OFFSET_BAND_M[0]:g}-{OFFSET_BAND_M[1]:g} m away",
        10,
    ),
    (
        "parallel_ways",
        lambda r, s, t: s.parallel_ways >= 2,
        "two or more OSM pedestrian ways running beside the record",
        10,
    ),
    (
        "short_piece",
        lambda r, s, t: r.length_m < SHORT_PIECE_M,
        f"shorter than {SHORT_PIECE_M:g} m, not a curb cut",
        8,
    ),
    (
        "osm_split_or_long",
        lambda r, s, t: s.splitting_ways >= 2 or r.length_m >= LONG_M or len(parts(r.geometry)) > 1,
        f"two or more OSM ways each nearest for a fifth of it, {LONG_M:g} m or longer, or multi-part",
        10,
    ),
    (
        "dense_intersection",
        lambda r, s, t: s.city_neighbours >= t.dense_city_neighbours,
        f"among the top tenth by City records within {NEIGHBOUR_M:g} m",
        8,
    ),
    (
        "candidate_heavy",
        lambda r, s, t: s.candidate_ways >= t.heavy_candidate_ways,
        "among the top tenth by candidate OSM ways",
        6,
    ),
    ("crossing", lambda r, s, t: r.family == "crossing", "crosswalks and trail crossings", 8),
    ("straightforward", lambda r, s, t: True, "every other eligible record", 6),
)


def thresholds(all_signals: Sequence[Signals]) -> Thresholds:
    neighbours = np.array([s.city_neighbours for s in all_signals])
    candidates = np.array([s.candidate_ways for s in all_signals])
    return Thresholds(
        dense_city_neighbours=int(np.ceil(np.quantile(neighbours, TOP_SHARE))),
        heavy_candidate_ways=int(np.ceil(np.quantile(candidates, TOP_SHARE))),
    )


def assign_stratum(record: Record, s: Signals, t: Thresholds) -> str:
    for name, rule, _why, _target in STRATA:
        if rule(record, s, t):
            return name
    raise AssertionError("the last stratum accepts everything")  # pragma: no cover


def seed_for(snapshot_id: str, osm_extract_sha256: str) -> str:
    return f"{SAMPLE_VERSION}:{snapshot_id}:{osm_extract_sha256}"


def selection_key(seed: str, activetransportid: int) -> str:
    return hashlib.sha256(f"{seed}:{activetransportid}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Drawn:
    record: Record
    signals: Signals
    stratum: str
    rank: int


def draw(
    records: Sequence[Record],
    record_signals: Mapping[int, Signals],
    development: frozenset[int],
    seed: str,
) -> tuple[list[Drawn], dict[str, Any]]:
    """The held-out sample and a description of how it was drawn."""
    pool = [r for r in records if r.activetransportid not in development]
    limits = thresholds([record_signals[r.activetransportid] for r in pool])
    members: dict[str, list[Record]] = {name: [] for name, *_ in STRATA}
    for record in pool:
        stratum = assign_stratum(record, record_signals[record.activetransportid], limits)
        members[stratum].append(record)
    drawn: list[Drawn] = []
    strata: dict[str, Any] = {}
    for name, _rule, why, target in STRATA:
        ordered = sorted(members[name], key=lambda r: selection_key(seed, r.activetransportid))
        chosen = ordered[:target]
        drawn.extend(
            Drawn(r, record_signals[r.activetransportid], name, rank)
            for rank, r in enumerate(chosen, start=1)
        )
        strata[name] = {
            "rule": why,
            "target": target,
            "population": len(members[name]),
            "sampled": len(chosen),
        }
    description = {
        "eligible_records": len(records),
        "development_records_excluded": len(records) - len(pool),
        "pool": len(pool),
        "thresholds": {
            "dense_city_neighbours": limits.dense_city_neighbours,
            "heavy_candidate_ways": limits.heavy_candidate_ways,
        },
        "strata": strata,
    }
    return drawn, description


def sample_sha256(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


#: Why the sample is the size it is, carried in the file.
SIZE_RATIONALE = (
    "About 200 records. Each evidence class gets strata of its own large enough to show "
    "failures, with room for both matches and hard negatives: 56 curb cuts across two strata "
    "(with and without an OSM kerb node nearby), 20 stairs, 20 other structures and 28 "
    "non-default surfaces. Nine further strata of 6 to 10 records put the known geometric "
    "failure modes in front of the matcher. The ceiling is review cost: every record is "
    "labelled blind, and a subset twice. The size carries no claim of statistical certainty."
)


def holdout_document(
    drawn: Sequence[Drawn],
    description: Mapping[str, Any],
    identity: Mapping[str, Any],
    development: Mapping[str, Any],
    seed: str,
    geometries: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    """The sample as GeoJSON, in the shape PA-GEO-04's sample file has."""
    features = [
        {
            "type": "Feature",
            "id": item.record.activetransportid,
            "properties": {
                "activetransportid": item.record.activetransportid,
                "stratum": item.stratum,
                "rank_in_stratum": item.rank,
                "classes": list(item.record.classes),
                "family": item.record.family,
                "length_m": round(item.record.length_m, 2),
                "signals": item.signals.as_dict(),
            },
            "geometry": geometries[item.record.activetransportid],
        }
        for item in drawn
    ]
    return {
        "type": "FeatureCollection",
        "metadata": {
            "purpose": "PA-GEO-05 held-out conflation benchmark: records the matcher's design never saw",
            "sample_version": SAMPLE_VERSION,
            "snapshot_id": identity["kitchener"]["snapshot_id"],
            "osm_extract_sha256": identity["osm_frozen"]["extract_sha256"],
            "seed": seed,
            "method": (
                "Eligible records minus PA-GEO-04's development records, one stratum each by "
                "first matching rule, a fixed number per stratum (or all of a smaller one), "
                "within a stratum in ascending sha256(seed:ACTIVETRANSPORTID)."
            ),
            "size_rationale": SIZE_RATIONALE,
            "eligibility": identity["eligibility"],
            "candidate_contract": identity["candidate_contract"],
            "development_set": dict(development),
            **dict(description),
            "coordinates": "OGC:CRS84, rounded to 7 decimal places (about 1 cm) for inspection",
            "attribution": (
                "Contains information licensed under the Open Government Licence - The "
                "Corporation of the City of Kitchener. Signals read OpenStreetMap: "
                "© OpenStreetMap contributors, ODbL 1.0."
            ),
        },
        "features": features,
    }


class HoldoutError(RuntimeError):
    """The development set could not be established as it was recorded."""


def development_ids(
    path: Path, expected_sha256: str | None
) -> tuple[frozenset[int], dict[str, Any]]:
    """PA-GEO-04's sampled records: the development set, excluded from the holdout."""
    actual = file_sha256(path)
    if expected_sha256 is not None and actual != expected_sha256:
        msg = f"{path.name} hashes to {actual}, not the recorded {expected_sha256}."
        raise HoldoutError(msg)
    document = json.loads(path.read_text("utf-8"))
    ids = frozenset(int(f["properties"]["activetransportid"]) for f in document["features"])
    return ids, {"file": path.name, "sha256": actual, "records": len(ids)}


def _crs84(parquet: Path, ids: Sequence[int]) -> dict[int, dict[str, Any]]:
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("SET autoinstall_known_extensions = false")
        connection.execute("SET autoload_known_extensions = false")
        rows = connection.execute(
            "SELECT activetransportid, geometry FROM read_parquet(?) "
            "WHERE activetransportid IN (SELECT unnest(?))",
            [parquet.as_posix(), list(ids)],
        ).fetchall()
    finally:
        connection.close()
    found = {}
    for record_id, wkb in rows:
        geometry = shapely.set_precision(shapely.from_wkb(bytes(wkb)), 1e-7)
        found[int(record_id)] = shapely.geometry.mapping(geometry)
    return found


def build_holdout(
    inputs: ConflationInputs,
    development_sample: Path,
    *,
    expected_development_sha256: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    say = progress or (lambda _message: None)
    development, development_identity = development_ids(
        development_sample, expected_development_sha256
    )
    records = inputs.population.records
    record_signals: dict[int, Signals] = {}
    for count, record in enumerate(records, start=1):
        record_signals[record.activetransportid] = signals(
            candidate_set(record, inputs.osm), inputs.eligible
        )
        if count % 2000 == 0:
            say(f"signals: {count} of {len(records)}")
    seed = seed_for(
        inputs.identity["kitchener"]["snapshot_id"],
        inputs.identity["osm_frozen"]["extract_sha256"],
    )
    drawn, description = draw(records, record_signals, development, seed)
    geometries = _crs84(inputs.parquet, [d.record.activetransportid for d in drawn])
    return holdout_document(
        drawn, description, inputs.identity, development_identity, seed, geometries
    )


#: The blind second pass: one record per stratum, then filled by hash to this size.
REPEAT_VERSION = "pathable-pa-geo-05-repeat-v1"
REPEAT_TARGET = 60


def repeat_subset(document: Mapping[str, Any], *, target: int = REPEAT_TARGET) -> list[int]:
    """The held-out records labelled a second time, blind to the first pass."""
    features = [f["properties"] for f in document["features"]]
    seed = f"{REPEAT_VERSION}:{document['metadata']['seed']}"
    ordered = sorted(features, key=lambda p: selection_key(seed, int(p["activetransportid"])))
    chosen: list[int] = []
    for stratum in dict.fromkeys(p["stratum"] for p in features):
        first = next(p for p in ordered if p["stratum"] == stratum)
        chosen.append(int(first["activetransportid"]))
    for item in ordered:
        if len(chosen) >= target:
            break
        if int(item["activetransportid"]) not in chosen:
            chosen.append(int(item["activetransportid"]))
    return sorted(chosen)
