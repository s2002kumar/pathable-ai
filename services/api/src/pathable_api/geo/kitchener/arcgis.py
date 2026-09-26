"""A complete, verifiable read of one ArcGIS feature layer.

A feature service answers at most ``maxRecordCount`` features per request and
says so only with an ``exceededTransferLimit`` flag, which is easy to miss. A
read that trusts the first page, or pages by offset while the layer is being
republished, returns a plausible-looking subset with no error at all. So this
module does not page by offset:

1. It asks for the feature count and for every object id, and requires the two
   to agree.
2. It asks for the features by id, in fixed chunks well under the server
   limit, and requires every chunk to return exactly the ids it asked for.
3. It reads the layer's edit timestamps and count before and after, and starts
   again if either moved during the read — a snapshot that straddles a
   republish is not a snapshot.

Every request is idempotent, so any of them can be retried. Transient failures
(connection errors, HTTP 429/5xx, and the HTTP 200 responses ArcGIS uses to
carry its own 5xx errors) are retried with backoff; anything else stops the
read with the reason.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import requests

#: Default features per request: half the Kitchener layers' ``maxRecordCount``.
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_ATTEMPTS = 4

#: ArcGIS error codes, carried in an HTTP 200 body, that mean "try again".
_TRANSIENT_ARCGIS_CODES = frozenset({429, 500, 502, 503, 504})
_TRANSIENT_HTTP = frozenset({429, 500, 502, 503, 504})


class ArcGISError(RuntimeError):
    """The service refused a request, or answered something that cannot be trusted."""


class IncompleteReadError(ArcGISError):
    """The features returned do not account for every feature the layer holds."""


class LayerChangedError(ArcGISError):
    """The layer was edited or republished while it was being read."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]


class TransportError(RuntimeError):
    """The request never produced an HTTP response."""


class Transport(Protocol):
    def get(self, url: str, params: Mapping[str, str]) -> HttpResponse: ...

    def post(self, url: str, data: Mapping[str, str]) -> HttpResponse: ...


class RequestsTransport:
    """HTTP over ``requests``, with a user agent that names the project."""

    def __init__(self, *, timeout_seconds: float = 120.0) -> None:
        self._session = requests.Session()
        self._session.headers["User-Agent"] = (
            "pathable-kitchener-audit (+https://github.com/s2002kumar/pathable-ai)"
        )
        self._timeout = timeout_seconds

    def get(self, url: str, params: Mapping[str, str]) -> HttpResponse:
        try:
            response = self._session.get(url, params=dict(params), timeout=self._timeout)
        except requests.RequestException as error:
            raise TransportError(str(error)) from error
        return HttpResponse(response.status_code, response.content, dict(response.headers))

    def post(self, url: str, data: Mapping[str, str]) -> HttpResponse:
        try:
            response = self._session.post(url, data=dict(data), timeout=self._timeout)
        except requests.RequestException as error:
            raise TransportError(str(error)) from error
        return HttpResponse(response.status_code, response.content, dict(response.headers))


@dataclass(slots=True)
class RequestLog:
    """What the read cost, counted as it happened."""

    requests: int = 0
    retries: int = 0
    bytes_received: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "requests": self.requests,
            "retries": self.retries,
            "bytes_received": self.bytes_received,
        }


@dataclass(frozen=True, slots=True)
class JsonResponse:
    document: dict[str, Any]
    body: bytes
    headers: Mapping[str, str]


class ArcGISClient:
    """ArcGIS REST requests with retries, error detection and accounting."""

    def __init__(
        self,
        transport: Transport,
        *,
        attempts: int = DEFAULT_ATTEMPTS,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if attempts < 1:
            msg = "attempts must be at least 1."
            raise ValueError(msg)
        self._transport = transport
        self._attempts = attempts
        self._backoff = backoff_seconds
        self._sleep = sleep
        self.log = RequestLog()

    def get_json(self, url: str, params: Mapping[str, str] | None = None) -> JsonResponse:
        return self._request("GET", url, {"f": "json", **(params or {})})

    def post_json(self, url: str, data: Mapping[str, str]) -> JsonResponse:
        return self._request("POST", url, {"f": "json", **data})

    def get_bytes(self, url: str) -> HttpResponse:
        """A plain document (not ArcGIS JSON), retried the same way."""
        for attempt in range(1, self._attempts + 1):
            try:
                response = self._send("GET", url, {})
            except TransportError as error:
                self._retry_or_raise(attempt, f"GET {url} failed: {error}")
                continue
            if response.status in _TRANSIENT_HTTP:
                self._retry_or_raise(attempt, f"GET {url} returned HTTP {response.status}")
                continue
            return response
        raise AssertionError("unreachable")  # pragma: no cover

    def _request(self, method: str, url: str, params: Mapping[str, str]) -> JsonResponse:
        for attempt in range(1, self._attempts + 1):
            try:
                response = self._send(method, url, params)
            except TransportError as error:
                self._retry_or_raise(attempt, f"{method} {url} failed: {error}")
                continue
            if response.status in _TRANSIENT_HTTP:
                self._retry_or_raise(attempt, f"{method} {url} returned HTTP {response.status}")
                continue
            if response.status != 200:
                msg = f"{method} {url} returned HTTP {response.status}."
                raise ArcGISError(msg)
            try:
                document = json.loads(response.body)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                msg = f"{method} {url} did not return JSON: {error}"
                raise ArcGISError(msg) from error
            if not isinstance(document, dict):
                msg = f"{method} {url} returned JSON that is not an object."
                raise ArcGISError(msg)
            error_body = document.get("error")
            if isinstance(error_body, dict):
                code = error_body.get("code")
                detail = f"{method} {url}: ArcGIS error {code}: {error_body.get('message')}"
                if code in _TRANSIENT_ARCGIS_CODES:
                    self._retry_or_raise(attempt, detail)
                    continue
                raise ArcGISError(detail)
            return JsonResponse(document, response.body, response.headers)
        raise AssertionError("unreachable")  # pragma: no cover

    def _send(self, method: str, url: str, params: Mapping[str, str]) -> HttpResponse:
        self.log.requests += 1
        if method == "GET":
            response = self._transport.get(url, params)
        else:
            response = self._transport.post(url, params)
        self.log.bytes_received += len(response.body)
        return response

    def _retry_or_raise(self, attempt: int, detail: str) -> None:
        if attempt >= self._attempts:
            msg = f"{detail} (gave up after {attempt} attempts)"
            raise ArcGISError(msg)
        self.log.retries += 1
        self._sleep(self._backoff * 2 ** (attempt - 1))


# ---------------------------------------------------------------------------
# Layer description
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldCheck:
    missing: tuple[str, ...]
    mismatched: tuple[str, ...]
    additional: tuple[str, ...]

    @property
    def compatible(self) -> bool:
        return not self.missing and not self.mismatched

    def as_dict(self) -> dict[str, Any]:
        return {
            "compatible": self.compatible,
            "missing": list(self.missing),
            "mismatched": list(self.mismatched),
            "additional_fields": list(self.additional),
        }


class IncompatibleLayerError(ArcGISError):
    def __init__(self, layer_url: str, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__(f"{layer_url} does not satisfy the contract: " + "; ".join(problems))


def check_fields(
    fields: Sequence[Mapping[str, Any]],
    contract: Mapping[str, str],
    compatible: Mapping[str, frozenset[str]],
) -> FieldCheck:
    observed = {str(item["name"]): str(item["type"]) for item in fields}
    missing = [name for name in contract if name not in observed]
    mismatched = [
        f"{name} is {observed[name]}, expected {expected}"
        for name, expected in contract.items()
        if name in observed and observed[name] not in compatible.get(expected, {expected})
    ]
    additional = sorted(name for name in observed if name not in contract)
    return FieldCheck(tuple(missing), tuple(mismatched), tuple(additional))


def editing_info(layer: Mapping[str, Any]) -> dict[str, int | None]:
    info = layer.get("editingInfo") or {}
    return {
        key: (int(info[key]) if isinstance(info.get(key), int | float) else None)
        for key in ("lastEditDate", "dataLastEditDate", "schemaLastEditDate")
    }


# ---------------------------------------------------------------------------
# Complete read
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Page:
    """One request's worth of features, kept byte for byte."""

    index: int
    object_ids: tuple[int, ...]
    body: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


@dataclass(slots=True)
class LayerRead:
    layer_url: str
    layer: dict[str, Any]
    layer_body: bytes
    fields: FieldCheck
    count: int
    object_ids: tuple[int, ...]
    features: list[dict[str, Any]]
    pages: list[Page]
    editing_before: dict[str, int | None]
    editing_after: dict[str, int | None]
    #: The fixed query parameters every page used, recorded so a read can be repeated.
    parameters: dict[str, str]
    attempts: int
    seconds: float
    log: dict[str, int] = field(default_factory=dict)


def read_layer(
    client: ArcGISClient,
    layer_url: str,
    *,
    contract: Mapping[str, str],
    compatible: Mapping[str, frozenset[str]],
    expected_geometry: str,
    expected_wkid: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    attempts: int = 3,
) -> LayerRead:
    """Read every feature of one layer, or fail saying why not.

    The layer description is checked first: geometry type, coordinate system and
    the column contract. Then the read is repeated from the top, up to
    ``attempts`` times, while the layer keeps changing underneath it.
    """
    last_change = ""
    for attempt in range(1, attempts + 1):
        try:
            return _read_once(
                client,
                layer_url,
                contract=contract,
                compatible=compatible,
                expected_geometry=expected_geometry,
                expected_wkid=expected_wkid,
                chunk_size=chunk_size,
                attempt=attempt,
            )
        except LayerChangedError as error:
            last_change = str(error)
    msg = f"{layer_url} kept changing during {attempts} attempted reads: {last_change}"
    raise LayerChangedError(msg)


def _read_once(
    client: ArcGISClient,
    layer_url: str,
    *,
    contract: Mapping[str, str],
    compatible: Mapping[str, frozenset[str]],
    expected_geometry: str,
    expected_wkid: int,
    chunk_size: int,
    attempt: int,
) -> LayerRead:
    started = time.perf_counter()
    described = client.get_json(layer_url)
    layer = described.document
    _check_layer(layer_url, layer, contract, compatible, expected_geometry, expected_wkid)
    fields = check_fields(layer["fields"], contract, compatible)
    before = editing_info(layer)

    max_records = int(layer.get("maxRecordCount") or 0)
    if max_records <= 0:
        msg = f"{layer_url} does not state a maxRecordCount."
        raise ArcGISError(msg)
    size = min(chunk_size, max_records)
    if size < 1:
        msg = "chunk_size must be at least 1."
        raise ValueError(msg)

    query_url = f"{layer_url}/query"
    count = _count(client, query_url)
    object_ids = _object_ids(client, query_url, layer, count)

    out_fields = ",".join(str(item["name"]) for item in layer["fields"])
    parameters = {
        "outFields": out_fields,
        "returnGeometry": "true",
        "outSR": str(expected_wkid),
        "returnZ": "false",
        "returnM": "false",
        "returnTrueCurves": "false",
    }
    oid_field = str(layer["objectIdField"])
    features: list[dict[str, Any]] = []
    pages: list[Page] = []
    for index, start in enumerate(range(0, len(object_ids), size), start=1):
        chunk = object_ids[start : start + size]
        response = client.post_json(
            query_url, {"objectIds": ",".join(str(i) for i in chunk), **parameters}
        )
        page_features = _page_features(layer_url, response.document, chunk, oid_field)
        features.extend(page_features)
        pages.append(Page(index=index, object_ids=chunk, body=response.body))

    described_after = client.get_json(layer_url)
    after = editing_info(described_after.document)
    count_after = _count(client, query_url)
    if after != before or count_after != count:
        msg = f"edit info {before} → {after}, count {count} → {count_after} (attempt {attempt})"
        raise LayerChangedError(msg)

    return LayerRead(
        layer_url=layer_url,
        layer=layer,
        layer_body=described.body,
        fields=fields,
        count=count,
        object_ids=object_ids,
        features=features,
        pages=pages,
        editing_before=before,
        editing_after=after,
        parameters=parameters,
        attempts=attempt,
        seconds=time.perf_counter() - started,
    )


def _check_layer(
    layer_url: str,
    layer: Mapping[str, Any],
    contract: Mapping[str, str],
    compatible: Mapping[str, frozenset[str]],
    expected_geometry: str,
    expected_wkid: int,
) -> None:
    problems: list[str] = []
    if layer.get("geometryType") != expected_geometry:
        problems.append(f"geometry is {layer.get('geometryType')}, expected {expected_geometry}")
    reference = (layer.get("extent") or {}).get("spatialReference") or {}
    wkids = {reference.get("wkid"), reference.get("latestWkid")}
    if expected_wkid not in wkids:
        problems.append(f"spatial reference is {reference}, expected wkid {expected_wkid}")
    if layer.get("hasZ") or layer.get("hasM"):
        problems.append("layer has Z or M values, which this read does not handle")
    if not layer.get("objectIdField"):
        problems.append("layer names no objectIdField")
    fields = layer.get("fields")
    if not isinstance(fields, list):
        problems.append("layer lists no fields")
    else:
        check = check_fields(fields, contract, compatible)
        problems.extend(f"missing field {name}" for name in check.missing)
        problems.extend(check.mismatched)
    if problems:
        raise IncompatibleLayerError(layer_url, problems)


def _count(client: ArcGISClient, query_url: str) -> int:
    document = client.get_json(query_url, {"where": "1=1", "returnCountOnly": "true"}).document
    count = document.get("count")
    if not isinstance(count, int) or count < 0:
        msg = f"{query_url} returned no usable count: {count!r}"
        raise ArcGISError(msg)
    return count


def _object_ids(
    client: ArcGISClient, query_url: str, layer: Mapping[str, Any], count: int
) -> tuple[int, ...]:
    limit = layer.get("maxIdsCount") or layer.get("standardMaxIdsCount")
    if isinstance(limit, int) and count > limit:
        msg = (
            f"{query_url} holds {count} features but returns at most {limit} ids per request; "
            "this read would be incomplete."
        )
        raise IncompleteReadError(msg)
    document = client.get_json(query_url, {"where": "1=1", "returnIdsOnly": "true"}).document
    raw = document.get("objectIds")
    if raw is None:
        raw = []
    if not isinstance(raw, list) or not all(isinstance(i, int) for i in raw):
        msg = f"{query_url} returned malformed object ids."
        raise ArcGISError(msg)
    ids = tuple(sorted(raw))
    if len(set(ids)) != len(ids):
        msg = f"{query_url} returned duplicate object ids."
        raise IncompleteReadError(msg)
    if len(ids) != count:
        msg = f"{query_url} reports {count} features but returned {len(ids)} object ids."
        raise IncompleteReadError(msg)
    return ids


def _page_features(
    layer_url: str,
    document: Mapping[str, Any],
    requested: Sequence[int],
    oid_field: str,
) -> list[dict[str, Any]]:
    if document.get("exceededTransferLimit"):
        msg = f"{layer_url} truncated a page of {len(requested)} ids (exceededTransferLimit)."
        raise IncompleteReadError(msg)
    features = document.get("features")
    if not isinstance(features, list):
        msg = f"{layer_url} returned a page without a feature list."
        raise ArcGISError(msg)
    returned: list[int] = []
    for feature in features:
        attributes = feature.get("attributes") if isinstance(feature, dict) else None
        if not isinstance(attributes, dict) or not isinstance(attributes.get(oid_field), int):
            msg = f"{layer_url} returned a feature without an integer {oid_field}."
            raise ArcGISError(msg)
        geometry = feature.get("geometry")
        if isinstance(geometry, dict) and "curvePaths" in geometry:
            msg = f"{layer_url} returned a true curve although returnTrueCurves=false."
            raise ArcGISError(msg)
        returned.append(int(attributes[oid_field]))
    if sorted(returned) != sorted(requested):
        asked = set(requested)
        got = set(returned)
        missing = len(asked - got)
        extra = len(got - asked)
        duplicated = len(returned) - len(got)
        # A missing id means the feature was deleted after the id list was taken:
        # the layer changed, and the whole read starts again.
        if missing and not extra and not duplicated:
            msg = f"{missing} requested feature(s) no longer exist"
            raise LayerChangedError(msg)
        msg = (
            f"{layer_url} page answered {len(returned)} feature(s) for {len(requested)} ids: "
            f"{missing} missing, {extra} unrequested, {duplicated} duplicated."
        )
        raise IncompleteReadError(msg)
    return [dict(feature) for feature in features]


def canonical_feature(feature: Mapping[str, Any]) -> str:
    """One feature as a stable line: sorted keys, no insignificant whitespace.

    Floats are written with Python's shortest round-trip representation, so the
    same parsed coordinates always produce the same text.
    """
    return json.dumps(
        {"attributes": feature.get("attributes"), "geometry": feature.get("geometry")},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
