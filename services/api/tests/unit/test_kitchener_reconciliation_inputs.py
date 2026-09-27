"""What the reconciliation accepts as input, and what it refuses.

It reads PA-GEO-05's artifact rather than re-running the matcher, so the
artifact is its contract: the decisions must be the ones the benchmark
measured, from matcher v1, byte for byte what the manifest recorded.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import duckdb
import pytest

from pathable_api.geo.kitchener import conflation
from pathable_api.geo.kitchener.canonical import _MATCH_COLUMNS, write_table
from pathable_api.geo.kitchener.reconciliation_run import (
    ReconciliationError,
    city_record_fields,
    load_geo05_artifact,
)

MATCHER = "kitchener-geo05-matcher-v1"


def _match_rows(version: str = MATCHER) -> list[dict[str, Any]]:
    common = {"matcher_version": version, "candidate_contract_version": "c1"}
    return [
        {
            "source_record_id": 7,
            "match_state": "matched",
            "rule": "curb_cut_kerb_and_carrier",
            "relationship": "many_to_one",
            "representation": "multiple",
            "targets": [
                {
                    "element": "node/5",
                    "osm_version": 2,
                    "role": "kerb",
                    "from_m": None,
                    "to_m": None,
                },
                {
                    "element": "way/9",
                    "osm_version": 4,
                    "role": "carrier",
                    "from_m": 1.5,
                    "to_m": 3.0,
                },
            ],
            "signals": json.dumps({"coverage": 1.0}),
            **common,
        },
        {
            "source_record_id": 8,
            "match_state": "ambiguous",
            "rule": "competing_way",
            "relationship": None,
            "representation": "none",
            "targets": [],
            "signals": json.dumps({}),
            **common,
        },
    ]


def _artifact(folder: Path, *, version: str = MATCHER, row_version: str = MATCHER) -> Path:
    entry = write_table(folder / "matches.parquet", _MATCH_COLUMNS, _match_rows(row_version))
    manifest = {
        "policy": {"version": version},
        "files": {"matches": entry},
        "decisions_sha256": "d" * 64,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def test_pa_geo_05_decisions_are_read_exactly_as_the_artifact_holds_them(tmp_path: Path) -> None:
    found = load_geo05_artifact(_artifact(tmp_path))

    matched, ambiguous = found.decisions[7], found.decisions[8]
    assert (matched.state, matched.rule, matched.relationship) == (
        "matched",
        "curb_cut_kerb_and_carrier",
        "many_to_one",
    )
    assert [(t.element, t.role, t.from_m, t.to_m) for t in matched.targets] == [
        ("node/5", "kerb", None, None),
        ("way/9", "carrier", 1.5, 3.0),
    ]
    assert matched.signals == {"coverage": 1.0}
    assert (ambiguous.state, ambiguous.targets) == ("ambiguous", ())
    manifest = (tmp_path / "manifest.json").read_bytes()
    assert found.manifest_sha256 == hashlib.sha256(manifest).hexdigest()


def test_a_decisions_file_changed_after_its_manifest_is_refused(tmp_path: Path) -> None:
    folder = _artifact(tmp_path)
    (folder / "matches.parquet").write_bytes((folder / "matches.parquet").read_bytes() + b"\0")

    with pytest.raises(ReconciliationError, match="does not match"):
        load_geo05_artifact(folder)


@pytest.mark.parametrize(
    ("manifest_version", "row_version"),
    [("kitchener-geo05-matcher-v2", MATCHER), (MATCHER, "kitchener-geo05-matcher-v2")],
)
def test_another_matchers_decisions_are_refused(
    tmp_path: Path, manifest_version: str, row_version: str
) -> None:
    # Matcher v2 needs its own benchmark before anything reconciles on it.
    folder = _artifact(tmp_path, version=manifest_version, row_version=row_version)

    with pytest.raises(ReconciliationError, match="v1"):
        load_geo05_artifact(folder)


def test_city_dates_are_read_in_utc_and_curb_cuts_only_from_physical_records(
    tmp_path: Path,
) -> None:
    # Regression: DuckDB formats a timestamp in the machine's time zone unless
    # told otherwise. On this laptop (America/Toronto) that moved the City's
    # midnight-UTC SOURCE_DATE to the previous day and labelled local times "Z".
    parquet = tmp_path / "normalized.parquet"
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("SET TimeZone = 'UTC'")
        connection.execute(
            """
            CREATE TABLE t AS SELECT * FROM (VALUES
                (1, TIMESTAMPTZ '2014-06-30 04:00:00+00', TIMESTAMPTZ '2026-08-24 11:55:00+00',
                 TIMESTAMPTZ '2012-05-01 00:00:00+00', 'non_default', 'Y', 'non_default',
                 'physical_active'),
                (2, NULL, NULL, NULL, 'template_default', 'Y', 'non_default', 'virtual_link'),
                (3, NULL, NULL, NULL, 'template_default', 'N', 'template_default',
                 'physical_active')
            ) AS v(activetransportid, create_date, update_date, source_date, state_feature_type,
                   curbcut, state_curbcut, physical_class)
            """
        )
        connection.execute(f"COPY t TO '{parquet.as_posix()}' (FORMAT parquet)")
    finally:
        connection.close()

    fields, curb_cuts = city_record_fields(parquet)

    assert fields[1].created_at == "2014-06-30T04:00:00Z"
    assert fields[1].modified_at == "2026-08-24T11:55:00Z"
    assert fields[1].state_feature_type == "non_default"
    assert fields[1].source_date == "2012-05-01"
    assert fields[2].created_at is None
    # A virtual link is topology, not a curb cut; CURBCUT = N is never one.
    assert curb_cuts == {1}


def test_every_kitchener_query_that_formats_a_date_formats_it_in_utc() -> None:
    # The same regression, for every module: a strftime on a date column in SQL
    # needs the session in UTC, or its output depends on where it runs.
    kitchener = Path(conflation.__file__).parent
    unset = sorted(
        path.name
        for path in kitchener.glob("*.py")
        if re.search(r"strftime\([a-z_]+_date,", path.read_text("utf-8"))
        and "SET TimeZone = 'UTC'" not in path.read_text("utf-8")
    )

    assert unset == []
