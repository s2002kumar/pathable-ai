"""The PA-GEO-04 sample: stratified from the population, reproducible, never hand-picked."""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from pathable_api.geo.kitchener.sample import (
    STRATA,
    Candidate,
    allocate,
    assign_stratum,
    draw_sample,
    selection_key,
)

BASE = Candidate(
    activetransportid=0,
    physical_class="physical_active",
    network_role="pedestrian_way",
    subcategory="SIDEWALK",
    structure=None,
    curbcut="N",
    length_m=80.0,
    part_count=1,
    max_offset_to_osm_pedestrian_m=0.8,
    nearest_road_highway="tertiary",
    dense=False,
    parallel_pair=False,
)


def _candidates(count: int, **values: object) -> list[Candidate]:
    return [replace(BASE, activetransportid=10_000 + i, **values) for i in range(count)]  # type: ignore[arg-type]


class TestStrata:
    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            ({"physical_class": "virtual_link", "network_role": "virtual_link"}, "virtual_link"),
            ({"structure": "STAIRS", "curbcut": "Y"}, "stairs"),
            ({"curbcut": "Y", "dense": True}, "curb_cut_coded"),
            ({"max_offset_to_osm_pedestrian_m": None}, "not_along_osm_pedestrian_way"),
            ({"max_offset_to_osm_pedestrian_m": 25.0}, "not_along_osm_pedestrian_way"),
            ({"max_offset_to_osm_pedestrian_m": 4.0}, "offset_from_osm_pedestrian_way"),
            ({"network_role": "pedestrian_crossing", "subcategory": "CROSSWALK"}, "crossing"),
            ({"subcategory": "MUT"}, "trail"),
            ({"length_m": 3.0}, "split_looking"),
            ({"length_m": 900.0}, "merged_looking"),
            ({"dense": True, "parallel_pair": True}, "dense_core_sidewalk"),
            ({"parallel_pair": True}, "parallel_sidewalk_pair"),
            ({"nearest_road_highway": "residential"}, "residential_sidewalk"),
            ({}, "ordinary_sidewalk"),
            ({"network_role": "cycling_facility", "subcategory": "BICYCLE LANE"}, "other_physical"),
        ],
    )
    def test_the_first_matching_rule_wins(self, values: dict[str, object], expected: str) -> None:
        assert assign_stratum(replace(BASE, **values)) == expected  # type: ignore[arg-type]

    def test_every_stratum_is_named_once(self) -> None:
        names = [name for name, _rule, _why in STRATA]
        assert len(names) == len(set(names))
        assert names[-1] == "other_physical"


class TestAllocation:
    def test_small_strata_get_their_minimum_and_large_ones_the_rest(self) -> None:
        allocation = allocate({"big": 1000, "mid": 100, "rare": 2, "empty": 0}, 20, 3)

        # 3 + 3 + 2 first; the other 12 split 1000:100 → 10 and 1, and the last
        # seat goes to the largest remainder.
        assert allocation == {"big": 14, "mid": 4, "rare": 2, "empty": 0}
        assert sum(allocation.values()) == 20

    def test_nothing_is_allocated_beyond_what_exists(self) -> None:
        allocation = allocate({"a": 4, "b": 1}, 80, 3)

        assert allocation == {"a": 4, "b": 1}

    def test_the_remainder_follows_population_size(self) -> None:
        allocation = allocate({"a": 600, "b": 300, "c": 100}, 40, 3)

        assert allocation["a"] > allocation["b"] > allocation["c"] >= 3
        assert sum(allocation.values()) == 40


class TestDraw:
    def test_the_same_snapshot_draws_the_same_sample_whatever_the_input_order(self) -> None:
        population = _candidates(200) + _candidates(30, curbcut="Y")
        shuffled = population[:]
        random.Random(7).shuffle(shuffled)

        first, strata = draw_sample(population, "snapshot-a", target=12)
        second, _ = draw_sample(shuffled, "snapshot-a", target=12)

        assert [s.candidate.activetransportid for s in first] == [
            s.candidate.activetransportid for s in second
        ]
        assert strata["curb_cut_coded"]["population"] == 30
        assert strata["ordinary_sidewalk"]["population"] == 200

    def test_a_different_snapshot_draws_a_different_sample(self) -> None:
        population = _candidates(500)

        first, _ = draw_sample(population, "snapshot-a", target=10)
        second, _ = draw_sample(population, "snapshot-b", target=10)

        assert {s.candidate.activetransportid for s in first} != {
            s.candidate.activetransportid for s in second
        }

    def test_selection_is_the_documented_hash_order(self) -> None:
        population = _candidates(50)

        sampled, _ = draw_sample(population, "snap", target=5, minimum=5)

        expected = sorted(population, key=lambda c: selection_key("snap", c.activetransportid))[:5]
        assert [s.candidate for s in sampled] == expected
        assert [s.rank for s in sampled] == [1, 2, 3, 4, 5]
