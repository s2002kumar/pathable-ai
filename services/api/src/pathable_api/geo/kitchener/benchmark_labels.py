"""PA-GEO-05 correspondence labels: the schema, its definitions, and the development set.

A label says which OpenStreetMap elements represent the same physical facility
as one City record — the *exact correspondence set* — and how OSM represents
it. It is a correspondence judgement only: never a judgement of whether either
source is right about the facility or its attributes.

Two label sets exist:

- **development** — PA-GEO-04's adjudicated labels, converted to this schema by
  the explicit changes in :data:`DEVELOPMENT_CONVERSIONS`. The matcher is
  designed and tuned on them.
- **held-out** — labelled blind for PA-GEO-05 and frozen before the matcher is
  evaluated on them.

Both are an AI model's labels. Neither is human-reviewed or field-checked.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

LABELS_VERSION = 1

OBVIOUS = "obvious_correspondence"
AMBIGUOUS = "ambiguous_correspondence"
NONE = "no_correspondence"
NOT_COMPARABLE = "not_comparable"
CORRESPONDENCE = (OBVIOUS, AMBIGUOUS, NONE, NOT_COMPARABLE)
REPRESENTATION = ("separate_way", "node", "multiple", "road_attribute", "none")
RELATIONSHIP = ("one_to_one", "one_to_many", "many_to_one", "many_to_many")

#: The definitions the labellers apply, version :data:`LABELS_VERSION`. Kept in
#: the evidence so a label can always be read against the words it followed.
DEFINITIONS: dict[str, dict[str, str]] = {
    "correspondence": {
        OBVIOUS: (
            "OSM represents the same physical facility, and the labeller can name exactly which "
            "OSM elements, with no reasonable alternative. Closeness alone never qualifies: the "
            "element must be the same kind of facility in the same place — the same side of the "
            "road, the same crossing, the same stair."
        ),
        AMBIGUOUS: (
            "OSM may represent it, but the elements cannot be named with confidence: two equally "
            "plausible ways; a City piece of a metre or two that OSM collapses into a junction "
            "with no kerb node to say which; or a facility OSM records only as a tag on a road."
        ),
        NONE: (
            "Nothing in OSM represents this facility: no way or node of the same kind within "
            "about 5 m. A road alone is not a correspondence for a sidewalk unless it tags one."
        ),
        NOT_COMPARABLE: "The record cannot be judged, for example a broken geometry.",
    },
    "osm": {
        "ways": (
            "Every OSM way that carries the same facility over any part of the record, including "
            "a way that runs far beyond it; not ways that only touch its ends."
        ),
        "crossings": (
            "The crossing way over the same road at the same place; if OSM has no crossing way "
            "there but a highway=crossing node where the City's crossing is, the node."
        ),
        "curb_cuts": (
            "For a CURBCUT = Y record: the OSM kerb node (barrier=kerb or kerb=*) that marks this "
            "ramp's kerb, if one lies within about 2 m of the piece, and every OSM way the piece "
            "lies along (most of it within about 2 m, following the way). Neither: ambiguous. "
            "CURBCUT = Y does not say kerb=lowered or kerb=flush; the kerb value is not judged."
        ),
        "structures": (
            "Stairs: highway=steps ways. Bridges, overpasses, underpasses and boardwalks: the OSM "
            "ways that carry the same facility across the structure."
        ),
        "ambiguous": "For an ambiguous correspondence, the plausible alternatives, for the record.",
    },
    "representation": {
        "separate_way": "Only ways are cited.",
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


class LabelError(ValueError):
    """A label file that does not follow the schema or its definitions."""


@dataclass(frozen=True, slots=True)
class Label:
    activetransportid: int
    correspondence: str
    osm: frozenset[str]
    representation: str
    relationship: str | None
    note: str

    @property
    def truth(self) -> frozenset[str]:
        """The elements a correct match must name: only an obvious correspondence has any."""
        return self.osm if self.correspondence == OBVIOUS else frozenset()

    def as_dict(self) -> dict[str, Any]:
        return {
            "activetransportid": self.activetransportid,
            "correspondence": self.correspondence,
            "osm": sorted(self.osm, key=_element_order),
            "representation": self.representation,
            "relationship": self.relationship,
            "note": self.note,
        }


def _element_order(element: str) -> tuple[str, int]:
    kind, _, number = element.partition("/")
    return kind, int(number)


def _representation_of(osm: Iterable[str]) -> str:
    kinds = {element.split("/")[0] for element in osm}
    if kinds == {"way"}:
        return "separate_way"
    if kinds == {"node"}:
        return "node"
    return "multiple" if kinds else "none"


def parse_label(item: Mapping[str, Any]) -> Label:
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
        if representation != _representation_of(osm):
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
        correspondence,
        frozenset(osm),
        representation,
        relationship,
        str(item.get("note") or ""),
    )


def parse_labels(document: Mapping[str, Any]) -> dict[int, Label]:
    if document.get("kitchener_geo05_labels_version") != LABELS_VERSION:
        raise LabelError("not a PA-GEO-05 label file of a known version.")
    labels: dict[int, Label] = {}
    for item in document.get("records", []):
        label = parse_label(item)
        if label.activetransportid in labels:
            raise LabelError(f"record {label.activetransportid} is labelled twice.")
        labels[label.activetransportid] = label
    return labels


# ---------------------------------------------------------------------------
# The development set
# ---------------------------------------------------------------------------

#: PA-GEO-04's labels, re-read under these definitions. PA-GEO-04 cited ways
#: for curb cuts; these definitions also cite the kerb node that marks the
#: ramp, and a curb cut OSM represents only by such a node is an obvious
#: correspondence, not an ambiguous one. Every change, with its reason.
DEVELOPMENT_CONVERSIONS: dict[int, dict[str, Any]] = {
    335487: {
        "add": ["node/8512126422"],
        "representation": "multiple",
        "reason": "The kerb=lowered node 0.9 m from the piece ends OSM's own sidewalk stub there.",
    },
    335421: {
        "add": ["node/8295109529"],
        "representation": "multiple",
        "reason": "The kerb=lowered node 0.3 m from the piece marks the ramp before the crossing.",
    },
    403539: {
        "add": ["node/8905696991"],
        "representation": "multiple",
        "reason": "The kerb=lowered node 0.3 m away ends the sidewalk segment the piece lies along.",
    },
    321409: {
        "correspondence": OBVIOUS,
        "osm": ["node/9160884963"],
        "representation": "node",
        "relationship": "one_to_one",
        "reason": (
            "OSM draws no stub but has a kerb=lowered node 0.2 m from the piece where the crossing "
            "leaves the corner; PA-GEO-04 called it ambiguous because no way carries the piece."
        ),
    },
}


def development_labels(geo04_labels: Mapping[str, Any], eligible: Iterable[int]) -> dict[str, Any]:
    """PA-GEO-04's adjudicated labels for the eligible records, in this schema."""
    wanted = set(eligible)
    records = []
    applied = []
    for item in geo04_labels["records"]:
        record_id = int(item["activetransportid"])
        if record_id not in wanted:
            continue
        label = {
            "activetransportid": record_id,
            "correspondence": item["correspondence"],
            "osm": list(item["osm"]),
            "representation": item["representation"],
            "relationship": item.get("relationship"),
            "note": item.get("note") or "",
        }
        if label["correspondence"] == NONE:
            label["representation"] = "none"
        change = DEVELOPMENT_CONVERSIONS.get(record_id)
        if change is not None:
            before = {
                k: label[k] for k in ("correspondence", "osm", "representation", "relationship")
            }
            label["osm"] = sorted(
                set(change.get("osm", label["osm"])) | set(change.get("add", [])),
                key=_element_order,
            )
            for key in ("correspondence", "representation", "relationship"):
                if key in change:
                    label[key] = change[key]
            applied.append(
                {
                    "activetransportid": record_id,
                    "reason": change["reason"],
                    "before": before,
                    "after": {
                        k: label[k]
                        for k in ("correspondence", "osm", "representation", "relationship")
                    },
                }
            )
        records.append(parse_label(label).as_dict())
    return {
        "kitchener_geo05_labels_version": LABELS_VERSION,
        "set": "development",
        "source": (
            "PA-GEO-04's adjudicated labels (kitchener-geo04-labels.json, definitions version 2), "
            "for the records eligible for PA-GEO-05, re-read under these definitions."
        ),
        "labeller": geo04_labels.get("labeller"),
        "conversions": applied,
        "records": sorted(records, key=lambda r: r["activetransportid"]),
    }
