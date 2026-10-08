"""A research-only overlay of municipal surface assertions on the routing graph (PA-GEO-07).

PA-GEO-06 found City of Kitchener surface assertions where OpenStreetMap
records none. This module answers one narrow question with them: *if* those
assertions were someday admitted as routing evidence, which routing segments
would they describe, and what would the graph look like? It never admits them.

**The policy** (:data:`SHADOW_POLICY_VERSION`) fills a missing surface and
does nothing else:

- a segment OSM already describes keeps OSM's surface;
- a segment takes a City surface only from PA-GEO-06 rows classified
  ``source_only_kitchener`` — never from an agreement, a conflict, a template
  default or an ambiguous match, none of which reach those rows;
- the City's value is read through PathAble's own surface vocabulary; a value
  the cost model has no class for fills nothing;
- everything else stays unknown.

**Local scope.** PA-GEO-06 keeps each City assertion as the metres of an OSM
way the City record covers. PathAble's segments are the same ways cut at every
node — segment ``edge_key`` is the index of its first node in the way — so each
segment has an exact extent along its way in the same metres. A segment takes
a City surface only when City extents of one surface class cover
:data:`EDGE_COVERAGE_MIN` of it and no other class covers more than
:data:`OTHER_CLASS_MAX`. A short City record can therefore never make a long
way, or even a long segment, anything.

**The shadow graph** shares every unchanged segment with the loaded graph and
replaces only the filled ones, in a copy of the adjacency. The loaded graph,
the database and the routing service are never touched: nothing that serves a
route imports this module.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from pathable_api.geo.enums import SurfaceClass
from pathable_api.geo.features import EdgeFeatures, normalise_surface
from pathable_api.geo.kitchener.correspondence import CoordinateTransform
from pathable_api.geo.kitchener.osm_extract import StudyExtract
from pathable_api.geo.overture.evidence import file_sha256
from pathable_api.routing.graph import DirectedEdge, RoutableGraph

SHADOW_POLICY_VERSION = "surface-shadow-policy-v1"
#: A sensitivity analysis, never a policy: conflict extents take the City's side.
CONFLICT_SENSITIVITY = "conflict-city-side-sensitivity"

#: The PA-GEO-06 artifact and policy this overlay reads.
ACCEPTED_ARTIFACT = "kitchener-geo06-artifact-v1"
ACCEPTED_POLICY = "kitchener-geo06-reconciliation-v1"

#: Share of a segment City extents of one surface class must cover to fill it.
#: The slack is for the ends of City records, which PA-GEO-05 places to within
#: a metre or two, not for guessing: a segment half described stays unknown.
EDGE_COVERAGE_MIN = 0.9
#: Above this share, a second City surface class on the same segment is a
#: disagreement, and the segment stays unknown.
OTHER_CLASS_MAX = 0.1

ELIGIBLE = "source_only_kitchener"
CONFLICT = "conflict"


class ShadowError(RuntimeError):
    """The inputs are not the PA-GEO-06 artifact this study is bound to."""


class Skip(StrEnum):
    """Why a segment a City extent touches is not filled."""

    OSM_SURFACE_PRESENT = "osm_surface_present"
    BELOW_COVERAGE = "below_coverage"
    MIXED_CITY_SURFACES = "mixed_city_surfaces"
    #: The City value has no class in PathAble's surface vocabulary, so the
    #: cost model would treat it as unknown anyway.
    OUTSIDE_ROUTING_VOCABULARY = "outside_routing_vocabulary"


#: Why an assertion fills nothing, most decisive first.
_ASSERTION_REASONS = (
    Skip.OSM_SURFACE_PRESENT,
    Skip.OUTSIDE_ROUTING_VOCABULARY,
    Skip.MIXED_CITY_SURFACES,
    Skip.BELOW_COVERAGE,
)
#: An assertion whose extent no routing segment lies on: beyond the pilot box
#: the graph is clipped to, or on a way it leaves out.
NOT_IN_GRAPH = "no_routing_segment_on_its_extent"
FILLED = "filled"


# ---------------------------------------------------------------------------
# The evidence, from PA-GEO-06
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CitySurface:
    """One City surface assertion at its local extent, as PA-GEO-06 recorded it."""

    reconciliation_id: str
    record_id: int
    way_id: int
    from_m: float
    to_m: float
    raw_value: str
    #: The OSM-vocabulary value PA-GEO-06 normalized the City's value to.
    normalized_value: str | None
    #: PathAble's surface class for it; UNKNOWN when routing has none.
    surface_class: SurfaceClass
    relationship: str
    capture_source: str | None = None
    #: City SOURCE_DATE: when the record was captured, not an observation.
    source_capture_date: str | None = None
    inspection_year: int | None = None
    #: For a conflict: what OSM says on the same way.
    osm_value: str | None = None
    osm_class: SurfaceClass | None = None
    osm_observation_date: str | None = None
    osm_value_since: str | None = None
    lineage: str | None = None

    @property
    def freshness(self) -> str:
        """What dates the City's claim. The City supplies no observation date."""
        return "capture_dated_only" if self.source_capture_date else "undated_attribute_assertion"


def surface_class_of(value: str | None) -> SurfaceClass:
    """PathAble's class for an OSM-vocabulary surface value, exactly as routing reads one."""
    return normalise_surface(value)[1] if value else SurfaceClass.UNKNOWN


_EVIDENCE_QUERY = """
SELECT r.reconciliation_id, r.semantic_relationship, r.source_records[1], r.target_element,
    r.from_m, r.to_m, c.raw_value, c.normalized_value, c.capture_source,
    c.source_capture_date, c.inspection_year, o.raw_value, o.observation_date,
    o.osm_value_since, r.lineage_relationship
FROM read_parquet(?) r
LEFT JOIN read_parquet(?) c ON c.assertion_id = r.kitchener_assertions[1]
LEFT JOIN read_parquet(?) o ON o.assertion_id = r.osm_assertions[1]
WHERE r.topic = 'surface' AND r.semantic_relationship IN ('source_only_kitchener', 'conflict')
ORDER BY r.reconciliation_id
"""
_COUNT_QUERY = """
SELECT semantic_relationship, count(*) FROM read_parquet(?) WHERE topic = 'surface'
GROUP BY 1 ORDER BY 1
"""


@dataclass(slots=True)
class SurfaceEvidence:
    eligible: list[CitySurface]
    conflicts: list[CitySurface]
    #: Every PA-GEO-06 surface row by relationship: what the policy may and may not use.
    relationships: dict[str, int]
    identity: dict[str, Any]


def load_surface_evidence(artifact_dir: Path, committed_evidence: Path) -> SurfaceEvidence:
    """PA-GEO-06's surface rows, refused unless they are the committed evidence's artifact."""
    manifest_path = artifact_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    versions = manifest.get("versions", {})
    if (
        manifest.get("artifact_version") != ACCEPTED_ARTIFACT
        or versions.get("reconciliation_policy") != ACCEPTED_POLICY
    ):
        msg = f"the artifact is not {ACCEPTED_ARTIFACT} under {ACCEPTED_POLICY}."
        raise ShadowError(msg)
    committed = json.loads(committed_evidence.read_text("utf-8"))
    for name, entry in sorted(manifest["files"].items()):
        path = artifact_dir / entry["file"]
        if not path.is_file() or file_sha256(path) != entry["sha256"]:
            msg = f"PA-GEO-06's {name} table does not match its manifest."
            raise ShadowError(msg)
        if committed["artifact"]["files"].get(name, {}).get("sha256") != entry["sha256"]:
            msg = f"PA-GEO-06's {name} table is not the one its committed evidence describes."
            raise ShadowError(msg)
    reconciliations = (artifact_dir / "reconciliations.parquet").as_posix()
    assertions = (artifact_dir / "assertions.parquet").as_posix()
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("SET autoinstall_known_extensions = false")
        connection.execute("SET autoload_known_extensions = false")
        rows = connection.execute(
            _EVIDENCE_QUERY, [reconciliations, assertions, assertions]
        ).fetchall()
        counts = dict(connection.execute(_COUNT_QUERY, [reconciliations]).fetchall())
    finally:
        connection.close()
    eligible: list[CitySurface] = []
    conflicts: list[CitySurface] = []
    for (
        reconciliation_id,
        relationship,
        record_id,
        element,
        from_m,
        to_m,
        raw,
        normalized,
        capture_source,
        capture_date,
        inspection_year,
        osm_raw,
        osm_observed,
        osm_since,
        lineage,
    ) in rows:
        item = CitySurface(
            reconciliation_id=str(reconciliation_id),
            record_id=int(record_id),
            way_id=int(str(element).split("/")[1]),
            from_m=float(from_m),
            to_m=float(to_m),
            raw_value=str(raw),
            normalized_value=normalized,
            surface_class=surface_class_of(normalized),
            relationship=str(relationship),
            capture_source=capture_source,
            source_capture_date=capture_date,
            inspection_year=None if inspection_year is None else int(inspection_year),
            osm_value=osm_raw,
            osm_class=surface_class_of(str(osm_raw).strip().lower()) if osm_raw else None,
            osm_observation_date=osm_observed,
            osm_value_since=osm_since,
            lineage=lineage,
        )
        (eligible if relationship == ELIGIBLE else conflicts).append(item)
    if len(eligible) != committed["outcomes"]["surface"]["semantic_relationship"].get(ELIGIBLE):
        msg = "the City-only surface rows do not match the committed PA-GEO-06 count."
        raise ShadowError(msg)
    identity = {
        "artifact_manifest_sha256": file_sha256(manifest_path),
        "artifact_content_sha256": manifest.get("content_sha256"),
        "committed_evidence_content_sha256": committed.get("content_sha256"),
        "artifact_version": manifest["artifact_version"],
        "reconciliation_policy": versions.get("reconciliation_policy"),
        "files": {k: v["sha256"] for k, v in sorted(manifest["files"].items())},
    }
    return SurfaceEvidence(eligible, conflicts, dict(sorted(counts.items())), identity)


# ---------------------------------------------------------------------------
# Where each routing segment lies along its OSM way
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WaySegment:
    """One routing segment's extent along its OSM way, in the way's own metres."""

    identity: str
    way_id: int
    start_m: float
    end_m: float

    @property
    def length_m(self) -> float:
        return self.end_m - self.start_m


def way_vertex_positions(
    extract: StudyExtract, transformer: CoordinateTransform
) -> dict[int, np.ndarray[Any, Any]]:
    """For every way, the distance of each of its nodes from its first, in native metres.

    The same line PA-GEO-05 measured its extents along: every ref, in order.
    """
    positions: dict[int, np.ndarray[Any, Any]] = {}
    for way_id, way in extract.ways.items():
        xs, ys = transformer.transform(
            [extract.nodes[ref].lon for ref in way.refs],
            [extract.nodes[ref].lat for ref in way.refs],
        )
        steps = np.hypot(np.diff(np.asarray(xs, dtype=float)), np.diff(np.asarray(ys, dtype=float)))
        positions[way_id] = np.concatenate(([0.0], np.cumsum(steps)))
    return positions


@dataclass(frozen=True, slots=True)
class SegmentSource:
    """What the dataset records about one routing segment's origin."""

    source_u: str
    source_v: str
    edge_key: int
    source_way_id: str | None

    @property
    def identity(self) -> str:
        return f"{self.source_u}->{self.source_v}#{self.edge_key}"


def locate_segments(
    sources: Iterable[SegmentSource],
    extract: StudyExtract,
    positions: Mapping[int, np.ndarray[Any, Any]],
) -> tuple[dict[int, list[WaySegment]], Counter[str]]:
    """Every segment's extent along its way, checked against the way's own node order."""
    by_way: dict[int, list[WaySegment]] = defaultdict(list)
    problems: Counter[str] = Counter()
    for source in sources:
        way_id = source.source_way_id
        if way_id is None or not way_id.isdigit():
            problems["no_source_way"] += 1
            continue
        way = extract.ways.get(int(way_id))
        if way is None:
            problems["way_not_in_extract"] += 1
            continue
        key = source.edge_key
        refs = way.refs
        if (
            key + 1 >= len(refs)
            or str(refs[key]) != source.source_u
            or str(refs[key + 1]) != source.source_v
        ):
            problems["nodes_do_not_match_the_way"] += 1
            continue
        cumulative = positions[int(way_id)]
        by_way[int(way_id)].append(
            WaySegment(
                source.identity, int(way_id), float(cumulative[key]), float(cumulative[key + 1])
            )
        )
    for segments in by_way.values():
        segments.sort(key=lambda s: (s.start_m, s.identity))
    return dict(by_way), problems


# ---------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Fill:
    """A segment the overlay describes, and the City assertions it rests on."""

    identity: str
    way_id: int
    start_m: float
    end_m: float
    surface: str
    surface_class: SurfaceClass
    coverage: float
    records: tuple[int, ...]
    reconciliations: tuple[str, ...]
    #: For the conflict sensitivity: the OSM class the City's replaces.
    replaces: SurfaceClass | None = None


@dataclass(slots=True)
class OverlayPlan:
    policy: str
    fills: dict[str, Fill] = field(default_factory=dict)
    #: Every segment a City extent touches, with its best single-class coverage.
    touched: dict[str, float] = field(default_factory=dict)
    skipped: Counter[str] = field(default_factory=Counter)
    #: Per assertion: ``filled`` or why it fills nothing.
    assertion_outcomes: dict[str, str] = field(default_factory=dict)

    @property
    def digest(self) -> str:
        """The overlay's identity: which segments, with which surface, from which rows."""
        lines = [
            json.dumps(
                [f.identity, f.surface, str(f.surface_class), list(f.reconciliations)],
                separators=(",", ":"),
            )
            for f in sorted(self.fills.values(), key=lambda f: f.identity)
        ]
        payload = "\n".join([self.policy, *lines]).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def _merged_length(intervals: Sequence[tuple[float, float]]) -> float:
    total = 0.0
    end = -float("inf")
    for lo, hi in sorted(intervals):
        if hi <= end:
            continue
        total += hi - max(lo, end)
        end = hi
    return total


def plan_overlay(
    surfaces: Sequence[CitySurface],
    segments_by_way: Mapping[int, Sequence[WaySegment]],
    features: Mapping[str, EdgeFeatures],
    *,
    policy: str = SHADOW_POLICY_VERSION,
) -> OverlayPlan:
    """Which segments the City's assertions would describe, under ``policy``.

    Under the shadow policy only a segment with no OSM surface is filled. Under
    the conflict sensitivity, only a segment with one is — and the City's value
    replaces OSM's there, to measure what that choice would do.
    """
    plan = OverlayPlan(policy)
    by_way: dict[int, list[CitySurface]] = defaultdict(list)
    for item in surfaces:
        by_way[item.way_id].append(item)
    reasons: dict[str, set[str]] = defaultdict(set)
    for way_id in sorted(by_way):
        items = by_way[way_id]
        for segment in segments_by_way.get(way_id, ()):
            length = segment.length_m
            if length <= 0:
                continue
            overlaps: dict[SurfaceClass, list[tuple[float, float]]] = defaultdict(list)
            contributors: dict[SurfaceClass, list[CitySurface]] = defaultdict(list)
            for item in items:
                lo = max(segment.start_m, min(item.from_m, item.to_m))
                hi = min(segment.end_m, max(item.from_m, item.to_m))
                if hi > lo:
                    overlaps[item.surface_class].append((lo, hi))
                    contributors[item.surface_class].append(item)
            if not overlaps:
                continue
            coverage = {cls: _merged_length(v) / length for cls, v in overlaps.items()}
            best = max(coverage, key=lambda cls: (coverage[cls], str(cls)))
            plan.touched[segment.identity] = round(coverage[best], 4)
            touching = [i.reconciliation_id for items_ in contributors.values() for i in items_]
            osm = features.get(segment.identity)
            has_osm = osm is not None and (
                osm.surface_class is not SurfaceClass.UNKNOWN or osm.surface is not None
            )
            reason: Skip | None = None
            if policy == SHADOW_POLICY_VERSION and has_osm:
                reason = Skip.OSM_SURFACE_PRESENT
            elif policy == CONFLICT_SENSITIVITY and not has_osm:
                continue
            elif any(c > OTHER_CLASS_MAX for cls, c in coverage.items() if cls is not best):
                # The City's records disagree about this segment.
                reason = Skip.MIXED_CITY_SURFACES
            elif coverage[best] < EDGE_COVERAGE_MIN:
                reason = Skip.BELOW_COVERAGE
            elif best is SurfaceClass.UNKNOWN:
                reason = Skip.OUTSIDE_ROUTING_VOCABULARY
            if reason is not None:
                plan.skipped[str(reason)] += 1
                for name in touching:
                    reasons[name].add(str(reason))
                continue
            chosen = contributors[best]
            values: dict[str, float] = defaultdict(float)
            for item in chosen:
                lo = max(segment.start_m, min(item.from_m, item.to_m))
                hi = min(segment.end_m, max(item.from_m, item.to_m))
                values[str(item.normalized_value)] += round(hi - lo, 6)
            surface = min(values, key=lambda v: (-values[v], v))
            plan.fills[segment.identity] = Fill(
                identity=segment.identity,
                way_id=way_id,
                start_m=segment.start_m,
                end_m=segment.end_m,
                surface=surface,
                surface_class=best,
                coverage=round(coverage[best], 4),
                records=tuple(sorted({i.record_id for i in chosen})),
                reconciliations=tuple(sorted({i.reconciliation_id for i in chosen})),
                replaces=osm.surface_class if osm is not None and has_osm else None,
            )
            for name in touching:
                reasons[name].add(FILLED)
    for item in surfaces:
        found = reasons.get(item.reconciliation_id)
        if not found:
            plan.assertion_outcomes[item.reconciliation_id] = NOT_IN_GRAPH
        elif FILLED in found:
            plan.assertion_outcomes[item.reconciliation_id] = FILLED
        else:
            plan.assertion_outcomes[item.reconciliation_id] = next(
                str(r) for r in _ASSERTION_REASONS if str(r) in found
            )
    return plan


# ---------------------------------------------------------------------------
# The shadow graph
# ---------------------------------------------------------------------------


def shadow_graph(baseline: RoutableGraph, plan: OverlayPlan) -> RoutableGraph:
    """A second graph: the baseline with only the planned segments' surfaces replaced."""
    by_identity = {e.identity: e for e in baseline.segments}
    replacements = {
        identity: replace(
            by_identity[identity].features, surface=fill.surface, surface_class=fill.surface_class
        )
        for identity, fill in plan.fills.items()
        if identity in by_identity
    }
    return substitute_features(baseline, replacements, policy=plan.policy, digest=plan.digest)


def substitute_features(
    baseline: RoutableGraph,
    replacements: Mapping[str, EdgeFeatures],
    *,
    policy: str,
    digest: str,
) -> RoutableGraph:
    """A second graph: the baseline with only the named segments' features replaced.

    The baseline object is not changed. Unchanged segments are shared — they
    are immutable — and the adjacency is copied, so each replaced directed
    entry is written into the copy only, and only where it is the segment's own.
    PA-GEO-07 replaces surfaces this way and PA-GEO-09 kerbs; the mechanism is
    the same and lives once.
    """
    graph = baseline.graph.copy()
    segments = []
    for edge in baseline.segments:
        features = replacements.get(edge.identity)
        if features is None:
            segments.append(edge)
            continue
        changed = replace(edge, features=features)
        for source, target, directed in (
            (edge.source_u, edge.source_v, DirectedEdge(changed, features, reversed=False)),
            (edge.source_v, edge.source_u, DirectedEdge(changed, features.reversed(), True)),
        ):
            data = graph.get_edge_data(source, target, key=edge.edge_key)
            if data is not None and data["edge"].edge is edge:
                data["edge"] = directed
        segments.append(changed)
    return RoutableGraph(
        dataset_id=uuid.uuid5(baseline.dataset_id, digest),
        region_slug=f"{baseline.region_slug}:{policy}",
        checksum=f"{policy}:{digest}",
        graph=graph,
        node_positions=baseline.node_positions,
        segment_count=baseline.segment_count,
        _segments=segments,
    )
