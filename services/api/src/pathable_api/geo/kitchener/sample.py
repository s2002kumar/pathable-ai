"""A deterministic, stratified sample of Kitchener records for manual lineage study.

PA-GEO-04 will look at each sampled record by hand: its geometry against
OpenStreetMap, whether OSM's version came from the City, and whether its
attributes are true. That work is only worth doing on a sample nobody chose by
eye, so the sample is a function of three things:

- the snapshot's identity (``snapshot_id``),
- a documented seed string (:data:`SEED`),
- the strata below, assigned in a fixed priority order.

Each record in the study area falls into exactly one stratum — the first whose
rule it meets. Every non-empty stratum gets :data:`MINIMUM_PER_STRATUM` records
(or all of them, if it has fewer); the rest of :data:`TARGET` is shared out in
proportion to the strata's actual sizes, by largest remainder. Within a
stratum, records are taken in the order of ``sha256(seed:snapshot:id)``.

Rules that mention PathAble's graph ("3 to 20 m from an OSM footway") describe where
two datasets sit relative to each other. They exist to put hard cases into the
sample, not to match anything.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

SEED = "pathable-pa-geo-04-sample-v1"
TARGET = 80
MINIMUM_PER_STRATUM = 3

#: Metres, for the descriptive rules below.
SPLIT_LOOKING_MAX_M = 5.0
MERGED_LOOKING_MIN_M = 400.0
#: Worst-point offset from OSM pedestrian ways: from "somewhere off" to "not along".
OFFSET_BAND_M = (3.0, 20.0)

TRAILS = frozenset({"MUT", "BMUT", "MAJOR TRAIL", "MINOR TRAIL"})
OTHER_STRUCTURES = frozenset({"BRIDGE", "OVERPASS", "UNDERPASS", "BOARDWALK"})


@dataclass(frozen=True, slots=True)
class Candidate:
    """What the stratum rules need to know about one in-area record."""

    activetransportid: int
    physical_class: str
    network_role: str
    subcategory: str | None
    structure: str | None
    curbcut: str | None
    length_m: float | None
    part_count: int | None
    #: Worst-point offset from OSM footways/paths; ``None`` is beyond measuring range.
    max_offset_to_osm_pedestrian_m: float | None
    nearest_road_highway: str | None
    dense: bool
    parallel_pair: bool


def _sidewalk(c: Candidate) -> bool:
    return c.subcategory == "SIDEWALK" and c.physical_class == "physical_active"


def _physical_pedestrian(c: Candidate) -> bool:
    return c.physical_class == "physical_active" and c.network_role in (
        "pedestrian_way",
        "pedestrian_crossing",
    )


def _not_along_osm(c: Candidate) -> bool:
    offset = c.max_offset_to_osm_pedestrian_m
    return _physical_pedestrian(c) and (offset is None or offset >= OFFSET_BAND_M[1])


def _offset_from_osm(c: Candidate) -> bool:
    offset = c.max_offset_to_osm_pedestrian_m
    return (
        _physical_pedestrian(c)
        and offset is not None
        and OFFSET_BAND_M[0] <= offset < OFFSET_BAND_M[1]
    )


#: (name, rule, what it is for). Order is priority: first match wins.
STRATA: tuple[tuple[str, Callable[[Candidate], bool], str], ...] = (
    (
        "virtual_link",
        lambda c: c.physical_class == "virtual_link",
        "City's virtual street crossings",
    ),
    (
        "unofficial_connection",
        lambda c: c.physical_class == "unofficial_connection",
        "City's unofficial driveway and on-road connections",
    ),
    (
        "unresolved_semantics",
        lambda c: c.physical_class == "unresolved",
        "records whose physical or virtual nature the source leaves ambiguous",
    ),
    ("stairs", lambda c: c.structure == "STAIRS", "FEATURE_TYPE STAIRS"),
    (
        "other_structure",
        lambda c: c.structure in OTHER_STRUCTURES,
        "bridges, overpasses, underpasses, boardwalks",
    ),
    ("curb_cut_coded", lambda c: c.curbcut == "Y", "CURBCUT = Y (a curbcut down to street level)"),
    (
        "not_along_osm_pedestrian_way",
        _not_along_osm,
        f"pedestrian record with a point {OFFSET_BAND_M[1]:g} m or more from any OSM "
        "footway, path, pedestrian way or steps",
    ),
    (
        "offset_from_osm_pedestrian_way",
        _offset_from_osm,
        f"pedestrian record whose worst point is {OFFSET_BAND_M[0]:g}-{OFFSET_BAND_M[1]:g} m "
        "from OSM pedestrian ways",
    ),
    (
        "crossing",
        lambda c: c.network_role in ("pedestrian_crossing", "cycling_or_shared_crossing"),
        "crosswalks, trail crossings and crossrides",
    ),
    ("trail", lambda c: c.subcategory in TRAILS, "multi-use, boulevard and natural trails"),
    ("walkway", lambda c: c.subcategory == "WALKWAY", "walkways between neighbourhoods"),
    (
        "merged_looking",
        lambda c: (c.part_count or 1) > 1 or (c.length_m or 0.0) >= MERGED_LOOKING_MIN_M,
        f"multi-part or at least {MERGED_LOOKING_MIN_M:g} m long",
    ),
    (
        "split_looking",
        lambda c: c.length_m is not None and c.length_m < SPLIT_LOOKING_MAX_M,
        f"shorter than {SPLIT_LOOKING_MAX_M:g} m without a curb-cut code",
    ),
    (
        "dense_core_sidewalk",
        lambda c: _sidewalk(c) and c.dense,
        "sidewalk in the densest tenth of the inventory in the study area",
    ),
    (
        "parallel_sidewalk_pair",
        lambda c: _sidewalk(c) and c.parallel_pair,
        "sidewalk whose road segment has sidewalks on both sides",
    ),
    (
        "residential_sidewalk",
        lambda c: _sidewalk(c) and c.nearest_road_highway in ("residential", "living_street"),
        "sidewalk whose nearest OSM road is residential",
    ),
    ("ordinary_sidewalk", _sidewalk, "any other active sidewalk"),
    ("other_physical", lambda c: True, "cycling, maintenance and remaining physical records"),
)


def assign_stratum(candidate: Candidate) -> str:
    for name, rule, _why in STRATA:
        if rule(candidate):
            return name
    raise AssertionError("the last stratum accepts everything")  # pragma: no cover


def selection_key(snapshot_id: str, activetransportid: int, seed: str = SEED) -> str:
    return hashlib.sha256(f"{seed}:{snapshot_id}:{activetransportid}".encode()).hexdigest()


def allocate(sizes: dict[str, int], target: int, minimum: int) -> dict[str, int]:
    """Minimum per non-empty stratum, the remainder by largest remainder.

    Deterministic: ties in the remainder go to the larger stratum, then by name.
    Never allocates more than a stratum holds.
    """
    allocation = {name: min(size, minimum) for name, size in sizes.items()}
    remaining = target - sum(allocation.values())
    while remaining > 0:
        spare = {name: sizes[name] - allocation[name] for name in sizes}
        open_strata = {name: room for name, room in spare.items() if room > 0}
        if not open_strata:
            break
        weight = sum(sizes[name] for name in open_strata)
        quotas = {name: remaining * sizes[name] / weight for name in open_strata}
        granted = {name: min(int(quotas[name]), open_strata[name]) for name in open_strata}
        if sum(granted.values()) == 0:
            order = sorted(
                open_strata,
                key=lambda name: (-(quotas[name] - int(quotas[name])), -sizes[name], name),
            )
            granted = {order[0]: 1}
        for name, extra in granted.items():
            allocation[name] += extra
        remaining = target - sum(allocation.values())
    return allocation


@dataclass(frozen=True, slots=True)
class Sampled:
    candidate: Candidate
    stratum: str
    rank: int


def draw_sample(
    candidates: Sequence[Candidate],
    snapshot_id: str,
    *,
    target: int = TARGET,
    minimum: int = MINIMUM_PER_STRATUM,
    seed: str = SEED,
) -> tuple[list[Sampled], dict[str, dict[str, Any]]]:
    members: dict[str, list[Candidate]] = {name: [] for name, _rule, _why in STRATA}
    for candidate in candidates:
        members[assign_stratum(candidate)].append(candidate)
    sizes = {name: len(group) for name, group in members.items()}
    allocation = allocate(sizes, target, minimum)

    sampled: list[Sampled] = []
    for name, _rule, _why in STRATA:
        ordered = sorted(
            members[name],
            key=lambda c: selection_key(snapshot_id, c.activetransportid, seed),
        )
        sampled.extend(
            Sampled(candidate, name, rank)
            for rank, candidate in enumerate(ordered[: allocation[name]], start=1)
        )
    strata = {
        name: {"rule": why, "population": sizes[name], "sampled": allocation[name]}
        for name, _rule, why in STRATA
    }
    return sampled, strata
