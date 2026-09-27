"""The held-out sample: deterministic, stratified, and never a development record."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from shapely.geometry import LineString

from pathable_api.geo.kitchener.conflation import Record
from pathable_api.geo.kitchener.holdout import (
    STRATA,
    HoldoutError,
    Signals,
    Thresholds,
    assign_stratum,
    development_ids,
    draw,
    repeat_subset,
    seed_for,
)


def _record(record_id: int, *, curb_cut: bool = False, structure: str | None = None) -> Record:
    geometry = LineString([(0, 0), (20, 0)])
    return Record(
        activetransportid=record_id,
        network_role="pedestrian_way",
        family="sidewalk",
        subcategory="SIDEWALK",
        structure=structure,
        curb_cut=curb_cut,
        surface_material=None,
        length_m=20.0,
        street=None,
        geometry=geometry,
    )


def _signals(**overrides: object) -> Signals:
    values: dict[str, object] = {
        "candidate_ways": 5,
        "pedestrian_within_5m_share": 1.0,
        "best_worst_point_m": 1.0,
        "parallel_ways": 1,
        "splitting_ways": 1,
        "city_neighbours": 2,
        "osm_kerb_within_3m": False,
    }
    values.update(overrides)
    return Signals(**values)  # type: ignore[arg-type]


LIMITS = Thresholds(dense_city_neighbours=10, heavy_candidate_ways=30)


def test_the_first_matching_stratum_wins() -> None:
    stairs_curb_cut = _record(1, curb_cut=True, structure="STAIRS")

    assert assign_stratum(stairs_curb_cut, _signals(), LIMITS) == "stairs"
    kerb_near = _signals(osm_kerb_within_3m=True)
    assert assign_stratum(_record(2, curb_cut=True), kerb_near, LIMITS) == "curb_cut_osm_kerb_near"
    assert assign_stratum(_record(3), _signals(pedestrian_within_5m_share=0.0), LIMITS) == (
        "no_osm_pedestrian_way"
    )
    assert assign_stratum(_record(4), _signals(), LIMITS) == "straightforward"


def test_the_draw_is_deterministic_and_never_takes_a_development_record() -> None:
    records = [_record(i, curb_cut=i % 2 == 0) for i in range(1, 301)]
    signals = {r.activetransportid: _signals() for r in records}
    development = frozenset(range(1, 301, 7))
    seed = seed_for("snapshot", "extract")

    drawn, description = draw(records, signals, development, seed)
    again, _ = draw(list(reversed(records)), signals, development, seed)

    ids = [d.record.activetransportid for d in drawn]
    assert ids == [d.record.activetransportid for d in again]
    assert not set(ids) & development
    assert description["development_records_excluded"] == len(development)
    targets = {name: target for name, _rule, _why, target in STRATA}
    for name, stratum in description["strata"].items():
        assert stratum["sampled"] == min(targets[name], stratum["population"])
    other, _ = draw(records, signals, development, seed_for("snapshot", "another extract"))
    assert [d.record.activetransportid for d in other] != ids


def test_the_repeat_subset_covers_every_stratum_and_is_stable() -> None:
    features = [
        {"properties": {"activetransportid": i, "stratum": f"s{i % 4}"}} for i in range(1, 81)
    ]
    document = {"metadata": {"seed": "fixture"}, "features": features}

    chosen = repeat_subset(document, target=20)

    assert len(chosen) == 20
    assert {i % 4 for i in chosen} == {0, 1, 2, 3}
    assert chosen == repeat_subset({**document, "features": list(reversed(features))}, target=20)


def test_a_changed_development_sample_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "sample.geojson"
    path.write_text(json.dumps({"features": [{"properties": {"activetransportid": 7}}]}), "utf-8")

    ids, identity = development_ids(path, None)
    assert ids == {7}
    with pytest.raises(HoldoutError, match="not the recorded"):
        development_ids(path, "0" * 64)
    assert identity["records"] == 1
