"""Deterministic conflation of Kitchener pedestrian records with the frozen OSM extract.

PA-GEO-05 asks whether PathAble can say, automatically, which OpenStreetMap
elements represent the same physical facility as a City of Kitchener record —
and say "I cannot tell" when it cannot. This module is the engine:

- **eligibility** — which City records are matched at all (:func:`load_population`);
- **the candidate contract** — every ``highway`` way within
  :data:`WAY_RADIUS_M` and every kerb or crossing node within
  :data:`NODE_RADIUS_M`, versioned as :data:`CANDIDATE_CONTRACT_VERSION`;
- **per-sample geometry** — the record sampled every metre, and for each sample
  its distance to each candidate way, its position along it and the angle
  between the two there;
- **baselines** — the single nearest way by one signal, always matched;
- **the matcher** — interpretable rules over those samples, with named
  thresholds (:class:`MatcherPolicy`), that return ``matched``, ``ambiguous``
  or ``unmatched``.

A match relates a City record to OSM *elements with a local scope*: the metres
of a way the record covers, or a node. A two-metre curb-cut piece that lies
along a 400-metre sidewalk corresponds to two metres of it and to the kerb
node there — never to the whole sidewalk.

Nothing here reads or writes PathAble's routing database, and nothing in
routing reads this. Scores are decision signals, not probabilities.

All geometry is in the City's NAD83 / UTM 17N metres.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import shapely
from shapely.geometry import LineString, box
from shapely.geometry.base import BaseGeometry

from pathable_api.geo.kitchener.correspondence import (
    CoordinateTransform,
    KitchenerFeature,
    KitchenerIndex,
    OsmIndex,
    class_compatibility,
    kitchener_family,
    nearest_road,
    osm_class,
    parts,
    to_native,
)
from pathable_api.geo.kitchener.normalize import load_normalized
from pathable_api.geo.kitchener.osm_extract import load_study_extract
from pathable_api.geo.kitchener.semantics import SourceClass

CANDIDATE_CONTRACT_VERSION = "kitchener-geo05-candidates-v1"
MATCHER_VERSION = "kitchener-geo05-matcher-v1"

#: The candidate contract: every ``highway`` way this near a record, and every
#: kerb or crossing node this near it. Recall first: a matcher cannot recover
#: an element the contract discarded.
WAY_RADIUS_M = 25.0
NODE_RADIUS_M = 10.0
SAMPLE_SPACING_M = 1.0
#: Records must lie this far inside the study box, so that a counterpart way
#: just outside it — absent from the frozen extract — cannot pose as "none".
EDGE_MARGIN_M = 50.0

#: The City records the matcher works on: active, physical pedestrian ways and
#: crossings. Virtual links and unofficial connections are topology, not
#: facilities; cycling facilities and maintenance access are out of scope.
ELIGIBLE_PHYSICAL_CLASS = "physical_active"
ELIGIBLE_ROLES = ("pedestrian_way", "pedestrian_crossing")
STRUCTURES = frozenset({"STAIRS", "BRIDGE", "OVERPASS", "UNDERPASS", "BOARDWALK"})
#: OSM way classes a pedestrian facility can be drawn as.
PEDESTRIAN_CLASSES = frozenset({"sidewalk", "path", "crossing", "steps"})
#: A City record shorter than this is a piece at a junction, not a length of facility.
SHORT_PIECE_M = 5.0

_POPULATION_QUERY = """
SELECT activetransportid, network_role, physical_class, category, subcategory, feature_type,
    structure, curbcut, state_curbcut, surface_material, state_surface_material, railing,
    state_railing, surface_condition, state_surface_condition, street, source_class,
    strftime(source_date, '%Y-%m-%d'), last_inspection_year, length_m, part_count,
    origin_curbcut, origin_surface_material, origin_feature_type, origin_railing,
    origin_surface_condition, geometry_native
FROM read_parquet(?) WHERE activetransportid IS NOT NULL AND geometry_native IS NOT NULL
ORDER BY activetransportid
"""


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Record:
    """One City record the matcher works on."""

    activetransportid: int
    network_role: str
    family: str
    subcategory: str | None
    structure: str | None
    curb_cut: bool
    surface_material: str | None
    length_m: float
    street: str | None
    geometry: BaseGeometry
    #: The raw attribute view the evidence table and the attribute comparison read.
    attributes: Mapping[str, Any] = field(default_factory=dict)

    @property
    def classes(self) -> tuple[str, ...]:
        """The evidence classes the record belongs to; ``plain`` when none."""
        found = []
        if self.curb_cut:
            found.append("curb_cut")
        if self.structure is not None:
            found.append("structure")
        if self.surface_material is not None:
            found.append("surface")
        return tuple(found) or ("plain",)


@dataclass(slots=True)
class Population:
    records: list[Record]
    excluded: dict[str, int]
    #: Every physical City record with a geometry, for "what else lies along this way".
    physical: KitchenerIndex


def study_area(
    bounds: tuple[float, float, float, float], transformer: CoordinateTransform
) -> BaseGeometry:
    """The study box in native metres, shrunk by :data:`EDGE_MARGIN_M`."""
    west, south, east, north = bounds
    ring = box(west, south, east, north).exterior.coords
    xs, ys = transformer.transform([x for x, _ in ring], [y for _, y in ring])
    return shapely.Polygon(list(zip(xs, ys, strict=True))).buffer(-EDGE_MARGIN_M)


def load_population(parquet: Path, area: BaseGeometry) -> Population:
    """Every eligible City record inside the shrunk study area, in id order."""
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("SET autoinstall_known_extensions = false")
        connection.execute("SET autoload_known_extensions = false")
        rows = connection.execute(_POPULATION_QUERY, [parquet.as_posix()]).fetchall()
    finally:
        connection.close()
    geometries = shapely.from_wkb([bytes(row[-1]) for row in rows])
    excluded: Counter[str] = Counter()
    records: list[Record] = []
    physical: list[KitchenerFeature] = []
    for row, geometry in zip(rows, geometries, strict=True):
        (
            record_id,
            role,
            physical_class,
            category,
            subcategory,
            feature_type,
            structure,
            curbcut,
            state_curbcut,
            material,
            state_material,
            railing,
            state_railing,
            condition,
            state_condition,
            street,
            source_class,
            source_date,
            inspection_year,
            length_m,
            part_count,
            origin_curbcut,
            origin_material,
            origin_feature_type,
            origin_railing,
            origin_condition,
            _wkb,
        ) = row
        if physical_class != "virtual_link" and not geometry.is_empty:
            physical.append(
                KitchenerFeature(int(record_id), physical_class, role, subcategory, geometry)
            )
        if physical_class != ELIGIBLE_PHYSICAL_CLASS or role not in ELIGIBLE_ROLES:
            excluded["not_a_physical_pedestrian_way_or_crossing"] += 1
            continue
        if source_class == str(SourceClass.STREET_LEVEL_IMAGERY):
            excluded["sourced_from_street_level_imagery"] += 1
            continue
        if geometry.is_empty or not parts(geometry):
            excluded["no_line_geometry"] += 1
            continue
        if not area.covers(geometry):
            excluded["outside_the_shrunk_study_area"] += 1
            continue
        records.append(
            Record(
                activetransportid=int(record_id),
                network_role=str(role),
                family=kitchener_family(subcategory, feature_type, role),
                subcategory=subcategory,
                structure=structure if structure in STRUCTURES else None,
                curb_cut=curbcut == "Y" and state_curbcut == "non_default",
                surface_material=material if state_material == "non_default" else None,
                length_m=float(length_m) if length_m is not None else float(geometry.length),
                street=street,
                geometry=geometry,
                attributes={
                    "category": category,
                    "subcategory": subcategory,
                    "feature_type": feature_type,
                    "structure": structure,
                    "curbcut": curbcut,
                    "state_curbcut": state_curbcut,
                    "origin_curbcut": origin_curbcut,
                    "surface_material": material,
                    "state_surface_material": state_material,
                    "origin_surface_material": origin_material,
                    "origin_feature_type": origin_feature_type,
                    "railing": railing,
                    "state_railing": state_railing,
                    "origin_railing": origin_railing,
                    "surface_condition": condition,
                    "state_surface_condition": state_condition,
                    "origin_surface_condition": origin_condition,
                    "source_class": source_class,
                    "source_date": source_date,
                    "last_inspection_year": inspection_year,
                    "part_count": part_count,
                },
            )
        )
    return Population(records, dict(sorted(excluded.items())), KitchenerIndex.build(physical))


@dataclass(slots=True)
class ConflationInputs:
    """Both frozen sides, indexed once, and their identity."""

    osm: OsmIndex
    population: Population
    #: The eligible records alone, for neighbour counts.
    eligible: KitchenerIndex
    relationships: RelationshipIndex
    parquet: Path
    identity: dict[str, Any]

    def record(self, activetransportid: int) -> Record:
        return self.by_id[activetransportid]

    @property
    def by_id(self) -> dict[int, Record]:
        return {r.activetransportid: r for r in self.population.records}


def load_inputs(
    normalized_dir: Path,
    extract_path: Path,
    extract_manifest_path: Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> ConflationInputs:
    """The frozen Kitchener file and OSM extract, checked against their recorded hashes."""
    say = progress or (lambda _message: None)
    parquet, normalized = load_normalized(normalized_dir)
    snapshot_id = normalized.get("snapshot_id") or normalized.get("snapshot", {}).get("snapshot_id")
    manifest = json.loads(extract_manifest_path.read_text("utf-8"))
    recorded = manifest["output"]["sha256"]
    extract = load_study_extract(extract_path, expected_sha256=recorded)
    transformer = to_native()
    osm = OsmIndex.build(extract, transformer)
    say(f"osm: {len(extract.ways)} ways, {len(osm.fact_ids)} tagged nodes indexed")
    area = study_area(tuple(manifest["dataset"]["source_bbox"]), transformer)
    population = load_population(parquet, area)
    say(f"kitchener: {len(population.records)} eligible records")
    eligible = KitchenerIndex.build(
        KitchenerFeature(
            r.activetransportid, ELIGIBLE_PHYSICAL_CLASS, r.network_role, r.subcategory, r.geometry
        )
        for r in population.records
    )
    identity = {
        "kitchener": {
            "snapshot_id": snapshot_id,
            "normalized_file": parquet.name,
            "normalized_sha256": normalized["output"]["sha256"],
        },
        "osm_frozen": {
            "role": "the geometry and tags every match is made against: PathAble's own source extract",
            "dataset": manifest["dataset"],
            "extract_sha256": recorded,
            "extract_counts": manifest.get("counts"),
        },
        "eligibility": {
            "physical_class": ELIGIBLE_PHYSICAL_CLASS,
            "network_roles": list(ELIGIBLE_ROLES),
            "excludes": "records sourced from street-level imagery; records not wholly inside the "
            f"study box shrunk by {EDGE_MARGIN_M:g} m",
            "eligible_records": len(population.records),
            "excluded": population.excluded,
        },
        "candidate_contract": {
            "version": CANDIDATE_CONTRACT_VERSION,
            "way_radius_m": WAY_RADIUS_M,
            "node_radius_m": NODE_RADIUS_M,
            "node_kinds": ["kerb (barrier=kerb or kerb=*)", "crossing (highway=crossing)"],
            "sample_spacing_m": SAMPLE_SPACING_M,
        },
    }
    return ConflationInputs(
        osm,
        population,
        eligible,
        RelationshipIndex(population.physical, osm.lines),
        parquet,
        identity,
    )


# ---------------------------------------------------------------------------
# Candidates and per-sample geometry
# ---------------------------------------------------------------------------


def node_kind(tags: Mapping[str, str]) -> str | None:
    """``kerb``, ``crossing`` or ``None``: the node kinds a match may cite."""
    if "kerb" in tags or tags.get("barrier") == "kerb":
        return "kerb"
    if tags.get("highway") == "crossing":
        return "crossing"
    return None


@dataclass(frozen=True, slots=True)
class WayCandidate:
    osm_id: int
    osm_class: str
    compatibility: str
    #: Per sample of the record: distance to the way, position along it, angle there.
    distances: np.ndarray[Any, Any]
    positions: np.ndarray[Any, Any]
    angles: np.ndarray[Any, Any]
    min_distance_m: float
    length_m: float

    @property
    def median_offset_m(self) -> float:
        return float(np.median(self.distances))

    @property
    def max_offset_m(self) -> float:
        return float(self.distances.max())

    def share_within(self, metres: float) -> float:
        return float((self.distances <= metres).mean())


@dataclass(frozen=True, slots=True)
class NodeCandidate:
    osm_id: int
    kind: str
    distance_m: float
    on_ways: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CandidateSet:
    record: Record
    samples: np.ndarray[Any, Any]
    ways: tuple[WayCandidate, ...]
    nodes: tuple[NodeCandidate, ...]
    #: The OSM road nearest the record's middle, and how far.
    road_id: int | None
    road_distance_m: float | None

    @property
    def sample_count(self) -> int:
        return len(self.samples)


def samples_and_bearings(
    geometry: BaseGeometry, spacing: float = SAMPLE_SPACING_M
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    """The record sampled every ``spacing`` metres, with its direction at each sample."""
    points: list[np.ndarray[Any, Any]] = []
    bearings: list[np.ndarray[Any, Any]] = []
    for part in parts(geometry):
        coords = np.asarray(shapely.get_coordinates(shapely.segmentize(part, spacing)))
        if len(coords) == 1:
            coords = np.vstack([coords, coords])
        before = np.vstack([coords[:1], coords[:-1]])
        after = np.vstack([coords[1:], coords[-1:]])
        step = after - before
        points.append(coords)
        bearings.append(np.degrees(np.arctan2(step[:, 1], step[:, 0])))
    return np.vstack(points), np.concatenate(bearings)


def _angles(first: np.ndarray[Any, Any], second: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """Angles between undirected lines, 0 to 90°, element by element."""
    difference = np.abs(first - second) % 180.0
    return np.asarray(np.minimum(difference, 180.0 - difference), dtype=float)


def way_candidate(
    osm_id: int,
    line: LineString,
    tags: Mapping[str, str],
    family: str,
    record: BaseGeometry,
    points: np.ndarray[Any, Any],
    bearings: np.ndarray[Any, Any],
) -> WayCandidate:
    geometries = shapely.points(points)
    distances = np.asarray(shapely.distance(geometries, line), dtype=float)
    positions = np.asarray(shapely.line_locate_point(line, geometries), dtype=float)
    length = float(line.length)
    before = shapely.line_interpolate_point(line, np.clip(positions - 1.0, 0.0, length))
    after = shapely.line_interpolate_point(line, np.clip(positions + 1.0, 0.0, length))
    way_bearings = np.degrees(
        np.arctan2(
            shapely.get_y(after) - shapely.get_y(before),
            shapely.get_x(after) - shapely.get_x(before),
        )
    )
    klass = osm_class(tags)
    return WayCandidate(
        osm_id=osm_id,
        osm_class=klass,
        compatibility=class_compatibility(family, klass),
        distances=distances,
        positions=positions,
        angles=_angles(bearings, way_bearings),
        min_distance_m=float(record.distance(line)),
        length_m=length,
    )


def candidate_set(record: Record, index: OsmIndex) -> CandidateSet:
    """The contract's candidates for one record. Deterministic: ordered by OSM id."""
    points, bearings = samples_and_bearings(record.geometry)
    hits = index.tree.query(record.geometry, predicate="dwithin", distance=WAY_RADIUS_M)
    ways = tuple(
        way_candidate(
            osm_id,
            index.lines[osm_id],
            index.extract.ways[osm_id].tags,
            record.family,
            record.geometry,
            points,
            bearings,
        )
        for osm_id in sorted(index.way_ids[int(hit)] for hit in hits)
    )
    node_hits = index.fact_tree.query(record.geometry, predicate="dwithin", distance=NODE_RADIUS_M)
    nodes: list[NodeCandidate] = []
    for hit in node_hits:
        node_id = index.fact_ids[int(hit)]
        kind = node_kind(index.extract.nodes[node_id].tags)
        if kind is None:
            continue
        nodes.append(
            NodeCandidate(
                osm_id=node_id,
                kind=kind,
                distance_m=float(index.fact_points[node_id].distance(record.geometry)),
                on_ways=tuple(sorted(index.node_ways.get(node_id, []))),
            )
        )
    nodes.sort(key=lambda n: n.osm_id)
    middle = max(parts(record.geometry), key=lambda part: part.length).interpolate(
        0.5, normalized=True
    )
    road = nearest_road(middle, index)
    return CandidateSet(
        record=record,
        samples=points,
        ways=ways,
        nodes=tuple(nodes),
        road_id=road,
        road_distance_m=float(index.lines[road].distance(middle)) if road is not None else None,
    )


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

MATCHED = "matched"
AMBIGUOUS = "ambiguous"
UNMATCHED = "unmatched"


@dataclass(frozen=True, slots=True)
class Target:
    """One OSM element a record corresponds to, with the part of it the record covers."""

    element: str
    role: str
    #: For a way: the metres along it, from its first node, that the record covers.
    from_m: float | None = None
    to_m: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "element": self.element,
            "role": self.role,
            "from_m": None if self.from_m is None else round(self.from_m, 2),
            "to_m": None if self.to_m is None else round(self.to_m, 2),
        }


@dataclass(frozen=True, slots=True)
class Decision:
    activetransportid: int
    state: str
    #: The rule that decided, in the policy's own words: the decision basis.
    rule: str
    targets: tuple[Target, ...]
    relationship: str | None
    representation: str
    #: The values the rule read. Decision signals, not confidence.
    signals: Mapping[str, Any]

    @property
    def elements(self) -> frozenset[str]:
        return frozenset(t.element for t in self.targets) if self.state == MATCHED else frozenset()

    def as_dict(self) -> dict[str, Any]:
        return {
            "activetransportid": self.activetransportid,
            "state": self.state,
            "rule": self.rule,
            "targets": [t.as_dict() for t in self.targets],
            "relationship": self.relationship,
            "representation": self.representation,
            "signals": dict(self.signals),
        }


def _way_target(way: WayCandidate, mask: np.ndarray[Any, Any], role: str = "carrier") -> Target:
    """The part of a way the record's claimed samples project onto."""
    positions = way.positions[mask] if mask.any() else way.positions
    return Target(f"way/{way.osm_id}", role, float(positions.min()), float(positions.max()))


def _representation(targets: Sequence[Target]) -> str:
    kinds = {t.element.split("/")[0] for t in targets}
    if kinds == {"way"}:
        return "separate_way"
    if kinds == {"node"}:
        return "node"
    return "multiple" if kinds else "none"


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------

#: The baseline name → the signal it ranks ways by (lower is better).
BASELINES: dict[str, str] = {
    "A_nearest_geometry": "closest approach",
    "B_median_offset": "median offset",
    "C_worst_point": "worst-point distance (directed Hausdorff)",
    "D_overlap_2m": "share of the record within 2 m (higher is better)",
}


def baseline(name: str, candidates: CandidateSet) -> Decision:
    """The single best way by one signal, matched whenever any way exists. No abstention."""
    record_id = candidates.record.activetransportid
    if not candidates.ways:
        return Decision(record_id, UNMATCHED, "no_candidate_way", (), None, "none", {})
    keys = {
        "A_nearest_geometry": lambda w: (w.min_distance_m, w.osm_id),
        "B_median_offset": lambda w: (w.median_offset_m, w.osm_id),
        "C_worst_point": lambda w: (w.max_offset_m, w.osm_id),
        "D_overlap_2m": lambda w: (-w.share_within(2.0), w.median_offset_m, w.osm_id),
    }
    best = min(candidates.ways, key=keys[name])
    target = _way_target(best, np.ones(candidates.sample_count, dtype=bool))
    return Decision(record_id, MATCHED, name, (target,), None, "separate_way", {})


# ---------------------------------------------------------------------------
# The matcher
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MatcherPolicy:
    """Every threshold the matcher uses, named. Tuned on the development set only.

    ``provenance`` says, for each tuned value, how it was chosen; the switches
    at the end exist for ablation and are all on in the policy that is evaluated.
    """

    version: str = MATCHER_VERSION
    #: A sample is claimed by the nearest aligned compatible way within this.
    carry_m: float = 2.0
    #: A way counts as aligned with the record at a sample within this angle.
    align_max_deg: float = 45.0
    #: A way carries the record when it claims at least this share of its samples.
    min_claim_share: float = 0.2
    #: The carriers must claim at least this share of the samples for a match.
    cover_min: float = 0.75
    #: A sample is contested when another aligned compatible way, not joined to
    #: the nearest, is within this of the nearest distance.
    contest_margin_m: float = 1.0
    #: Above this share of contested samples, the matcher abstains.
    contest_max: float = 0.3
    #: Curb cuts: a kerb node within this of the piece marks its kerb, unless a
    #: second one is within ``kerb_margin_m`` of the first's distance.
    kerb_node_m: float = 2.0
    kerb_margin_m: float = 0.5
    #: Crossings OSM draws only as a node: a crossing node within this of the record.
    crossing_node_m: float = 3.0
    #: Nothing compatible this near (median over the record) means no counterpart.
    near_m: float = 5.0
    #: A road this near that tags the facility makes it a road attribute.
    road_attribute_m: float = 15.0
    # Ablation switches.
    use_class: bool = True
    use_alignment: bool = True
    use_contest: bool = True
    use_topology: bool = True
    use_nodes: bool = True
    provenance: Mapping[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["provenance"] = dict(self.provenance)
        return values

    def with_(self, **changes: Any) -> MatcherPolicy:
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class _Claims:
    """Which way claims each sample, and how contested the claims are."""

    carriers: tuple[WayCandidate, ...]
    masks: tuple[np.ndarray[Any, Any], ...]
    coverage: float
    contested_share: float
    shares: Mapping[int, float]


def _compatible(way: WayCandidate, policy: MatcherPolicy) -> bool:
    if not policy.use_class:
        return way.osm_class in PEDESTRIAN_CLASSES or way.compatibility in ("same", "plausible")
    return way.compatibility in ("same", "plausible")


def _chained(first: int, second: int, index: OsmIndex) -> bool:
    """Two ways that share a node are one facility's pieces, not competitors."""
    return bool(set(index.extract.ways[first].refs) & set(index.extract.ways[second].refs))


def claims(candidates: CandidateSet, policy: MatcherPolicy, index: OsmIndex) -> _Claims:
    ways = [w for w in candidates.ways if _compatible(w, policy)]
    n = candidates.sample_count
    if not ways:
        return _Claims((), (), 0.0, 0.0, {})
    distance = np.vstack([w.distances for w in ways])
    if policy.use_alignment:
        distance = np.where(
            np.vstack([w.angles for w in ways]) <= policy.align_max_deg, distance, np.inf
        )
    nearest = np.argmin(distance, axis=0)
    nearest_d = distance[nearest, np.arange(n)]
    claimed = nearest_d <= policy.carry_m
    shares = {ways[i].osm_id: float(((nearest == i) & claimed).sum() / n) for i in range(len(ways))}
    carrier_rows = [i for i in range(len(ways)) if shares[ways[i].osm_id] >= policy.min_claim_share]
    in_carrier = np.isin(nearest, carrier_rows) & claimed
    coverage = float(in_carrier.mean()) if n else 0.0
    contested = np.zeros(n, dtype=bool)
    if policy.use_contest and len(ways) > 1:
        for sample in np.flatnonzero(in_carrier):
            best = int(nearest[sample])
            for other in range(len(ways)):
                if other == best or not np.isfinite(distance[other, sample]):
                    continue
                if distance[other, sample] - nearest_d[sample] >= policy.contest_margin_m:
                    continue
                if policy.use_topology and _chained(ways[best].osm_id, ways[other].osm_id, index):
                    continue
                contested[sample] = True
                break
    claimed_count = int(in_carrier.sum())
    contested_share = float(contested.sum() / claimed_count) if claimed_count else 0.0
    carriers = tuple(ways[i] for i in carrier_rows)
    masks = tuple((nearest == i) & claimed for i in carrier_rows)
    return _Claims(carriers, masks, coverage, contested_share, shares)


def _nearest_compatible_median(candidates: CandidateSet, policy: MatcherPolicy) -> float | None:
    medians = [w.median_offset_m for w in candidates.ways if _compatible(w, policy)]
    return min(medians) if medians else None


def _road_tags_facility(candidates: CandidateSet, index: OsmIndex, policy: MatcherPolicy) -> bool:
    """Whether the nearby road records the facility as one of its own tags."""
    if candidates.road_id is None or candidates.road_distance_m is None:
        return False
    if candidates.road_distance_m > policy.road_attribute_m:
        return False
    tags = index.extract.ways[candidates.road_id].tags
    keys = ("sidewalk", "sidewalk:both", "sidewalk:left", "sidewalk:right", "footway")
    values = {tags[k] for k in keys if k in tags}
    return bool(values - {"no", "none", "separate"})


def match(
    candidates: CandidateSet,
    policy: MatcherPolicy,
    index: OsmIndex,
    relationships: RelationshipIndex | None = None,
) -> Decision:
    """The matcher's decision for one record. Deterministic for a given policy."""
    record = candidates.record
    found = claims(candidates, policy, index)
    signals: dict[str, Any] = {
        "coverage": round(found.coverage, 3),
        "contested_share": round(found.contested_share, 3),
        "carriers": [f"way/{w.osm_id}" for w in found.carriers],
        "claim_shares": {f"way/{k}": round(v, 3) for k, v in found.shares.items() if v > 0},
    }
    covered = found.coverage >= policy.cover_min
    contested = found.contested_share > policy.contest_max
    carriers = tuple(_way_target(w, m) for w, m in zip(found.carriers, found.masks, strict=True))

    def decide(state: str, rule: str, targets: tuple[Target, ...] = ()) -> Decision:
        relationship = None
        if state == MATCHED:
            relationship = (relationships or RelationshipIndex.empty()).relationship(
                record, targets
            )
        representation = _representation(targets) if state == MATCHED else "none"
        return Decision(
            record.activetransportid, state, rule, targets, relationship, representation, signals
        )

    if record.curb_cut and policy.use_nodes:
        kerbs = sorted(
            (
                n
                for n in candidates.nodes
                if n.kind == "kerb" and n.distance_m <= policy.kerb_node_m
            ),
            key=lambda n: (n.distance_m, n.osm_id),
        )
        signals["kerb_nodes"] = [[f"node/{n.osm_id}", round(n.distance_m, 2)] for n in kerbs]
        if len(kerbs) > 1 and kerbs[1].distance_m - kerbs[0].distance_m < policy.kerb_margin_m:
            return decide(AMBIGUOUS, "curb_cut_two_kerb_nodes")
        kerb = (Target(f"node/{kerbs[0].osm_id}", "kerb"),) if kerbs else ()
        if covered and not contested:
            return decide(
                MATCHED,
                "curb_cut_kerb_and_carrier" if kerb else "curb_cut_carrier",
                kerb + carriers,
            )
        if kerb:
            return decide(MATCHED, "curb_cut_kerb_node", kerb)
        median = _nearest_compatible_median(candidates, policy)
        if median is not None and median <= policy.near_m:
            return decide(AMBIGUOUS, "curb_cut_at_junction_without_kerb")
        return decide(UNMATCHED, "curb_cut_no_counterpart")

    if covered and contested:
        return decide(AMBIGUOUS, "competing_way")
    if covered and record.length_m < SHORT_PIECE_M and len(carriers) > 1:
        return decide(AMBIGUOUS, "short_piece_at_junction")
    if covered:
        return decide(MATCHED, "covered_by_carriers", carriers)
    if record.family == "crossing" and policy.use_nodes:
        crossing_nodes = sorted(
            (
                n
                for n in candidates.nodes
                if n.kind == "crossing" and n.distance_m <= policy.crossing_node_m
            ),
            key=lambda n: (n.distance_m, n.osm_id),
        )
        crossing_ways = [
            w
            for w in candidates.ways
            if w.osm_class == "crossing" and w.min_distance_m <= policy.near_m
        ]
        if crossing_nodes and not crossing_ways:
            return decide(
                MATCHED,
                "crossing_as_node",
                (Target(f"node/{crossing_nodes[0].osm_id}", "crossing"),),
            )
    median = _nearest_compatible_median(candidates, policy)
    if median is not None and median <= policy.near_m:
        return decide(AMBIGUOUS, "partial_or_offset_counterpart")
    if _road_tags_facility(candidates, index, policy):
        return decide(AMBIGUOUS, "road_attribute")
    return decide(UNMATCHED, "no_counterpart")


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------

#: A City record lies along a way when this share of it is within this distance.
ALONG_M = 3.0
ALONG_SHARE = 0.5


@dataclass(slots=True)
class RelationshipIndex:
    """Which other physical City records lie along each OSM way, for N:1 and N:M."""

    physical: KitchenerIndex | None
    lines: Mapping[int, LineString]
    _cache: dict[int, frozenset[int]] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> RelationshipIndex:
        return cls(None, {})

    def along(self, way_id: int) -> frozenset[int]:
        if self.physical is None or way_id not in self.lines:
            return frozenset()
        if way_id not in self._cache:
            line = self.lines[way_id]
            found = set()
            for other in self.physical.near(line, ALONG_M):
                feature = self.physical.features[other]
                if feature.geometry.length < SHORT_PIECE_M:
                    continue  # junction pieces are the junction, not the facility
                points = shapely.points(samples_and_bearings(feature.geometry)[0])
                share = float((np.asarray(shapely.distance(points, line)) <= ALONG_M).mean())
                if share >= ALONG_SHARE:
                    found.add(other)
            self._cache[way_id] = frozenset(found)
        return self._cache[way_id]

    def relationship(self, record: Record, targets: Sequence[Target]) -> str:
        ways = [int(t.element.split("/")[1]) for t in targets if t.element.startswith("way/")]
        if not ways:
            return "one_to_one"
        shared = any(self.along(w) - {record.activetransportid} for w in ways)
        if len(ways) == 1:
            return "many_to_one" if shared else "one_to_one"
        return "many_to_many" if shared else "one_to_many"


def decide_all(
    population: Iterable[CandidateSet],
    policy: MatcherPolicy,
    index: OsmIndex,
    relationships: RelationshipIndex | None = None,
) -> list[Decision]:
    return [match(c, policy, index, relationships) for c in population]
