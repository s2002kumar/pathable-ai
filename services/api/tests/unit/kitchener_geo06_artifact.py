"""A miniature PA-GEO-06 artifact, for tests of what reads one.

One surface row of every relationship and one curb-ramp row, with the
manifest and the committed evidence that describe them, hashes and all.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from pathable_api.geo.overture.evidence import file_sha256

RECONCILIATIONS = """CREATE TABLE r AS SELECT * FROM (VALUES
('s1', 'surface', 'source_only_kitchener', [1::BIGINT], 'way/{eligible_way}', 0.0, 1000000.0,
 ['kitchener/1#surface_material'], []::VARCHAR[], 'not_applicable'),
('s2', 'surface', 'conflict', [2::BIGINT], 'way/{conflict_way}', 0.0, 1000000.0,
 ['kitchener/2#surface_material'], ['way/{conflict_way}@v3#surface'], 'apparently_independent'),
('s3', 'surface', 'agreement', [3::BIGINT], 'way/102', 0.0, 20.0,
 ['kitchener/3#surface_material'], ['way/102@v1#surface'], 'possible_shared_lineage'),
('s4', 'surface', 'source_only_osm', [4::BIGINT], 'way/103', 0.0, 20.0,
 []::VARCHAR[], ['way/103@v1#surface'], 'not_applicable'),
('s5', 'surface', 'unknown', [5::BIGINT], 'way/104', 0.0, 20.0,
 []::VARCHAR[], []::VARCHAR[], 'not_applicable'),
('c1', 'curb_ramp', 'source_only_kitchener', [6::BIGINT], 'node/9', NULL, NULL,
 ['kitchener/6#curb_ramp'], ['node/9@v1#barrier'], 'not_applicable')
) AS v(reconciliation_id, topic, semantic_relationship, source_records, target_element,
       from_m, to_m, kitchener_assertions, osm_assertions, lineage_relationship)"""

ASSERTIONS = """CREATE TABLE a AS SELECT * FROM (VALUES
('kitchener/1#surface_material', 'ASPHALT', 'asphalt', 'orthoimagery', '2012-05-01',
 2021::BIGINT, NULL, NULL),
('kitchener/2#surface_material', 'GRAVEL', 'gravel', 'orthoimagery', NULL, NULL, NULL, NULL),
('way/{conflict_way}@v3#surface', 'asphalt', 'asphalt', NULL, NULL, NULL, '2021-03-25',
 '2021-03-25T00:00:00Z')
) AS v(assertion_id, raw_value, normalized_value, capture_source, source_capture_date,
       inspection_year, observation_date, osm_value_since)"""


def write_geo06_artifact(
    folder: Path,
    *,
    evidence_name: str = "evidence.json",
    eligible_way: int = 100,
    conflict_way: int = 101,
    eligible_count: int = 1,
) -> tuple[Path, Path]:
    """The artifact folder and the committed evidence file that describes it."""
    folder.mkdir(parents=True, exist_ok=True)
    ways = {"eligible_way": eligible_way, "conflict_way": conflict_way}
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(RECONCILIATIONS.format(**ways))
        connection.execute(ASSERTIONS.format(**ways))
        for table, name in (("r", "reconciliations"), ("a", "assertions")):
            connection.execute(f"COPY {table} TO '{(folder / name).as_posix()}.parquet'")
    finally:
        connection.close()
    files = {
        name: {"file": f"{name}.parquet", "sha256": file_sha256(folder / f"{name}.parquet")}
        for name in ("reconciliations", "assertions")
    }
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                "artifact_version": "kitchener-geo06-artifact-v1",
                "versions": {"reconciliation_policy": "kitchener-geo06-reconciliation-v1"},
                "files": files,
                "content_sha256": "c" * 64,
            }
        ),
        encoding="utf-8",
    )
    committed = folder / evidence_name
    committed.write_text(
        json.dumps(
            {
                "artifact": {"files": files},
                "outcomes": {
                    "surface": {"semantic_relationship": {"source_only_kitchener": eligible_count}}
                },
                "content_sha256": "e" * 64,
            }
        ),
        encoding="utf-8",
    )
    return folder, committed
