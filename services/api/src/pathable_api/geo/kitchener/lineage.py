"""Labels for the lineage study, what each one means, and the rules that assign lineage.

Two kinds of judgement live here, and they are kept apart:

- **Manual labels** — correspondence, relationship, geometry and topology —
  are a reviewer's, read from the review artifact. This module defines them
  (before anyone applies them), validates a label file against the candidates
  it was made from, and measures how consistently they repeat. It never
  assigns one.
- **Lineage labels** are assigned by deterministic rules over an element's
  OSM history and the changesets behind it. They are conservative:
  ``apparently_independent`` needs positive evidence, and the absence of a
  municipal source tag is not evidence of anything.

Geometry lineage and attribute lineage are separate questions with separate
answers: a way traced from imagery can carry a kerb value copied from the City.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pathable_api.geo.kitchener.osm_history import Changeset, Contribution

LABELS_FORMAT_VERSION = 1


class LabelError(ValueError):
    """A label file does not fit the definitions or the candidates it describes."""


# ---------------------------------------------------------------------------
# Manual labels, defined before they are applied
# ---------------------------------------------------------------------------


class Correspondence(StrEnum):
    OBVIOUS = "obvious_correspondence"
    AMBIGUOUS = "ambiguous_correspondence"
    NONE = "no_correspondence"
    NOT_COMPARABLE = "not_comparable"


class Relationship(StrEnum):
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"


class GeometryRelation(StrEnum):
    CLOSELY_ALIGNED = "closely_aligned"
    OFFSET = "offset"
    DIFFERENTLY_SPLIT = "differently_split"
    DIFFERENTLY_MERGED = "differently_merged"
    PARTIAL_OVERLAP = "partial_overlap"
    MATERIALLY_DIFFERENT = "materially_different"


class Topology(StrEnum):
    AGREEMENT = "topology_agreement"
    DISAGREEMENT = "topology_disagreement"
    AMBIGUOUS = "ambiguous_topology"
    NOT_ASSESSED = "not_assessed"


class Representation(StrEnum):
    """How OSM carries the facility, when it does."""

    SEPARATE_WAY = "separate_way"
    ROAD_ATTRIBUTE = "road_attribute"
    NODE = "node"
    NONE = "none"


DEFINITIONS: dict[str, dict[str, str]] = {
    "correspondence": {
        Correspondence.OBVIOUS: (
            "One or more ways in the frozen OSM extract carry the same facility as the "
            "Kitchener record — the same sidewalk, path, stair or crossing; for a virtual link "
            "or an unofficial connection, the same connection across or along the same road "
            "— and a reviewer seeing the geometry, the classes and the road would not "
            "reasonably choose a different way or conclude that none corresponds. Closeness "
            "alone is not enough: a parallel path on the other side of a road is not a "
            "correspondence however near it runs."
        ),
        Correspondence.AMBIGUOUS: (
            "OSM might carry the facility, but the reviewer cannot say which way, or whether "
            "a nearby way is the same facility or a different one, or OSM carries it only "
            "indirectly (a sidewalk tag on the road, a crossing node without a way) so the "
            "shapes cannot be compared."
        ),
        Correspondence.NONE: (
            "Nothing in the frozen extract plausibly carries the facility; the nearby "
            "candidates are recognisably other facilities, or there are none."
        ),
        Correspondence.NOT_COMPARABLE: (
            "The record does not describe something whose correspondence to an OSM way can "
            "be judged: a record whose physical or virtual nature the City leaves unresolved "
            "and neither the geometry nor OSM settles, or an unusable geometry."
        ),
    },
    "relationship": {
        Relationship.ONE_TO_ONE: (
            "The record and one OSM way cover substantially the same extent, and that way "
            "carries no other physical City record of the same facility. City virtual links, "
            "and connector stubs of a few metres at a junction, are not counted: they are the "
            "junction, not the facility."
        ),
        Relationship.ONE_TO_MANY: (
            "The record corresponds to several OSM ways; OSM splits it. A record that runs "
            "about a junction's width onto the next way is not split."
        ),
        Relationship.MANY_TO_ONE: (
            "The corresponding OSM way also carries other physical City records of the same "
            "facility; OSM merges what the City splits. Virtual links and junction stubs are "
            "not counted."
        ),
        Relationship.MANY_TO_MANY: "Several records and several ways, with no clean nesting.",
    },
    "geometry": {
        GeometryRelation.CLOSELY_ALIGNED: (
            "Same extent, give or take about a junction's width (5 m) at each end, and the "
            "shapes run together within what digitising two sources would produce. An OSM way "
            "that runs on to a road centreline where the City's network stops at the kerb is "
            "not a difference in extent."
        ),
        GeometryRelation.OFFSET: (
            "Same extent and shape, displaced sideways by a consistent distance beyond close "
            "alignment."
        ),
        GeometryRelation.DIFFERENTLY_SPLIT: (
            "The shapes agree, but OSM divides the facility into more pieces than the City "
            "(the one-to-many case)."
        ),
        GeometryRelation.DIFFERENTLY_MERGED: (
            "The shapes agree, but OSM carries in one piece what the City divides (the "
            "many-to-one case)."
        ),
        GeometryRelation.PARTIAL_OVERLAP: (
            "They share only part of their extent: one runs beyond the other by more than a "
            "junction's width, and no other record or way of the same facility accounts for "
            "the difference."
        ),
        GeometryRelation.MATERIALLY_DIFFERENT: (
            "The facility corresponds but its shape does not: a different alignment, a "
            "different route around an obstacle, a missing or extra section."
        ),
    },
    "geometry_precedence": {
        "order": (
            "materially_different, then offset, then partial_overlap, then differently_split "
            "or differently_merged, then closely_aligned: the first that applies."
        ),
    },
    "topology": {
        Topology.AGREEMENT: (
            "Among the facilities both sources have, the record's ends join the same ones, it "
            "lies beside the same road on the same side, and it crosses the same road at the "
            "same place. A facility only one source models — a City virtual link, an informal "
            "side path, a road centreline the City does not map — is a coverage difference, "
            "named in the note; it does not decide the label. Facilities joining along the "
            "record, rather than at its ends, are not compared."
        ),
        Topology.DISAGREEMENT: (
            "Among facilities both sources have, the connections differ: an end joins a "
            "different facility, one source connects two facilities the other keeps apart, "
            "the facility lies on another side of the road, or it crosses a different road."
        ),
        Topology.AMBIGUOUS: "The connections cannot be compared with confidence.",
        Topology.NOT_ASSESSED: "No correspondence to compare, or the record is not comparable.",
    },
    "representation": {
        Representation.SEPARATE_WAY: "OSM draws the facility as its own way.",
        Representation.ROAD_ATTRIBUTE: "OSM records it only as a tag on the road.",
        Representation.NODE: "OSM records it only as a node (a crossing point, say).",
        Representation.NONE: "OSM does not record it.",
    },
    "citation": {
        "corner_piece": (
            "For a City piece of a metre or two that OSM collapses into a junction, cite the "
            "kerb node OSM has there, or else every way that meets at that junction."
        ),
    },
}

#: The version of the definitions above. Version 1 is what both labelling passes
#: used; version 2 settles what their disagreements showed was ambiguous.
DEFINITIONS_VERSION = 2
DEFINITION_REFINEMENTS: tuple[dict[str, str], ...] = (
    {
        "version": "2",
        "prompted_by": "the repeat review's topology disagreements (30 of 40 agreed)",
        "change": (
            "Topology compares only facilities both sources have, at the record's ends. A City "
            "virtual link, an informal side path or a road centreline only one source models "
            "is a coverage difference, noted but not deciding the label; facilities joining "
            "along the record are not compared."
        ),
    },
    {
        "version": "2",
        "prompted_by": "the relationship and geometry disagreements on 88440, 392049 and 307104",
        "change": (
            "Virtual links and junction stubs of a few metres are not counted in a "
            "relationship; about a junction's width (5 m) of end slop is not a difference in "
            "extent; an OSM way running on to a road centreline is not either."
        ),
    },
    {
        "version": "2",
        "prompted_by": "the different elements cited for the corner pieces 321269 and 321409",
        "change": (
            "A corner piece OSM collapses into a junction cites the kerb node there, or else "
            "every way that meets at the junction."
        ),
    },
)


@dataclass(frozen=True, slots=True)
class RecordLabel:
    activetransportid: int
    correspondence: Correspondence
    osm: tuple[str, ...]
    representation: Representation
    relationship: Relationship | None
    geometry: GeometryRelation | None
    topology: Topology
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "activetransportid": self.activetransportid,
            "correspondence": str(self.correspondence),
            "osm": list(self.osm),
            "representation": str(self.representation),
            "relationship": str(self.relationship) if self.relationship else None,
            "geometry": str(self.geometry) if self.geometry else None,
            "topology": str(self.topology),
            "note": self.note,
        }


def parse_label(item: Mapping[str, Any], candidates: Iterable[str]) -> RecordLabel:
    """One record's labels, refused unless they fit the definitions and the candidates."""
    record = int(item["activetransportid"])

    def fail(message: str) -> LabelError:
        return LabelError(f"record {record}: {message}")

    try:
        correspondence = Correspondence(item["correspondence"])
        representation = Representation(item.get("representation") or "none")
        relationship = Relationship(item["relationship"]) if item.get("relationship") else None
        geometry = GeometryRelation(item["geometry"]) if item.get("geometry") else None
        topology = Topology(item.get("topology") or "not_assessed")
    except ValueError as error:
        raise fail(str(error)) from error
    osm = tuple(str(value) for value in item.get("osm") or [])
    known = set(candidates)
    unknown = [value for value in osm if value not in known]
    if unknown:
        raise fail(f"{', '.join(unknown)} were not among its candidate ways or nearby nodes")
    if correspondence is Correspondence.OBVIOUS:
        if not any(value.startswith("way/") for value in osm):
            raise fail("an obvious correspondence names at least one OSM way")
        if relationship is None:
            raise fail("an obvious correspondence needs a relationship")
    elif relationship is not None:
        raise fail("only an obvious correspondence has a relationship")
    if correspondence in (Correspondence.NONE, Correspondence.NOT_COMPARABLE):
        if osm or geometry is not None:
            raise fail(f"{correspondence} names no OSM way and no geometry class")
        if topology is not Topology.NOT_ASSESSED:
            raise fail(f"{correspondence} has no topology to assess")
    return RecordLabel(
        activetransportid=record,
        correspondence=correspondence,
        osm=osm,
        representation=representation,
        relationship=relationship,
        geometry=geometry,
        topology=topology,
        note=str(item.get("note") or ""),
    )


def parse_labels(
    document: Mapping[str, Any], candidates: Mapping[int, Iterable[str]]
) -> dict[int, RecordLabel]:
    """A label file: every labelled record must be in the study, once."""
    if document.get("kitchener_geo04_labels_version") != LABELS_FORMAT_VERSION:
        msg = "not a PA-GEO-04 label file of a known version."
        raise LabelError(msg)
    labels: dict[int, RecordLabel] = {}
    for item in document.get("records") or []:
        record = int(item["activetransportid"])
        if record not in candidates:
            msg = f"record {record} is not in the study sample."
            raise LabelError(msg)
        if record in labels:
            msg = f"record {record} is labelled twice."
            raise LabelError(msg)
        labels[record] = parse_label(item, candidates[record])
    return labels


# ---------------------------------------------------------------------------
# Repeat-label consistency
# ---------------------------------------------------------------------------


def raw_agreement(
    first: Mapping[int, str | None], second: Mapping[int, str | None]
) -> dict[str, Any]:
    """How often two passes gave the same label, over the records both labelled.

    Raw agreement only: with both passes made by the same agent, a chance-
    corrected statistic would describe a rater pair that does not exist.
    """
    common = sorted(set(first) & set(second))
    matrix: dict[str, Counter[str]] = {}
    disagreements = []
    for record in common:
        a, b = str(first[record]), str(second[record])
        matrix.setdefault(a, Counter())[b] += 1
        if a != b:
            disagreements.append({"activetransportid": record, "first": a, "second": b})
    agree = len(common) - len(disagreements)
    return {
        "records": len(common),
        "agree": agree,
        "raw_agreement": round(agree / len(common), 3) if common else None,
        "matrix": {a: dict(sorted(row.items())) for a, row in sorted(matrix.items())},
        "disagreements": disagreements,
    }


# ---------------------------------------------------------------------------
# What a changeset or an element says about where its data came from
# ---------------------------------------------------------------------------


class Signal(StrEnum):
    KITCHENER = "kitchener_data"
    #: Region of Waterloo, Ontario or City orthophotos: photographs the City's own
    #: ORTHO-sourced records may have been traced from too.
    PUBLIC_IMAGERY = "public_orthoimagery"
    OTHER_GOVERNMENT = "other_government_data"
    IMPORT = "import_or_external_data"
    SURVEY = "survey"
    STREET_LEVEL = "declared_street_level_imagery"
    DECLARED_IMAGERY = "declared_unrelated_imagery"
    #: What an editor recorded as displayed, not what the mapper said they used.
    EDITOR_IMAGERY = "editor_recorded_imagery"
    EDITOR_STREET_LEVEL = "editor_recorded_street_level_imagery"
    EDITOR_GPS = "editor_recorded_gps_trace"
    UNSPECIFIED_IMAGERY = "unspecified_imagery"
    GOOGLE = "google_named"


#: Signals that tie a contribution to the City's data or to data it may share.
SHARED = frozenset({Signal.PUBLIC_IMAGERY, Signal.OTHER_GOVERNMENT, Signal.IMPORT})
#: Signals made by the mapper (or a survey app), as opposed to recorded by an editor.
DECLARED = frozenset({Signal.SURVEY, Signal.STREET_LEVEL, Signal.DECLARED_IMAGERY})

# Source tags join words with underscores and digits ("Geobase_Import_2009",
# "Bing_2015"), and an underscore is a word character, so a word boundary would
# miss them: a "word" here ends wherever letters do.
_A, _Z = r"(?<![a-z])", r"(?![a-z])"
_IMAGERY_WORDS = r"ortho|aerial|imagery|photo|satellite"
_DATA_WORDS = (
    rf"open ?data|import|data ?set|{_A}gis{_Z}|shapefile|geojson|licen[cs]e|{_A}ogl{_Z}|"
    r"city data|municipal data|active transportation|inventory"
)
_KITCHENER = re.compile(rf"{_A}kitchener{_Z}", re.IGNORECASE)
_MUNICIPAL_PLACES = re.compile(
    rf"region of waterloo|waterloo region|city of waterloo|{_A}cambridge{_Z}|{_A}woolwich{_Z}",
    re.IGNORECASE,
)
#: The Region's and the Province's orthophotos, however a mapper or an editor
#: names them: "Region of Waterloo 2024", the Region's imagery WMS, the Ontario mosaics.
_PUBLIC_IMAGERY = re.compile(
    r"region of waterloo \d{4}|regionofwaterloo|waimagery|geospatial ontario|"
    rf"ontario (imagery|mosaic|orthophoto)|{_A}swoop{_Z}|{_A}oids{_Z}",
    re.IGNORECASE,
)
_GOVERNMENT = re.compile(
    rf"canvec|geobase|nrcan|statistics canada|statcan|ontario road network|{_A}orn{_Z}|"
    rf"land information ontario|{_A}lio{_Z}|government",
    re.IGNORECASE,
)
_IMAGERY = re.compile(_IMAGERY_WORDS, re.IGNORECASE)
_DATA = re.compile(_DATA_WORDS, re.IGNORECASE)
# Not preceded by a letter: "Geobase_Import_2009" names an import.
_IMPORT = re.compile(rf"{_A}import", re.IGNORECASE)
_SURVEY = re.compile(
    rf"{_A}survey|{_A}gps{_Z}|{_A}gnss{_Z}|on[- ]the[- ]ground|local knowledge|ground truth|"
    rf"{_A}in person{_Z}|streetcomplete|every ?door",
    re.IGNORECASE,
)
_STREET_LEVEL = re.compile(
    r"mapillary|kartaview|openstreetcam|panoramax|streetside|streetlevel|street[- ]level",
    re.IGNORECASE,
)
_NAMED_IMAGERY = re.compile(
    rf"{_A}bing{_Z}|{_A}esri{_Z}|mapbox|maxar|digitalglobe|world ?imagery|nearmap|vexcel",
    re.IGNORECASE,
)
_GOOGLE = re.compile(r"google", re.IGNORECASE)
_SURVEY_EDITORS = re.compile(r"^(streetcomplete|every ?door)", re.IGNORECASE)
#: The words iD writes into a changeset's source tag by itself, from the layers
#: that were on screen. A mapper's own choices ("survey", "local knowledge",
#: "gps") are ticked, not written for them, so those stay the mapper's.
_ID_RECORDED = frozenset(
    {
        "aerial imagery",
        "streetlevel imagery",
        "mapillary",
        "openstreetcam",
        "kartaview",
        "streetside",
        "bing streetside",
        "panoramax",
    }
)


def signals_in_source(value: str) -> set[Signal]:
    """What a ``source``-like value, a tag a mapper wrote to name a source, says."""
    found: set[Signal] = set()
    public_imagery = bool(_PUBLIC_IMAGERY.search(value))
    if public_imagery:
        found.add(Signal.PUBLIC_IMAGERY)
    if _KITCHENER.search(value):
        found.add(Signal.PUBLIC_IMAGERY if _IMAGERY.search(value) else Signal.KITCHENER)
    if _MUNICIPAL_PLACES.search(value) and not public_imagery:
        found.add(Signal.PUBLIC_IMAGERY if _IMAGERY.search(value) else Signal.OTHER_GOVERNMENT)
    if _GOVERNMENT.search(value):
        found.add(Signal.OTHER_GOVERNMENT)
    if _IMPORT.search(value) or re.search(r"open ?data", value, re.IGNORECASE):
        found.add(Signal.IMPORT)
    if _SURVEY.search(value):
        found.add(Signal.SURVEY)
    if _STREET_LEVEL.search(value):
        found.add(Signal.STREET_LEVEL)
    if _NAMED_IMAGERY.search(value):
        found.add(Signal.DECLARED_IMAGERY)
    if _GOOGLE.search(value):
        found.add(Signal.GOOGLE)
    if not found and _IMAGERY.search(value):
        found.add(Signal.UNSPECIFIED_IMAGERY)
    return found


def signals_in_imagery_used(value: str) -> set[Signal]:
    """What an editor's record of the layers on screen says, layer by layer."""
    found: set[Signal] = set()
    for layer in (part.strip() for part in value.split(";")):
        if not layer or layer.lower() == "none":
            continue
        if (
            _PUBLIC_IMAGERY.search(layer)
            or _KITCHENER.search(layer)
            or _MUNICIPAL_PLACES.search(layer)
        ):
            found.add(Signal.PUBLIC_IMAGERY)
        elif _STREET_LEVEL.search(layer):
            found.add(Signal.EDITOR_STREET_LEVEL)
        elif ".gpx" in layer.lower():
            found.add(Signal.EDITOR_GPS)
        elif _NAMED_IMAGERY.search(layer):
            found.add(Signal.EDITOR_IMAGERY)
        elif _GOOGLE.search(layer):
            found.add(Signal.GOOGLE)
        else:
            found.add(Signal.UNSPECIFIED_IMAGERY)
    return found


def signals_in_changeset_source(value: str, *, editor: str) -> set[Signal]:
    """A changeset's source tag. From iD, the layer words are the editor's own record."""
    if not editor.startswith("iD "):
        return signals_in_source(value)
    found: set[Signal] = set()
    for word in (part.strip() for part in value.split(";")):
        if not word:
            continue
        if word.lower() in _ID_RECORDED:
            street_level = _STREET_LEVEL.search(word)
            found.add(Signal.EDITOR_STREET_LEVEL if street_level else Signal.UNSPECIFIED_IMAGERY)
        else:
            found |= signals_in_source(word)
    return found


def signals_in_comment(value: str) -> set[Signal]:
    """What free text says. A place name alone is not a source: "Kitchener" must
    come with words about data or imagery to count."""
    found: set[Signal] = set()
    data = bool(_DATA.search(value))
    imagery = bool(_IMAGERY.search(value))
    for pattern, as_data in (
        (_KITCHENER, Signal.KITCHENER),
        (_MUNICIPAL_PLACES, Signal.OTHER_GOVERNMENT),
    ):
        if pattern.search(value):
            if data:
                found.add(as_data)
            elif imagery:
                found.add(Signal.PUBLIC_IMAGERY)
    if _IMPORT.search(value):
        found.add(Signal.IMPORT)
    if _SURVEY.search(value):
        found.add(Signal.SURVEY)
    if _STREET_LEVEL.search(value):
        found.add(Signal.STREET_LEVEL)
    return found


@dataclass(frozen=True, slots=True)
class Evidence:
    """One statement about a source, and where it was found."""

    signal: Signal
    where: str
    value: str

    def as_dict(self) -> dict[str, str]:
        return {"signal": str(self.signal), "where": self.where, "value": self.value}


#: Changeset comments are not committed; for them the evidence records the
#: words that matched, not the text.
_COMMENT_EXCERPT = re.compile(
    rf"[^.;,]*(kitchener|waterloo|{_DATA_WORDS}|{_IMAGERY_WORDS}|survey|mapillary)[^.;,]*",
    re.IGNORECASE,
)


def changeset_evidence(changeset: Changeset | None) -> list[Evidence]:
    if changeset is None:
        return []
    evidence: list[Evidence] = []
    tags = changeset.tags
    editor = tags.get("created_by", "")
    if "source" in tags:
        evidence.extend(
            Evidence(signal, "changeset source", tags["source"])
            for signal in sorted(signals_in_changeset_source(tags["source"], editor=editor))
        )
    if "imagery_used" in tags:
        evidence.extend(
            Evidence(signal, "changeset imagery_used", tags["imagery_used"])
            for signal in sorted(signals_in_imagery_used(tags["imagery_used"]))
        )
    if "comment" in tags:
        for signal in sorted(signals_in_comment(tags["comment"])):
            match = _COMMENT_EXCERPT.search(tags["comment"])
            excerpt = match.group(0).strip() if match else ""
            evidence.append(Evidence(signal, "changeset comment", excerpt[:80]))
    if tags.get("import", "").lower() in ("yes", "true"):
        evidence.append(Evidence(Signal.IMPORT, "changeset import", tags["import"]))
    if _SURVEY_EDITORS.search(editor):
        evidence.append(Evidence(Signal.SURVEY, "changeset created_by", editor.split(" ")[0]))
    return evidence


def element_source_evidence(
    before: Mapping[str, str] | None, after: Mapping[str, str], keys: Sequence[str]
) -> list[Evidence]:
    """Source tags a contribution set or changed on the element itself.

    A ``source`` tag outlives the edit that wrote it, so it is evidence only for
    the contribution that set it.
    """
    evidence: list[Evidence] = []
    for key in keys:
        value = after.get(key)
        if value is None or (before is not None and before.get(key) == value):
            continue
        evidence.extend(
            Evidence(s, f"element {key}", value) for s in sorted(signals_in_source(value))
        )
    return evidence


# ---------------------------------------------------------------------------
# Lineage rules
# ---------------------------------------------------------------------------


class Lineage(StrEnum):
    KNOWN = "known_kitchener_derived"
    POSSIBLE = "possible_shared_lineage"
    INDEPENDENT = "apparently_independent"
    UNKNOWN = "unknown_lineage"


#: The Kitchener-side marker for records whose own source is restricted street-level imagery.
RESTRICTED = "restricted_or_unresolved_lineage"

#: The order in which several ways' lineages combine into a record's: the least
#: independent answer wins.
_COMBINE = (Lineage.KNOWN, Lineage.POSSIBLE, Lineage.UNKNOWN, Lineage.INDEPENDENT)

#: What counts as positive evidence of an unrelated source depends on what the
#: source could show. A shape can be traced from aerial imagery, a GPS trace or
#: on the ground; street-level photos place nothing precisely.
GEOMETRY_EVIDENCE = frozenset(
    {
        Signal.SURVEY,
        Signal.STREET_LEVEL,
        Signal.DECLARED_IMAGERY,
        Signal.EDITOR_IMAGERY,
        Signal.EDITOR_GPS,
    }
)
#: A surface, stairs or a bridge can be seen from above and from the street.
VISIBLE_FROM_ABOVE = frozenset({"surface", "highway", "bridge", "tunnel", "layer"})
ABOVE_EVIDENCE = frozenset(
    {
        Signal.SURVEY,
        Signal.STREET_LEVEL,
        Signal.DECLARED_IMAGERY,
        Signal.EDITOR_IMAGERY,
        Signal.EDITOR_STREET_LEVEL,
    }
)
#: A kerb height, tactile paving or a handrail only from the street.
STREET_EVIDENCE = frozenset({Signal.SURVEY, Signal.STREET_LEVEL, Signal.EDITOR_STREET_LEVEL})


def accepted_evidence(key: str | None) -> frozenset[Signal]:
    """The signals that count as an unrelated source for a geometry (None) or a tag."""
    if key is None:
        return GEOMETRY_EVIDENCE
    return ABOVE_EVIDENCE if key in VISIBLE_FROM_ABOVE else STREET_EVIDENCE


@dataclass(frozen=True, slots=True)
class Step:
    """One contribution, as lineage evidence."""

    timestamp: str
    changeset: int
    kind: str
    evidence: tuple[Evidence, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "changeset": self.changeset,
            "kind": self.kind,
            "evidence": [e.as_dict() for e in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class LineageFinding:
    label: Lineage
    reasons: tuple[str, ...]
    steps: tuple[Step, ...]
    notes: tuple[str, ...] = ()
    #: For apparent independence: "declared" when every contribution's evidence
    #: includes the mapper's own statement, "editor_recorded" when some rests only
    #: on what an editor recorded, "dates" when the shape predates the City's record.
    basis: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": str(self.label),
            "basis": self.basis,
            "reasons": list(self.reasons),
            "steps": [s.as_dict() for s in self.steps],
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class ElementHistory:
    """An element's contributions and whether they reach the frozen state."""

    element: str
    contributions: tuple[Contribution, ...]
    #: False when the frozen extract holds a later state than the history does.
    reaches_frozen_state: bool
    completeness_note: str | None = None


def _kinds(contribution: Contribution) -> str:
    flags = [
        name
        for name, present in (
            ("creation", contribution.creation),
            ("geometry", contribution.geometry_change),
            ("tags", contribution.tag_change),
            ("deletion", contribution.deletion),
        )
        if present
    ]
    return "+".join(flags) or "unflagged"


def _positive(evidence: Iterable[Evidence], accepted: frozenset[Signal]) -> list[Evidence]:
    return [e for e in evidence if e.signal in accepted]


def geometry_lineage(
    history: ElementHistory,
    changesets: Mapping[int, Changeset],
    *,
    municipal_since: str | None,
    vertex_coincidence: bool,
) -> LineageFinding:
    """Where a way's shape likely came from. Conservative by construction.

    ``municipal_since`` is the earliest date the City's record can have existed
    — the earlier of its creation and source dates — so an OSM shape last
    changed before it cannot have been copied from it.
    """
    steps: list[Step] = []
    previous: Mapping[str, str] | None = None
    for contribution in history.contributions:
        if contribution.creation or contribution.geometry_change:
            evidence = changeset_evidence(changesets.get(contribution.changeset))
            evidence += element_source_evidence(
                previous, contribution.tags, ("source", "source:geometry")
            )
            steps.append(
                Step(
                    contribution.timestamp,
                    contribution.changeset,
                    _kinds(contribution),
                    tuple(evidence),
                )
            )
        previous = contribution.tags
    return _decide(
        steps,
        history,
        municipal_since=municipal_since,
        vertex_coincidence=vertex_coincidence,
        accepted=accepted_evidence(None),
        missing_changesets=[s.changeset for s in steps if s.changeset not in changesets],
    )


def attribute_lineage(
    history: ElementHistory,
    changesets: Mapping[int, Changeset],
    key: str,
    *,
    municipal_since: str | None,
    frozen_value: str | None = None,
) -> LineageFinding | None:
    """Where the element's current value of ``key`` came from; ``None`` when it has none.

    ``frozen_value`` is the value in the frozen extract. When the history does
    not end on it — the value was set or changed after the history ends —
    nothing in the history says where it came from, and the finding is unknown
    rather than the lineage of an older value.
    """
    contributions = history.contributions
    last = contributions[-1].tags.get(key) if contributions else None
    if frozen_value is not None and last != frozen_value:
        return LineageFinding(
            Lineage.UNKNOWN,
            ("the frozen value is not in the element's history",),
            (),
            (history.completeness_note or "history ends before the frozen state",),
        )
    if last is None:
        return None
    current = last
    introduced = 0
    for position in range(len(contributions) - 1, -1, -1):
        if contributions[position].tags.get(key) != current:
            introduced = position + 1
            break
    contribution = contributions[introduced]
    previous = contributions[introduced - 1].tags if introduced > 0 else None
    evidence = changeset_evidence(changesets.get(contribution.changeset))
    evidence += element_source_evidence(previous, contribution.tags, ("source", f"source:{key}"))
    step = Step(
        contribution.timestamp, contribution.changeset, _kinds(contribution), tuple(evidence)
    )
    notes = []
    if contribution.creation or contribution.geometry_change:
        notes.append("introduced in the same contribution as the geometry it sits on")
    confirmations = [
        c
        for c in contributions[introduced + 1 :]
        if f"check_date:{key}" in c.tags
        and any(e.signal is Signal.SURVEY for e in changeset_evidence(changesets.get(c.changeset)))
    ]
    if confirmations:
        notes.append(f"later confirmed by survey in changeset {confirmations[-1].changeset}")
    finding = _decide(
        [step],
        history,
        municipal_since=municipal_since,
        vertex_coincidence=False,
        accepted=accepted_evidence(key),
        missing_changesets=[] if contribution.changeset in changesets else [contribution.changeset],
    )
    return LineageFinding(
        finding.label, finding.reasons, finding.steps, (*finding.notes, *notes), finding.basis
    )


def _decide(
    steps: Sequence[Step],
    history: ElementHistory,
    *,
    municipal_since: str | None,
    vertex_coincidence: bool,
    accepted: frozenset[Signal],
    missing_changesets: Sequence[int],
) -> LineageFinding:
    notes = []
    if not history.reaches_frozen_state:
        notes.append(history.completeness_note or "history ends before the frozen state")
    if missing_changesets:
        notes.append(f"changesets not found in the dump: {sorted(set(missing_changesets))}")
    if not steps:
        return LineageFinding(
            Lineage.UNKNOWN, ("no contributions in the history",), (), tuple(notes)
        )
    evidence = [e for step in steps for e in step.evidence]
    kitchener = [e for e in evidence if e.signal is Signal.KITCHENER]
    if kitchener:
        return LineageFinding(
            Lineage.KNOWN,
            tuple(sorted({f"{e.where} names Kitchener data" for e in kitchener})),
            tuple(steps),
            tuple(notes),
        )
    shared = [e for e in evidence if e.signal in SHARED]
    if shared or vertex_coincidence:
        reasons = sorted({f"{e.where}: {e.signal}" for e in shared})
        if vertex_coincidence:
            reasons.append("OSM vertices coincide with the City's under one common displacement")
        return LineageFinding(Lineage.POSSIBLE, tuple(reasons), tuple(steps), tuple(notes))
    if history.reaches_frozen_state and not missing_changesets:
        predates = municipal_since is not None and max(s.timestamp for s in steps) < municipal_since
        positive = [_positive(step.evidence, accepted) for step in steps]
        if predates or all(positive):
            reasons = []
            if predates:
                reasons.append(f"last shaping edit predates the City's record ({municipal_since})")
            declared = False
            if all(positive):
                signals = sorted({str(e.signal) for found in positive for e in found})
                reasons.append(
                    f"every contribution states an unrelated source: {', '.join(signals)}"
                )
                declared = all(any(e.signal in DECLARED for e in found) for found in positive)
            # The strongest evidence names the basis: a mapper's own statement,
            # then the dates, then only what an editor recorded as displayed.
            basis = "declared" if declared else "dates" if predates else "editor_recorded"
            return LineageFinding(
                Lineage.INDEPENDENT, tuple(reasons), tuple(steps), tuple(notes), basis
            )
        if any(positive):
            notes.append("some contributions state an unrelated source, others state none")
    reason = (
        "the stated sources do not settle it" if evidence else "no contribution states a source"
    )
    return LineageFinding(Lineage.UNKNOWN, (reason,), tuple(steps), tuple(notes))


def combine(findings: Iterable[Lineage]) -> Lineage | None:
    """A record's lineage from its ways': the least independent wins."""
    present = set(findings)
    for label in _COMBINE:
        if label in present:
            return label
    return None
