"""Freezing the Kitchener source: complete, verified, and identical when the source is.

Every test runs the real client and snapshot code against the in-memory
service in ``tests/kitchener_fixture.py``. The failure modes are the ones a
feature service actually has: pages silently capped at ``maxRecordCount``, a
count that disagrees with the id list, a republish in the middle of a read,
and ArcGIS errors carried inside HTTP 200 responses.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from pathable_api.geo.kitchener.arcgis import (
    ArcGISClient,
    ArcGISError,
    HttpResponse,
    IncompatibleLayerError,
    IncompleteReadError,
    LayerChangedError,
    LayerRead,
    read_layer,
)
from pathable_api.geo.kitchener.snapshot import (
    SNAPSHOT_MANIFEST,
    SnapshotError,
    load_manifest,
    municipal_content_sha256,
    verified_features,
)
from pathable_api.geo.kitchener.source import (
    ACTIVE_TRANSPORTATION,
    COMPATIBLE_TYPES,
    NATIVE_WKID,
    licence_terms_found,
)
from pathable_api.geo.overture.evidence import file_sha256
from tests.kitchener_fixture import (
    AT_RECORDS,
    LICENCE_HTML,
    FakeArcGIS,
    FakeLayer,
    build_layers,
    error_response,
    snapshot,
)

AT_COUNT = len(AT_RECORDS)


def _read(
    layer: FakeLayer, *, chunk_size: int = 3, attempts: int = 3
) -> tuple[FakeArcGIS, LayerRead]:
    server = FakeArcGIS([layer])
    client = ArcGISClient(server, sleep=lambda _s: None)
    result = read_layer(
        client,
        ACTIVE_TRANSPORTATION.layer_url,
        contract=ACTIVE_TRANSPORTATION.contract,
        compatible=COMPATIBLE_TYPES,
        expected_geometry="esriGeometryPolyline",
        expected_wkid=NATIVE_WKID,
        chunk_size=chunk_size,
        attempts=attempts,
    )
    return server, result


def _feature_posts(server: FakeArcGIS) -> list[list[int]]:
    return [
        [int(i) for i in params["objectIds"].split(",")]
        for method, url, params in server.log
        if method == "POST" and url.endswith("/query")
    ]


class TestCompleteRead:
    def test_every_feature_is_read_by_id_in_bounded_chunks(self) -> None:
        at, _walk = build_layers()
        server, result = _read(at, chunk_size=3)

        posts = _feature_posts(server)
        assert [len(chunk) for chunk in posts] == [3, 3, 3, 1]
        assert sorted(i for chunk in posts for i in chunk) == list(range(1, AT_COUNT + 1))
        assert sorted(f["attributes"]["OBJECTID"] for f in result.features) == list(
            range(1, AT_COUNT + 1)
        )

    def test_the_chunk_never_exceeds_the_servers_own_limit(self) -> None:
        at, _walk = build_layers(max_record_count=2)
        server, _result = _read(at, chunk_size=1000)

        assert max(len(chunk) for chunk in _feature_posts(server)) == 2

    def test_a_page_capped_by_the_server_is_refused_not_trusted(self) -> None:
        at, _walk = build_layers(truncate_pages_to=2)

        with pytest.raises(IncompleteReadError, match="exceededTransferLimit"):
            _read(at, chunk_size=3)

    def test_a_count_that_disagrees_with_the_id_list_is_refused(self) -> None:
        at, _walk = build_layers(count_override=AT_COUNT + 1)

        with pytest.raises(IncompleteReadError, match="object ids"):
            _read(at)

    def test_a_republish_during_the_read_starts_it_again(self) -> None:
        at, _walk = build_layers(republish_after_pages=2, republish_attempts=1)

        _server, result = _read(at, attempts=3)

        assert result.attempts == 2
        assert len(result.features) == AT_COUNT

    def test_a_layer_that_keeps_changing_is_refused(self) -> None:
        at, _walk = build_layers(republish_after_pages=2, republish_attempts=5)

        with pytest.raises(LayerChangedError, match="kept changing during 2"):
            _read(at, attempts=2)

    def test_features_deleted_after_the_id_list_mean_the_layer_changed(self) -> None:
        at, _walk = build_layers(deleted_after_listing={4})

        with pytest.raises(LayerChangedError):
            _read(at, attempts=1)


class TestRetries:
    def test_transient_http_and_arcgis_errors_are_retried(self) -> None:
        at, walk = build_layers()
        server = FakeArcGIS([at, walk])
        server.failures[("GET", ACTIVE_TRANSPORTATION.layer_url)] = [
            HttpResponse(503, b"busy", {}),
            error_response(504),
        ]
        client = ArcGISClient(server, sleep=lambda _s: None)

        document = client.get_json(ACTIVE_TRANSPORTATION.layer_url).document

        assert document["name"] == "Active Transportation"
        assert client.log.retries == 2

    def test_a_non_transient_arcgis_error_stops_immediately(self) -> None:
        at, walk = build_layers()
        server = FakeArcGIS([at, walk])
        server.failures[("GET", ACTIVE_TRANSPORTATION.layer_url)] = [error_response(400, "bad")]
        client = ArcGISClient(server, sleep=lambda _s: None)

        with pytest.raises(ArcGISError, match="ArcGIS error 400: bad"):
            client.get_json(ACTIVE_TRANSPORTATION.layer_url)
        assert client.log.retries == 0

    def test_retries_give_up_with_the_reason(self) -> None:
        at, walk = build_layers()
        server = FakeArcGIS([at, walk])
        server.failures[("GET", ACTIVE_TRANSPORTATION.layer_url)] = [
            HttpResponse(503, b"busy", {}) for _ in range(4)
        ]
        client = ArcGISClient(server, attempts=4, sleep=lambda _s: None)

        with pytest.raises(ArcGISError, match="HTTP 503 \\(gave up after 4 attempts\\)"):
            client.get_json(ACTIVE_TRANSPORTATION.layer_url)


class TestLayerContract:
    def test_a_missing_contract_field_is_refused(self) -> None:
        at, _walk = build_layers(drop_fields=("CURBCUT",))

        with pytest.raises(IncompatibleLayerError, match="missing field CURBCUT"):
            _read(at)

    def test_another_coordinate_system_is_refused(self) -> None:
        at, _walk = build_layers(wkid=4326)

        with pytest.raises(IncompatibleLayerError, match="expected wkid 26917"):
            _read(at)

    def test_fields_outside_the_contract_are_recorded_not_refused(self, tmp_path: Path) -> None:
        result = snapshot(tmp_path)

        contract = result.manifest["publications"]["active_transportation"]["layer"]["contract"]
        assert contract["compatible"]
        assert contract["additional_fields"] == ["CREATE_BY", "WAYFINDING"]


class TestSnapshot:
    def test_the_manifest_hashes_what_was_written(self, tmp_path: Path) -> None:
        result = snapshot(tmp_path)

        manifest = load_manifest(result.folder)
        for key in ("active_transportation", "walkability"):
            record = manifest["publications"][key]
            path = verified_features(result.folder, manifest, key)
            assert file_sha256(path) == record["features"]["sha256"]
            assert record["completeness"]["count"] == record["features"]["records"]
            for page in record["pages"]:
                assert file_sha256(result.folder / page["file"]) == page["sha256"]
        assert manifest["publications"]["active_transportation"]["features"]["records"] == AT_COUNT

    def test_an_identical_source_gives_an_identical_snapshot(self, tmp_path: Path) -> None:
        first = snapshot(tmp_path / "a")
        second = snapshot(tmp_path / "b")

        assert first.snapshot_id == second.snapshot_id
        for key in ("active_transportation", "walkability"):
            assert (
                first.manifest["publications"][key]["features"]
                == second.manifest["publications"][key]["features"]
            )

    def test_renumbered_object_ids_keep_the_municipal_hash(self, tmp_path: Path) -> None:
        # The City documents that OBJECTID changes on export and import; a
        # republish that only renumbers rows must not look like new content.
        first = snapshot(tmp_path / "a")
        renumbered = snapshot(tmp_path / "b", FakeArcGIS(build_layers(at_object_id_start=5001)))

        before = first.manifest["publications"]["active_transportation"]["features"]
        after = renumbered.manifest["publications"]["active_transportation"]["features"]
        assert before["sha256"] != after["sha256"]
        assert before["municipal_content_sha256"] == after["municipal_content_sha256"]

    def test_the_municipal_hash_changes_when_a_record_does(self) -> None:
        lines = [
            json.dumps(
                {
                    "attributes": {"OBJECTID": 1, "ACTIVETRANSPORTID": 7, "WIDTH_M": 1.5},
                    "geometry": None,
                }
            )
        ]
        edited = [
            json.dumps(
                {
                    "attributes": {"OBJECTID": 1, "ACTIVETRANSPORTID": 7, "WIDTH_M": 2.0},
                    "geometry": None,
                }
            )
        ]

        assert municipal_content_sha256(lines) != municipal_content_sha256(edited)

    def test_the_snapshot_is_read_only_and_tampering_is_detected(self, tmp_path: Path) -> None:
        result = snapshot(tmp_path)
        features = result.folder / "features" / "active_transportation.jsonl"
        assert not features.stat().st_mode & stat.S_IWRITE

        features.chmod(stat.S_IWRITE | stat.S_IREAD)
        features.write_text(features.read_text("utf-8").replace("CONCRETE", "ASPHALT"), "utf-8")
        with pytest.raises(SnapshotError, match="does not match its recorded SHA-256"):
            verified_features(result.folder, load_manifest(result.folder), "active_transportation")

    def test_an_edited_manifest_is_refused(self, tmp_path: Path) -> None:
        result = snapshot(tmp_path)
        path = result.folder / SNAPSHOT_MANIFEST
        path.chmod(stat.S_IWRITE | stat.S_IREAD)
        document = json.loads(path.read_text("utf-8"))
        document["publications"]["active_transportation"]["features"]["records"] = 1
        path.write_text(json.dumps(document), "utf-8")

        with pytest.raises(SnapshotError, match="edited since it was written"):
            load_manifest(result.folder)

    def test_a_failed_read_leaves_no_folder_behind(self, tmp_path: Path) -> None:
        server = FakeArcGIS(build_layers(truncate_pages_to=1))

        with pytest.raises(IncompleteReadError):
            snapshot(tmp_path, server)
        assert list(tmp_path.iterdir()) == []

    def test_documents_are_archived_with_their_hashes(self, tmp_path: Path) -> None:
        result = snapshot(tmp_path)

        documents = {doc["key"]: doc for doc in result.manifest["documents"]}
        assert documents["osm_kitchener_authorization_revision"]["revision"] == {
            "revid": 42,
            "timestamp": "2024-07-03T04:39:36Z",
        }
        assert documents["licence_page"]["states_version_1_0"] is True
        for document in documents.values():
            assert file_sha256(result.folder / document["file"]) == document["sha256"]


class TestLicence:
    def test_the_citys_licence_text_carries_every_recorded_term(self) -> None:
        assert all(licence_terms_found(LICENCE_HTML).values())

    def test_a_licence_without_a_recorded_term_is_flagged(self, tmp_path: Path) -> None:
        changed = LICENCE_HTML.replace(
            "including for commercial purposes", "for non-commercial use"
        )
        result = snapshot(tmp_path, FakeArcGIS(build_layers(), licence_html=changed))

        assert not result.licence_matches
        terms = {term["term"]: term["found"] for term in result.manifest["licence"]["terms"]}
        assert terms["commercial_use"] is False
        assert result.warnings
