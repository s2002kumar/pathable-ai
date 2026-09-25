"""How PathAble's OSM identities relate to an Overture release — measured, not assumed.

The linkage is read from Overture's own provenance: every segment lists the OSM
ways it was built from in ``sources``, each with a version and, where the way
covers only part of the segment, a ``between`` range. Connectors list the OSM
node they came from. Nothing is matched by geometry here — a nearest-neighbour
guess would raise the match rate by inventing correspondences, and that is a
separate experiment with its own error analysis.

Three questions are kept apart because they have different answers:

* **Identity.** Does Overture cite this OSM way at all?
* **Version.** Is it the same revision PathAble ingested? PathAble stores no
  versions, so without outside evidence every identity match is
  ``id_match_version_unknown``. With the dataset's own checksum-verified source
  extract, the version can be compared exactly.
* **Cardinality.** One way can be split across several segments, and one
  segment can merge several ways. Both are recorded, with the ranges, rather
  than forced into one GERS id per way.

Every source row is accounted for: linked, property-only, non-OSM, malformed or
duplicate. Nothing is dropped silently.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb

from pathable_api.geo.overture.evidence import content_sha256, file_sha256
from pathable_api.geo.overture.extract import (
    BRIDGE_SAMPLE_FILE,
    CHANGELOG_FILE,
    CONNECTOR_FILE,
    EXTRACT_FORMAT_VERSION,
    EXTRACT_MANIFEST,
    SEGMENT_FILE,
)
from pathable_api.geo.overture.identity import (
    OSM_DATASET,
    LinearRange,
    MalformedRange,
    MalformedRecordId,
    OsmElementRef,
    OsmElementType,
    parse_between,
    parse_osm_record_id,
    parse_pathable_osm_id,
)
from pathable_api.geo.overture.osm_versions import ElementState, VersionEvidence
from pathable_api.geo.overture.pathable import PathAbleIdentities

LINKAGE_FORMAT_VERSION = 1

#: How many examples each category carries. Chosen by hash, not by hand.
EXAMPLES_PER_CATEGORY = 3

#: OSM's UTC edit-time form, as both Overture and the extract reader write it.
_OSM_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


class ExtractMismatchError(RuntimeError):
    """The extract on disk is not the one its manifest describes."""


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceRow:
    """One provenance entry: an element of ``sources[]`` or one bridge-file row."""

    gers_id: str
    dataset: str | None
    record_id: str | None
    #: ``""`` when the source contributed the feature itself; a JSON pointer such
    #: as ``/routes`` when it contributed one property only. Bridge rows have no
    #: such column, so this is ``None`` for them.
    property: str | None
    between: tuple[float, ...] | None
    update_time: str | None
    #: Overture's ``version`` field. For OSM it names the planet snapshot, not
    #: the element's version — that lives in the ``@n`` suffix of ``record_id``.
    resource_version: str | None
    confidence: float | None = None
    dataset_between: tuple[float, ...] | None = None


@dataclass(frozen=True, slots=True)
class SegmentFeature:
    gers_id: str
    subtype: str | None
    feature_class: str | None
    subclass: str | None
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class ChangeRow:
    gers_id: str
    feature_type: str
    change_type: str
    columns_changed: tuple[str, ...]


@dataclass(slots=True)
class OvertureSide:
    manifest: dict[str, Any]
    segments: dict[str, SegmentFeature]
    segment_sources: list[SourceRow]
    connector_ids: set[str]
    connector_sources: list[SourceRow]
    bridge_sample: list[SourceRow] | None = None
    changelog: list[ChangeRow] | None = None

    @property
    def release(self) -> str:
        return str(self.manifest["release"]["observed"])

    @property
    def region_bounds(self) -> tuple[float, float, float, float]:
        bounds = self.manifest["region"]["bounds"]
        return (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))


def load_overture_side(extract_dir: Path) -> OvertureSide:
    """Load an extract, refusing one whose files no longer match their manifest."""
    manifest_path = extract_dir / EXTRACT_MANIFEST
    if not manifest_path.is_file():
        msg = f"{extract_dir} has no {EXTRACT_MANIFEST}; run `pathable overture extract` first."
        raise ExtractMismatchError(msg)
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("overture_extract_version") != EXTRACT_FORMAT_VERSION:
        msg = f"Unsupported extract format {manifest.get('overture_extract_version')!r}."
        raise ExtractMismatchError(msg)
    if content_sha256({k: v for k, v in manifest.items() if k != "content_sha256"}) != manifest.get(
        "content_sha256"
    ):
        msg = f"{manifest_path} has been edited since it was written."
        raise ExtractMismatchError(msg)
    for artifact in manifest["artifacts"].values():
        path = extract_dir / artifact["output"]["file"]
        if not path.is_file() or file_sha256(path) != artifact["output"]["sha256"]:
            msg = f"{path} is missing or differs from the manifest."
            raise ExtractMismatchError(msg)

    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("SET autoinstall_known_extensions = false")
        connection.execute("SET autoload_known_extensions = false")
        segment_path = (extract_dir / SEGMENT_FILE).as_posix()
        segments = {
            row[0]: SegmentFeature(
                gers_id=row[0],
                subtype=row[1],
                feature_class=row[2],
                subclass=row[3],
                bbox=(float(row[4]), float(row[5]), float(row[6]), float(row[7])),
            )
            for row in connection.execute(_SEGMENTS_QUERY, [segment_path]).fetchall()
        }
        connector_path = (extract_dir / CONNECTOR_FILE).as_posix()
        side = OvertureSide(
            manifest=manifest,
            segments=segments,
            segment_sources=_source_rows(connection, segment_path),
            connector_ids={
                str(row[0]) for row in connection.execute(_IDS_QUERY, [connector_path]).fetchall()
            },
            connector_sources=_source_rows(connection, connector_path),
        )
        if "bridge_sample" in manifest["artifacts"]:
            side.bridge_sample = _bridge_rows(
                connection, (extract_dir / BRIDGE_SAMPLE_FILE).as_posix()
            )
        if "changelog" in manifest["artifacts"]:
            side.changelog = [
                ChangeRow(str(row[0]), str(row[1]), str(row[2]), tuple(row[3] or ()))
                for row in connection.execute(
                    _CHANGELOG_ROWS_QUERY, [(extract_dir / CHANGELOG_FILE).as_posix()]
                ).fetchall()
            ]
    finally:
        connection.close()
    return side


_SEGMENTS_QUERY = (
    "SELECT id, subtype, class, subclass, bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax "
    "FROM read_parquet(?)"
)
_IDS_QUERY = "SELECT id FROM read_parquet(?)"
_SOURCES_QUERY = (
    "SELECT id, s.dataset, s.record_id, s.property, s.between, s.update_time, s.version, "
    "s.confidence FROM (SELECT id, unnest(sources) AS s FROM read_parquet(?)) "
    "ORDER BY id, s.record_id NULLS FIRST, s.property"
)
_BRIDGE_ROWS_QUERY = (
    "SELECT id, dataset, record_id, between, update_time, version, dataset_between "
    "FROM read_parquet(?) ORDER BY id, record_id"
)
_CHANGELOG_ROWS_QUERY = (
    "SELECT id, type, change_type, columns_changed FROM read_parquet(?) "
    "ORDER BY type, change_type, id"
)


def _source_rows(connection: duckdb.DuckDBPyConnection, parquet: str) -> list[SourceRow]:
    rows = connection.execute(_SOURCES_QUERY, [parquet]).fetchall()
    return [
        SourceRow(
            gers_id=str(row[0]),
            dataset=row[1],
            record_id=row[2],
            property=row[3],
            between=tuple(row[4]) if row[4] is not None else None,
            update_time=row[5],
            resource_version=row[6],
            confidence=row[7],
        )
        for row in rows
    ]


def _bridge_rows(connection: duckdb.DuckDBPyConnection, parquet: str) -> list[SourceRow]:
    rows = connection.execute(_BRIDGE_ROWS_QUERY, [parquet]).fetchall()
    return [
        SourceRow(
            gers_id=str(row[0]),
            dataset=row[1],
            record_id=row[2],
            property=None,
            between=tuple(row[3]) if row[3] is not None else None,
            update_time=row[4],
            resource_version=row[5],
            dataset_between=tuple(row[6]) if row[6] is not None else None,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


class RowKind(StrEnum):
    OSM_WAY = "osm_way_geometry"
    OSM_PROPERTY_ONLY = "osm_property_only"
    OSM_OTHER_ELEMENT = "osm_node_or_relation_geometry"
    OSM_NODE = "osm_node"
    NON_OSM = "non_osm_dataset"
    MALFORMED_RECORD_ID = "malformed_record_id"
    MALFORMED_BETWEEN = "malformed_between"
    DUPLICATE = "duplicate_row"


class WayMatch(StrEnum):
    LINKED = "linked"
    NOT_IN_OVERTURE = "not_in_overture_sources"
    NOT_AN_OSM_ID = "pathable_id_not_osm"


class Cardinality(StrEnum):
    #: The way is the only way in the only segment it appears in.
    ONE_TO_ONE = "one_to_one"
    #: Overture split the way across several segments, none shared with other ways.
    ONE_TO_MANY = "one_to_many"
    #: The way's only segment also merges other ways.
    MANY_TO_ONE = "many_to_one"
    #: Split across several segments, at least one of which merges other ways.
    MANY_TO_MANY = "many_to_many"


class VersionStatus(StrEnum):
    #: Same version, and Overture's ``update_time`` equals the latest edit PathAble's
    #: snapshot holds for the element (and, for a way, all its nodes).
    EXACT = "exact_version_match"
    #: Same way version, but Overture saw a node edit PathAble's snapshot predates:
    #: the shape may differ even though the way's version does not.
    NODES_EDITED_LATER = "way_version_match_nodes_edited_later"
    #: Same version, but there is no edit time on one side to confirm it.
    TIME_UNVERIFIED = "version_match_time_unverified"
    #: Same version, but Overture's edit time is earlier than PathAble's — which the
    #: observed semantics say cannot happen. Kept visible rather than absorbed.
    TIME_INCONSISTENT = "version_match_time_inconsistent"
    UNKNOWN = "id_match_version_unknown"
    PATHABLE_OLDER = "version_mismatch_pathable_older"
    PATHABLE_NEWER = "version_mismatch_pathable_newer"
    #: Overture cites the same way at two different versions.
    AMBIGUOUS = "ambiguous_conflicting_overture_versions"
    #: Evidence was supplied but does not contain this element.
    NO_EVIDENCE_FOR_ELEMENT = "version_evidence_missing_element"


class SegmentOutcome(StrEnum):
    ALL_WAYS_IN_PATHABLE = "all_osm_ways_in_pathable"
    SOME_WAYS_IN_PATHABLE = "some_osm_ways_in_pathable"
    NO_WAYS_IN_PATHABLE = "osm_ways_not_in_pathable"
    UNRESOLVED = "unresolved_no_osm_way_source"


class EdgeOutcome(StrEnum):
    SINGLE_SEGMENT = "way_in_single_segment"
    SPLIT_WAY = "ambiguous_way_split_across_segments"
    WAY_NOT_IN_OVERTURE = "way_not_in_overture_sources"
    NOT_AN_OSM_ID = "pathable_id_not_osm"
    NO_WAY_ID = "no_source_way_id"


@dataclass(frozen=True, slots=True, order=True)
class WayLink:
    """One way contributing geometry to one segment."""

    gers_id: str
    way: OsmElementRef
    #: The part of the *segment* this way covers. ``None`` is the whole segment.
    segment_range: LinearRange | None
    update_time: str | None


@dataclass(slots=True)
class ParsedSources:
    links: list[WayLink] = field(default_factory=list)
    kinds: Counter[str] = field(default_factory=Counter)
    kinds_by_dataset: Counter[tuple[str, str]] = field(default_factory=Counter)
    property_paths: Counter[str] = field(default_factory=Counter)
    malformed: list[SourceRow] = field(default_factory=list)
    #: Segments with at least one way link.
    linked_segments: set[str] = field(default_factory=set)
    datasets_by_segment: dict[str, set[str]] = field(default_factory=dict)
    null_confidence: int = 0
    null_update_time_by_kind: Counter[str] = field(default_factory=Counter)


def parse_segment_sources(rows: Iterable[SourceRow]) -> ParsedSources:
    parsed = ParsedSources()
    seen: set[SourceRow] = set()
    for row in rows:
        parsed.datasets_by_segment.setdefault(row.gers_id, set()).add(row.dataset or "")
        if row.confidence is None:
            parsed.null_confidence += 1
        if row in seen:
            _count(parsed, row, RowKind.DUPLICATE)
            continue
        seen.add(row)
        kind = _classify_segment_row(row, parsed)
        _count(parsed, row, kind)
        if row.update_time is None:
            parsed.null_update_time_by_kind[kind] += 1
    parsed.links.sort()
    return parsed


def _classify_segment_row(row: SourceRow, parsed: ParsedSources) -> RowKind:
    if row.dataset != OSM_DATASET:
        return RowKind.NON_OSM
    reference = parse_osm_record_id(row.record_id)
    if isinstance(reference, MalformedRecordId):
        parsed.malformed.append(row)
        return RowKind.MALFORMED_RECORD_ID
    if row.property:
        parsed.property_paths[row.property] += 1
        return RowKind.OSM_PROPERTY_ONLY
    if reference.element_type is not OsmElementType.WAY:
        return RowKind.OSM_OTHER_ELEMENT
    segment_range = parse_between(row.between)
    if isinstance(segment_range, MalformedRange):
        parsed.malformed.append(row)
        return RowKind.MALFORMED_BETWEEN
    parsed.links.append(WayLink(row.gers_id, reference, segment_range, row.update_time))
    parsed.linked_segments.add(row.gers_id)
    return RowKind.OSM_WAY


def _count(parsed: ParsedSources, row: SourceRow, kind: RowKind) -> None:
    parsed.kinds[kind] += 1
    parsed.kinds_by_dataset[(row.dataset or "null", kind)] += 1


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WayResult:
    raw_id: str
    match: WayMatch
    cardinality: Cardinality | None = None
    version: VersionStatus | None = None
    segments: tuple[str, ...] = ()
    overture_versions: tuple[int, ...] = ()
    pathable_version: int | None = None
    partial_ranges: int = 0


def classify_ways(
    identities: PathAbleIdentities,
    parsed: ParsedSources,
    evidence: VersionEvidence | None,
) -> list[WayResult]:
    by_way: dict[int, list[WayLink]] = defaultdict(list)
    ways_in_segment: dict[str, set[int]] = defaultdict(set)
    for link in parsed.links:
        by_way[link.way.element_id].append(link)
        ways_in_segment[link.gers_id].add(link.way.element_id)

    results: list[WayResult] = []
    for raw_id in sorted(identities.way_edges):
        way_id = parse_pathable_osm_id(raw_id)
        if way_id is None:
            results.append(WayResult(raw_id, WayMatch.NOT_AN_OSM_ID))
            continue
        links = by_way.get(way_id)
        if not links:
            results.append(WayResult(raw_id, WayMatch.NOT_IN_OVERTURE))
            continue
        segments = tuple(sorted({link.gers_id for link in links}))
        merged = any(len(ways_in_segment[gers]) > 1 for gers in segments)
        split = len(segments) > 1
        cardinality = {
            (False, False): Cardinality.ONE_TO_ONE,
            (True, False): Cardinality.ONE_TO_MANY,
            (False, True): Cardinality.MANY_TO_ONE,
            (True, True): Cardinality.MANY_TO_MANY,
        }[(split, merged)]
        overture_versions = tuple(sorted({link.way.version for link in links}))
        overture_times = {link.update_time for link in links}
        pathable_state = evidence.ways.get(way_id) if evidence is not None else None
        results.append(
            WayResult(
                raw_id=raw_id,
                match=WayMatch.LINKED,
                cardinality=cardinality,
                version=_version_status(
                    overture_versions, overture_times, evidence, pathable_state
                ),
                segments=segments,
                overture_versions=overture_versions,
                pathable_version=pathable_state.version if pathable_state is not None else None,
                partial_ranges=sum(1 for link in links if link.segment_range is not None),
            )
        )
    return results


def _version_status(
    overture_versions: Sequence[int],
    overture_times: Collection[str | None],
    evidence: VersionEvidence | None,
    state: ElementState | None,
) -> VersionStatus:
    if len(overture_versions) > 1:
        return VersionStatus.AMBIGUOUS
    if evidence is None:
        return VersionStatus.UNKNOWN
    if state is None:
        return VersionStatus.NO_EVIDENCE_FOR_ELEMENT
    overture = overture_versions[0]
    if state.version != overture:
        return (
            VersionStatus.PATHABLE_OLDER
            if state.version < overture
            else VersionStatus.PATHABLE_NEWER
        )
    times = set(overture_times)
    latest = state.latest_member_timestamp
    if len(times) != 1 or latest is None:
        return VersionStatus.TIME_UNVERIFIED
    (overture_time,) = times
    if overture_time is None or _OSM_TIME.fullmatch(overture_time) is None:
        return VersionStatus.TIME_UNVERIFIED
    # Same fixed-width UTC form on both sides, so string order is time order.
    if overture_time == latest:
        return VersionStatus.EXACT
    if overture_time > latest:
        return VersionStatus.NODES_EDITED_LATER
    return VersionStatus.TIME_INCONSISTENT


def build_report(
    identities: PathAbleIdentities,
    overture: OvertureSide,
    evidence: VersionEvidence | None,
    *,
    run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed = parse_segment_sources(overture.segment_sources)
    ways = classify_ways(identities, parsed, evidence)
    pathable_way_ids = {
        way_id
        for way_id in (parse_pathable_osm_id(raw) for raw in identities.way_edges)
        if way_id is not None
    }

    report: dict[str, Any] = {
        "overture_linkage_version": LINKAGE_FORMAT_VERSION,
        "what_this_shows": (
            "How PathAble's stored OSM identities appear in Overture's own provenance "
            "(segment and connector `sources`), for one pinned release and one region. "
            "Matching is by identifier only; no geometry matching was attempted."
        ),
        "what_this_does_not_show": [
            "That PathAble is synchronized with Overture, or that incremental updates are correct.",
            "That an id match is the same OSM revision, unless version_evidence says so.",
            "That Overture is more or less accurate or complete than OpenStreetMap.",
            "Anything about routing: no dataset was written, activated or re-routed.",
        ],
        "pathable": {
            **identities.facts.as_dict(),
            "distinct_source_way_ids": len(identities.way_edges),
            "segments_without_source_way_id": identities.edges_without_way,
            "distinct_source_node_ids": len(identities.node_ids),
            "stores_osm_versions": False,
        },
        "overture": {
            "release": overture.manifest["release"],
            "extract_manifest_sha256": overture.manifest["content_sha256"],
            "region_bounds": list(overture.region_bounds),
            "segments": len(overture.segments),
            "connectors": len(overture.connector_ids),
        },
        "snapshots": _snapshots(identities, overture),
        "version_evidence": (
            evidence.describe()
            if evidence is not None
            else {"method": "none — PathAble stores no OSM versions"}
        ),
        "source_rows": _source_row_summary(parsed, overture),
        "ways": _way_summary(ways, identities, evidence, parsed),
        "edges": _edge_summary(ways, identities),
        "segments": _segment_summary(overture, parsed, pathable_way_ids),
        "connectors": _connector_summary(overture, identities, evidence),
        "bridge_verification": _bridge_summary(overture),
        "changelog": _changelog_summary(overture, parsed, pathable_way_ids),
    }
    report["content_sha256"] = content_sha256(report)
    if run is not None:
        report["run"] = run
    return report


def _snapshots(identities: PathAbleIdentities, overture: OvertureSide) -> dict[str, Any]:
    osm_versions = sorted(
        {
            row.resource_version
            for row in overture.segment_sources
            if row.dataset == OSM_DATASET and row.resource_version is not None
        }
    )
    pathable_date = _date(identities.facts.source_timestamp)
    overture_date = _date(osm_versions[0]) if len(osm_versions) == 1 else None
    return {
        "pathable_source_timestamp": identities.facts.source_timestamp,
        "overture_osm_resource_versions": osm_versions,
        "overture_osm_resource_version_meaning": (
            "Overture's `version` field on OSM sources: the planet snapshot it read, "
            "not an element version"
        ),
        "days_between_snapshots": (
            (overture_date - pathable_date).days
            if pathable_date is not None and overture_date is not None
            else None
        ),
    }


def _source_row_summary(parsed: ParsedSources, overture: OvertureSide) -> dict[str, Any]:
    return {
        "segment_source_rows": len(overture.segment_sources),
        "by_kind": _sorted_counts(parsed.kinds),
        "by_dataset_and_kind": {
            f"{dataset}/{kind}": count
            for (dataset, kind), count in sorted(parsed.kinds_by_dataset.items())
        },
        "property_only_paths": _sorted_counts(parsed.property_paths),
        "rows_with_null_confidence": parsed.null_confidence,
        "rows_with_null_update_time_by_kind": _sorted_counts(parsed.null_update_time_by_kind),
        "malformed_examples": [
            _row_dict(row) for row in _pick(parsed.malformed, lambda row: repr(_row_dict(row)))
        ],
        "unknowns_policy": (
            "Null confidence, update_time and between are reported as null. A null `between` "
            "is Overture's convention for 'the whole feature' and is kept distinct from [0, 1]."
        ),
    }


def _way_summary(
    ways: Sequence[WayResult],
    identities: PathAbleIdentities,
    evidence: VersionEvidence | None,
    parsed: ParsedSources,
) -> dict[str, Any]:
    linked = [way for way in ways if way.match is WayMatch.LINKED]
    unmatched = [way for way in ways if way.match is WayMatch.NOT_IN_OVERTURE]
    by_cardinality_and_version = Counter(
        f"{way.cardinality}/{way.version}" for way in linked if way.cardinality and way.version
    )
    split_sizes = Counter(len(way.segments) for way in linked)
    segment_way_counts = Counter(
        len(ways_in) for ways_in in _ways_per_segment(parsed.links).values()
    )

    summary: dict[str, Any] = {
        "pathable_ways": len(ways),
        "by_match": _sorted_counts(Counter(way.match.value for way in ways)),
        "id_level_matches": len(linked),
        "by_cardinality": _sorted_counts(Counter(str(way.cardinality) for way in linked)),
        "by_version_status": _sorted_counts(Counter(str(way.version) for way in linked)),
        "by_cardinality_and_version_status": _sorted_counts(by_cardinality_and_version),
        "ways_with_partial_segment_ranges": sum(1 for way in linked if way.partial_ranges),
        "segments_per_linked_way": {str(k): v for k, v in sorted(split_sizes.items())},
        "osm_ways_per_linked_segment": {str(k): v for k, v in sorted(segment_way_counts.items())},
        "unmatched_by_pathable_highway": _sorted_counts(
            Counter(identities.way_highway.get(way.raw_id, "unknown") for way in unmatched)
        ),
        "linked_by_pathable_highway": _sorted_counts(
            Counter(identities.way_highway.get(way.raw_id, "unknown") for way in linked)
        ),
        "examples": _way_examples(ways, parsed),
    }
    if evidence is not None:
        summary["update_time_semantics"] = _update_time_semantics(linked, parsed, evidence)
        summary["version_gap_when_pathable_older"] = _sorted_counts(
            Counter(
                str(way.overture_versions[0] - way.pathable_version)
                for way in linked
                if way.version is VersionStatus.PATHABLE_OLDER and way.pathable_version is not None
            ),
            numeric=True,
        )
    return summary


def _update_time_semantics(
    linked: Sequence[WayResult], parsed: ParsedSources, evidence: VersionEvidence
) -> dict[str, Any]:
    """What Overture's ``update_time`` on an OSM way actually is, tested on same-version ways.

    If it were the way's own edit time, same (id, version) would always mean the
    same time. It is not: it matches the latest edit across the way and its
    nodes. Measured here rather than assumed, because the version-status
    categories above depend on it.
    """
    overture_time: dict[int, set[str | None]] = defaultdict(set)
    for link in parsed.links:
        overture_time[link.way.element_id].add(link.update_time)
    counts = Counter[str]()
    for way in linked:
        way_id = parse_pathable_osm_id(way.raw_id)
        state = evidence.ways.get(way_id) if way_id is not None else None
        # Only an unambiguous same-version pair can test the semantics.
        if way_id is None or state is None or way.overture_versions != (state.version,):
            continue
        times = overture_time[way_id]
        latest = state.latest_member_timestamp
        overture = next(iter(times)) if len(times) == 1 else None
        if overture is None or latest is None or state.timestamp is None:
            counts["unverifiable"] += 1
            continue
        if overture == state.timestamp == latest:
            counts["equals_way_edit_time"] += 1
        elif overture == latest:
            counts["equals_latest_node_edit_time"] += 1
        elif overture == state.timestamp:
            counts["equals_way_edit_time_despite_later_node_edit"] += 1
        elif overture > latest:
            counts["later_than_every_edit_in_pathable_snapshot"] += 1
        else:
            counts["earlier_than_pathable_snapshot_edits"] += 1
    return {
        "same_version_ways": sum(counts.values()),
        "by_relation": _sorted_counts(counts),
        "meaning": (
            "Overture's update_time on an OSM way equals the latest edit across the way and "
            "its nodes. A node edit moves a way without changing the way's version, so a "
            "same-version match is only 'exact' when these times agree."
        ),
    }


def _edge_summary(ways: Sequence[WayResult], identities: PathAbleIdentities) -> dict[str, Any]:
    counts = Counter[str]()
    for way in ways:
        edges = identities.way_edges[way.raw_id]
        if way.match is WayMatch.NOT_AN_OSM_ID:
            counts[EdgeOutcome.NOT_AN_OSM_ID] += edges
        elif way.match is WayMatch.NOT_IN_OVERTURE:
            counts[EdgeOutcome.WAY_NOT_IN_OVERTURE] += edges
        elif len(way.segments) == 1:
            counts[EdgeOutcome.SINGLE_SEGMENT] += edges
        else:
            counts[EdgeOutcome.SPLIT_WAY] += edges
    if identities.edges_without_way:
        counts[EdgeOutcome.NO_WAY_ID] += identities.edges_without_way
    return {
        "pathable_segments": sum(identities.way_edges.values()) + identities.edges_without_way,
        "by_outcome": _sorted_counts(counts),
        "meaning": (
            f"'{EdgeOutcome.SINGLE_SEGMENT}' means the edge's OSM way id appears in exactly one "
            "GERS segment — at identifier level, and at Overture's version of the way. "
            f"'{EdgeOutcome.SPLIT_WAY}' needs the edge's position along the way to pick a "
            "segment, which PathAble does not store."
        ),
    }


def _segment_summary(
    overture: OvertureSide, parsed: ParsedSources, pathable_way_ids: set[int]
) -> dict[str, Any]:
    ways_in = _ways_per_segment(parsed.links)
    outcomes: dict[str, SegmentOutcome] = {}
    for gers_id in sorted(overture.segments):
        ways = ways_in.get(gers_id, set())
        if not ways:
            outcomes[gers_id] = SegmentOutcome.UNRESOLVED
            continue
        present = len(ways & pathable_way_ids)
        if present == len(ways):
            outcomes[gers_id] = SegmentOutcome.ALL_WAYS_IN_PATHABLE
        elif present:
            outcomes[gers_id] = SegmentOutcome.SOME_WAYS_IN_PATHABLE
        else:
            outcomes[gers_id] = SegmentOutcome.NO_WAYS_IN_PATHABLE

    bounds = overture.region_bounds
    unlinked = [g for g, o in outcomes.items() if o is SegmentOutcome.NO_WAYS_IN_PATHABLE]
    unresolved = [g for g, o in outcomes.items() if o is SegmentOutcome.UNRESOLVED]
    return {
        "segments": len(outcomes),
        "by_outcome": _sorted_counts(Counter(outcome.value for outcome in outcomes.values())),
        "not_in_pathable_by_overture_class": _sorted_counts(
            Counter(_class_label(overture.segments[g]) for g in unlinked)
        ),
        "not_in_pathable_by_extent": _sorted_counts(
            Counter(_extent_label(overture.segments[g].bbox, bounds) for g in unlinked)
        ),
        "unresolved_by_source_datasets": _sorted_counts(
            Counter(
                "+".join(sorted(parsed.datasets_by_segment.get(g, {"no sources"})))
                for g in unresolved
            )
        ),
        "examples": {
            outcome.value: sorted(_pick([g for g, o in outcomes.items() if o is outcome], str))
            for outcome in SegmentOutcome
        },
    }


def _connector_summary(
    overture: OvertureSide, identities: PathAbleIdentities, evidence: VersionEvidence | None
) -> dict[str, Any]:
    pathable_nodes = {
        node_id
        for node_id in (parse_pathable_osm_id(raw) for raw in identities.node_ids)
        if node_id is not None
    }
    kinds = Counter[str]()
    versions = Counter[str]()
    node_refs: dict[int, set[int]] = defaultdict(set)
    node_times: dict[int, set[str | None]] = defaultdict(set)
    versionless_nodes: set[int] = set()
    malformed: list[SourceRow] = []
    for row in overture.connector_sources:
        if row.dataset != OSM_DATASET:
            kinds[RowKind.NON_OSM] += 1
            continue
        reference = parse_osm_record_id(row.record_id)
        if isinstance(reference, MalformedRecordId):
            kinds[f"{RowKind.MALFORMED_RECORD_ID}:{reference.reason}"] += 1
            malformed.append(row)
            if reference.element_type is OsmElementType.NODE and reference.element_id:
                versionless_nodes.add(reference.element_id)
            continue
        if reference.element_type is not OsmElementType.NODE:
            kinds[RowKind.OSM_OTHER_ELEMENT] += 1
            continue
        kinds[RowKind.OSM_NODE] += 1
        node_refs[reference.element_id].add(reference.version)
        node_times[reference.element_id].add(row.update_time)

    matched = sorted(node_id for node_id in node_refs if node_id in pathable_nodes)
    for node_id in matched:
        overture_versions = sorted(node_refs[node_id])
        state = evidence.nodes.get(node_id) if evidence is not None else None
        status = _version_status(overture_versions, node_times[node_id], evidence, state)
        versions[status.value] += 1
    connectors_with_sources = {row.gers_id for row in overture.connector_sources}
    return {
        "connectors": len(overture.connector_ids),
        "connectors_without_sources": len(overture.connector_ids - connectors_with_sources),
        "source_rows_by_kind": _sorted_counts(kinds),
        "distinct_osm_nodes_cited": len(node_refs),
        "osm_nodes_in_pathable": len(matched),
        "osm_nodes_not_in_pathable": len(node_refs) - len(matched),
        "version_zero_nodes_in_pathable": len(versionless_nodes & pathable_nodes),
        "pathable_nodes_that_are_connectors": len(matched),
        "pathable_nodes_not_connectors": len(pathable_nodes) - len(matched),
        "by_version_status": _sorted_counts(versions),
        "malformed_examples": [
            _row_dict(row) for row in _pick(malformed, lambda row: repr(_row_dict(row)))
        ],
        "meaning": (
            "Overture creates connectors only where segments meet or end; PathAble keeps "
            "every OSM node. A PathAble node that is not a connector is a shape point in "
            "Overture, not a missing match."
        ),
    }


def _bridge_summary(overture: OvertureSide) -> dict[str, Any]:
    if overture.bridge_sample is None:
        return {"performed": False}
    artifact = overture.manifest["artifacts"]["bridge_sample"]
    by_key: dict[tuple[Any, ...], set[str | None]] = defaultdict(set)
    for row in overture.segment_sources:
        by_key[_bridge_key(row)].add(row.property)
    matched = 0
    property_only = 0
    unmatched: list[SourceRow] = []
    for row in overture.bridge_sample:
        properties = by_key.get(_bridge_key(row))
        if properties is None:
            unmatched.append(row)
            continue
        matched += 1
        if "" not in properties:
            property_only += 1
    return {
        "performed": True,
        "bridge_files_read": artifact["files_opened"],
        "bridge_files_available": artifact["files_available"],
        "rows_for_extracted_segments": len(overture.bridge_sample),
        "rows_matching_a_segment_source": matched,
        "rows_matching_only_a_property_source": property_only,
        "rows_without_a_matching_segment_source": len(unmatched),
        "rows_with_dataset_between": sum(
            1 for row in overture.bridge_sample if row.dataset_between is not None
        ),
        "record_types": _sorted_counts(
            Counter((row.record_id or "null")[:1] for row in overture.bridge_sample)
        ),
        "unmatched_examples": [
            _row_dict(row) for row in _pick(unmatched, lambda row: repr(_row_dict(row)))
        ],
        "meaning": (
            "A sample, not a census: bridge files are not spatially ordered, so a regional "
            "read of every file is a full scan. The bridge has no `property` column, so a "
            "relation that only contributed route names is indistinguishable there from a "
            "geometry source."
        ),
    }


def _bridge_key(row: SourceRow) -> tuple[Any, ...]:
    return (row.gers_id, row.record_id, row.between, row.update_time, row.resource_version)


def _changelog_summary(
    overture: OvertureSide, parsed: ParsedSources, pathable_way_ids: set[int]
) -> dict[str, Any]:
    if overture.changelog is None:
        return {"performed": False}
    linked_segments = {
        gers for gers, ways in _ways_per_segment(parsed.links).items() if ways & pathable_way_ids
    }
    by_type = Counter(f"{row.feature_type}/{row.change_type}" for row in overture.changelog)
    columns = Counter(
        column
        for row in overture.changelog
        if row.feature_type == "segment" and row.change_type == "data_changed"
        for column in row.columns_changed
    )
    linked_changes = Counter(
        row.change_type
        for row in overture.changelog
        if row.feature_type == "segment" and row.gers_id in linked_segments
    )
    return {
        "performed": True,
        "by_type_and_change": _sorted_counts(by_type),
        "segment_columns_changed": _sorted_counts(columns),
        "segments_linked_to_pathable_by_change": _sorted_counts(linked_changes),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ways_per_segment(links: Iterable[WayLink]) -> dict[str, set[int]]:
    ways: dict[str, set[int]] = defaultdict(set)
    for link in links:
        ways[link.gers_id].add(link.way.element_id)
    return ways


def _way_examples(ways: Sequence[WayResult], parsed: ParsedSources) -> dict[str, list[Any]]:
    links_by_way: dict[int, list[WayLink]] = defaultdict(list)
    for link in parsed.links:
        links_by_way[link.way.element_id].append(link)

    def describe(way: WayResult) -> dict[str, Any]:
        way_id = parse_pathable_osm_id(way.raw_id)
        return {
            "pathable_source_way_id": way.raw_id,
            "pathable_version": way.pathable_version,
            "segments": [
                {
                    "gers_id": link.gers_id,
                    "record_id": str(link.way),
                    "segment_range": link.segment_range.as_list() if link.segment_range else None,
                }
                for link in sorted(links_by_way.get(way_id or -1, []))
            ],
        }

    groups: dict[str, list[WayResult]] = defaultdict(list)
    for way in ways:
        key = (
            f"{way.match}/{way.cardinality}/{way.version}"
            if way.match is WayMatch.LINKED
            else str(way.match)
        )
        groups[key].append(way)
    return {
        key: [describe(way) for way in _pick(group, lambda way: way.raw_id)]
        for key, group in sorted(groups.items())
    }


def _pick[T](items: Sequence[T], key: Callable[[T], str]) -> list[T]:
    """A few examples, chosen by hash of their identifier rather than by anyone's eye."""
    return sorted(items, key=lambda item: hashlib.sha256(key(item).encode()).hexdigest())[
        :EXAMPLES_PER_CATEGORY
    ]


def _row_dict(row: SourceRow) -> dict[str, Any]:
    return {
        "gers_id": row.gers_id,
        "dataset": row.dataset,
        "record_id": row.record_id,
        "property": row.property,
        "between": list(row.between) if row.between is not None else None,
        "update_time": row.update_time,
        "version": row.resource_version,
    }


def _class_label(segment: SegmentFeature) -> str:
    label = f"{segment.subtype}/{segment.feature_class}"
    return f"{label}/{segment.subclass}" if segment.subclass else label


def _extent_label(
    bbox: tuple[float, float, float, float], bounds: tuple[float, float, float, float]
) -> str:
    min_lon, min_lat, max_lon, max_lat = bounds
    inside = bbox[0] >= min_lon and bbox[1] >= min_lat and bbox[2] <= max_lon and bbox[3] <= max_lat
    return "inside_region_bounds" if inside else "crosses_region_boundary"


def _sorted_counts(counter: Counter[Any], *, numeric: bool = False) -> dict[str, int]:
    items = [(str(key), int(value)) for key, value in counter.items()]
    if numeric:
        return dict(sorted(items, key=lambda item: int(item[0])))
    return dict(sorted(items, key=lambda item: (-item[1], item[0])))


def _date(value: str | None) -> dt.date | None:
    if value is None:
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None
