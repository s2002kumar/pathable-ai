"""The research artifact: what the City asserts, beside what OSM says, never merged."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
from shapely.geometry import LineString

from pathable_api.geo.kitchener.canonical import UNRESOLVED, assertions, comparisons, write_artifact
from pathable_api.geo.kitchener.conflation import MATCHED, Decision, Record, Target
from tests.unit.kitchener_streets import SIDEWALK, Street


def _record(**attributes: Any) -> Record:
    geometry = LineString([(98, 0), (100, 0)])
    values: dict[str, Any] = {"source_date": "2016-05-01", "last_inspection_year": None}
    values.update(attributes)
    return Record(
        activetransportid=10,
        network_role="pedestrian_way",
        family="sidewalk",
        subcategory="SIDEWALK",
        structure=values.get("structure"),
        curb_cut=values.get("curbcut") == "Y" and values.get("state_curbcut") == "non_default",
        surface_material=values.get("surface_material")
        if values.get("state_surface_material") == "non_default"
        else None,
        length_m=2.0,
        street=None,
        geometry=geometry,
        attributes=values,
    )


CURB_CUT: dict[str, Any] = {
    "curbcut": "Y",
    "state_curbcut": "non_default",
    "origin_curbcut": "observed_source",
}


class TestAssertions:
    def test_a_curb_cut_is_asserted_as_present_and_never_as_a_kerb_height(self) -> None:
        (row,) = assertions(_record(**CURB_CUT))

        assert row["attribute"] == "curb_cut"
        assert row["normalized_value"] == "curb_cut_present"
        assert "lowered" not in json.dumps(row)
        assert "flush" not in json.dumps(row)
        assert row["lineage_state"] == "not_assessed"

    def test_defaults_assert_nothing(self) -> None:
        record = _record(
            curbcut="N",
            state_curbcut="default",
            surface_material="CONCRETE",
            state_surface_material="default",
            railing="N",
            state_railing="default",
            surface_condition="GOOD",
            state_surface_condition="default",
        )

        assert assertions(record) == []

    def test_a_2015_condition_is_historical(self) -> None:
        (row,) = assertions(
            _record(surface_condition="POOR", state_surface_condition="non_default")
        )

        assert row["observed"] == "2015"
        assert "not a current condition" in row["note"]


class TestComparisons:
    def test_both_sides_are_kept_and_nothing_is_resolved(self) -> None:
        street = Street()
        kerb = street.node(100, 0.3, {"barrier": "kerb", "kerb": "raised"})
        street.way(1, [street.node(0, 0.3), kerb], {**SIDEWALK, "surface": "concrete"})
        record = _record(
            **CURB_CUT, surface_material="ASPHALT", state_surface_material="non_default"
        )
        decision = Decision(
            10,
            MATCHED,
            "fixture",
            (Target(f"node/{kerb}", "kerb"), Target("way/1", "carrier", 98.0, 100.0)),
            "one_to_one",
            "multiple",
            {},
        )

        rows = {row["attribute"]: row for row in comparisons(record, decision, street.index())}

        assert rows["curb_cut"]["comparison"] == "conflict"
        assert rows["curb_cut"]["osm_values"] == ["raised"]
        assert rows["surface_material"]["comparison"] == "conflict"
        assert rows["surface_material"]["kitchener_value"] == "asphalt"
        assert rows["surface_material"]["osm_values"] == ["concrete"]
        assert {row["resolution"] for row in rows.values()} == {UNRESOLVED}

    def test_an_osm_surface_the_city_leaves_at_its_default_is_osm_only(self) -> None:
        street = Street()
        street.line(1, [(0, 0.3), (100, 0.3)], {**SIDEWALK, "surface": "paving_stones"})
        decision = Decision(
            10, MATCHED, "fixture", (Target("way/1", "carrier", 98.0, 100.0),), None, "", {}
        )

        (row,) = comparisons(_record(), decision, street.index())

        assert (row["kitchener_value"], row["comparison"]) == (None, "osm_only")


def test_the_artifact_is_geoparquet_and_byte_for_byte_reproducible(tmp_path: Path) -> None:
    street = Street()
    street.line(1, [(0, 0.3), (100, 0.3)], SIDEWALK)
    record = _record(**CURB_CUT)
    decision = Decision(
        10, MATCHED, "fixture", (Target("way/1", "carrier", 98.0, 100.0),), "one_to_one", "", {}
    )

    first = write_artifact(tmp_path / "a", [record], {10: decision}, street.index(), "snap", "v")
    second = write_artifact(tmp_path / "b", [record], {10: decision}, street.index(), "snap", "v")

    assert first == second
    assert sorted(p.name for p in (tmp_path / "a").iterdir()) == [
        "assertions.parquet",
        "comparisons.parquet",
        "matches.parquet",
        "source_features.parquet",
    ]
    source = (tmp_path / "a" / "source_features.parquet").as_posix()
    connection = duckdb.connect()
    geo = connection.execute(
        f"SELECT value FROM parquet_kv_metadata('{source}') WHERE key = 'geo'"  # noqa: S608
    ).fetchone()
    assert geo is not None
    assert json.loads(geo[0])["columns"]["geometry"]["encoding"] == "WKB"
    matches = (tmp_path / "a" / "matches.parquet").as_posix()
    targets = connection.execute(
        f"SELECT targets FROM read_parquet('{matches}')"  # noqa: S608
    ).fetchone()
    assert targets is not None
    assert targets[0][0]["osm_version"] == 1
    assert targets[0][0]["to_m"] - targets[0][0]["from_m"] == 2.0
