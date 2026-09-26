"""The edit history of OSM elements, and the changesets behind it, for the lineage study.

Two read-only sources, and neither is the OSM editing API, which the OSMF API
usage policy reserves for editing:

- **ohsome API** (HeiGIT), ``contributions/geometry`` — every change to an
  element's geometry or tags up to the service's temporal extent, with the
  changeset that made it. Node moves that reshape a way are contributions to
  that way, attributed to the changeset that moved the node.
- **The planet changeset dump** — each changeset's tags: ``source``,
  ``imagery_used``, ``created_by``, ``comment``. The dump is one bzip2 file of
  independent streams in changeset-id order, so a changeset is found by
  indexing where each stream starts and which id it starts with.

Neither is the frozen OSM geometry the study compares against — that is
:mod:`pathable_api.geo.kitchener.osm_extract`. History is metadata about how
that geometry came to be, and it ends where ohsome's extent ends.

Contributor names and ids are never read into the study: ``user`` and ``uid``
are dropped as each changeset is parsed. Of a changeset's tags only
:data:`CHANGESET_TAG_KEYS` are kept.
"""

from __future__ import annotations

import bisect
import bz2
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pathable_api.geo.kitchener.arcgis import HttpResponse, Transport, TransportError
from pathable_api.geo.overture.evidence import file_sha256

OHSOME_API = "https://api.ohsome.org/v1"
#: Element ids per ohsome request.
OHSOME_BATCH = 50
OHSOME_ATTEMPTS = 4
HISTORY_FORMAT_VERSION = 1

#: Changeset tags kept from the dump. Everything else — including counts of a
#: contributor's own edits that some editors add — is dropped.
CHANGESET_TAG_KEYS = frozenset(
    {
        "comment",
        "source",
        "imagery_used",
        "created_by",
        "hashtags",
        "import",
        "bot",
        "mechanical",
        "StreetComplete:quest_type",
    }
)

Progress = Callable[[str], None]


class HistoryError(RuntimeError):
    """History could not be read, or does not belong to the elements asked about."""


# ---------------------------------------------------------------------------
# ohsome contributions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Contribution:
    """One change to one element: what it looked like afterwards, and who changed it."""

    element: str
    timestamp: str
    version: int | None
    changeset: int
    creation: bool
    deletion: bool
    geometry_change: bool
    tag_change: bool
    tags: dict[str, str]
    #: Longitude/latitude pairs after the change; ``None`` for a deletion.
    coordinates: tuple[tuple[float, float], ...] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "element": self.element,
            "timestamp": self.timestamp,
            "version": self.version,
            "changeset": self.changeset,
            "creation": self.creation,
            "deletion": self.deletion,
            "geometry_change": self.geometry_change,
            "tag_change": self.tag_change,
            "tags": dict(sorted(self.tags.items())),
        }


def parse_contributions(document: Mapping[str, Any]) -> list[Contribution]:
    """Contributions from an ohsome ``contributions/geometry`` GeoJSON response."""
    if document.get("type") != "FeatureCollection":
        msg = "ohsome answered something other than a FeatureCollection."
        raise HistoryError(msg)
    found = []
    for feature in document.get("features") or []:
        properties = feature.get("properties") or {}
        element = properties.get("@osmId")
        changeset = properties.get("@contributionChangesetId", properties.get("@changesetId"))
        timestamp = properties.get("@timestamp")
        if not isinstance(element, str) or changeset is None or not isinstance(timestamp, str):
            msg = f"ohsome feature without an element, changeset or timestamp: {properties!r}"
            raise HistoryError(msg)
        found.append(
            Contribution(
                element=element,
                timestamp=timestamp,
                version=int(properties["@version"]) if "@version" in properties else None,
                changeset=int(changeset),
                creation=bool(properties.get("@creation", False)),
                deletion=bool(properties.get("@deletion", False)),
                geometry_change=bool(properties.get("@geometryChange", False)),
                tag_change=bool(properties.get("@tagChange", False)),
                tags={k: str(v) for k, v in properties.items() if not k.startswith("@")},
                coordinates=_coordinates(feature.get("geometry")),
            )
        )
    found.sort(key=lambda c: (c.element, c.timestamp, c.changeset))
    return found


def _coordinates(geometry: Mapping[str, Any] | None) -> tuple[tuple[float, float], ...] | None:
    if not geometry:
        return None
    kind = geometry.get("type")
    coordinates: Any = geometry.get("coordinates")
    if not coordinates:
        return None
    if kind == "Point":
        return ((float(coordinates[0]), float(coordinates[1])),)
    if kind == "LineString":
        return tuple((float(x), float(y)) for x, y, *_ in coordinates)
    if kind == "Polygon":
        return tuple((float(x), float(y)) for x, y, *_ in coordinates[0])
    return None


@dataclass(frozen=True, slots=True)
class OhsomeRequest:
    endpoint: str
    params: dict[str, str]

    @property
    def key(self) -> str:
        canonical = json.dumps(
            {"endpoint": self.endpoint, "params": self.params},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class FetchedHistory:
    contributions: list[Contribution] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    api_version: str | None = None


def ohsome_requests(
    elements: Iterable[str],
    *,
    bbox: Sequence[float],
    time_range: tuple[str, str],
    batch: int = OHSOME_BATCH,
) -> list[OhsomeRequest]:
    """One request per batch of same-type ids, in a fixed order."""
    by_type: dict[str, list[int]] = {}
    for element in sorted(set(elements)):
        kind, _, number = element.partition("/")
        if kind not in ("node", "way") or not number.isdigit():
            msg = f"not an OSM node or way id: {element!r}"
            raise HistoryError(msg)
        by_type.setdefault(kind, []).append(int(number))
    requests = []
    for kind in sorted(by_type):
        ids = sorted(by_type[kind])
        for start in range(0, len(ids), batch):
            chunk = ", ".join(f"{kind}/{number}" for number in ids[start : start + batch])
            requests.append(
                OhsomeRequest(
                    endpoint="contributions/geometry",
                    params={
                        "bboxes": ",".join(f"{value:.6f}" for value in bbox),
                        "time": f"{time_range[0]},{time_range[1]}",
                        "filter": f"id:({chunk})",
                        "properties": "tags,metadata,contributionTypes",
                        "clipGeometry": "false",
                    },
                )
            )
    return requests


def fetch_history(
    requests: Sequence[OhsomeRequest],
    *,
    transport: Transport,
    cache_dir: Path,
    base_url: str = OHSOME_API,
    progress: Progress | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> FetchedHistory:
    """Run each request once; answers are cached by request hash and reused."""
    say = progress or (lambda _message: None)
    cache_dir.mkdir(parents=True, exist_ok=True)
    result = FetchedHistory()
    for number, request in enumerate(requests, start=1):
        body_path = cache_dir / f"{request.key}.json"
        meta_path = cache_dir / f"{request.key}.request.json"
        if body_path.is_file() and meta_path.is_file():
            body = body_path.read_bytes()
            meta = json.loads(meta_path.read_text("utf-8"))
            if hashlib.sha256(body).hexdigest() != meta["response_sha256"]:
                msg = f"cached ohsome answer {body_path.name} does not match its recorded hash."
                raise HistoryError(msg)
            say(f"ohsome {number}/{len(requests)}: cached")
        else:
            say(f"ohsome {number}/{len(requests)}: requesting")
            body = _post_with_retries(transport, f"{base_url}/{request.endpoint}", request, sleep)
            meta = {
                "endpoint": request.endpoint,
                "params": request.params,
                "response_sha256": hashlib.sha256(body).hexdigest(),
                "response_bytes": len(body),
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            body_path.write_bytes(body)
            meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), "utf-8")
        document = json.loads(body)
        contributions = parse_contributions(document)
        result.contributions.extend(contributions)
        result.api_version = result.api_version or document.get("apiVersion")
        result.requests.append(
            {
                "request_sha256": request.key,
                "endpoint": request.endpoint,
                "elements": request.params["filter"].count("/"),
                "response_sha256": meta["response_sha256"],
                "response_bytes": meta["response_bytes"],
                "contributions": len(contributions),
                "fetched_at": meta["fetched_at"],
            }
        )
    result.contributions.sort(key=lambda c: (c.element, c.timestamp, c.changeset))
    return result


def ohsome_metadata(transport: Transport, *, base_url: str = OHSOME_API) -> dict[str, Any]:
    """The service's version and the time span its history covers."""
    try:
        response = transport.get(f"{base_url}/metadata", {})
    except TransportError as error:
        msg = f"ohsome metadata: {error}"
        raise HistoryError(msg) from error
    if response.status != 200:
        msg = f"ohsome metadata: HTTP {response.status}"
        raise HistoryError(msg)
    document = json.loads(response.body)
    region = document.get("extractRegion") or {}
    extent = region.get("temporalExtent") or {}
    if not extent.get("fromTimestamp") or not extent.get("toTimestamp"):
        msg = "ohsome metadata names no temporal extent."
        raise HistoryError(msg)
    return {
        "api": base_url,
        "api_version": document.get("apiVersion"),
        "temporal_extent": {"from": extent["fromTimestamp"], "to": extent["toTimestamp"]},
        "replication_sequence": region.get("replicationSequenceNumber"),
        "attribution": (document.get("attribution") or {}).get("text"),
    }


def _post_with_retries(
    transport: Transport, url: str, request: OhsomeRequest, sleep: Callable[[float], None]
) -> bytes:
    last: str = ""
    for attempt in range(1, OHSOME_ATTEMPTS + 1):
        try:
            response: HttpResponse = transport.post(url, request.params)
        except TransportError as error:
            last = str(error)
        else:
            if response.status == 200:
                return response.body
            last = f"HTTP {response.status}: {response.body[:300]!r}"
            if response.status not in (429, 500, 502, 503, 504):
                break
        sleep(min(60.0, 5.0 * 2 ** (attempt - 1)))
    msg = f"ohsome refused {request.endpoint} ({request.key[:12]}): {last}"
    raise HistoryError(msg)


# ---------------------------------------------------------------------------
# The planet changeset dump
# ---------------------------------------------------------------------------

#: A bzip2 stream header followed by the first block's magic number.
_STREAM_START = re.compile(rb"BZh[1-9]1AY&SY")
_FIRST_ID = re.compile(rb'<changeset id="(\d+)"')
_READ_CHUNK = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Changeset:
    id: int
    created_at: str | None
    closed_at: str | None
    num_changes: int | None
    #: min lon, min lat, max lon, max lat, when the changeset has a box.
    bbox: tuple[float, float, float, float] | None
    tags: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "closed_at": self.closed_at,
            "num_changes": self.num_changes,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "tags": dict(sorted(self.tags.items())),
        }

    @classmethod
    def from_dict(cls, item: Mapping[str, Any]) -> Changeset:
        bbox = item.get("bbox")
        return cls(
            id=int(item["id"]),
            created_at=item.get("created_at"),
            closed_at=item.get("closed_at"),
            num_changes=item.get("num_changes"),
            bbox=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])) if bbox else None,
            tags=dict(item.get("tags") or {}),
        )


def parse_changeset(fragment: str) -> Changeset:
    """One ``<changeset>`` element; ``user`` and ``uid`` are never kept."""
    element = ET.fromstring(fragment)  # noqa: S314 - the dump is OSMF's own XML
    attributes = element.attrib
    bbox: tuple[float, float, float, float] | None = None
    if all(key in attributes for key in ("min_lon", "min_lat", "max_lon", "max_lat")):
        bbox = (
            float(attributes["min_lon"]),
            float(attributes["min_lat"]),
            float(attributes["max_lon"]),
            float(attributes["max_lat"]),
        )
    tags = {
        str(tag.get("k")): str(tag.get("v"))
        for tag in element.iter("tag")
        if tag.get("k") in CHANGESET_TAG_KEYS
    }
    return Changeset(
        id=int(attributes["id"]),
        created_at=attributes.get("created_at"),
        closed_at=attributes.get("closed_at"),
        num_changes=int(attributes["num_changes"]) if "num_changes" in attributes else None,
        bbox=bbox,
        tags=tags,
    )


@dataclass(slots=True)
class StreamIndex:
    """Where each bzip2 stream starts, and the first changeset id that starts in it."""

    dump_bytes: int
    offsets: list[int]
    first_ids: list[int | None]

    def as_dict(self) -> dict[str, Any]:
        return {"dump_bytes": self.dump_bytes, "offsets": self.offsets, "first_ids": self.first_ids}

    def starts(self) -> tuple[list[int], list[int]]:
        """First ids, and their streams, for the streams where an element starts."""
        pairs = [(first, k) for k, first in enumerate(self.first_ids) if first is not None]
        return [first for first, _ in pairs], [k for _, k in pairs]

    def stream_for(
        self, changeset_id: int, starts: tuple[list[int], list[int]] | None = None
    ) -> int:
        """The last stream in which an element starts at or below ``changeset_id``.

        A stream in which no element starts cannot be where one begins, so it is
        never chosen. (It once was, filled with the previous stream's first id,
        and the lookup then began one stream too late and missed the element.)
        """
        firsts, streams = starts or self.starts()
        position = bisect.bisect_right(firsts, changeset_id) - 1
        return streams[position] if position >= 0 else 0


def stream_offsets(path: Path, *, chunk: int = _READ_CHUNK) -> list[int]:
    """Byte offsets of every bzip2 stream in a multi-stream file."""
    offsets: list[int] = []
    overlap = 9
    position = 0
    tail = b""
    with path.open("rb") as handle:
        while True:
            data = handle.read(chunk)
            if not data:
                break
            window = tail + data
            base = position - len(tail)
            for match in _STREAM_START.finditer(window):
                offset = base + match.start()
                if not offsets or offset > offsets[-1]:
                    offsets.append(offset)
            tail = window[-overlap:]
            position += len(data)
    if not offsets or offsets[0] != 0:
        msg = f"{path.name} does not start with a bzip2 stream."
        raise HistoryError(msg)
    return offsets


class ChangesetDump:
    """Random access to a planet changeset dump through its stream index."""

    def __init__(self, path: Path, index: StreamIndex, *, workers: int = 8) -> None:
        if path.stat().st_size != index.dump_bytes:
            msg = f"the stream index was built for a different {path.name}."
            raise HistoryError(msg)
        self._path = path
        self._index = index
        self._workers = workers

    @classmethod
    def open(
        cls,
        path: Path,
        index_path: Path,
        *,
        workers: int = 8,
        progress: Progress | None = None,
    ) -> ChangesetDump:
        """Load the stream index, building it first if it does not exist yet."""
        if index_path.is_file():
            stored = json.loads(index_path.read_text("utf-8"))
            index = StreamIndex(stored["dump_bytes"], stored["offsets"], stored["first_ids"])
            return cls(path, index, workers=workers)
        say = progress or (lambda _message: None)
        say(f"indexing {path.name}: finding stream boundaries...")
        offsets = stream_offsets(path)
        say(f"indexing {path.name}: {len(offsets)} streams; reading their first ids...")
        size = path.stat().st_size
        bounds = list(zip(offsets, [*offsets[1:], size], strict=True))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            first_ids = list(pool.map(lambda b: _first_id(path, b[0], b[1]), bounds))
        index = StreamIndex(size, offsets, first_ids)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps(index.as_dict()), "utf-8")
        return cls(path, index, workers=workers)

    def _stream_bytes(self, stream: int) -> bytes:
        # Bytes, not text: a stream can end in the middle of a multi-byte
        # character, so only a whole element is ever decoded.
        offsets = self._index.offsets
        end = offsets[stream + 1] if stream + 1 < len(offsets) else self._index.dump_bytes
        return _decompress(self._path, offsets[stream], end)

    def lookup(self, ids: Iterable[int]) -> dict[int, Changeset]:
        """The changesets with these ids; ids the dump does not hold are left out."""
        wanted = sorted(set(ids))
        starts = self._index.starts()
        groups: dict[int, list[int]] = {}
        for changeset_id in wanted:
            groups.setdefault(self._index.stream_for(changeset_id, starts), []).append(changeset_id)
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            found = pool.map(lambda item: self._extract(*item), sorted(groups.items()))
            return {c.id: c for batch in found for c in batch}

    def _extract(self, stream: int, ids: Sequence[int]) -> list[Changeset]:
        data = self._stream_bytes(stream)
        following = stream + 1
        found = []
        for changeset_id in ids:
            fragment = fragment_of(data, changeset_id)
            # Streams split the XML anywhere, so an element — even its opening
            # tag — can straddle the end of one. Read on through streams in
            # which nothing starts, and one stream more for the element's tail.
            while fragment is None and following < len(self._index.offsets):
                starts_something = self._index.first_ids[following] is not None
                data += self._stream_bytes(following)
                following += 1
                fragment = fragment_of(data, changeset_id)
                if starts_something:
                    break
            if fragment is not None:
                found.append(parse_changeset(fragment))
        return found


def fragment_of(data: bytes, changeset_id: int) -> str | None:
    """One whole ``<changeset>`` element from decompressed dump bytes, decoded."""
    start = data.find(b'<changeset id="%d"' % changeset_id)
    if start < 0:
        return None
    end = data.find(b"<changeset ", start + 1)
    if end < 0:
        end = data.find(b"</osm>", start)
        if end < 0:
            return None
    return data[start:end].strip().decode("utf-8")


def _decompress(path: Path, start: int, end: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(start)
        return bz2.decompress(handle.read(end - start))


def _first_id(path: Path, start: int, end: int) -> int | None:
    match = _FIRST_ID.search(_decompress(path, start, end))
    return int(match.group(1)) if match else None


def dump_header(path: Path) -> dict[str, str]:
    """The ``<osm>`` element's attributes: generator and timestamp."""
    with path.open("rb") as handle:
        head = bz2.BZ2Decompressor().decompress(handle.read(1 << 20))
    match = re.search(rb"<osm ([^>]*)>", head)
    if match is None:
        msg = f"{path.name} does not begin with an <osm> element."
        raise HistoryError(msg)
    return {
        key.decode(): value.decode()
        for key, value in re.findall(rb'(\w+)="([^"]*)"', match.group(1))
    }


def iter_elements(
    contributions: Iterable[Contribution],
) -> Iterator[tuple[str, list[Contribution]]]:
    """Contributions grouped by element, each group in time order."""
    grouped: dict[str, list[Contribution]] = {}
    for contribution in contributions:
        grouped.setdefault(contribution.element, []).append(contribution)
    for element in sorted(grouped):
        yield element, sorted(grouped[element], key=lambda c: (c.timestamp, c.changeset))


def dump_identity(path: Path) -> dict[str, Any]:
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
        "header": dump_header(path),
    }
