"""The analytical GeoParquet file: complete, faithful, byte-reproducible, and honest.

Built from the fixture snapshot with the real normalization code, then read
back with DuckDB — the reader the profile uses — with extension autoloading
off, so nothing here can reach the network.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import duckdb
import pytest

from pathable_api.geo.kitchener.normalize import (
    GEOPARQUET_VERSION,
    NORMALIZED_FILE,
    NormalizationError,
    load_normalized,
    normalize_snapshot,
)
from pathable_api.geo.kitchener.snapshot import SnapshotError
from pathable_api.geo.overture.evidence import file_sha256
from tests.kitchener_fixture import (
    AT_RECORDS,
    LICENCE_HTML,
    WALK_RECORDS,
    X0,
    FakeArcGIS,
    build_layers,
    snapshot,
)


def _connect() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute("SET autoinstall_known_extensions = false")
    connection.execute("SET autoload_known_extensions = false")
    return connection


def _rows(path: Path, sql: str) -> list[tuple[Any, ...]]:
    with _connect() as connection:
        return [tuple(r) for r in connection.execute(sql, [path.as_posix()]).fetchall()]


def _by_id(path: Path, columns: str) -> dict[int, tuple[Any, ...]]:
    query = f"SELECT activetransportid, {columns} FROM read_parquet(?)"  # noqa: S608 - test columns
    return {int(row[0]): row[1:] for row in _rows(path, query)}


@pytest.fixture
def normalized(tmp_path: Path) -> Path:
    taken = snapshot(tmp_path / "snapshots")
    return normalize_snapshot(taken.folder, tmp_path / "normalized").folder / NORMALIZED_FILE


class TestJoin:
    def test_one_row_per_permanent_id_across_both_publications(self, normalized: Path) -> None:
        at_ids = {r["attributes"]["ACTIVETRANSPORTID"] for _p, r in AT_RECORDS}
        walk_ids = {r["attributes"]["ACTIVETRANSPORTID"] for _p, r in WALK_RECORDS}
        rows = _by_id(normalized, "in_active_transportation, in_walkability, identity_state")

        assert set(rows) == at_ids | walk_ids
        assert rows[1001] == (True, True, "unique")
        assert rows[1004] == (True, False, "unique")
        assert rows[2001] == (False, True, "unique")

    def test_fields_a_publication_does_not_carry_are_not_published(self, normalized: Path) -> None:
        rows = _by_id(normalized, "state_curbcut, state_status, lifecycle, curbcut")

        assert rows[2001] == ("not_published", "not_published", "not_published", None)
        assert rows[1002][:3] == ("non_default", "template_default", "ACTIVE")

    def test_walkability_stripping_defaults_does_not_hide_them(self, normalized: Path) -> None:
        # Regression: the Walkability publication serves no default values, so
        # classifying its records by its own schema called a template CONCRETE
        # "non_default". Defaults belong to the City's layer, which only
        # Active_Transportation publishes.
        rows = _by_id(normalized, "surface_material, state_surface_material")

        assert rows[2003] == ("CONCRETE", "template_default")

    def test_publication_disagreements_are_listed_not_resolved(self, tmp_path: Path) -> None:
        walk = [json.loads(json.dumps(r)) for _p, r in WALK_RECORDS]
        walk[0]["attributes"]["WIDTH_M"] = 2  # record 1001 disagrees on width
        taken = snapshot(tmp_path / "s", FakeArcGIS(build_layers(walk_records=walk)))
        result = normalize_snapshot(taken.folder, tmp_path / "n")

        rows = _by_id(result.folder / NORMALIZED_FILE, "publication_disagreements, width_m")
        assert rows[1001] == (["WIDTH_M"], 1.5)
        assert result.manifest["joins"]["fields_differing_between_publications"] == {"WIDTH_M": 1}

    def test_records_without_a_usable_identity_are_kept_but_never_joined(
        self, tmp_path: Path
    ) -> None:
        # Regression: an id repeated inside Active_Transportation was refused
        # there, but Walkability's single copy was still reported as a unique,
        # joined identity. An id that repeats anywhere is joined nowhere.
        at = [json.loads(json.dumps(r)) for _p, r in AT_RECORDS]
        at[1]["attributes"]["ACTIVETRANSPORTID"] = None  # was 1002
        at[2]["attributes"]["ACTIVETRANSPORTID"] = 1001  # was 1003; now collides with 1001
        taken = snapshot(tmp_path / "s", FakeArcGIS(build_layers(at_records=at)))
        result = normalize_snapshot(taken.folder, tmp_path / "n")

        rows = _rows(
            result.folder / NORMALIZED_FILE,
            "SELECT identity_state, in_active_transportation, in_walkability, count(*) "
            "FROM read_parquet(?) WHERE activetransportid = 1001 OR activetransportid IS NULL "
            "GROUP BY ALL ORDER BY ALL",
        )
        assert rows == [
            ("duplicate", False, True, 1),  # Walkability's 1001: not joined to either AT copy
            ("duplicate", True, False, 2),  # both Active_Transportation copies
            ("null", True, False, 1),
        ]
        # 1002 and 1003 now exist only in Walkability, as unique identities.
        assert result.manifest["joins"]["identity_states"] == {
            "duplicate": 3,
            "null": 1,
            "unique": 12,
        }


class TestClassification:
    def test_physical_and_virtual_records_are_classified(self, normalized: Path) -> None:
        rows = _by_id(normalized, "physical_class, network_role")

        assert rows[1001] == ("physical_active", "pedestrian_way")
        assert rows[1003] == ("physical_active", "pedestrian_crossing")
        assert rows[1007] == ("unresolved", "unresolved")
        assert rows[1008] == ("physical_active", "cycling_facility")
        assert rows[2001] == ("virtual_link", "virtual_link")
        assert rows[2002] == ("unofficial_connection", "unofficial_connection")
        assert rows[2003] == ("unresolved", "unresolved")

    def test_null_blank_unknown_and_default_stay_apart(self, normalized: Path) -> None:
        rows = _by_id(normalized, "state_surface_material, state_width_m, state_curbcut")

        assert rows[1001] == ("template_default", "template_default", "template_default")
        assert rows[1006] == ("null", "null", "unknown")
        assert rows[1010] == ("blank", "non_default", "template_default")
        assert rows[1005][0] == "non_default"

    def test_no_staff_names_reach_the_analytical_file(self, normalized: Path) -> None:
        columns = {row[0] for row in _rows(normalized, "DESCRIBE SELECT * FROM read_parquet(?)")}

        assert not {"create_by", "update_by", "objectid"} & columns
        rows = _by_id(normalized, "update_account")
        assert rows[1006] == ("named_account",)
        assert rows[1001] == ("GIS_DATA",)


class TestGeometry:
    def test_both_coordinate_systems_are_kept_with_axes_in_order(self, normalized: Path) -> None:
        with _connect() as connection:
            raw = connection.execute(
                "SELECT geometry, geometry_native, bbox FROM read_parquet(?) "
                "WHERE activetransportid = 1001",
                [normalized.as_posix()],
            ).fetchone()
        assert raw is not None
        import shapely

        primary = shapely.from_wkb(bytes(raw[0]))
        native = shapely.from_wkb(bytes(raw[1]))
        # The fixture starts on zone 17N's central meridian, so the first vertex
        # is exactly 81°W; a swapped axis order would put it near 45°.
        assert primary.coords[0][0] == pytest.approx(-81.0, abs=1e-9)
        assert 44.0 < primary.coords[0][1] < 46.0
        assert native.coords[0] == (X0, 5_000_000.0)
        assert raw[2]["xmin"] == pytest.approx(-81.0, abs=1e-9)

    def test_the_file_declares_geoparquet_1_1_with_its_crs(self, normalized: Path) -> None:
        with _connect() as connection:
            geo_json = connection.execute(
                "SELECT decode(value) FROM parquet_kv_metadata(?) WHERE decode(key) = 'geo'",
                [normalized.as_posix()],
            ).fetchone()
            types = connection.execute(
                "SELECT typeof(geometry), typeof(geometry_native) FROM read_parquet(?) LIMIT 1",
                [normalized.as_posix()],
            ).fetchone()
        assert geo_json is not None
        geo = json.loads(geo_json[0])
        assert geo["version"] == GEOPARQUET_VERSION == "1.1.0"
        assert geo["primary_column"] == "geometry"
        assert "crs" not in geo["columns"]["geometry"]  # the specification's OGC:CRS84
        assert geo["columns"]["geometry"]["covering"]["bbox"]["xmin"] == ["bbox", "xmin"]
        assert geo["columns"]["geometry_native"]["crs"]["id"] == {
            "authority": "EPSG",
            "code": 26917,
        }
        assert geo["columns"]["geometry"]["geometry_types"] == ["LineString"]
        assert len(geo["columns"]["geometry"]["bbox"]) == 4
        assert types is not None
        assert types[0] == "GEOMETRY('OGC:CRS84')"

    def test_lengths_are_metres_in_the_native_crs(self, normalized: Path) -> None:
        rows = _by_id(normalized, "length_m, shape_length_m, geometry_issue")

        assert rows[1001] == (100.0, 100.0, None)
        assert rows[1002][0] == pytest.approx(2.0)


class TestReproducibility:
    def test_the_same_snapshot_normalizes_to_the_same_bytes(self, tmp_path: Path) -> None:
        taken = snapshot(tmp_path / "s")
        first = normalize_snapshot(taken.folder, tmp_path / "one")
        second = normalize_snapshot(taken.folder, tmp_path / "two")

        assert first.manifest["output"]["sha256"] == second.manifest["output"]["sha256"]
        assert first.manifest["content_sha256"] == second.manifest["content_sha256"]
        assert file_sha256(first.folder / NORMALIZED_FILE) == file_sha256(
            second.folder / NORMALIZED_FILE
        )

    def test_output_is_never_overwritten(self, tmp_path: Path) -> None:
        taken = snapshot(tmp_path / "s")
        normalize_snapshot(taken.folder, tmp_path / "n")

        with pytest.raises(NormalizationError, match="never overwritten"):
            normalize_snapshot(taken.folder, tmp_path / "n")

    def test_a_tampered_snapshot_is_refused(self, tmp_path: Path) -> None:
        taken = snapshot(tmp_path / "s")
        features = taken.folder / "features" / "walkability.jsonl"
        features.chmod(stat.S_IWRITE | stat.S_IREAD)
        features.write_text("", "utf-8")

        with pytest.raises(SnapshotError, match="recorded SHA-256"):
            normalize_snapshot(taken.folder, tmp_path / "n")

    def test_a_changed_licence_stops_normalization(self, tmp_path: Path) -> None:
        changed = LICENCE_HTML.replace("No credit is required", "Credit is required")
        taken = snapshot(tmp_path / "s", FakeArcGIS(build_layers(), licence_html=changed))

        with pytest.raises(NormalizationError, match="licence"):
            normalize_snapshot(taken.folder, tmp_path / "n")

    def test_a_modified_output_is_refused_on_load(self, normalized: Path) -> None:
        normalized.write_bytes(normalized.read_bytes() + b"\0")

        with pytest.raises(NormalizationError, match="SHA-256"):
            load_normalized(normalized.parent)
