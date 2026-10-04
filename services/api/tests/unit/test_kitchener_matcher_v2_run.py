"""PA-GEO-08's benchmark run end to end, on invented streets and labels.

The held-out evaluation runs once, so the pipeline around it must refuse to be
anything else: a different development policy, a pilot that disagrees with the
evaluation, or labels made for another sample.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import LineString

from pathable_api.geo.kitchener.benchmark_labels import Label
from pathable_api.geo.kitchener.conflation import (
    ConflationInputs,
    Population,
    Record,
    RelationshipIndex,
)
from pathable_api.geo.kitchener.correspondence import KitchenerFeature, KitchenerIndex
from pathable_api.geo.kitchener.matcher_v2 import MatcherV2Policy
from pathable_api.geo.kitchener.matcher_v2_benchmark import (
    BenchmarkV2Error,
    LabelSets,
    load_label_sets,
    render_errors,
    run_benchmark,
    run_pilot,
)
from pathable_api.geo.kitchener.matcher_v2_labels import LABELS_KEY, LABELS_VERSION
from tests.unit.kitchener_streets import CROSSING, SIDEWALK, Street

KERB = {"barrier": "kerb", "kerb": "lowered"}


def _record(record_id: int, points: list[tuple[float, float]], *, curb_cut: bool = False) -> Record:
    geometry = LineString(points)
    return Record(
        activetransportid=record_id,
        network_role="pedestrian_way",
        family="sidewalk",
        subcategory="SIDEWALK",
        structure=None,
        curb_cut=curb_cut,
        surface_material=None,
        length_m=float(geometry.length),
        street="FIXTURE ST",
        geometry=geometry,
    )


def _inputs() -> tuple[ConflationInputs, int]:
    street = Street()
    kerb = street.node(100, 0, KERB)
    street.way(1, [street.node(0, 0), kerb], SIDEWALK)
    street.way(2, [kerb, street.node(114, 0)], CROSSING)
    index = street.index()
    records = [
        _record(1, [(10, 0.5), (90, 0.5)]),
        _record(2, [(98.5, 0.3), (101.5, 0.3)], curb_cut=True),
        _record(3, [(0, 50), (80, 50)]),
    ]
    physical = KitchenerIndex.build(
        KitchenerFeature(
            r.activetransportid, "physical_active", r.network_role, r.subcategory, r.geometry
        )
        for r in records
    )
    inputs = ConflationInputs(
        osm=index,
        population=Population(records, {}, physical),
        eligible=physical,
        relationships=RelationshipIndex(physical, index.lines),
        parquet=Path("fixture.parquet"),
        identity={},
    )
    return inputs, kerb


def _sets(kerb: int) -> LabelSets:
    development = {
        1: Label(
            1, "obvious_correspondence", frozenset({"way/1"}), "separate_way", "one_to_one", ""
        ),
        3: Label(3, "no_correspondence", frozenset(), "none", None, ""),
    }
    holdout = {
        2: Label(
            2,
            "obvious_correspondence",
            frozenset({f"node/{kerb}", "way/1", "way/2"}),
            "multiple",
            "one_to_many",
            "",
        )
    }
    return LabelSets(
        development=development,
        holdout=holdout,
        repeat=dict(holdout),
        strata={2: "curb_cut_kerb_onto_crossing"},
        packs={2: "primary-1"},
        identity={},
    )


def _frozen_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    # Two development records cannot select a policy; the grid is not what is tested here.
    monkeypatch.setattr(
        "pathable_api.geo.kitchener.matcher_v2_benchmark.tune",
        lambda _decide, base: (base, []),
    )


def test_the_run_scores_the_holdout_and_the_pilot_agrees_with_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _frozen_grid(monkeypatch)
    inputs, kerb = _inputs()

    report, _timings, decisions = run_benchmark(inputs, _sets(kerb))
    pilot, _ = run_pilot(inputs, check=decisions)

    holdout = report["holdout"]
    assert holdout["matcher_v2"]["records_level"]["exact_set_agreement"] == 1
    assert holdout["candidate_generation"]["recall"] == 1.0
    # v1's class rule never lets the crossing carry the curb cut; v2 names it.
    assert holdout["v1_against_v2_by_class"]["curb_cuts"]["records_changed"] == {"fixed_by_v2": 1}
    assert pilot["v2_states"] == {"matched": 2, "unmatched": 1}
    assert pilot["agrees_with_the_benchmark_decisions"] == 1
    assert "PA-GEO-08 held-out failures" in render_errors(
        report, inputs.population.physical, inputs.osm, {"osm": "© OpenStreetMap contributors"}
    )


def test_the_run_refuses_a_development_grid_that_selects_another_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pathable_api.geo.kitchener.matcher_v2_benchmark.tune",
        lambda _decide, base: (base.with_(follow_max_deg=20.0), []),
    )
    inputs, kerb = _inputs()

    with pytest.raises(BenchmarkV2Error, match="changed after it was frozen"):
        run_benchmark(inputs, _sets(kerb))


def test_the_pilot_refuses_to_disagree_with_the_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    _frozen_grid(monkeypatch)
    inputs, kerb = _inputs()
    _report, _timings, decisions = run_benchmark(inputs, _sets(kerb))
    tampered = {2: replace(decisions[2], rule="something_else")}

    with pytest.raises(BenchmarkV2Error, match="decided differently"):
        run_pilot(inputs, check=tampered)


def _write(folder: Path, name: str, document: dict[str, Any]) -> Path:
    path = folder / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_labels_made_for_another_sample_are_refused(tmp_path: Path) -> None:
    sample = {
        "metadata": {"seed": "seed"},
        "features": [{"properties": {"activetransportid": 2, "stratum": "s"}}],
    }
    _write(tmp_path, "kitchener-geo08-holdout.geojson", sample)
    (tmp_path / "kitchener-geo08-labelling-guide.md").write_text("guide", encoding="utf-8")
    label = {
        "activetransportid": 2,
        "correspondence": "no_correspondence",
        "osm": [],
        "representation": "none",
        "relationship": None,
        "note": "",
        "pack": "primary-1",
    }
    labels = {
        LABELS_KEY: LABELS_VERSION,
        "holdout": {"sha256": "not the sample"},
        "labelling_guide": {"sha256": "whatever"},
        "records": [label],
    }
    for name in ("holdout-labels", "holdout-repeat-labels"):
        _write(tmp_path, f"kitchener-geo08-{name}.json", labels)
    _write(
        tmp_path,
        "kitchener-geo08-development-labels.json",
        {LABELS_KEY: LABELS_VERSION, "records": []},
    )

    with pytest.raises(BenchmarkV2Error, match="different held-out sample"):
        load_label_sets(tmp_path)


def test_the_frozen_policy_is_the_one_the_write_up_describes() -> None:
    frozen = MatcherV2Policy()
    assert (frozen.follow_max_deg, frozen.rival_extra_deg, frozen.carry_m, frozen.cover_min) == (
        15.0,
        15.0,
        3.0,
        0.75,
    )
