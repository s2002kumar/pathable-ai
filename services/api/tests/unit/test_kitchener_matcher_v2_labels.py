"""PA-GEO-08's labels: definitions version 2, the development set, and the blind material."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pathable_api import cli
from pathable_api.geo.kitchener.benchmark_labels import OBVIOUS, LabelError
from pathable_api.geo.kitchener.matcher_v2_labels import (
    LABELS_KEY,
    LABELS_VERSION,
    development_labels,
    parse_label,
    parse_labels,
)
from pathable_api.geo.kitchener.matcher_v2_review import connections

EXIT_OK = 0
EXIT_FAILED = 1


def _label(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "activetransportid": 1,
        "correspondence": "obvious_correspondence",
        "osm": ["way/10"],
        "representation": "separate_way",
        "relationship": "one_to_one",
        "note": "",
    }
    item.update(overrides)
    return item


def test_a_generic_way_is_a_way_only_representation() -> None:
    assert parse_label(_label(representation="generic_way")).representation == "generic_way"
    with pytest.raises(LabelError, match="does not describe"):
        parse_label(_label(osm=["node/5"], representation="generic_way"))
    with pytest.raises(LabelError, match="does not describe"):
        parse_label(_label(osm=["way/10", "node/5"], representation="generic_way"))


def test_a_label_file_of_another_version_is_refused() -> None:
    with pytest.raises(LabelError, match="PA-GEO-08"):
        parse_labels({"kitchener_geo05_labels_version": 1, "records": [_label()]})
    assert parse_labels({LABELS_KEY: LABELS_VERSION, "records": [_label()]})[1].truth == {"way/10"}


def test_a_stair_on_a_plain_footway_becomes_a_correspondence_and_nothing_else_changes() -> None:
    stair = _label(
        activetransportid=13622,
        correspondence="ambiguous_correspondence",
        osm=["way/146313339"],
        relationship=None,
    )
    sidewalk = _label(activetransportid=2)
    document = development_labels(
        {"records": [sidewalk]},
        {"records": [stair]},
        structures={13622: "STAIRS"},
        structure_tagged={"13622:way/146313339": False},
        other_records_along={"way/146313339": frozenset({13622, 389863})},
    )

    labels = {r["activetransportid"]: r for r in document["records"]}
    assert labels[13622]["correspondence"] == OBVIOUS
    assert labels[13622]["representation"] == "generic_way"
    # The footway also carries the City's other stair record: OSM merges them.
    assert labels[13622]["relationship"] == "many_to_one"
    assert labels[2] == {**sidewalk, "source": labels[2]["source"]}
    assert [c["activetransportid"] for c in document["conversions"]] == [13622]


def test_a_structure_on_a_tagged_way_keeps_its_representation() -> None:
    bridge = _label(activetransportid=5, osm=["way/7", "way/8"], relationship="one_to_many")
    document = development_labels(
        {"records": []},
        {"records": [bridge]},
        structures={5: "BRIDGE"},
        structure_tagged={"5:way/7": True, "5:way/8": False},
        other_records_along={},
    )

    assert document["records"][0]["representation"] == "separate_way"
    assert document["conversions"] == []


def test_the_digest_says_which_candidates_meet_and_where() -> None:
    ways = {
        1: SimpleNamespace(refs=[100, 101, 102]),
        2: SimpleNamespace(refs=[102, 103]),
        3: SimpleNamespace(refs=[200, 101, 201]),
        4: SimpleNamespace(refs=[300, 301]),
    }
    osm: Any = SimpleNamespace(extract=SimpleNamespace(ways=ways))

    found = connections([(1, 1), (2, 2), (3, 3), (4, 4)], osm)

    assert found[1] == [
        "C2 (at this way's end, that way's end)",
        "C3 (at this way's mid-way, that way's mid-way)",
    ]
    assert found[4] == []


def _pack(tmp_path: Path, labels: list[dict[str, Any]]) -> list[str]:
    elements = tmp_path / "elements.json"
    elements.write_text(
        json.dumps(
            {"pack": "p", "records": [1, 2], "elements": {"1": ["way/10"], "2": ["way/20"]}}
        ),
        encoding="utf-8",
    )
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({LABELS_KEY: LABELS_VERSION, "records": labels}), encoding="utf-8")
    return [
        "kitchener",
        "matcher-v2-validate-labels",
        "--labels",
        str(path),
        "--pack-elements",
        str(elements),
    ]


def test_the_validator_refuses_an_element_the_pack_never_showed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = [_label(), _label(activetransportid=2, osm=["way/20"])]
    assert cli.main(_pack(tmp_path, good)) == EXIT_OK

    stray = [_label(), _label(activetransportid=2, osm=["way/99"])]
    assert cli.main(_pack(tmp_path, stray)) == EXIT_FAILED
    assert "way/99" in capsys.readouterr().err

    reordered = [_label(activetransportid=2, osm=["way/20"]), _label()]
    assert cli.main(_pack(tmp_path, reordered)) == EXIT_FAILED
