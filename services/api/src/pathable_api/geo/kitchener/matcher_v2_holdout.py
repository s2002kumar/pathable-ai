"""The held-out benchmark sample for PA-GEO-08, matcher v2.

PA-GEO-05's held-out sample is spent: matcher v1 was evaluated on it once, and
its failures shaped matcher v2. So it, and PA-GEO-04's sample, are now
*development* data, and matcher v2 is measured on a new sample neither design
has seen:

- drawn from every eligible City record (:func:`conflation.load_population`)
  that is in **neither** earlier sample;
- into strata, first matching rule wins, aimed at what matcher v1 could not
  settle — curb cuts with no OSM kerb node, curb cuts onto crossings, pieces of
  under a metre, corner and junction pieces, stairs OSM draws as a plain
  footway, stairs with OSM steps displaced nearby, structures OSM splits — with
  small control strata where v1 did well, so that a regression shows;
- a fixed number per stratum (:data:`STRATA`), or all of a smaller one;
- within a stratum in the order of ``sha256(seed:id)``, where the seed names
  the Kitchener snapshot, the OSM extract and :data:`SAMPLE_VERSION`.

The situation signals below say where the two datasets sit relative to each
other. None of them is matcher v1 or v2, and nothing here decides a match.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pathable_api.geo.kitchener.conflation import (
    PEDESTRIAN_CLASSES,
    SHORT_PIECE_M,
    CandidateSet,
    ConflationInputs,
    Record,
    candidate_set,
)
from pathable_api.geo.kitchener.holdout import (
    Signals,
    _crs84,
    development_ids,
    selection_key,
    signals,
)

SAMPLE_VERSION = "pathable-pa-geo-08-holdout-v1"
#: The blind second pass: one record per stratum, then filled by hash to this size.
REPEAT_VERSION = "pathable-pa-geo-08-repeat-v1"
REPEAT_TARGET = 60
PRIMARY_PACKS = 5
REPEAT_PACKS = 2

#: Descriptive distances, in metres. They describe the situation; none is a
#: matching threshold of either matcher.
KERB_NEAR_M = 2.0
CROSSING_WAY_NEAR_M = 2.0
CROSSING_NODE_NEAR_M = 3.0
CROSSING_WAY_ABSENT_M = 5.0
PEDESTRIAN_NEAR_M = 3.0
COVER_WITHIN_M = 3.0
COVER_SHARE = 0.5
NO_COUNTERPART_M = 5.0
SUB_METRE_M = 1.0


@dataclass(frozen=True, slots=True)
class Situation:
    """What surrounds a record in OSM: the facts the strata are drawn on."""

    base: Signals
    kerb_within_2m: bool
    crossing_way_within_2m: bool
    crossing_node_within_3m: bool
    crossing_way_within_5m: bool
    pedestrian_ways_within_3m: int
    #: An OSM ``highway=steps`` way with half the record within 3 m of it.
    steps_covering: bool
    #: Any OSM ``highway=steps`` way among the candidates (within 25 m).
    steps_near: bool
    #: A non-steps pedestrian way with half the record within 3 m of it.
    generic_covering: bool
    nearest_pedestrian_m: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.base.as_dict(),
            "osm_kerb_within_2m": self.kerb_within_2m,
            "osm_crossing_way_within_2m": self.crossing_way_within_2m,
            "osm_crossing_node_within_3m": self.crossing_node_within_3m,
            "osm_crossing_way_within_5m": self.crossing_way_within_5m,
            "osm_pedestrian_ways_within_3m": self.pedestrian_ways_within_3m,
            "osm_steps_covering": self.steps_covering,
            "osm_steps_within_25m": self.steps_near,
            "osm_generic_way_covering": self.generic_covering,
            "nearest_osm_pedestrian_way_m": None
            if self.nearest_pedestrian_m is None
            else round(self.nearest_pedestrian_m, 2),
        }


def situation(candidates: CandidateSet, base: Signals) -> Situation:
    pedestrian = [w for w in candidates.ways if w.osm_class in PEDESTRIAN_CLASSES]
    steps = [w for w in pedestrian if w.osm_class == "steps"]
    return Situation(
        base=base,
        kerb_within_2m=any(
            n.kind == "kerb" and n.distance_m <= KERB_NEAR_M for n in candidates.nodes
        ),
        crossing_way_within_2m=any(
            w.osm_class == "crossing" and w.min_distance_m <= CROSSING_WAY_NEAR_M
            for w in candidates.ways
        ),
        crossing_node_within_3m=any(
            n.kind == "crossing" and n.distance_m <= CROSSING_NODE_NEAR_M for n in candidates.nodes
        ),
        crossing_way_within_5m=any(
            w.osm_class == "crossing" and w.min_distance_m <= CROSSING_WAY_ABSENT_M
            for w in candidates.ways
        ),
        pedestrian_ways_within_3m=sum(
            1 for w in pedestrian if w.min_distance_m <= PEDESTRIAN_NEAR_M
        ),
        steps_covering=any(w.share_within(COVER_WITHIN_M) >= COVER_SHARE for w in steps),
        steps_near=bool(steps),
        generic_covering=any(
            w.osm_class != "steps" and w.share_within(COVER_WITHIN_M) >= COVER_SHARE
            for w in pedestrian
        ),
        nearest_pedestrian_m=min((w.min_distance_m for w in pedestrian), default=None),
    )


Rule = Callable[[Record, Situation], bool]


def _no_kerb_curb_cut(r: Record, s: Situation) -> bool:
    return r.curb_cut and not s.kerb_within_2m


def _other_structure(r: Record) -> bool:
    return r.structure is not None and r.structure != "STAIRS"


#: (name, rule, what it is for, target). Order is priority: first match wins.
STRATA: tuple[tuple[str, Rule, str, int], ...] = (
    (
        "stairs_explicit_steps",
        lambda r, s: r.structure == "STAIRS" and s.steps_covering,
        "City STAIRS with an OSM highway=steps way beside half of it (within 3 m)",
        20,
    ),
    (
        "stairs_displaced_steps",
        lambda r, s: r.structure == "STAIRS" and s.steps_near,
        "City STAIRS with an OSM highway=steps way within 25 m that does not run beside it",
        20,
    ),
    (
        "stairs_generic_footway",
        lambda r, s: r.structure == "STAIRS" and s.generic_covering,
        "City STAIRS with no OSM steps within 25 m and a plain footway or path beside half of it",
        20,
    ),
    (
        "stairs_other",
        lambda r, s: r.structure == "STAIRS",
        "every other City STAIRS record",
        20,
    ),
    (
        "structure_split",
        lambda r, s: _other_structure(r) and s.base.splitting_ways >= 2,
        "bridges, overpasses, underpasses and boardwalks across two or more OSM ways",
        12,
    ),
    (
        "structure_other",
        lambda r, s: _other_structure(r),
        "every other bridge, overpass, underpass and boardwalk",
        12,
    ),
    (
        "curb_cut_sub_metre",
        lambda r, s: r.curb_cut and r.length_m < SUB_METRE_M,
        f"CURBCUT = Y pieces shorter than {SUB_METRE_M:g} m",
        16,
    ),
    (
        "curb_cut_no_kerb_junction",
        lambda r, s: _no_kerb_curb_cut(r, s) and s.pedestrian_ways_within_3m >= 2,
        f"CURBCUT = Y, no OSM kerb node within {KERB_NEAR_M:g} m, two or more OSM pedestrian "
        f"ways within {PEDESTRIAN_NEAR_M:g} m",
        36,
    ),
    (
        "curb_cut_no_kerb_single_way",
        lambda r, s: _no_kerb_curb_cut(r, s) and s.pedestrian_ways_within_3m == 1,
        f"CURBCUT = Y, no OSM kerb node within {KERB_NEAR_M:g} m, one OSM pedestrian way within "
        f"{PEDESTRIAN_NEAR_M:g} m",
        12,
    ),
    (
        "curb_cut_no_kerb_no_way",
        _no_kerb_curb_cut,
        f"CURBCUT = Y with no OSM kerb node within {KERB_NEAR_M:g} m and no OSM pedestrian way "
        f"within {PEDESTRIAN_NEAR_M:g} m",
        6,
    ),
    (
        "curb_cut_kerb_onto_crossing",
        lambda r, s: r.curb_cut and s.crossing_way_within_2m,
        f"CURBCUT = Y with an OSM kerb node and an OSM crossing way within {KERB_NEAR_M:g} m",
        16,
    ),
    (
        "curb_cut_kerb_other",
        lambda r, s: r.curb_cut,
        "every other CURBCUT = Y record: a kerb node near and no crossing way",
        4,
    ),
    (
        "corner_junction_piece",
        lambda r, s: r.length_m < SHORT_PIECE_M and s.pedestrian_ways_within_3m >= 2,
        f"pieces shorter than {SHORT_PIECE_M:g} m, not curb cuts, with two or more OSM "
        f"pedestrian ways within {PEDESTRIAN_NEAR_M:g} m",
        26,
    ),
    (
        "crossing_as_node",
        lambda r, s: r.family == "crossing"
        and s.crossing_node_within_3m
        and not s.crossing_way_within_5m,
        f"City crossings with an OSM crossing node within {CROSSING_NODE_NEAR_M:g} m and no OSM "
        f"crossing way within {CROSSING_WAY_ABSENT_M:g} m",
        6,
    ),
    (
        "parallel_facilities",
        lambda r, s: s.base.parallel_ways >= 2,
        "two or more OSM pedestrian ways running beside the record",
        10,
    ),
    (
        "hard_negative",
        lambda r, s: s.nearest_pedestrian_m is None or s.nearest_pedestrian_m > NO_COUNTERPART_M,
        f"no OSM footway, path, crossing or steps within {NO_COUNTERPART_M:g} m",
        10,
    ),
    (
        "short_other",
        lambda r, s: r.length_m < SHORT_PIECE_M,
        f"every other piece shorter than {SHORT_PIECE_M:g} m",
        4,
    ),
    ("straightforward", lambda r, s: True, "every other eligible record", 8),
)

#: Why the sample is the size it is, carried in the file.
SIZE_RATIONALE = (
    "About 190 records, weighted to what matcher v1 could not settle. Curb cuts get 90 across "
    "six strata, most of them where OSM has no kerb node, because that is where 1,152 City curb "
    "cuts wait. Stairs get every eligible record not already used: only 17 remain after "
    "PA-GEO-05 took 20, so stair results will rest on those alone and are reported as such. "
    "Corner and junction pieces get 26, structures up to 24. Small control strata (curb cuts "
    "with a kerb node and no crossing, parallel facilities, straightforward records) are there "
    "to show a regression where v1 did well. The ceiling is review cost: every record is "
    "labelled blind, and 60 twice. The size carries no claim of statistical certainty."
)


def assign_stratum(record: Record, s: Situation) -> str:
    for name, rule, _why, _target in STRATA:
        if rule(record, s):
            return name
    raise AssertionError("the last stratum accepts everything")  # pragma: no cover


def seed_for(snapshot_id: str, osm_extract_sha256: str) -> str:
    return f"{SAMPLE_VERSION}:{snapshot_id}:{osm_extract_sha256}"


@dataclass(frozen=True, slots=True)
class Drawn:
    record: Record
    situation: Situation
    stratum: str
    rank: int


def draw(
    records: Sequence[Record],
    situations: Mapping[int, Situation],
    development: frozenset[int],
    seed: str,
) -> tuple[list[Drawn], dict[str, Any]]:
    """The held-out sample and a description of how it was drawn."""
    pool = [r for r in records if r.activetransportid not in development]
    members: dict[str, list[Record]] = {name: [] for name, *_ in STRATA}
    for record in pool:
        members[assign_stratum(record, situations[record.activetransportid])].append(record)
    drawn: list[Drawn] = []
    strata: dict[str, Any] = {}
    for name, _rule, why, target in STRATA:
        ordered = sorted(members[name], key=lambda r: selection_key(seed, r.activetransportid))
        chosen = ordered[:target]
        drawn.extend(
            Drawn(r, situations[r.activetransportid], name, rank)
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
        "strata": strata,
    }
    return drawn, description


def holdout_document(
    drawn: Sequence[Drawn],
    description: Mapping[str, Any],
    identity: Mapping[str, Any],
    development: Sequence[Mapping[str, Any]],
    seed: str,
    geometries: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    """The sample as GeoJSON, in the shape of PA-GEO-04's and PA-GEO-05's sample files."""
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
                "structure": item.record.structure,
                "length_m": round(item.record.length_m, 2),
                "situation": item.situation.as_dict(),
            },
            "geometry": geometries[item.record.activetransportid],
        }
        for item in drawn
    ]
    return {
        "type": "FeatureCollection",
        "metadata": {
            "purpose": (
                "PA-GEO-08 held-out benchmark for matcher v2: records neither matcher's design saw"
            ),
            "sample_version": SAMPLE_VERSION,
            "snapshot_id": identity["kitchener"]["snapshot_id"],
            "osm_extract_sha256": identity["osm_frozen"]["extract_sha256"],
            "seed": seed,
            "method": (
                "Eligible records minus every record of PA-GEO-04's and PA-GEO-05's samples, one "
                "stratum each by first matching rule, a fixed number per stratum (or all of a "
                "smaller one), within a stratum in ascending sha256(seed:ACTIVETRANSPORTID)."
            ),
            "size_rationale": SIZE_RATIONALE,
            "eligibility": identity["eligibility"],
            "candidate_contract": identity["candidate_contract"],
            "development_sets": list(development),
            **dict(description),
            "coordinates": "OGC:CRS84, rounded to 7 decimal places (about 1 cm) for inspection",
            "attribution": (
                "Contains information licensed under the Open Government Licence - The "
                "Corporation of the City of Kitchener. Situations read OpenStreetMap: "
                "© OpenStreetMap contributors, ODbL 1.0."
            ),
        },
        "features": features,
    }


def build_holdout(
    inputs: ConflationInputs,
    development_samples: Sequence[tuple[Path, str | None]],
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Draw the sample. ``development_samples`` are the earlier samples, with their hashes."""
    say = progress or (lambda _message: None)
    development: set[int] = set()
    identities = []
    for path, expected in development_samples:
        ids, identity = development_ids(path, expected)
        development |= ids
        identities.append(identity)
    records = inputs.population.records
    situations: dict[int, Situation] = {}
    for count, record in enumerate(records, start=1):
        candidates = candidate_set(record, inputs.osm)
        situations[record.activetransportid] = situation(
            candidates, signals(candidates, inputs.eligible)
        )
        if count % 2000 == 0:
            say(f"situations: {count} of {len(records)}")
    seed = seed_for(
        inputs.identity["kitchener"]["snapshot_id"],
        inputs.identity["osm_frozen"]["extract_sha256"],
    )
    drawn, description = draw(records, situations, frozenset(development), seed)
    geometries = _crs84(inputs.parquet, [d.record.activetransportid for d in drawn])
    return holdout_document(drawn, description, inputs.identity, identities, seed, geometries)


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


def packs(ids: Sequence[int], count: int, prefix: str) -> dict[str, list[int]]:
    """Records dealt to labelling packs in id order, round robin: every pack sees every stratum."""
    dealt: dict[str, list[int]] = {f"{prefix}-{n}": [] for n in range(1, count + 1)}
    names = list(dealt)
    for position, record_id in enumerate(sorted(ids)):
        dealt[names[position % count]].append(record_id)
    return dealt
