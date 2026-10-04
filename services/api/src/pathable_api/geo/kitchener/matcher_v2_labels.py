"""PA-GEO-08 correspondence labels: the schema, definitions version 2, and the development set.

The same kind of label as PA-GEO-05's (:mod:`benchmark_labels`): which OSM
elements represent the same physical facility as one City record, and how.
Definitions version 2 changes it only where PA-GEO-05's failures showed the
first version left the answer open:

- **physical correspondence and attributes are separate** — a City stair that
  OSM draws as a plain footway, in the same place and topology, corresponds to
  that footway: the stair is then an assertion only the City makes, recorded
  as representation ``generic_way``, not a reason to call the match ambiguous;
- **a displaced stair stays ambiguous** — OSM steps nearby that may be the same
  stair drawn elsewhere leave the physical identity unclear;
- **a way is cited for a curb cut only if the piece follows it** — a crossing
  way the piece runs onto counts exactly like a sidewalk; a way the piece only
  crosses or touches at an angle does not;
- **two kerb nodes** — the one where the crossing the piece runs onto begins;
  if the piece serves both crossings or neither can be told, ambiguous;
- **corner and junction pieces** — obvious only when the piece clearly follows
  one way;
- **a way under construction** is not a current facility.

Every label is an AI model's. None is human-reviewed or field-checked.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pathable_api.geo.kitchener.benchmark_labels import (
    AMBIGUOUS,
    CORRESPONDENCE,
    NONE,
    OBVIOUS,
    RELATIONSHIP,
    Label,
    LabelError,
)

LABELS_VERSION = 2
LABELS_KEY = "kitchener_geo08_labels_version"
REPRESENTATION = ("separate_way", "generic_way", "node", "multiple", "road_attribute", "none")
WAY_ONLY = frozenset({"separate_way", "generic_way"})

#: The definitions the labellers apply, version :data:`LABELS_VERSION`.
DEFINITIONS: dict[str, dict[str, str]] = {
    "principle": {
        "correspondence_is_physical": (
            "A label says which OSM elements are the same physical facility as the City record. "
            "It never judges whether either source is right about the facility's attributes. "
            "Physical correspondence and attribute agreement are separate questions: OSM "
            "describing the facility more generally than the City (a plain footway where the City "
            "records a stair) is an attribute difference, not by itself a reason for ambiguity."
        ),
    },
    "correspondence": {
        OBVIOUS: (
            "OSM represents the same physical facility, and the labeller can name exactly which "
            "OSM elements, with no reasonable alternative. Closeness alone never qualifies: the "
            "element must be the same facility in the same place — the same side of the road, "
            "the same crossing, the same flight of stairs."
        ),
        AMBIGUOUS: (
            "OSM may represent it, but the elements cannot be named with confidence: two equally "
            "plausible ways; a short piece at a corner or junction that follows no single way "
            "(including a curb cut there with no kerb node); two kerb nodes when it cannot be "
            "told which marks this ramp; OSM steps nearby that may be the same stair drawn "
            "elsewhere; a way under construction; or a facility OSM records only as a tag on a "
            "road."
        ),
        NONE: (
            "Nothing in OSM represents this facility: no way or node of the same kind within "
            "about 5 m. A road alone is not a correspondence for a sidewalk unless it tags one, "
            "and a way that only touches one end of the record at an angle is not one."
        ),
        "not_comparable": "The record cannot be judged, for example a broken geometry.",
    },
    "osm": {
        "ways": (
            "Every OSM way that carries the same facility over any part of the record, including "
            "a way that runs far beyond it. Not ways that only touch its ends: about a junction's "
            "width (5 m) of the record onto the next way is end slop, not a second way."
        ),
        "crossings": (
            "The crossing way over the same road at the same place; if OSM has no crossing way "
            "there but a highway=crossing node where the City's crossing is, the node."
        ),
        "curb_cuts": (
            "For a CURBCUT = Y record: the OSM kerb node (barrier=kerb or kerb=*) that marks this "
            "ramp, if one lies within about 2 m of the piece; and every OSM way the piece "
            "follows — most of it within about 2 m, running in line with the way, not across it. "
            "A crossing way counts exactly like a sidewalk: a piece running from the end of a "
            "sidewalk onto the first metres of a crossing follows both. With two kerb nodes near, "
            "cite the one where the crossing the piece runs onto begins; if the piece serves both "
            "crossings or you cannot tell, ambiguous. With no kerb node and no way the piece "
            "follows — it sits across a junction — ambiguous. A curb cut is local: never cite a "
            "way for a curb cut because the piece touches it. CURBCUT = Y does not say "
            "kerb=lowered or kerb=flush; the kerb value is not judged."
        ),
        "stairs": (
            "The OSM ways that are the same flight of stairs. If OSM tags it highway=steps, cite "
            "those. If OSM draws the same stair as a plain footway or path — same place, same "
            "line, same connections, no highway=steps near — cite that way: an obvious "
            "correspondence, representation generic_way. If a highway=steps way lies nearby but "
            "not on the record, it may be the same stair drawn elsewhere: ambiguous. Also "
            "ambiguous: several plausible ways, topology that disagrees, or an unclear split or "
            "merge."
        ),
        "structures": (
            "Bridges, overpasses, underpasses and boardwalks: every OSM way that carries the same "
            "facility over any part of the record, including approach ways the City record runs "
            "along. If none is tagged as the structure (bridge=*, tunnel=*), the representation is "
            "generic_way."
        ),
        "corner_and_junction_pieces": (
            "A piece of a few metres (not a curb cut) at a corner or junction: obvious only if it "
            "clearly follows one way. If it lies between two ways that meet at the corner, or "
            "across the junction at an angle, ambiguous."
        ),
        "construction": (
            "An OSM way tagged highway=construction is not a current facility; if it is the only "
            "candidate, the correspondence is ambiguous."
        ),
        "ambiguous": "For an ambiguous correspondence, the plausible alternatives, for the record.",
    },
    "representation": {
        "separate_way": "Only ways are cited, and at least one is the City's kind of facility.",
        "generic_way": (
            "Only ways are cited, and none carries the City's structure type: a City stair on a "
            "way not tagged highway=steps; a City bridge, overpass, underpass or boardwalk on "
            "ways with no bridge=* or tunnel=* tag."
        ),
        "node": "Only nodes are cited.",
        "multiple": "Ways and nodes are cited.",
        "road_attribute": "OSM records the facility only as a tag on a road.",
        "none": "No correspondence.",
    },
    "relationship": {
        "one_to_one": (
            "The record and one OSM way cover substantially the same extent, and that way carries "
            "no other physical City record of the same facility. A node-only correspondence."
        ),
        "one_to_many": "The record corresponds to several OSM ways: OSM splits it.",
        "many_to_one": (
            "The OSM way also carries other physical City records of the same facility: OSM "
            "merges what the City splits."
        ),
        "many_to_many": "Several records and several ways, with no clean nesting.",
        "not_counted": (
            "Virtual links and connector stubs of a few metres at a junction are not counted; "
            "about a junction's width (5 m) of end slop is not a difference in extent."
        ),
    },
}


def _element_order(element: str) -> tuple[str, int]:
    kind, _, number = element.partition("/")
    return kind, int(number)


def _kinds(osm: Iterable[str]) -> set[str]:
    return {element.split("/")[0] for element in osm}


def parse_label(item: Mapping[str, Any]) -> Label:
    """One label under definitions version 2, checked against the schema."""
    record_id = int(item["activetransportid"])
    where = f"record {record_id}"
    correspondence = item.get("correspondence")
    if correspondence not in CORRESPONDENCE:
        raise LabelError(f"{where}: correspondence {correspondence!r} is not defined.")
    osm = [str(e) for e in item.get("osm") or []]
    for element in osm:
        kind, _, number = element.partition("/")
        if kind not in ("way", "node") or not number.isdigit():
            raise LabelError(f"{where}: {element!r} is not a way/ID or node/ID.")
    representation = item.get("representation")
    if representation not in REPRESENTATION:
        raise LabelError(f"{where}: representation {representation!r} is not defined.")
    relationship = item.get("relationship")
    if correspondence == OBVIOUS:
        if not osm:
            raise LabelError(f"{where}: an obvious correspondence names its OSM elements.")
        kinds = _kinds(osm)
        expected = WAY_ONLY if kinds == {"way"} else {"node"} if kinds == {"node"} else {"multiple"}
        if representation not in expected:
            raise LabelError(
                f"{where}: representation {representation} does not describe {sorted(osm)}."
            )
        if relationship not in RELATIONSHIP:
            raise LabelError(f"{where}: an obvious correspondence needs a relationship.")
    elif relationship is not None:
        raise LabelError(f"{where}: only an obvious correspondence has a relationship.")
    if correspondence == NONE and (osm or representation != "none"):
        raise LabelError(f"{where}: no correspondence names no elements and representation none.")
    return Label(
        record_id,
        str(correspondence),
        frozenset(osm),
        str(representation),
        relationship,
        str(item.get("note") or ""),
    )


def parse_labels(document: Mapping[str, Any]) -> dict[int, Label]:
    if document.get(LABELS_KEY) != LABELS_VERSION:
        raise LabelError("not a PA-GEO-08 label file of a known version.")
    labels: dict[int, Label] = {}
    for item in document.get("records", []):
        label = parse_label(item)
        if label.activetransportid in labels:
            raise LabelError(f"record {label.activetransportid} is labelled twice.")
        labels[label.activetransportid] = label
    return labels


def label_dict(label: Label) -> dict[str, Any]:
    return {
        "activetransportid": label.activetransportid,
        "correspondence": label.correspondence,
        "osm": sorted(label.osm, key=_element_order),
        "representation": label.representation,
        "relationship": label.relationship,
        "note": label.note,
    }


# ---------------------------------------------------------------------------
# The development set
# ---------------------------------------------------------------------------

#: PA-GEO-05's held-out labels for stairs OSM draws as a plain footway, re-read
#: under definitions version 2. Each was labelled ambiguous only because the
#: footway is not tagged highway=steps; in each, one footway carries the whole
#: stair within about a metre, nearly parallel, and no OSM steps way lies within
#: 25 m. Record 419322 is not converted: OSM steps lie 7.5 m along the same path,
#: which may be the same stair drawn elsewhere.
STAIR_CONVERSIONS: dict[int, dict[str, Any]] = {
    13622: {"osm": ["way/146313339"], "measured": "footway at 1.1 m over all of the 5.4 m stair"},
    17381: {"osm": ["way/116233513"], "measured": "footway at 0.5 m over all of the 5.3 m stair"},
    389863: {"osm": ["way/146313339"], "measured": "footway at 0.3 m over all of the 3.9 m stair"},
    395207: {"osm": ["way/37692290"], "measured": "footway at 0.0 m over all of the 4.8 m stair"},
    403882: {"osm": ["way/965483393"], "measured": "footway at 0.9 m over all of the 11.5 m stair"},
    403892: {"osm": ["way/116233513"], "measured": "footway at 0.2 m over all of the 11.5 m stair"},
}


def development_labels(
    geo05_development: Mapping[str, Any],
    geo05_holdout: Mapping[str, Any],
    *,
    structures: Mapping[int, str],
    structure_tagged: Mapping[str, bool],
    other_records_along: Mapping[str, frozenset[int]],
) -> dict[str, Any]:
    """PA-GEO-04's and PA-GEO-05's labels, re-read under definitions version 2.

    ``structures`` maps a record to its City structure; ``structure_tagged``
    says whether an OSM way is tagged as that record's structure (keyed
    ``"<record>:<way>"``); ``other_records_along`` lists, per way, the other
    physical City records lying along it — the facts the labellers were shown.
    """
    records: list[dict[str, Any]] = []
    conversions: list[dict[str, Any]] = []
    for source, document in (
        ("PA-GEO-04 development (kitchener-geo05-development-labels.json)", geo05_development),
        ("PA-GEO-05 held-out, now spent (kitchener-geo05-holdout-labels.json)", geo05_holdout),
    ):
        for item in document["records"]:
            record_id = int(item["activetransportid"])
            label = {
                "activetransportid": record_id,
                "correspondence": item["correspondence"],
                "osm": list(item["osm"]),
                "representation": item["representation"],
                "relationship": item.get("relationship"),
                "note": item.get("note") or "",
                "source": source,
            }
            before = {
                k: label[k] for k in ("correspondence", "osm", "representation", "relationship")
            }
            reasons = []
            stair = STAIR_CONVERSIONS.get(record_id)
            if stair is not None:
                label["correspondence"] = OBVIOUS
                label["osm"] = list(stair["osm"])
                along = set().union(
                    *(other_records_along.get(w, frozenset()) for w in stair["osm"])
                ) - {record_id}
                label["relationship"] = "many_to_one" if along else "one_to_one"
                reasons.append(
                    "A stair OSM draws as a plain footway, in the same place and line with no "
                    f"OSM steps within 25 m ({stair['measured']}): under definitions 2 an obvious "
                    "correspondence, the stair an assertion only the City makes."
                )
            structure = structures.get(record_id)
            if (
                structure is not None
                and label["correspondence"] == OBVIOUS
                and _kinds(label["osm"]) == {"way"}
            ):
                tagged = any(structure_tagged[f"{record_id}:{w}"] for w in label["osm"])
                wanted = "separate_way" if tagged else "generic_way"
                if label["representation"] != wanted:
                    label["representation"] = wanted
                    reasons.append(
                        "Representation re-read under definitions 2: "
                        + (
                            "a cited way is tagged as the City's structure."
                            if tagged
                            else f"no cited way is tagged as the City's {structure.lower()}."
                        )
                    )
            if reasons:
                conversions.append(
                    {
                        "activetransportid": record_id,
                        "reasons": reasons,
                        "before": before,
                        "after": {
                            k: label[k]
                            for k in ("correspondence", "osm", "representation", "relationship")
                        },
                    }
                )
            parsed = parse_label(label)
            records.append({**label_dict(parsed), "source": source})
    return {
        LABELS_KEY: LABELS_VERSION,
        "set": "development",
        "source": (
            "PA-GEO-04's development labels and PA-GEO-05's held-out labels, both as committed, "
            "re-read under definitions version 2 with every change recorded below. PA-GEO-05's "
            "held-out sample is spent; its records are development data for matcher v2."
        ),
        "labeller": (
            "AI model instances (Claude). The conversions below are the matcher designer's "
            "reading of the definitions, not a blind relabelling."
        ),
        "conversions": conversions,
        "records": sorted(records, key=lambda r: r["activetransportid"]),
    }


def structure_tagged(structure: str, tags: Mapping[str, str]) -> bool:
    """Whether an OSM way's tags record the City's structure type."""
    if structure == "STAIRS":
        return tags.get("highway") == "steps"
    if structure == "UNDERPASS":
        return tags.get("tunnel", "no") != "no"
    return tags.get("bridge", "no") != "no"


def label_facts(inputs: Any, documents: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The facts :func:`development_labels` reads, from the frozen inputs, for these labels."""
    by_id = inputs.by_id
    structures: dict[int, str] = {}
    tagged: dict[str, bool] = {}
    along: dict[str, frozenset[int]] = {}
    for document in documents:
        for item in document["records"]:
            record_id = int(item["activetransportid"])
            record = by_id.get(record_id)
            if record is None:
                continue
            ways = [e for e in item["osm"] if e.startswith("way/")]
            ways += list(STAIR_CONVERSIONS.get(record_id, {}).get("osm", []))
            if record.structure is not None:
                structures[record_id] = record.structure
                for way in ways:
                    tags = inputs.osm.extract.ways[int(way.split("/")[1])].tags
                    tagged[f"{record_id}:{way}"] = structure_tagged(record.structure, tags)
            for way in ways:
                along[way] = inputs.relationships.along(int(way.split("/")[1]))
    return {"structures": structures, "structure_tagged": tagged, "other_records_along": along}


LABELLER = (
    "Separate AI model instances (Claude), one per pack, each labelling its pack blind from the "
    "pack's text digest and maps under the frozen guide, with no access to either matcher, their "
    "output, the development labels or another pack. They were told to open only their pack "
    "folder and to run only the validator, and each reported back only its record count and the "
    "validator's verdict. These are AI labels: not human ground truth, not expert labels, not "
    "externally validated, and the same model family as the guide's author and the matcher's "
    "designer."
)


def collect_labels(
    packs: Mapping[str, Mapping[str, Any]],
    *,
    labelling_pass: str,
    sample: Mapping[str, Any],
    material: Mapping[str, Any],
) -> dict[str, Any]:
    """One pass's pack files, checked and merged, each record carrying the pack it came from."""
    records: list[dict[str, Any]] = []
    seen: set[int] = set()
    for name, document in sorted(packs.items()):
        for record_id, label in parse_labels(document).items():
            if record_id in seen:
                raise LabelError(f"record {record_id} is labelled in two packs.")
            seen.add(record_id)
            records.append({**label_dict(label), "pack": name})
    counts: dict[str, int] = {}
    for item in records:
        counts[item["correspondence"]] = counts.get(item["correspondence"], 0) + 1
    return {
        LABELS_KEY: LABELS_VERSION,
        "set": "holdout",
        "pass": labelling_pass,
        **dict(material),
        "labeller": LABELLER,
        "frozen": (
            "Collected and committed after matcher v2's policy was frozen and before either "
            "matcher or any baseline was run on a held-out record. Nothing in this file is changed "
            "after the held-out evaluation."
        ),
        "counts": dict(sorted(counts.items())),
        "packs": len(packs),
        "records": sorted(records, key=lambda r: r["activetransportid"]),
    }
