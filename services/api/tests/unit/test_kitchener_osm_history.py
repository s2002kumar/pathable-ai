"""Reading OSM history: ohsome contributions, the request cache, and the changeset dump.

No network: ohsome is a fake transport, and the changeset dump is a small
multi-stream bzip2 file built here the way the planet dump is built — each
stream compressed on its own, the XML split wherever a stream happens to end.
"""

from __future__ import annotations

import bz2
import itertools
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pathable_api.geo.kitchener.arcgis import HttpResponse, TransportError
from pathable_api.geo.kitchener.osm_history import (
    ChangesetDump,
    HistoryError,
    OhsomeRequest,
    dump_header,
    fetch_history,
    fragment_of,
    iter_elements,
    ohsome_metadata,
    ohsome_requests,
    parse_changeset,
    parse_contributions,
    stream_offsets,
)

CONTRIBUTIONS = {
    "type": "FeatureCollection",
    "apiVersion": "1.10.4",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[-80.5, 43.4], [-80.49, 43.41]]},
            "properties": {
                "@osmId": "way/7",
                "@changesetId": 100,
                "@contributionChangesetId": 100,
                "@creation": True,
                "@timestamp": "2012-05-01T10:00:00Z",
                "@version": 1,
                "highway": "footway",
                "source": "Bing",
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[-80.5, 43.4], [-80.48, 43.41]]},
            "properties": {
                "@osmId": "way/7",
                "@changesetId": 100,
                "@contributionChangesetId": 250,
                "@geometryChange": True,
                "@timestamp": "2019-03-02T08:00:00Z",
                "@version": 1,
                "highway": "footway",
                "source": "Bing",
            },
        },
    ],
}


class TestContributions:
    def test_a_node_move_is_credited_to_the_changeset_that_moved_it(self) -> None:
        created, moved = parse_contributions(CONTRIBUTIONS)

        assert created.creation
        assert not created.geometry_change
        assert moved.geometry_change
        assert not moved.creation
        assert moved.version == 1  # the way itself did not change version
        assert moved.changeset == 250  # but this changeset reshaped it
        assert created.tags == {"highway": "footway", "source": "Bing"}
        assert moved.coordinates == ((-80.5, 43.4), (-80.48, 43.41))

    def test_anything_but_a_feature_collection_is_refused(self) -> None:
        with pytest.raises(HistoryError, match="FeatureCollection"):
            parse_contributions({"type": "Feature"})

    def test_contributions_group_by_element_in_time_order(self) -> None:
        items = list(iter_elements(reversed(parse_contributions(CONTRIBUTIONS))))

        assert [element for element, _ in items] == ["way/7"]
        assert [c.changeset for c in items[0][1]] == [100, 250]


class TestRequests:
    def test_batches_are_per_type_in_a_fixed_order(self) -> None:
        requests = ohsome_requests(
            ["way/3", "node/9", "way/1", "way/2", "way/1"],
            bbox=(-80.6, 43.4, -80.4, 43.5),
            time_range=("2007-10-08T00:00:00Z", "2026-07-27T09:00Z"),
            batch=2,
        )

        assert [r.params["filter"] for r in requests] == [
            "id:(node/9)",
            "id:(way/1, way/2)",
            "id:(way/3)",
        ]
        assert requests[0].params["properties"] == "tags,metadata,contributionTypes"

    def test_the_same_request_always_has_the_same_key(self) -> None:
        first = OhsomeRequest("contributions/geometry", {"filter": "id:(way/1)", "time": "a,b"})
        second = OhsomeRequest("contributions/geometry", {"time": "a,b", "filter": "id:(way/1)"})

        assert first.key == second.key

    def test_an_id_that_is_not_an_osm_element_is_refused(self) -> None:
        with pytest.raises(HistoryError, match="not an OSM node or way"):
            ohsome_requests(["relation/5"], bbox=(0, 0, 1, 1), time_range=("a", "b"))


class _Ohsome:
    def __init__(self, answers: list[HttpResponse | Exception]) -> None:
        self.answers = answers
        self.posts: list[Mapping[str, str]] = []

    def get(self, url: str, params: Mapping[str, str]) -> HttpResponse:
        body = {
            "apiVersion": "1.10.4",
            "attribution": {"text": "© OpenStreetMap contributors"},
            "extractRegion": {
                "temporalExtent": {
                    "fromTimestamp": "2007-10-08T00:00:00Z",
                    "toTimestamp": "2026-07-27T09:00Z",
                },
                "replicationSequenceNumber": 121586,
            },
        }
        return HttpResponse(200, json.dumps(body).encode(), {})

    def post(self, url: str, data: Mapping[str, str]) -> HttpResponse:
        self.posts.append(data)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _ok() -> HttpResponse:
    return HttpResponse(200, json.dumps(CONTRIBUTIONS).encode(), {})


REQUEST = OhsomeRequest("contributions/geometry", {"filter": "id:(way/7)", "time": "a,b"})


class TestFetch:
    def test_an_answer_is_cached_and_reused(self, tmp_path: Path) -> None:
        server = _Ohsome([_ok()])

        first = fetch_history(
            [REQUEST], transport=server, cache_dir=tmp_path, sleep=lambda _s: None
        )
        second = fetch_history(
            [REQUEST], transport=server, cache_dir=tmp_path, sleep=lambda _s: None
        )

        assert len(server.posts) == 1
        assert len(first.contributions) == len(second.contributions) == 2
        assert first.requests == second.requests
        assert first.api_version == "1.10.4"

    def test_a_changed_cache_file_is_refused(self, tmp_path: Path) -> None:
        fetch_history([REQUEST], transport=_Ohsome([_ok()]), cache_dir=tmp_path)
        (tmp_path / f"{REQUEST.key}.json").write_text('{"type": "FeatureCollection"}', "utf-8")

        with pytest.raises(HistoryError, match="does not match its recorded hash"):
            fetch_history([REQUEST], transport=_Ohsome([]), cache_dir=tmp_path)

    def test_a_busy_service_is_retried_and_a_refusal_is_not(self, tmp_path: Path) -> None:
        busy = _Ohsome([TransportError("reset"), HttpResponse(503, b"busy", {}), _ok()])
        fetched = fetch_history(
            [REQUEST], transport=busy, cache_dir=tmp_path, sleep=lambda _s: None
        )
        assert len(fetched.contributions) == 2

        refused = _Ohsome([HttpResponse(400, b"bad filter", {})])
        with pytest.raises(HistoryError, match="HTTP 400"):
            fetch_history(
                [REQUEST], transport=refused, cache_dir=tmp_path / "b", sleep=lambda _s: None
            )
        assert len(refused.posts) == 1

    def test_metadata_names_the_extent_the_history_reaches(self) -> None:
        metadata = ohsome_metadata(_Ohsome([]))

        assert metadata["temporal_extent"] == {
            "from": "2007-10-08T00:00:00Z",
            "to": "2026-07-27T09:00Z",
        }
        assert metadata["api_version"] == "1.10.4"


def _changeset(changeset_id: int, comment: str, **tags: str) -> str:
    children = "".join(
        f'  <tag k="{k}" v="{v}"/>\n' for k, v in {"comment": comment, **tags}.items()
    )
    return (
        f' <changeset id="{changeset_id}" created_at="2020-01-0{changeset_id % 9 + 1}T00:00:00Z" '
        f'closed_at="2020-01-02T00:00:00Z" open="false" user="Someone" uid="42" '
        f'min_lat="43.4" min_lon="-80.5" max_lat="43.5" max_lon="-80.4" num_changes="3" '
        f'comments_count="0">\n{children} </changeset>\n'
    )


def _dump(path: Path) -> Path:
    """A planet-style changeset dump in several independent bzip2 streams."""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<osm version="0.6" generator="fixture" timestamp="2026-09-21T00:00:03Z">\n'
        + _changeset(11, "first")
        + _changeset(12, "Café mapping on the Iron Horse Trail", source="survey")
        + _changeset(13, "third", imagery_used="Esri World Imagery", changesets_count="99")
        + ' <changeset id="14" created_at="2020-01-05T00:00:00Z" open="false" num_changes="0"/>\n'
        + "</osm>\n"
    ).encode("utf-8")
    # Cut the streams where the planet dump would: anywhere. One cut lands in
    # the middle of the two-byte "é", one inside changeset 13's opening tag.
    cafe = xml.index("Café".encode()) + 3
    inside_13 = xml.index(b'<changeset id="13"') + 8
    cuts = [0, cafe, inside_13, len(xml)]
    path.write_bytes(b"".join(bz2.compress(xml[a:b]) for a, b in itertools.pairwise(cuts)))
    return path


class TestChangesetDump:
    def test_every_stream_is_found(self, tmp_path: Path) -> None:
        assert len(stream_offsets(_dump(tmp_path / "c.osm.bz2"), chunk=64)) == 3

    def test_changesets_are_found_across_stream_boundaries(self, tmp_path: Path) -> None:
        # Regressions, both found building this study: decoding one stream at a
        # time failed on a character a stream boundary split in two; and a
        # stream in which no element starts (here the second, which begins
        # inside 12 and ends inside 13's opening tag) was given the previous
        # stream's first id, so the lookup for 11 and 12 began one stream late.
        path = _dump(tmp_path / "c.osm.bz2")
        dump = ChangesetDump.open(path, tmp_path / "c.streams.json", workers=2)

        found = dump.lookup([12, 13, 14, 11, 99])

        assert sorted(found) == [11, 12, 13, 14]
        assert found[12].tags == {
            "comment": "Café mapping on the Iron Horse Trail",
            "source": "survey",
        }
        assert found[13].tags["imagery_used"] == "Esri World Imagery"
        assert found[14].tags == {}
        assert found[12].bbox == (-80.5, 43.4, -80.4, 43.5)

    def test_contributors_and_unlisted_tags_are_never_kept(self, tmp_path: Path) -> None:
        path = _dump(tmp_path / "c.osm.bz2")
        dump = ChangesetDump.open(path, tmp_path / "c.streams.json", workers=2)

        record = dump.lookup([13])[13].as_dict()

        assert "changesets_count" not in record["tags"]
        assert "Someone" not in json.dumps(record)
        assert "uid" not in record
        assert "user" not in record

    def test_an_index_for_another_file_is_refused(self, tmp_path: Path) -> None:
        path = _dump(tmp_path / "c.osm.bz2")
        ChangesetDump.open(path, tmp_path / "c.streams.json")
        path.write_bytes(path.read_bytes() + bz2.compress(b"<!-- more -->"))

        with pytest.raises(HistoryError, match="different"):
            ChangesetDump.open(path, tmp_path / "c.streams.json")

    def test_the_header_names_the_dump(self, tmp_path: Path) -> None:
        header = dump_header(_dump(tmp_path / "c.osm.bz2"))

        assert header["timestamp"] == "2026-09-21T00:00:03Z"

    def test_a_fragment_is_one_whole_element(self) -> None:
        data = _changeset(5, "a").encode() + _changeset(55, "b").encode()

        fragment = fragment_of(data, 5)

        assert fragment is not None
        assert parse_changeset(fragment).id == 5
        assert fragment_of(data, 6) is None


def test_parse_changeset_keeps_the_box_and_counts() -> None:
    parsed: Any = parse_changeset(_changeset(7, "x", source="Bing").strip())

    assert parsed.num_changes == 3
    assert parsed.created_at == "2020-01-08T00:00:00Z"
    assert parsed.tags == {"comment": "x", "source": "Bing"}
