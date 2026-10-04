"""PA-GEO-08's held-out sample: aimed at what v1 could not settle, and never development data."""

from __future__ import annotations

from dataclasses import replace

from shapely.geometry import LineString

from pathable_api.geo.kitchener.conflation import Record
from pathable_api.geo.kitchener.holdout import Signals
from pathable_api.geo.kitchener.matcher_v2_holdout import (
    Situation,
    assign_stratum,
    draw,
    packs,
    repeat_subset,
    seed_for,
)


def _record(
    record_id: int,
    *,
    curb_cut: bool = False,
    structure: str | None = None,
    length_m: float = 20.0,
    family: str = "sidewalk",
) -> Record:
    return Record(
        activetransportid=record_id,
        network_role="pedestrian_way",
        family=family,
        subcategory="SIDEWALK",
        structure=structure,
        curb_cut=curb_cut,
        surface_material=None,
        length_m=length_m,
        street=None,
        geometry=LineString([(0, 0), (length_m, 0)]),
    )


BASE = Signals(
    candidate_ways=5,
    pedestrian_within_5m_share=1.0,
    best_worst_point_m=1.0,
    parallel_ways=1,
    splitting_ways=1,
    city_neighbours=2,
    osm_kerb_within_3m=False,
)
PLAIN = Situation(
    base=BASE,
    kerb_within_2m=False,
    crossing_way_within_2m=False,
    crossing_node_within_3m=False,
    crossing_way_within_5m=False,
    pedestrian_ways_within_3m=1,
    steps_covering=False,
    steps_near=False,
    generic_covering=True,
    nearest_pedestrian_m=0.5,
)


def test_stairs_are_told_apart_by_what_osm_draws_there() -> None:
    stair = _record(1, structure="STAIRS")

    assert assign_stratum(stair, replace(PLAIN, steps_covering=True, steps_near=True)) == (
        "stairs_explicit_steps"
    )
    # Steps nearby that do not run beside the stair: possibly the stair, displaced.
    assert assign_stratum(stair, replace(PLAIN, steps_near=True)) == "stairs_displaced_steps"
    # No steps anywhere near, a plain footway beside it.
    assert assign_stratum(stair, PLAIN) == "stairs_generic_footway"
    assert assign_stratum(stair, replace(PLAIN, generic_covering=False)) == "stairs_other"


def test_curb_cuts_are_split_by_kerb_node_junction_and_length() -> None:
    junction = replace(PLAIN, pedestrian_ways_within_3m=2)

    assert assign_stratum(_record(1, curb_cut=True, length_m=0.6), junction) == (
        "curb_cut_sub_metre"
    )
    assert assign_stratum(_record(2, curb_cut=True, length_m=2.0), junction) == (
        "curb_cut_no_kerb_junction"
    )
    assert assign_stratum(_record(3, curb_cut=True, length_m=2.0), PLAIN) == (
        "curb_cut_no_kerb_single_way"
    )
    onto_crossing = replace(junction, kerb_within_2m=True, crossing_way_within_2m=True)
    assert assign_stratum(_record(4, curb_cut=True, length_m=2.0), onto_crossing) == (
        "curb_cut_kerb_onto_crossing"
    )
    # Not a curb cut: a short piece where ways meet is a corner or junction piece.
    assert assign_stratum(_record(5, length_m=3.0), junction) == "corner_junction_piece"


def test_the_draw_never_takes_a_record_of_either_earlier_sample() -> None:
    records = [_record(i, curb_cut=i % 3 == 0, length_m=2.0) for i in range(1, 401)]
    situations = {r.activetransportid: PLAIN for r in records}
    development = frozenset(range(1, 401, 5))
    seed = seed_for("snapshot", "extract")

    drawn, description = draw(records, situations, development, seed)
    again, _ = draw(list(reversed(records)), situations, development, seed)

    ids = [d.record.activetransportid for d in drawn]
    assert ids == [d.record.activetransportid for d in again]
    assert not set(ids) & development
    assert description["development_records_excluded"] == len(development)
    assert description["strata"]["curb_cut_no_kerb_single_way"]["sampled"] == 12


def test_the_repeat_subset_and_packs_see_every_stratum() -> None:
    features = [
        {"properties": {"activetransportid": i, "stratum": f"s{i % 7}"}} for i in range(1, 191)
    ]
    document = {"metadata": {"seed": "seed"}, "features": features}

    repeat = repeat_subset(document)
    dealt = packs(list(range(1, 191)), 5, "primary")

    assert len(repeat) == 60
    assert {f"s{i % 7}" for i in repeat} == {f"s{n}" for n in range(7)}
    assert repeat == repeat_subset(document)
    assert sorted(len(v) for v in dealt.values()) == [38] * 5
    assert sorted(i for v in dealt.values() for i in v) == list(range(1, 191))
