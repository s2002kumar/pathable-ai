"""The whole benchmark run on invented streets: what it refuses, and what it writes.

The development records are built so that the declared selection rule picks
exactly the frozen policy: a sidewalk drawn 2.5 m off needs the 3 m carry
distance, and a record running 35 m past the end of its sidewalk needs the
0.6 coverage floor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import LineString

from pathable_api.geo.kitchener.benchmark_labels import Label, parse_label
from pathable_api.geo.kitchener.conflation import (
    ConflationInputs,
    Population,
    Record,
    RelationshipIndex,
)
from pathable_api.geo.kitchener.correspondence import KitchenerFeature, KitchenerIndex
from pathable_api.geo.kitchener.evaluation import (
    BenchmarkError,
    LabelSets,
    run_benchmark,
    run_pilot,
)
from pathable_api.geo.kitchener.failures_page import render_failures
from tests.unit.kitchener_streets import SIDEWALK, Street


def _record(record_id: int, points: list[tuple[float, float]]) -> Record:
    geometry = LineString(points)
    return Record(
        activetransportid=record_id,
        network_role="pedestrian_way",
        family="sidewalk",
        subcategory="SIDEWALK",
        structure=None,
        curb_cut=False,
        surface_material=None,
        length_m=float(geometry.length),
        street=None,
        geometry=geometry,
        attributes={"publications": ["Active_Transportation"]},
    )


def _obvious(record_id: int, way: int) -> Label:
    return parse_label(
        {
            "activetransportid": record_id,
            "correspondence": "obvious_correspondence",
            "osm": [f"way/{way}"],
            "representation": "separate_way",
            "relationship": "one_to_one",
        }
    )


def _none(record_id: int) -> Label:
    return parse_label(
        {
            "activetransportid": record_id,
            "correspondence": "no_correspondence",
            "osm": [],
            "representation": "none",
            "relationship": None,
        }
    )


def _inputs() -> ConflationInputs:
    street = Street()
    street.line(1, [(0, 2.5), (100, 2.5)], SIDEWALK)  # development: 2.5 m off
    street.line(2, [(1000, 1), (1065, 1)], SIDEWALK)  # development: ends at 65 m
    street.line(3, [(2000, 1), (2100, 1)], SIDEWALK)  # held out
    street.line(4, [(4000, 1), (4100, 1)], SIDEWALK)  # held out, the wrong way
    street.line(5, [(4000, 9), (4100, 9)], SIDEWALK)
    records = [
        _record(1, [(10, 0), (90, 0)]),
        _record(2, [(1000, 0), (1100, 0)]),
        _record(3, [(2010, 0), (2090, 0)]),
        _record(4, [(3010, 0), (3090, 0)]),  # nothing within 25 m
        _record(5, [(4010, 0), (4090, 0)]),
    ]
    physical = KitchenerIndex.build(
        KitchenerFeature(
            r.activetransportid, "physical_active", r.network_role, "SIDEWALK", r.geometry
        )
        for r in records
    )
    index = street.index()
    return ConflationInputs(
        osm=index,
        population=Population(records, {}, physical),
        eligible=physical,
        relationships=RelationshipIndex(physical, index.lines),
        parquet=Path("fixture.parquet"),
        identity={"kitchener": {"snapshot_id": "fixture"}},
    )


def _sets(**overrides: Any) -> LabelSets:
    holdout = {3: _obvious(3, 3), 4: _none(4), 5: _obvious(5, 5)}
    values: dict[str, Any] = {
        "development": {1: _obvious(1, 1), 2: _obvious(2, 2)},
        "holdout": holdout,
        "repeat": {3: _obvious(3, 3)},
        "strata": {3: "straightforward", 4: "no_osm_pedestrian_way", 5: "parallel_ways"},
        "packs": {3: "primary-1", 4: "primary-1", 5: "primary-2"},
        "identity": {},
    }
    values.update(overrides)
    return LabelSets(**values)


def test_the_run_scores_the_frozen_policy_and_names_every_failure(tmp_path: Path) -> None:
    inputs = _inputs()

    report, timings, decisions = run_benchmark(inputs, _sets())

    assert report["development"]["selected"] == {
        "carry_m": 3.0,
        "cover_min": 0.6,
        "contest_margin_m": 1.5,
        "contest_max": 0.2,
    }
    holdout = report["holdout"]
    assert holdout["matcher"]["outcomes"]["obvious_correspondence"] == {"exact": 1, "wrong": 1}
    assert holdout["matcher"]["outcomes"]["no_correspondence"] == {"correctly_unmatched": 1}
    (failure,) = holdout["failure_analysis"]["records"]
    assert (failure["activetransportid"], failure["outcome"]) == (5, "wrong")
    assert set(holdout["baselines"]) == {
        "A_nearest_geometry",
        "B_median_offset",
        "C_worst_point",
        "D_overlap_2m",
    }
    assert holdout["repeat_labels"]["same_correspondence"] == 1
    assert "holdout_matching_s" in timings

    pilot, _ = run_pilot(inputs, tmp_path / "artifact", check=decisions)
    assert pilot["records"] == 5
    assert pilot["agrees_with_the_benchmark_decisions"] == 3
    assert pilot["artifact"]["files"]["matches"]["rows"] == 5

    page = render_failures(report, inputs.population.physical, inputs.osm, {"osm": "fixture"})
    assert page.count('<section class="record"') == 1
    assert "Cause not yet recorded" in page


def test_the_run_refuses_when_the_grid_no_longer_selects_the_frozen_policy() -> None:
    # With only the clean held-out-like record to tune on, every grid point ties
    # and the rule picks the most conservative values, not the frozen ones.
    sets = _sets(development={3: _obvious(3, 3)})

    with pytest.raises(BenchmarkError, match="not the frozen policy"):
        run_benchmark(_inputs(), sets)


def test_the_pilot_refuses_to_disagree_with_the_benchmark(tmp_path: Path) -> None:
    inputs = _inputs()
    _report, _timings, decisions = run_benchmark(inputs, _sets())
    altered = {3: decisions[5], **{k: v for k, v in decisions.items() if k != 3}}

    with pytest.raises(BenchmarkError, match="decided differently"):
        run_pilot(inputs, tmp_path / "artifact", check=altered)
