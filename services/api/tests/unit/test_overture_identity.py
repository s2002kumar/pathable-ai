"""Source identities are parsed exactly, and anything off-shape is counted as malformed.

The cost of a lenient parser is a false match: ``w123`` read as "way 123, any
version" would turn an identifier Overture never wrote into evidence of the
same revision.
"""

from __future__ import annotations

import pytest

from pathable_api.geo.overture.identity import (
    LinearRange,
    MalformedRange,
    MalformedReason,
    MalformedRecordId,
    OsmElementRef,
    OsmElementType,
    parse_between,
    parse_osm_record_id,
    parse_pathable_osm_id,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("w1383497096@2", OsmElementRef(OsmElementType.WAY, 1383497096, 2)),
        ("n2757802019@9", OsmElementRef(OsmElementType.NODE, 2757802019, 9)),
        ("r19079213@2", OsmElementRef(OsmElementType.RELATION, 19079213, 2)),
    ],
)
def test_it_reads_the_documented_shape(raw: str, expected: OsmElementRef) -> None:
    parsed = parse_osm_record_id(raw)

    assert parsed == expected
    assert str(parsed) == raw


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (None, MalformedReason.MISSING),
        ("", MalformedReason.MISSING),
        # No version: an id alone must never pass for a specific revision.
        ("w123", MalformedReason.UNRECOGNISED_SHAPE),
        ("w123@", MalformedReason.UNRECOGNISED_SHAPE),
        ("w0123@1", MalformedReason.UNRECOGNISED_SHAPE),
        ("x123@1", MalformedReason.UNRECOGNISED_SHAPE),
        ("W123@1", MalformedReason.UNRECOGNISED_SHAPE),
        (" w123@1", MalformedReason.UNRECOGNISED_SHAPE),
        ("n11@x", MalformedReason.UNRECOGNISED_SHAPE),
        ("w-5@1", MalformedReason.UNRECOGNISED_SHAPE),
    ],
)
def test_it_refuses_anything_else(raw: str | None, reason: MalformedReason) -> None:
    assert parse_osm_record_id(raw) == MalformedRecordId(raw, reason)


def test_version_zero_keeps_the_id_but_never_counts_as_a_version() -> None:
    # OSM versions start at 1. Overture writes @0 on some connectors.
    assert parse_osm_record_id("n2558539625@0") == MalformedRecordId(
        "n2558539625@0", MalformedReason.VERSION_ZERO, OsmElementType.NODE, 2558539625
    )


def test_pathable_ids_that_are_not_osm_ids_are_not_read_as_one() -> None:
    # The synthetic fixture's ids must never coincide with a real OSM way.
    assert parse_pathable_osm_id("27046680") == 27046680
    assert parse_pathable_osm_id("synthetic-003") is None
    assert parse_pathable_osm_id(None) is None
    assert parse_pathable_osm_id("007") is None


def test_a_null_range_means_the_whole_feature_and_stays_distinct_from_zero_to_one() -> None:
    assert parse_between(None) is None
    assert parse_between([0.0, 1.0]) == LinearRange(0.0, 1.0)
    assert parse_between([0.215457829, 0.241181547]) == LinearRange(0.215457829, 0.241181547)


@pytest.mark.parametrize(
    "raw",
    [[0.7, 0.2], [0.5, 0.5], [-0.1, 0.5], [0.5, 1.2], [0.1], [0.0, 0.5, 1.0], [0.0, float("nan")]],
)
def test_a_range_that_is_not_a_proper_interval_is_malformed_not_clamped(raw: list[float]) -> None:
    assert isinstance(parse_between(raw), MalformedRange)
