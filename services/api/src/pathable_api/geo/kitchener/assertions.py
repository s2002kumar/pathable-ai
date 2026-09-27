"""The evidence model PA-GEO-06 reconciles in: sources, assertions, and how they relate.

Bounded to what OpenStreetMap and the City of Kitchener actually showed in
PA-GEO-03, -04 and -05. It is not a universal ontology:

- a **source** — who published the data, which snapshot, under which licence;
- an **assertion** — one source's claim about one property of one record: the
  raw attribute and value exactly as published, a normalized value only where
  the mapping is defensible, the value's state (a template default is kept, and
  marked unusable), what kind of claim it is, typed dates, and lineage;
- a **reconciliation** — for one property at one local target, every
  assertion from each source side by side, how they relate semantically, how
  they relate by lineage, and why none of it may be routed on.

Three rules the model makes hard to break:

- **Agreement is not independence.** The semantic relationship and the lineage
  relationship are separate fields. Nothing combines them into a confidence.
- **Nothing is resolved.** A conflict keeps both assertions and says so; there
  is no chosen value and no source precedence.
- **Dates keep their meaning.** Capture, observation, inspection, record
  maintenance and OSM edit times are different columns. Only an observation
  date is read as freshness.

Nothing here routes: every reconciliation is ``not_routing_eligible``, and the
blockers say why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

ASSERTION_SCHEMA_VERSION = "kitchener-geo06-assertion-schema-v1"


class Topic(StrEnum):
    """What a reconciliation is about. Railing is kept apart: no route reads it."""

    SURFACE = "surface"
    CURB_RAMP = "curb_ramp"
    STRUCTURE = "structure"
    RAILING = "railing"


#: Topics PathAble's routing reads from OpenStreetMap. Railing is not one.
ROUTING_TOPICS = frozenset({Topic.SURFACE, Topic.CURB_RAMP, Topic.STRUCTURE})


class Relationship(StrEnum):
    """How two sources' assertions about one property relate, semantically only."""

    #: Both assert the same value.
    AGREEMENT = "agreement"
    #: Both assert values that are consistent without being the same claim: one
    #: is more specific, the two overlap, or they state different aspects.
    COMPATIBLE = "compatible"
    #: Both assert comparable values that cannot both hold.
    CONFLICT = "conflict"
    #: Both assert something, but the claims are too different to compare.
    INCOMPARABLE = "incomparable"
    SOURCE_ONLY_KITCHENER = "source_only_kitchener"
    SOURCE_ONLY_OSM = "source_only_osm"
    #: Neither source asserts anything usable about the property here.
    UNKNOWN = "unknown"


#: Relationships where both sources assert something.
TWO_SIDED = frozenset(
    {
        Relationship.AGREEMENT,
        Relationship.COMPATIBLE,
        Relationship.CONFLICT,
        Relationship.INCOMPARABLE,
    }
)


class Specificity(StrEnum):
    #: The two claims are at the same level of detail (whether or not they agree).
    SAME_LEVEL = "same_level"
    KITCHENER_MORE_SPECIFIC = "kitchener_more_specific"
    OSM_MORE_SPECIFIC = "osm_more_specific"
    #: Related terms, neither containing the other.
    OVERLAPPING = "overlapping"
    #: The two claims are about different properties of the same thing.
    DIFFERENT_PROPERTY = "different_property"
    NOT_APPLICABLE = "not_applicable"


class LineageRelationship(StrEnum):
    """Whether OSM's value may share an origin with the City's, from OSM's edit history."""

    #: The edit that introduced OSM's value names the City's data.
    KNOWN_SHARED = "known_shared_lineage"
    #: The edit names a source the City's data may share: the Region's or the
    #: City's own photographs (Esri World Imagery since 2016), an import.
    POSSIBLE_SHARED = "possible_shared_lineage"
    #: Every edit states an unrelated source. What OSM's metadata states, not
    #: proven independence.
    APPARENTLY_INDEPENDENT = "apparently_independent"
    UNKNOWN = "unknown_lineage"
    #: No history was read for the element.
    NOT_ASSESSED = "not_assessed"
    #: Only one source asserts anything.
    NOT_APPLICABLE = "not_applicable"


class EvidenceState(StrEnum):
    """What the evidence amounts to at the target, without choosing a value."""

    CONSISTENT = "consistent_assertions"
    UNRESOLVED_CONFLICT = "unresolved_conflict"
    INCOMPARABLE = "incomparable_assertions"
    SINGLE_SOURCE = "single_source"
    NO_ASSERTION = "no_assertion"


def evidence_state(relationship: Relationship) -> EvidenceState:
    match relationship:
        case Relationship.AGREEMENT | Relationship.COMPATIBLE:
            return EvidenceState.CONSISTENT
        case Relationship.CONFLICT:
            return EvidenceState.UNRESOLVED_CONFLICT
        case Relationship.INCOMPARABLE:
            return EvidenceState.INCOMPARABLE
        case Relationship.SOURCE_ONLY_KITCHENER | Relationship.SOURCE_ONLY_OSM:
            return EvidenceState.SINGLE_SOURCE
        case _:
            return EvidenceState.NO_ASSERTION


NOT_ROUTING_ELIGIBLE = "not_routing_eligible"
RESEARCH_CANDIDATE = "research_candidate"


class Blocker(StrEnum):
    """Why a reconciliation cannot reach routing. Each is a separate gate."""

    #: The founder licensing gate on combining Kitchener data with the
    #: OSM-derived routing database is closed.
    LICENSING = "blocked_by_licensing"
    #: No person, field check or external party has validated the matches or
    #: the reconciliation.
    VALIDATION = "blocked_by_validation"
    #: No routing policy says which evidence classes may change feasibility or
    #: cost, under what conditions.
    ROUTING_POLICY = "blocked_by_routing_policy"
    #: The property is not one PathAble routes on.
    NOT_A_ROUTING_PROPERTY = "not_a_routing_property"


def blockers(topic: Topic, *, has_kitchener: bool) -> tuple[str, ...]:
    """Every reason a reconciliation stays out of routing, in a fixed order."""
    found = [Blocker.ROUTING_POLICY]
    if has_kitchener:
        found += [Blocker.LICENSING, Blocker.VALIDATION]
    if topic not in ROUTING_TOPICS:
        found.append(Blocker.NOT_A_ROUTING_PROPERTY)
    return tuple(sorted(str(b) for b in found))


# ---------------------------------------------------------------------------
# Sources and assertions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Source:
    source_id: str
    provider: str
    dataset: str
    publications: tuple[str, ...]
    #: The frozen snapshot or extract the assertions were read from.
    snapshot: str
    #: When the snapshot was retrieved or the extract's source was published.
    as_of: str | None
    licence: str
    licence_url: str | None
    attribution: str
    role: str


@dataclass(frozen=True, slots=True)
class Dates:
    """Every date an assertion carries, each under what it actually dates."""

    #: City ``SOURCE_DATE``: when the record was captured (for orthoimagery
    #: sources, the photographs' date). Not when any attribute was observed.
    source_capture_date: str | None = None
    #: When the value was observed, and only where something dates an
    #: observation: an OSM ``check_date:<key>``, ``check_date`` or
    #: ``survey:date`` tag, or else the edit of a survey app (StreetComplete,
    #: Every Door) that entered the value. ``observation_date_basis`` says
    #: which. The City supplies no per-attribute observation date.
    observation_date: str | None = None
    observation_date_basis: str | None = None
    #: City ``LAST_INSPECTION_YEAR``: the year of an inspection, not what it found.
    inspection_year: int | None = None
    #: City ``CREATE_DATE``: database maintenance.
    record_created_at: str | None = None
    #: City ``UPDATE_DATE``: database maintenance, 98.1% on one bulk day. Never freshness.
    record_modified_at: str | None = None
    #: When OSM's element last changed in any way: an edit, not an observation.
    osm_edit_timestamp: str | None = None
    #: When OSM's current value entered OSM, from the element's history.
    osm_value_since: str | None = None

    @property
    def freshness_basis(self) -> str:
        """The only date read as freshness is an observation date."""
        return "observation_date" if self.observation_date else "no_observation_date"


@dataclass(frozen=True, slots=True)
class ValueHistory:
    """What OSM's edit history says about how a value entered OSM: facts, not a verdict.

    Whether they make the value independent of the City's depends on the City
    record it is compared with (an edit older than the record cannot have
    copied it), so that judgement belongs to the reconciliation.
    """

    assessed: bool = False
    introducing_changeset: int | None = None
    #: The source classes the introducing edit states (PA-GEO-04's signals).
    stated_sources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Assertion:
    """One source's claim about one property of one record, exactly as published."""

    assertion_id: str
    source_id: str
    #: ``kitchener/<ACTIVETRANSPORTID>``, ``node/<id>`` or ``way/<id>``.
    source_record: str
    source_record_version: int | None
    topic: Topic
    #: The property claimed (written as ``property``): the City's curb cut and
    #: OSM's kerb are different properties of one corner.
    prop: str
    raw_attribute: str
    raw_value: str | None
    normalized_value: str | None
    #: ``non_default``, ``template_default``, ``unknown``, ``null``,
    #: ``not_applicable`` … for the City; ``asserted`` for an OSM tag.
    value_state: str
    #: Whether the value may be read as evidence at all. A template default,
    #: an unknown or a null never is.
    usable: bool
    #: ``administrative_assertion``, ``observed_survey``, ``template_default`` …
    #: for the City; ``osm_contributor_edit`` for OSM, whose method is only what
    #: the edit states (``history.stated_sources``).
    evidence_origin: str
    #: ``kitchener_record``, ``osm_node`` or ``osm_way``: what the claim is about.
    scope: str
    #: The City's SOURCE vocabulary class (orthoimagery, the 2015 trail
    #: inventory …): how the record was captured. The City documents no
    #: per-attribute source, so its lineage relative to OSM is not known.
    capture_source: str | None = None
    dates: Dates = field(default_factory=Dates)
    history: ValueHistory = field(default_factory=ValueHistory)
    note: str | None = None


# ---------------------------------------------------------------------------
# Reconciliations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Target:
    """The local physical target: an OSM node, or the metres of a way a City record covers."""

    element: str
    osm_version: int | None
    target_type: str
    from_m: float | None = None
    to_m: float | None = None


OSM_NODE = "osm_node"
OSM_WAY_EXTENT = "osm_way_extent"


@dataclass(frozen=True, slots=True)
class Reconciliation:
    reconciliation_id: str
    topic: Topic
    #: The property reconciled, written as ``property``.
    prop: str
    target: Target
    #: The City records whose accepted correspondence reaches this target.
    source_records: tuple[int, ...]
    correspondence_rules: tuple[str, ...]
    correspondence_relationship: str | None
    #: The City's usable assertions: the only City values the relationship reads.
    kitchener_assertions: tuple[str, ...]
    #: The City's values here that are not evidence — a template default, an
    #: unknown — kept so a reader sees why the City side is empty.
    kitchener_withheld: tuple[str, ...]
    osm_assertions: tuple[str, ...]
    kitchener_values: tuple[str, ...]
    osm_values: tuple[str, ...]
    relationship: Relationship
    specificity: Specificity
    #: The vocabulary rule that classified the pair, in words.
    rule: str
    #: OSM's value relative to the City's, from OSM's edit history. Never
    #: folded into the relationship.
    lineage: LineageRelationship = LineageRelationship.NOT_APPLICABLE
    lineage_basis: str | None = None
    lineage_reasons: tuple[str, ...] = ()
    #: The target element's own geometry lineage, kept apart from its value's.
    target_geometry_lineage: str = str(LineageRelationship.NOT_APPLICABLE)

    @property
    def evidence_state(self) -> EvidenceState:
        return evidence_state(self.relationship)

    @property
    def conflict(self) -> str | None:
        """A conflict stays open: both assertions are kept and neither is chosen."""
        if self.relationship is Relationship.CONFLICT:
            return "unresolved: both assertions are kept and neither is chosen"
        return None

    @property
    def routing_property(self) -> bool:
        return self.topic in ROUTING_TOPICS

    @property
    def blockers(self) -> tuple[str, ...]:
        return blockers(self.topic, has_kitchener=bool(self.kitchener_assertions))

    @property
    def routing_eligibility(self) -> str:
        return NOT_ROUTING_ELIGIBLE
