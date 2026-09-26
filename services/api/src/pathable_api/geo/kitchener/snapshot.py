"""Freeze one complete snapshot of Kitchener's published inventory.

A snapshot is a folder that never changes after it is written:

- ``metadata/``: the item, service and layer descriptions, byte for byte;
- ``pages/``: every query response, byte for byte;
- ``features/<publication>.jsonl``: every feature as one canonical line, in
  ``OBJECTID`` order — the file later steps read, verified by its SHA-256;
- ``documents/``: the City's metadata reports, its licence page, and the
  OpenStreetMap wiki's record of the City's permission;
- ``snapshot-manifest.json``: what was read, from where, when, and the hash of
  everything above.

Two content hashes identify what was read. ``features_sha256`` covers the
features exactly as served. ``municipal_content_sha256`` sorts by the City's
permanent id and leaves ``OBJECTID`` out, because the City documents that
``OBJECTID`` values change on export and import: a republish that renumbers
object ids without changing a single record keeps the second hash.

Nothing here reads or writes the PathAble database.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import stat
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pathable_api.geo.kitchener.arcgis import (
    DEFAULT_CHUNK_SIZE,
    ArcGISClient,
    ArcGISError,
    LayerRead,
    canonical_feature,
    read_layer,
)
from pathable_api.geo.kitchener.source import (
    COMPATIBLE_TYPES,
    DOCUMENTS,
    IDENTITY_FIELD,
    LICENCE_NAME,
    LICENCE_TERMS,
    LICENCE_VERSION,
    NATIVE_WKID,
    OBJECT_ID_FIELD,
    PUBLICATIONS,
    PUBLISHER,
    Document,
    Publication,
    licence_plain_text,
    licence_terms_found,
)
from pathable_api.geo.overture.evidence import content_sha256, file_sha256, write_json

SNAPSHOT_MANIFEST = "snapshot-manifest.json"
SNAPSHOT_FORMAT_VERSION = 1
GEOMETRY_TYPE = "esriGeometryPolyline"

Progress = Callable[[str], None]


class SnapshotError(RuntimeError):
    """The snapshot could not be taken, or cannot be trusted."""


class LicenceChangedError(SnapshotError):
    """The licence served with the data no longer says what the audit relies on."""


@dataclass(frozen=True, slots=True)
class SnapshotPlan:
    publications: tuple[Publication, ...] = PUBLICATIONS
    documents: tuple[Document, ...] = DOCUMENTS
    chunk_size: int = DEFAULT_CHUNK_SIZE
    read_attempts: int = 3


@dataclass(slots=True)
class SnapshotResult:
    folder: Path
    manifest: dict[str, Any]
    licence_matches: bool
    warnings: list[str] = field(default_factory=list)

    @property
    def snapshot_id(self) -> str:
        return str(self.manifest["snapshot_id"])


def take_snapshot(
    client: ArcGISClient,
    out_root: Path,
    *,
    plan: SnapshotPlan | None = None,
    progress: Progress | None = None,
    measure: Callable[[], dict[str, Any]] | None = None,
    now: Callable[[], dt.datetime] | None = None,
) -> SnapshotResult:
    """Read every publication in full and write an immutable snapshot folder.

    The folder is written under a temporary name and renamed only when complete,
    so a failed run never leaves something that looks like a snapshot.
    """
    chosen = plan or SnapshotPlan()
    say = progress or (lambda _message: None)
    clock = now or (lambda: dt.datetime.now(tz=dt.UTC))
    started = time.perf_counter()
    retrieved_at = clock().astimezone(dt.UTC)

    out_root.mkdir(parents=True, exist_ok=True)
    staging = out_root / f".incomplete-{uuid.uuid4().hex[:12]}"
    staging.mkdir()
    try:
        publications: dict[str, Any] = {}
        licence_texts: dict[str, str] = {}
        warnings: list[str] = []
        for publication in chosen.publications:
            say(f"{publication.key}: reading item, service and layer descriptions...")
            record, licence_html = _capture_publication(client, publication, chosen, staging, say)
            publications[publication.key] = record
            licence_texts[publication.key] = licence_html

        licence = _licence_record(licence_texts)
        if not licence["matches_recorded_terms"]:
            warnings.append(
                "The licence served with the data does not contain every sentence the audit "
                "relies on; the snapshot is kept as evidence but must be reviewed."
            )

        say("documents: archiving metadata reports, licence page and OSM permission record...")
        documents = _capture_documents(client, chosen.documents, staging / "documents", warnings)

        feature_hashes = [
            f"{key}:{record['features']['sha256']}" for key, record in publications.items()
        ]
        snapshot_id = hashlib.sha256("\n".join(feature_hashes).encode("utf-8")).hexdigest()
        manifest: dict[str, Any] = {
            "kitchener_snapshot_version": SNAPSHOT_FORMAT_VERSION,
            "snapshot_id": snapshot_id,
            "publisher": PUBLISHER,
            "publications": publications,
            "licence": licence,
            "documents": documents,
            "acquisition": {
                "method": (
                    "count + every object id, then features by object id in fixed chunks; "
                    "layer edit info and count re-read afterwards and required unchanged"
                ),
                "chunk_size": chosen.chunk_size,
                "read_attempts_allowed": chosen.read_attempts,
                "native_crs": f"EPSG:{NATIVE_WKID}",
                "hub_download_not_used": (
                    "The Hub's cached downloads are regenerated on the portal's schedule and "
                    "cannot be verified feature by feature; the service itself can."
                ),
            },
            "warnings": sorted(warnings),
            "retrieved_at": retrieved_at.isoformat(timespec="seconds"),
            "run": {
                "seconds": round(time.perf_counter() - started, 2),
                "requests": client.log.as_dict(),
                **(measure() if measure is not None else {}),
            },
        }
        manifest["content_sha256"] = content_sha256(manifest)
        write_json(staging / SNAPSHOT_MANIFEST, manifest)

        folder = out_root / f"{retrieved_at.strftime('%Y%m%dT%H%M%SZ')}-{snapshot_id[:12]}"
        if folder.exists():
            msg = f"{folder} already exists; a snapshot folder is never overwritten."
            raise SnapshotError(msg)
        staging.rename(folder)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    _make_read_only(folder)
    return SnapshotResult(
        folder=folder,
        manifest=manifest,
        licence_matches=bool(licence["matches_recorded_terms"]),
        warnings=sorted(warnings),
    )


def _capture_publication(
    client: ArcGISClient,
    publication: Publication,
    plan: SnapshotPlan,
    staging: Path,
    say: Progress,
) -> tuple[dict[str, Any], str]:
    item = client.get_json(publication.item_url)
    service = client.get_json(publication.service_url)
    _check_item(publication, item.document)

    read = read_layer(
        client,
        publication.layer_url,
        contract=publication.contract,
        compatible=COMPATIBLE_TYPES,
        expected_geometry=GEOMETRY_TYPE,
        expected_wkid=NATIVE_WKID,
        chunk_size=plan.chunk_size,
        attempts=plan.read_attempts,
    )
    say(
        f"{publication.key}: {len(read.features)} features in {len(read.pages)} requests "
        f"({read.seconds:.1f}s)."
    )

    metadata = staging / "metadata"
    metadata.mkdir(exist_ok=True)
    _write_bytes(metadata / f"{publication.key}.item.json", item.body)
    _write_bytes(metadata / f"{publication.key}.service.json", service.body)
    _write_bytes(metadata / f"{publication.key}.layer.json", read.layer_body)

    pages_dir = staging / "pages" / publication.key
    pages_dir.mkdir(parents=True)
    pages = []
    for page in read.pages:
        name = f"{page.index:04d}.json"
        _write_bytes(pages_dir / name, page.body)
        pages.append(
            {
                "file": f"pages/{publication.key}/{name}",
                "bytes": len(page.body),
                "sha256": page.sha256,
                "records": len(page.object_ids),
                "first_object_id": page.object_ids[0],
                "last_object_id": page.object_ids[-1],
            }
        )

    features_path = staging / "features" / f"{publication.key}.jsonl"
    features_path.parent.mkdir(exist_ok=True)
    lines = [canonical_feature(feature) for feature in _by_object_id(read.features)]
    features_path.write_text("".join(line + "\n" for line in lines), encoding="utf-8", newline="\n")

    record = {
        "role": publication.role,
        "item": _item_record(item.document),
        "service": _service_record(service.document),
        "layer": _layer_record(publication, read),
        "query": {
            "url": f"{publication.layer_url}/query",
            "fixed_parameters": read.parameters,
            "object_ids_per_request": min(plan.chunk_size, int(read.layer["maxRecordCount"])),
        },
        "completeness": {
            "count": read.count,
            "object_ids": len(read.object_ids),
            "features": len(read.features),
            "pages": len(read.pages),
            "edit_info_unchanged_during_read": read.editing_before == read.editing_after,
            "attempts": read.attempts,
        },
        "features": {
            "file": f"features/{publication.key}.jsonl",
            "records": len(lines),
            "bytes": features_path.stat().st_size,
            "sha256": file_sha256(features_path),
            "municipal_content_sha256": municipal_content_sha256(lines),
        },
        "pages": pages,
        "measurement": {"seconds": round(read.seconds, 2)},
    }
    return record, str(item.document.get("licenseInfo") or "")


def municipal_content_sha256(lines: Sequence[str]) -> str:
    """The content independent of the service's own row numbering.

    Records are ordered by the City's permanent id, and ``OBJECTID`` is dropped.
    Records without a permanent id sort after the others by their own text, so
    the hash stays deterministic even for a malformed publication.
    """
    keyed: list[tuple[int, int, str]] = []
    for line in lines:
        feature = json.loads(line)
        attributes = dict(feature.get("attributes") or {})
        attributes.pop(OBJECT_ID_FIELD, None)
        identity = attributes.get(IDENTITY_FIELD)
        text = json.dumps(
            {"attributes": attributes, "geometry": feature.get("geometry")},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        if isinstance(identity, int):
            keyed.append((0, identity, text))
        else:
            keyed.append((1, 0, text))
    digest = hashlib.sha256()
    for _missing, _identity, text in sorted(keyed):
        digest.update(text.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _by_object_id(features: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(features, key=lambda feature: int(feature["attributes"][OBJECT_ID_FIELD]))


def _check_item(publication: Publication, item: Mapping[str, Any]) -> None:
    problems = []
    if item.get("id") != publication.item_id:
        problems.append(f"item id is {item.get('id')!r}")
    if item.get("type") != "Feature Service":
        problems.append(f"item type is {item.get('type')!r}")
    if str(item.get("url") or "").rstrip("/") != publication.service_url:
        problems.append(f"item url is {item.get('url')!r}, expected {publication.service_url}")
    if problems:
        msg = f"{publication.key}: the portal item is not the frozen source: " + "; ".join(problems)
        raise ArcGISError(msg)


def _item_record(item: Mapping[str, Any]) -> dict[str, Any]:
    licence = str(item.get("licenseInfo") or "")
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "type": item.get("type"),
        "owner": item.get("owner"),
        "org_id": item.get("orgId"),
        "url": item.get("url"),
        "access_information": item.get("accessInformation"),
        "snippet": item.get("snippet"),
        "content_status": item.get("contentStatus"),
        "created": _iso_ms(item.get("created")),
        "modified": _iso_ms(item.get("modified")),
        "extent_wgs84": item.get("extent"),
        "licence_info_sha256": hashlib.sha256(licence.encode("utf-8")).hexdigest(),
        "measurement": {"num_views": item.get("numViews"), "size_bytes": item.get("size")},
    }


def _service_record(service: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "service_item_id": service.get("serviceItemId"),
        "description": service.get("serviceDescription"),
        "copyright_text": service.get("copyrightText"),
        "capabilities": service.get("capabilities"),
        "max_record_count": service.get("maxRecordCount"),
        "supported_export_formats": service.get("supportedExportFormats"),
        "spatial_reference": service.get("spatialReference"),
        "current_version": service.get("currentVersion"),
        "layers": [
            {"id": layer.get("id"), "name": layer.get("name")}
            for layer in service.get("layers") or []
        ],
    }


def _layer_record(publication: Publication, read: LayerRead) -> dict[str, Any]:
    layer = read.layer
    return {
        "url": publication.layer_url,
        "id": layer.get("id"),
        "name": layer.get("name"),
        "geometry_type": layer.get("geometryType"),
        "spatial_reference": (layer.get("extent") or {}).get("spatialReference"),
        "extent_native": {
            k: (layer.get("extent") or {}).get(k) for k in ("xmin", "ymin", "xmax", "ymax")
        },
        "object_id_field": layer.get("objectIdField"),
        "global_id_field": layer.get("globalIdField") or None,
        "type_id_field": layer.get("typeIdField"),
        "max_record_count": layer.get("maxRecordCount"),
        "max_ids_count": layer.get("maxIdsCount"),
        "date_fields_time_reference": layer.get("dateFieldsTimeReference"),
        "edit_info": {key: _iso_ms(value) for key, value in read.editing_before.items()},
        "fields": [
            {
                "name": item.get("name"),
                "type": item.get("type"),
                "alias": item.get("alias"),
                "nullable": item.get("nullable"),
                "default_value": item.get("defaultValue"),
                "domain": (item.get("domain") or {}).get("name"),
            }
            for item in layer.get("fields") or []
        ],
        "contract": read.fields.as_dict(),
        "template_prototypes": [
            {
                "type": entry.get("id"),
                "template": template.get("name"),
                "attributes": (template.get("prototype") or {}).get("attributes"),
            }
            for entry in layer.get("types") or []
            for template in entry.get("templates") or []
        ],
    }


def _licence_record(licence_texts: Mapping[str, str]) -> dict[str, Any]:
    distinct = sorted(set(licence_texts.values()))
    if not distinct or not distinct[0]:
        msg = "The portal item carries no licence text."
        raise LicenceChangedError(msg)
    found: dict[str, bool] = {}
    for text in distinct:
        for term, present in licence_terms_found(text).items():
            found[term] = found.get(term, True) and present
    reference = distinct[0]
    return {
        "name": LICENCE_NAME,
        "version_recorded": LICENCE_VERSION,
        "text_of_record": "portal item licenseInfo, served with the data",
        "identical_across_publications": len(distinct) == 1,
        "licence_info_sha256": hashlib.sha256(reference.encode("utf-8")).hexdigest(),
        "plain_text_sha256": hashlib.sha256(
            licence_plain_text(reference).encode("utf-8")
        ).hexdigest(),
        "terms": [
            {
                "term": term.term,
                "reading": term.reading,
                "phrase": term.phrase,
                "found": found.get(term.term, False),
            }
            for term in LICENCE_TERMS
        ],
        "matches_recorded_terms": all(found.get(term.term, False) for term in LICENCE_TERMS),
        "not_legal_advice": True,
    }


def _capture_documents(
    client: ArcGISClient,
    documents: Sequence[Document],
    folder: Path,
    warnings: list[str],
) -> list[dict[str, Any]]:
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    for document in documents:
        response = client.get_bytes(document.url)
        headers = {key.lower(): value for key, value in response.headers.items()}
        record: dict[str, Any] = {
            "key": document.key,
            "url": document.url,
            "why": document.why,
            "http_status": response.status,
            "content_type": headers.get("content-type"),
            "last_modified": headers.get("last-modified"),
            "etag": headers.get("etag"),
        }
        if response.status != 200:
            warnings.append(f"document {document.key} returned HTTP {response.status}")
        else:
            name = f"{document.key}{_extension(headers.get('content-type'))}"
            _write_bytes(folder / name, response.body)
            record.update(
                {
                    "file": f"documents/{name}",
                    "bytes": len(response.body),
                    "sha256": hashlib.sha256(response.body).hexdigest(),
                }
            )
            record.update(_document_facts(document, response.body))
        records.append(record)
    return records


def _document_facts(document: Document, body: bytes) -> dict[str, Any]:
    """The few facts worth reading out of a document, recorded next to its hash."""
    if document.key == "osm_kitchener_authorization_revision":
        try:
            pages = json.loads(body)["query"]["pages"]
            revision = next(iter(pages.values()))["revisions"][0]
        except (KeyError, StopIteration, TypeError, ValueError, IndexError):
            return {"revision": None}
        return {
            "revision": {"revid": revision.get("revid"), "timestamp": revision.get("timestamp")}
        }
    if document.key == "licence_page":
        text = licence_plain_text(body.decode("utf-8", errors="replace"))
        return {
            "states_version_1_0": (
                "This is version 1.0 of the Open Government Licence - The Corporation of the "
                "City of Kitchener"
            ).casefold()
            in text.casefold()
        }
    return {}


def _extension(content_type: str | None) -> str:
    kind = (content_type or "").split(";")[0].strip().lower()
    return {
        "application/pdf": ".pdf",
        "application/json": ".json",
        "text/html": ".html",
        "text/x-wiki": ".wiki",
    }.get(kind, ".bin")


def _write_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def _make_read_only(folder: Path) -> None:
    """Belt and braces: later steps verify hashes, but nothing should try to edit."""
    for path in folder.rglob("*"):
        if path.is_file():
            path.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


def _iso_ms(value: object) -> str | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    moment = dt.datetime.fromtimestamp(value / 1000, tz=dt.UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def load_manifest(folder: Path) -> dict[str, Any]:
    path = folder / SNAPSHOT_MANIFEST
    if not path.is_file():
        msg = f"{folder} is not a Kitchener snapshot (no {SNAPSHOT_MANIFEST})."
        raise SnapshotError(msg)
    document = json.loads(path.read_text("utf-8"))
    if not isinstance(document, dict):
        msg = f"{path} is not a JSON object."
        raise SnapshotError(msg)
    if document.get("content_sha256") != manifest_content_sha256(document):
        msg = f"{path} has been edited since it was written (content hash mismatch)."
        raise SnapshotError(msg)
    return document


def manifest_content_sha256(document: Mapping[str, Any]) -> str:
    """The hash a manifest records about itself, computed without that field."""
    return content_sha256({k: v for k, v in document.items() if k != "content_sha256"})


def verified_features(folder: Path, manifest: Mapping[str, Any], key: str) -> Path:
    """The features file of one publication, refused unless its SHA-256 matches."""
    record = manifest["publications"][key]["features"]
    path = folder / str(record["file"])
    if not path.is_file():
        msg = f"{path} is missing from the snapshot."
        raise SnapshotError(msg)
    actual = file_sha256(path)
    if actual != record["sha256"]:
        msg = f"{path} does not match its recorded SHA-256 ({actual} != {record['sha256']})."
        raise SnapshotError(msg)
    return path
