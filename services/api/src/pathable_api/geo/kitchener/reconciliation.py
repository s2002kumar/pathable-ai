"""What OSM and the City each claim, wherever PA-GEO-05 earned a correspondence.

PA-GEO-06 asks how PathAble should hold what two sources say about one
facility without overwriting either, losing where each claim came from,
inventing independence, or turning open questions into routing truth. This
module answers it for the classes PA-GEO-05 granted, and only those.

**The accepted input contract** (:data:`INPUT_CONTRACT_VERSION`). A PA-GEO-05
``matched`` decision is not enough by itself; each class has its own gate:

- *curb cuts* — only through the OSM kerb node the matcher named. The ways a
  curb-cut decision names are the way-level set PA-GEO-05 found unreliable,
  so nothing reconciles on them, and a curb cut never reaches a whole way;
- *structures* — only where OSM itself tags the structure the City records
  (the decision's ``structure_carriers``). A City stair OSM draws as a plain
  footway waits for matcher v2 and a new holdout;
- *surfaces* — the way-level correspondence, except for short pieces
  (:data:`~pathable_api.geo.kitchener.conflation.SHORT_PIECE_M` or less),
  which PA-GEO-05 found weak at junctions.

Ambiguous and unmatched decisions reconcile nothing. Every exclusion is
recorded with its reason.

**Reconciliation** is per property, per local target: a kerb node, or the
metres of an OSM way one City record covers. It lists each source's
assertions, classifies how they relate (:mod:`reconciliation_vocabulary`),
and — where OSM's edit history was read — whether OSM's value may share an
origin with the City's. It never picks a value.

**OSM-only kerbs.** A kerb OSM records where the City records no curb cut is
found by location, not by a match: a kerb node with no City curb cut within
3 m and a City facility within 10 m (PA-GEO-04's distances). No correspondence
to a City record is claimed for it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from shapely.geometry.base import BaseGeometry

from pathable_api.geo.kitchener.assertions import (
    NOT_ROUTING_ELIGIBLE,
    OSM_NODE,
    OSM_WAY_EXTENT,
    TWO_SIDED,
    Assertion,
    Dates,
    LineageRelationship,
    Reconciliation,
    Relationship,
    Target,
    Topic,
    ValueHistory,
)
from pathable_api.geo.kitchener.conflation import (
    AMBIGUOUS,
    MATCHED,
    SHORT_PIECE_M,
    Decision,
    Record,
    node_kind,
)
from pathable_api.geo.kitchener.correspondence import KitchenerIndex, OsmIndex, vertex_agreement
from pathable_api.geo.kitchener.lineage import (
    Lineage,
    LineageFinding,
    Signal,
    attribute_lineage,
    combine,
    geometry_lineage,
)
from pathable_api.geo.kitchener.reconciliation_vocabulary import (
    CITY_STRUCTURE,
    CITY_SURFACE,
    CURB_RAMP_PRESENT,
    RAILING_PRESENT,
    STRUCTURE_FAMILIES,
    Relation,
    normalize_osm_surface,
    osm_handrails,
    osm_kerb,
    osm_structures,
    relate_curb,
    relate_railing,
    relate_structure,
    relate_surface,
)
from pathable_api.geo.kitchener.study import History, vertex_coincidence

INPUT_CONTRACT_VERSION = "kitchener-geo06-accepted-input-v1"
POLICY_VERSION = "kitchener-geo06-reconciliation-v1"
#: The only matcher whose output this contract accepts.
ACCEPTED_MATCHER = "kitchener-geo05-matcher-v1"

KITCHENER_SOURCE = "kitchener-active-transportation"
OSM_SOURCE = "openstreetmap"

#: PA-GEO-04's distances for "the City records a curb cut here" and "the City
#: has mapped a facility here", reused for the OSM-only kerb locations.
CITY_CURB_CUT_NEAR_M = 3.0
CITY_COVERAGE_M = 10.0

#: Tags that date an observation of a value, most specific first.
OBSERVATION_TAGS = ("check_date:{key}", "check_date", "survey:date")


class Exclusion(StrEnum):
    """Why a PA-GEO-05 decision does not reach reconciliation for a topic."""

    AMBIGUOUS = "ambiguous_match"
    NO_COUNTERPART = "no_counterpart"
    #: The ways a curb-cut decision names: PA-GEO-05's weak way-level set.
    CURB_CUT_WAY_LEVEL = "curb_cut_way_level_correspondence"
    #: A curb cut matched only way-level: OSM has no kerb node within 2 m.
    CURB_CUT_WITHOUT_KERB_NODE = "curb_cut_without_kerb_node"
    SHORT_PIECE = "short_piece"
    #: OSM draws the facility as a node, so there is no way to compare.
    NODE_ONLY = "node_only_correspondence"
    #: The City records a structure OSM does not tag, such as a stair drawn as
    #: a plain footway: matcher v2's question.
    STRUCTURE_NOT_IN_OSM = "structure_not_represented_in_osm"


EXCLUSION_CATEGORY = {
    Exclusion.AMBIGUOUS: "excluded_by_ambiguity",
    Exclusion.NO_COUNTERPART: "excluded_no_counterpart",
    Exclusion.CURB_CUT_WAY_LEVEL: "excluded_by_class",
    Exclusion.CURB_CUT_WITHOUT_KERB_NODE: "excluded_by_class",
    Exclusion.SHORT_PIECE: "excluded_by_class",
    Exclusion.NODE_ONLY: "excluded_osm_representation_absent",
    Exclusion.STRUCTURE_NOT_IN_OSM: "excluded_osm_representation_absent",
}


class KerbLocation(StrEnum):
    """What became of each OSM kerb node in the study area."""

    ACCEPTED = "accepted_city_curb_cut_correspondence"
    CITY_COVERED = "city_facility_without_curb_cut"
    #: A City curb cut lies within 3 m, but no accepted correspondence names
    #: this node: its decision was ambiguous, way-level only, or named another.
    CITY_CURB_CUT_NEAR = "city_curb_cut_near_without_accepted_correspondence"
    OUTSIDE_CITY_COVERAGE = "outside_city_coverage"


# ---------------------------------------------------------------------------
# The accepted input contract
# ---------------------------------------------------------------------------

WAY_TOPICS = (Topic.SURFACE, Topic.STRUCTURE, Topic.RAILING)


@dataclass(frozen=True, slots=True)
class Gate:
    """Which parts of one PA-GEO-05 decision this card may reconcile on."""

    kerb_nodes: tuple[str, ...] = ()
    ways: tuple[tuple[str, float | None, float | None], ...] = ()
    #: topic → reason, for every topic the record could carry and does not.
    exclusions: Mapping[Topic, Exclusion] = field(default_factory=dict)

    @property
    def accepted(self) -> tuple[Topic, ...]:
        found = []
        if self.kerb_nodes:
            found.append(Topic.CURB_RAMP)
        if self.ways:
            found.extend(WAY_TOPICS)
        return tuple(found)


def gate(record: Record, decision: Decision) -> Gate:
    """Apply the class-specific contract to one decision."""
    topics = (Topic.CURB_RAMP, *WAY_TOPICS) if record.curb_cut else WAY_TOPICS
    if decision.state != MATCHED:
        reason = Exclusion.AMBIGUOUS if decision.state == AMBIGUOUS else Exclusion.NO_COUNTERPART
        return Gate(exclusions=dict.fromkeys(topics, reason))
    kerbs = tuple(
        t.element for t in decision.targets if t.role == "kerb" and t.element.startswith("node/")
    )
    ways = tuple(
        (t.element, t.from_m, t.to_m) for t in decision.targets if t.element.startswith("way/")
    )
    exclusions: dict[Topic, Exclusion] = {}
    if record.curb_cut:
        if not kerbs:
            exclusions[Topic.CURB_RAMP] = Exclusion.CURB_CUT_WITHOUT_KERB_NODE
        way_reason: Exclusion | None = Exclusion.CURB_CUT_WAY_LEVEL
    elif not ways:
        way_reason = Exclusion.NODE_ONLY
    elif record.length_m <= SHORT_PIECE_M:
        way_reason = Exclusion.SHORT_PIECE
    elif record.structure is not None and not decision.signals.get("structure_carriers"):
        way_reason = Exclusion.STRUCTURE_NOT_IN_OSM
    else:
        way_reason = None
    if way_reason is not None:
        exclusions.update(dict.fromkeys(WAY_TOPICS, way_reason))
        ways = ()
    return Gate(kerbs if record.curb_cut else (), ways, exclusions)


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CityFields:
    """City fields read here rather than from PA-GEO-05's records: the dates, in
    UTC, and the value state of FEATURE_TYPE, which those records do not carry."""

    created_at: str | None = None
    modified_at: str | None = None
    state_feature_type: str | None = None
    #: SOURCE_DATE's calendar date. The City stores it at midnight UTC.
    source_date: str | None = None


def _city_dates(record: Record, extra: CityFields | None) -> Dates:
    a = record.attributes
    year = a.get("last_inspection_year")
    return Dates(
        source_capture_date=extra.source_date if extra else None,
        inspection_year=int(year) if year is not None and str(year).isdigit() else None,
        record_created_at=extra.created_at if extra else None,
        record_modified_at=extra.modified_at if extra else None,
    )


def city_assertion(record: Record, topic: Topic, extra: CityFields | None = None) -> Assertion:
    """The City's claim on one topic, whatever its value state; only some are usable."""
    a = {
        **record.attributes,
        "state_feature_type": extra.state_feature_type if extra else None,
    }
    if topic is Topic.SURFACE:
        raw, state = a.get("surface_material"), a.get("state_surface_material")
        usable = state == "non_default" and raw in CITY_SURFACE
        field_name, prop = "SURFACE_MATERIAL", "surface_material"
        normalized = CITY_SURFACE[str(raw)][0] if usable else None
        origin = a.get("origin_surface_material")
    elif topic is Topic.CURB_RAMP:
        raw, state = a.get("curbcut"), a.get("state_curbcut")
        usable = raw == "Y" and state == "non_default"
        field_name, prop = "CURBCUT", "curb_ramp"
        normalized = CURB_RAMP_PRESENT if usable else None
        origin = a.get("origin_curbcut")
    elif topic is Topic.STRUCTURE:
        raw, state = a.get("feature_type"), a.get("state_feature_type")
        usable = state == "non_default" and raw in CITY_STRUCTURE
        field_name, prop = "FEATURE_TYPE", "structure"
        normalized = CITY_STRUCTURE[str(raw)][1] if usable else None
        origin = a.get("origin_feature_type")
    else:
        raw, state = a.get("railing"), a.get("state_railing")
        usable = raw == "Y" and state == "non_default"
        field_name, prop = "RAILING", "railing"
        normalized = RAILING_PRESENT if usable else None
        origin = a.get("origin_railing")
    note = None
    if topic is Topic.CURB_RAMP and usable:
        note = "The City defines CURBCUT = Y as 'a curbcut down to street level'; no kerb height."
    return Assertion(
        assertion_id=f"kitchener/{record.activetransportid}#{prop}",
        source_id=KITCHENER_SOURCE,
        source_record=f"kitchener/{record.activetransportid}",
        source_record_version=None,
        topic=topic,
        prop=prop,
        raw_attribute=field_name,
        raw_value=None if raw is None else str(raw),
        normalized_value=normalized,
        value_state=str(state) if state is not None else "null",
        usable=usable,
        evidence_origin=str(origin) if origin is not None else "unknown",
        scope="kitchener_record",
        capture_source=a.get("source_class"),
        dates=_city_dates(record, extra),
        note=note,
    )


def _observation(tags: Mapping[str, str], key: str) -> tuple[str | None, str | None]:
    for template in OBSERVATION_TAGS:
        name = template.format(key=key)
        if tags.get(name):
            return tags[name], name
    return None, None


def osm_assertion(
    osm: OsmIndex, element: str, topic: Topic, key: str, value: str, normalized: str | None
) -> Assertion:
    """One OSM tag as an assertion: the element, its version, the tag exactly as frozen."""
    kind, _, number = element.partition("/")
    item = osm.extract.nodes[int(number)] if kind == "node" else osm.extract.ways[int(number)]
    observed, basis = _observation(item.tags, key)
    prop = {
        Topic.SURFACE: "surface_material",
        Topic.CURB_RAMP: "kerb",
        Topic.STRUCTURE: "structure",
        Topic.RAILING: "handrail",
    }[topic]
    return Assertion(
        assertion_id=f"{element}@v{item.version}#{key}",
        source_id=OSM_SOURCE,
        source_record=element,
        source_record_version=item.version,
        topic=topic,
        prop=prop,
        raw_attribute=key,
        raw_value=value,
        normalized_value=normalized,
        value_state="asserted",
        usable=True,
        evidence_origin="osm_contributor_edit",
        scope="osm_node" if kind == "node" else "osm_way",
        dates=Dates(
            observation_date=observed,
            observation_date_basis=basis,
            osm_edit_timestamp=item.timestamp,
        ),
    )


def kerb_assertion(osm: OsmIndex, element: str) -> Assertion:
    tags = osm.extract.nodes[int(element.split("/")[1])].tags
    kerb = osm_kerb(tags)
    if "kerb" in tags:
        return osm_assertion(osm, element, Topic.CURB_RAMP, "kerb", tags["kerb"], str(kerb))
    return osm_assertion(osm, element, Topic.CURB_RAMP, "barrier", "kerb", str(kerb))


# ---------------------------------------------------------------------------
# Reconciling
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Reconciled:
    """Everything one run produces, before it is written."""

    assertions: dict[str, Assertion]
    reconciliations: list[Reconciliation]
    gates: dict[int, Gate]
    #: Per OSM kerb node in the study area: what became of it.
    kerb_locations: dict[int, KerbLocation]
    #: Kerb-node correspondences: node → the City records that claim it.
    kerb_claims: dict[str, tuple[int, ...]]

    def history_elements(self) -> list[str]:
        """The OSM elements whose history the lineage of two-sided rows needs."""
        found = {
            self.assertions[a].source_record
            for r in self.reconciliations
            if r.relationship in TWO_SIDED
            for a in r.osm_assertions
        }
        return sorted(found, key=lambda e: (e.split("/")[0], int(e.split("/")[1])))


@dataclass(slots=True)
class _Builder:
    osm: OsmIndex
    city_fields: Mapping[int, CityFields]
    assertions: dict[str, Assertion] = field(default_factory=dict)
    rows: list[Reconciliation] = field(default_factory=list)

    def keep(self, assertion: Assertion) -> str:
        self.assertions.setdefault(assertion.assertion_id, assertion)
        return assertion.assertion_id

    def city(self, record: Record, topic: Topic) -> Assertion:
        found = city_assertion(record, topic, self.city_fields.get(record.activetransportid))
        self.keep(found)
        return found

    def version(self, element: str) -> int | None:
        kind, _, number = element.partition("/")
        item = (
            self.osm.extract.nodes.get(int(number))
            if kind == "node"
            else self.osm.extract.ways.get(int(number))
        )
        return None if item is None else item.version

    def add(
        self,
        topic: Topic,
        prop: str,
        target: Target,
        records: Sequence[Record],
        decisions: Sequence[Decision],
        relationship: str | None,
        city: Sequence[Assertion],
        osm: Sequence[Assertion],
        relation: Relation,
    ) -> None:
        usable = [a for a in city if a.usable]
        record_ids = tuple(sorted(r.activetransportid for r in records))
        scope = (
            f"{target.element}"
            if target.target_type == OSM_NODE
            else f"kitchener/{record_ids[0]}/{target.element}"
        )
        self.rows.append(
            Reconciliation(
                reconciliation_id=f"{prop}/{scope}",
                topic=topic,
                prop=prop,
                target=target,
                source_records=record_ids,
                correspondence_rules=tuple(sorted({d.rule for d in decisions})),
                correspondence_relationship=relationship,
                kitchener_assertions=tuple(sorted(a.assertion_id for a in usable)),
                kitchener_withheld=tuple(sorted(a.assertion_id for a in city if not a.usable)),
                osm_assertions=tuple(sorted(self.keep(a) for a in osm)),
                kitchener_values=tuple(sorted({str(a.raw_value) for a in usable})),
                osm_values=tuple(sorted({str(a.raw_value) for a in osm})),
                relationship=relation.relationship,
                specificity=relation.specificity,
                rule=relation.rule,
                lineage=(
                    LineageRelationship.NOT_ASSESSED
                    if relation.relationship in TWO_SIDED
                    else LineageRelationship.NOT_APPLICABLE
                ),
            )
        )


def reconcile(
    records: Mapping[int, Record],
    decisions: Mapping[int, Decision],
    osm: OsmIndex,
    *,
    area: BaseGeometry,
    city_physical: KitchenerIndex,
    city_curb_cuts: KitchenerIndex,
    city_fields: Mapping[int, CityFields] | None = None,
) -> Reconciled:
    """Every reconciliation the contract allows, in a deterministic order. No lineage yet."""
    build = _Builder(osm, city_fields or {})
    gates = {i: gate(records[i], decisions[i]) for i in sorted(decisions)}

    # Surfaces, structures and railings: per City record, per accepted way.
    for record_id, found in gates.items():
        record, decision = records[record_id], decisions[record_id]
        for element, from_m, to_m in found.ways:
            tags = osm.extract.ways[int(element.split("/")[1])].tags
            target = Target(element, build.version(element), OSM_WAY_EXTENT, from_m, to_m)
            _surface(build, record, decision, target, tags)
            _structures(build, record, decision, target, tags)
            _railing(build, record, decision, target, tags)

    # Curb ramps: per kerb node, every City record whose correspondence names it.
    claims: dict[str, list[int]] = defaultdict(list)
    for record_id, found in gates.items():
        for node in found.kerb_nodes:
            claims[node].append(record_id)
    for node in sorted(claims, key=lambda e: int(e.split("/")[1])):
        claimed = [records[i] for i in sorted(claims[node])]
        tags = osm.extract.nodes[int(node.split("/")[1])].tags
        build.add(
            Topic.CURB_RAMP,
            "curb_ramp",
            Target(node, build.version(node), OSM_NODE),
            claimed,
            [decisions[r.activetransportid] for r in claimed],
            "many_to_one" if len(claimed) > 1 else "one_to_one",
            [build.city(r, Topic.CURB_RAMP) for r in claimed],
            [kerb_assertion(osm, node)],
            relate_curb(True, tags),
        )

    # OSM's kerbs where the City records no curb cut: by location, not by match.
    locations = kerb_locations(osm, area, set(claims), city_physical, city_curb_cuts)
    for node_id, where in locations.items():
        if where is not KerbLocation.CITY_COVERED:
            continue
        node = f"node/{node_id}"
        tags = osm.extract.nodes[node_id].tags
        build.add(
            Topic.CURB_RAMP,
            "curb_ramp",
            Target(node, build.version(node), OSM_NODE),
            [],
            [],
            None,
            [],
            [kerb_assertion(osm, node)],
            relate_curb(False, tags),
        )
    return Reconciled(
        assertions=build.assertions,
        reconciliations=sorted(build.rows, key=lambda r: r.reconciliation_id),
        gates=gates,
        kerb_locations=locations,
        kerb_claims={k: tuple(sorted(v)) for k, v in claims.items()},
    )


def _surface(
    build: _Builder, record: Record, decision: Decision, target: Target, tags: Mapping[str, str]
) -> None:
    city = build.city(record, Topic.SURFACE)
    raw = tags.get("surface")
    osm_side = (
        [
            osm_assertion(
                build.osm,
                target.element,
                Topic.SURFACE,
                "surface",
                raw,
                normalize_osm_surface(raw),
            )
        ]
        if raw is not None
        else []
    )
    build.add(
        Topic.SURFACE,
        "surface_material",
        target,
        [record],
        [decision],
        decision.relationship,
        [city],
        osm_side,
        relate_surface(city.raw_value if city.usable else None, raw),
    )


def _structures(
    build: _Builder, record: Record, decision: Decision, target: Target, tags: Mapping[str, str]
) -> None:
    present = osm_structures(tags)
    city_family = CITY_STRUCTURE[record.structure][0] if record.structure else None
    for family in STRUCTURE_FAMILIES:
        if family != city_family and family not in present:
            continue
        key, value = present.get(family, (None, None))
        osm_side = []
        if key is not None and value is not None:
            normalized = family if value == "yes" or family == "steps" else value
            osm_side.append(
                osm_assertion(build.osm, target.element, Topic.STRUCTURE, key, value, normalized)
            )
        city = build.city(record, Topic.STRUCTURE)
        build.add(
            Topic.STRUCTURE,
            f"structure:{family}",
            target,
            [record],
            [decision],
            decision.relationship,
            # A City structure of another family says nothing about this one; a
            # template default is kept as context and never read.
            [city] if city_family in (None, family) else [],
            osm_side,
            relate_structure(record.structure, family, value),
        )


def _railing(
    build: _Builder, record: Record, decision: Decision, target: Target, tags: Mapping[str, str]
) -> None:
    handrails = osm_handrails(tags)
    city = city_assertion(record, Topic.RAILING)
    if not city.usable and not handrails:
        return
    build.add(
        Topic.RAILING,
        "railing",
        target,
        [record],
        [decision],
        decision.relationship,
        [build.city(record, Topic.RAILING)],
        [
            osm_assertion(build.osm, target.element, Topic.RAILING, k, v, v)
            for k, v in handrails.items()
        ],
        relate_railing(city.usable, list(handrails.values())),
    )


def kerb_locations(
    osm: OsmIndex,
    area: BaseGeometry,
    accepted: set[str],
    city_physical: KitchenerIndex,
    city_curb_cuts: KitchenerIndex,
) -> dict[int, KerbLocation]:
    """Every OSM kerb node in the study area, and what the City has near it."""
    found: dict[int, KerbLocation] = {}
    for node_id in osm.fact_ids:
        if node_kind(osm.extract.nodes[node_id].tags) != "kerb":
            continue
        point = osm.fact_points[node_id]
        if f"node/{node_id}" in accepted:
            found[node_id] = KerbLocation.ACCEPTED
        elif not area.covers(point):
            continue
        elif city_curb_cuts.near(point, CITY_CURB_CUT_NEAR_M):
            found[node_id] = KerbLocation.CITY_CURB_CUT_NEAR
        elif city_physical.near(point, CITY_COVERAGE_M):
            found[node_id] = KerbLocation.CITY_COVERED
        else:
            found[node_id] = KerbLocation.OUTSIDE_CITY_COVERAGE
    return found


# ---------------------------------------------------------------------------
# Lineage, from OSM's edit history
# ---------------------------------------------------------------------------

_LINEAGE = {
    Lineage.KNOWN: LineageRelationship.KNOWN_SHARED,
    Lineage.POSSIBLE: LineageRelationship.POSSIBLE_SHARED,
    Lineage.INDEPENDENT: LineageRelationship.APPARENTLY_INDEPENDENT,
    Lineage.UNKNOWN: LineageRelationship.UNKNOWN,
}


def municipal_since(records: Iterable[Record], city_fields: Mapping[int, CityFields]) -> str | None:
    """The earliest date any of these City records can have existed (PA-GEO-04's rule)."""
    dates = []
    for record in records:
        extra = city_fields.get(record.activetransportid)
        for value in (extra.created_at, extra.source_date) if extra else ():
            if value:
                dates.append(value[:10])
    return min(dates) if dates else None


def _finding(
    history: History, element: str, key: str, value: str, since: str | None
) -> LineageFinding | None:
    found = history.elements.get(element)
    if found is None:
        return LineageFinding(Lineage.UNKNOWN, ("no history was read for this element",), (), ())
    return attribute_lineage(
        found, history.changesets, key, municipal_since=since, frozen_value=value
    )


def attach_history(
    reconciled: Reconciled,
    records: Mapping[int, Record],
    history: History,
    city_fields: Mapping[int, CityFields],
    osm: OsmIndex,
) -> None:
    """Add what OSM's history says: value facts on assertions, lineage on two-sided rows.

    PA-GEO-04's rules, unchanged. Attribute lineage and the target's geometry
    lineage are computed and stored apart: a kerb node traced from shared
    photographs can still carry a kerb value a survey app recorded.
    """
    rows = []
    for row in reconciled.reconciliations:
        if row.relationship not in TWO_SIDED:
            rows.append(row)
            continue
        city_records = [records[i] for i in row.source_records]
        since = municipal_since(city_records, city_fields)
        labels: list[Lineage] = []
        bases: set[str] = set()
        reasons: set[str] = set()
        for assertion_id in row.osm_assertions:
            assertion = reconciled.assertions[assertion_id]
            finding = _finding(
                history,
                assertion.source_record,
                assertion.raw_attribute,
                str(assertion.raw_value),
                since,
            )
            if finding is None:
                labels.append(Lineage.UNKNOWN)
                reasons.add("the value is absent from the element's history")
                continue
            labels.append(finding.label)
            reasons.update(finding.reasons)
            if finding.basis:
                bases.add(finding.basis)
            if not assertion.history.assessed:
                reconciled.assertions[assertion_id] = _with_history(assertion, finding)
        combined = combine(labels)
        rows.append(
            replace(
                row,
                lineage=_LINEAGE[combined] if combined else LineageRelationship.UNKNOWN,
                lineage_basis=",".join(sorted(bases)) or None,
                lineage_reasons=tuple(sorted(reasons)),
                target_geometry_lineage=_geometry(row, city_records, history, since, osm),
            )
        )
    reconciled.reconciliations = rows


#: The observation-date basis for a value a survey app entered. StreetComplete
#: and Every Door record answers on the spot, so the edit dates the observation;
#: a ``source=survey`` a mapper typed does not say when the survey was.
SURVEY_APP_EDIT = "introducing_edit_by_survey_app"


def _with_history(assertion: Assertion, finding: LineageFinding) -> Assertion:
    """The facts of the edit that introduced the value; the same whatever it is compared with.

    An explicit observation tag keeps precedence: it is later than the edit
    that introduced the value.
    """
    step = finding.steps[0] if finding.steps else None
    dates = replace(assertion.dates, osm_value_since=step.timestamp if step else None)
    surveyed = step is not None and any(
        e.signal is Signal.SURVEY and e.where == "changeset created_by" for e in step.evidence
    )
    if surveyed and step is not None and dates.observation_date is None:
        dates = replace(
            dates, observation_date=step.timestamp[:10], observation_date_basis=SURVEY_APP_EDIT
        )
    return replace(
        assertion,
        dates=dates,
        history=ValueHistory(
            assessed=True,
            introducing_changeset=step.changeset if step else None,
            stated_sources=tuple(sorted({str(e.signal) for e in step.evidence})) if step else (),
        ),
    )


def _geometry(
    row: Reconciliation,
    records: Sequence[Record],
    history: History,
    since: str | None,
    osm: OsmIndex,
) -> str:
    """The target element's geometry lineage, apart from its value's."""
    found = history.elements.get(row.target.element)
    if found is None:
        return str(LineageRelationship.UNKNOWN)
    coincide = False
    if row.target.target_type == OSM_WAY_EXTENT and len(records) == 1:
        line = osm.lines.get(int(row.target.element.split("/")[1]))
        if line is not None:
            coincide = vertex_coincidence(
                {"vertices": vertex_agreement(records[0].geometry, line).as_dict()}
            )
    finding = geometry_lineage(
        found, history.changesets, municipal_since=since, vertex_coincidence=coincide
    )
    return str(_LINEAGE[finding.label])


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

#: How far past a way's end a GEO-05 extent may reach from rounding alone.
_EXTENT_SLACK_M = 0.01


def invariant_violations(reconciled: Reconciled, osm: OsmIndex) -> list[str]:
    """Every row whose classification disagrees with what it holds. Empty when sound.

    A relationship is only as good as the assertions behind it: agreement with
    no usable City assertion, a curb cut on a whole way, or a row that could
    reach routing would each be a silent error.
    """
    problems: list[str] = []
    for row in reconciled.reconciliations:
        name = row.reconciliation_id
        city = [reconciled.assertions[a] for a in row.kitchener_assertions]
        withheld = [reconciled.assertions[a] for a in row.kitchener_withheld]
        osm_side = [reconciled.assertions[a] for a in row.osm_assertions]
        relationship = row.relationship
        if relationship in TWO_SIDED and not (city and osm_side):
            problems.append(f"{name}: {relationship} without an assertion from each source")
        elif relationship is Relationship.SOURCE_ONLY_KITCHENER and not city:
            problems.append(f"{name}: City-only without a usable City assertion")
        elif relationship is Relationship.SOURCE_ONLY_OSM and (city or not osm_side):
            problems.append(f"{name}: OSM-only with a City assertion or without an OSM one")
        elif relationship is Relationship.UNKNOWN and city:
            problems.append(f"{name}: unknown despite a usable City assertion")
        if any(not a.usable or a.source_id != KITCHENER_SOURCE for a in city):
            problems.append(f"{name}: a listed City assertion is not usable City evidence")
        if any(a.usable for a in withheld):
            problems.append(f"{name}: a usable City assertion is withheld")
        if any(a.source_id != OSM_SOURCE for a in osm_side):
            problems.append(f"{name}: a listed OSM assertion is not from OSM")
        if row.topic is Topic.CURB_RAMP and row.target.target_type != OSM_NODE:
            problems.append(f"{name}: a curb ramp reconciled beyond its kerb node")
        if row.target.target_type == OSM_WAY_EXTENT:
            line = osm.lines.get(int(row.target.element.split("/")[1]))
            start, end = row.target.from_m, row.target.to_m
            if (
                line is None
                or start is None
                or end is None
                or start > end
                or start < 0
                or end > line.length + _EXTENT_SLACK_M
            ):
                problems.append(f"{name}: the local extent is not within its way")
        if row.routing_eligibility != NOT_ROUTING_ELIGIBLE:
            problems.append(f"{name}: routing eligible")
    return problems


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def class_accounting(
    records: Mapping[int, Record], decisions: Mapping[int, Decision], gates: Mapping[int, Gate]
) -> dict[str, Any]:
    """For each evidence class, how many full-pilot decisions reach reconciliation, and why not."""
    classes: dict[str, tuple[Topic, Callable[[Record], bool]]] = {
        "surface": (Topic.SURFACE, lambda r: r.surface_material is not None),
        "curb_cut": (Topic.CURB_RAMP, lambda r: r.curb_cut),
        "structure": (Topic.STRUCTURE, lambda r: r.structure is not None),
    }
    result: dict[str, Any] = {}
    for name, (topic, member) in classes.items():
        counts: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        detail: Counter[str] = Counter()
        for record_id, found in gates.items():
            record = records[record_id]
            if not member(record):
                continue
            counts["records"] += 1
            if topic in found.accepted:
                counts["eligible"] += 1
                continue
            reason = found.exclusions[topic]
            counts[EXCLUSION_CATEGORY[reason]] += 1
            reasons[str(reason)] += 1
            if reason is Exclusion.STRUCTURE_NOT_IN_OSM or topic is Topic.STRUCTURE:
                detail[f"{reason}: {record.structure}"] += 1
        result[name] = {
            **dict(sorted(counts.items())),
            "by_reason": dict(sorted(reasons.items())),
            **({"by_reason_and_type": dict(sorted(detail.items()))} if detail else {}),
        }
    return result
