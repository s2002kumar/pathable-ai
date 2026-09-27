"""How a City of Kitchener value and an OpenStreetMap value relate, property by property.

Each function answers one question: given what the City asserts and what OSM
asserts about the same property at the same place, is that agreement, a
compatible pair, a conflict, something incomparable, one source alone, or
nothing? Nothing here picks a value, and no source outranks the other.

Equivalence is kept narrow on purpose:

- **agreement** is the same claim — the City's ASPHALT and OSM's ``asphalt``;
- **compatible** is consistent without being the same claim — ASPHALT and
  ``paved`` (OSM less specific), NATURAL and ``dirt`` (OSM more specific), a
  City curb cut and ``kerb=lowered`` (a ramp's presence and a kerb's height);
- **conflict** needs both claims to be comparable and unable to both hold —
  BRICK and ``concrete``, a curb cut and ``kerb=raised``;
- a value this vocabulary does not recognise is **incomparable**, never
  silently a conflict or an agreement.

OSM values are read through PathAble's own vocabularies where they exist: the
kerb values of :mod:`pathable_api.geo.node_evidence` (``barrier=kerb`` alone
is a kerb of unrecorded height) and the surface classes of
:mod:`pathable_api.geo.features`.

A value the City records as a template default is not an assertion: callers
pass ``None`` for it, so it can only ever leave the property to OSM alone.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NamedTuple

from pathable_api.geo.enums import KerbType, SurfaceClass
from pathable_api.geo.features import normalise_surface
from pathable_api.geo.kitchener.assertions import Relationship, Specificity
from pathable_api.geo.node_evidence import read_node_evidence

VOCABULARY_VERSION = "kitchener-geo06-vocabulary-v1"


class Relation(NamedTuple):
    relationship: Relationship
    specificity: Specificity
    rule: str


def _relation(relationship: Relationship, specificity: Specificity, rule: str) -> Relation:
    return Relation(relationship, specificity, rule)


_NA = Specificity.NOT_APPLICABLE


def _alone(city: bool, osm: bool, *, what: str) -> Relation:
    """The relationship when at most one side asserts."""
    if city:
        return _relation(
            Relationship.SOURCE_ONLY_KITCHENER, _NA, f"only the City asserts {what} here"
        )
    if osm:
        return _relation(Relationship.SOURCE_ONLY_OSM, _NA, f"only OSM asserts {what} here")
    return _relation(Relationship.UNKNOWN, _NA, f"neither source asserts {what} here")


# ---------------------------------------------------------------------------
# Surface material
# ---------------------------------------------------------------------------

#: The City's non-default SURFACE_MATERIAL values, as the OSM ``surface`` value
#: that names the same material where one does (``None`` where none does), and
#: whether the material is paved. The raw value is always kept beside it.
CITY_SURFACE: dict[str, tuple[str | None, bool]] = {
    "ASPHALT": ("asphalt", True),
    # Paint is a marking on the asphalt; the material is asphalt.
    "ASPHALT (PAINTED)": ("asphalt", True),
    "CONCRETE": ("concrete", True),
    "BRICK": ("bricks", True),
    # The City's COBBLESTONE could be OSM's sett or unhewn cobblestone: no one value.
    "COBBLESTONE": (None, True),
    "STONE": ("stone", True),
    "STONEDUST": ("fine_gravel", False),
    "GRAVEL": ("gravel", False),
    # Natural ground, which OSM calls ``ground``.
    "NATURAL": ("ground", False),
    "WOOD": ("wood", True),
    # Steel is a metal; OSM has no narrower value.
    "STEEL": ("metal", True),
    "TAR AND CHIP": ("chipseal", True),
}

_AGREE = (Relationship.AGREEMENT, Specificity.SAME_LEVEL)
_OSM_MORE = (Relationship.COMPATIBLE, Specificity.OSM_MORE_SPECIFIC)
_CITY_MORE = (Relationship.COMPATIBLE, Specificity.KITCHENER_MORE_SPECIFIC)
_OVERLAP = (Relationship.COMPATIBLE, Specificity.OVERLAPPING)

#: For each City material, the OSM values that agree with it or are compatible
#: with it. Any other recognised OSM value is a different material: a conflict.
SURFACE_RELATIONS: dict[str, dict[str, tuple[Relationship, Specificity]]] = {
    "ASPHALT": {"asphalt": _AGREE},
    "ASPHALT (PAINTED)": {"asphalt": _AGREE},
    "CONCRETE": {"concrete": _AGREE, "concrete:plates": _OSM_MORE, "concrete:lanes": _OSM_MORE},
    # A municipal "brick" is often a paver: related to paving_stones, not the same.
    "BRICK": {"bricks": _AGREE, "brick": _AGREE, "paving_stones": _OVERLAP},
    "COBBLESTONE": {"cobblestone": _AGREE, "sett": _OVERLAP, "unhewn_cobblestone": _OVERLAP},
    "STONE": {"stone": _AGREE, "sett": _OVERLAP, "paving_stones": _OVERLAP},
    # Stone dust is crushed fines. ``compacted`` describes how a surface was
    # built, not what of: consistent, not the same claim.
    "STONEDUST": {"fine_gravel": _AGREE, "compacted": _OVERLAP},
    "GRAVEL": {
        "gravel": _AGREE,
        "fine_gravel": _OSM_MORE,
        "pebblestone": _OSM_MORE,
        "compacted": _OVERLAP,
    },
    "NATURAL": {
        "ground": _AGREE,
        "dirt": _OSM_MORE,
        "earth": _OSM_MORE,
        "grass": _OSM_MORE,
        "mud": _OSM_MORE,
        "sand": _OSM_MORE,
    },
    "WOOD": {"wood": _AGREE},
    "STEEL": {"metal": _CITY_MORE, "metal_grid": _OVERLAP},
    "TAR AND CHIP": {"chipseal": _AGREE},
}

#: OSM surface values this vocabulary treats as recognised materials, beyond
#: those PathAble's own surface classes know.
_EXTRA_SURFACES = frozenset(
    {"bricks", "brick", "stone", "metal_grid", "unhewn_cobblestone", "cobblestone"}
)
_COARSE = {"paved": True, "unpaved": False}


def surface_recognised(value: str) -> bool:
    _value, surface_class = normalise_surface(value)
    return surface_class is not SurfaceClass.UNKNOWN or value in _EXTRA_SURFACES or value in _COARSE


def normalize_osm_surface(raw: str | None) -> str | None:
    """OSM's surface value when it is one recognised value; ``None`` otherwise."""
    if raw is None:
        return None
    value = raw.strip().lower()
    return value if surface_recognised(value) else None


def relate_surface(city: str | None, osm: str | None) -> Relation:
    """The City's usable SURFACE_MATERIAL (raw) beside OSM's ``surface`` (raw)."""
    if city is None or osm is None:
        return _alone(city is not None, osm is not None, what="a surface material")
    value = osm.strip().lower()
    if city not in CITY_SURFACE:
        return _relation(
            Relationship.INCOMPARABLE, _NA, f"the City's {city} is not in the vocabulary"
        )
    if ";" in value or "," in value:
        return _relation(Relationship.INCOMPARABLE, _NA, "OSM lists several surfaces for one way")
    found = SURFACE_RELATIONS[city].get(value)
    if found is not None:
        relationship, specificity = found
        return _relation(relationship, specificity, f"{city} beside surface={value}")
    if value in _COARSE:
        paved = CITY_SURFACE[city][1]
        if _COARSE[value] == paved:
            return _relation(
                Relationship.COMPATIBLE,
                Specificity.KITCHENER_MORE_SPECIFIC,
                f"{city} is {value}; OSM names no material",
            )
        return _relation(
            Relationship.CONFLICT,
            Specificity.KITCHENER_MORE_SPECIFIC,
            f"{city} is {'paved' if paved else 'unpaved'}; OSM says {value}",
        )
    if surface_recognised(value):
        return _relation(
            Relationship.CONFLICT, Specificity.SAME_LEVEL, f"{city} and surface={value} differ"
        )
    return _relation(
        Relationship.INCOMPARABLE, _NA, f"surface={value} is not a recognised OSM surface"
    )


# ---------------------------------------------------------------------------
# Curb ramps and kerbs
# ---------------------------------------------------------------------------

#: The narrowest claim CURBCUT = Y supports: the City's definition, "a curbcut
#: down to street level", at this local feature. It states no kerb height.
CURB_RAMP_PRESENT = "curb_ramp_present"

#: What OSM's kerb at the node says beside a City curb cut there.
_KERB_BESIDE_A_CURB_CUT: dict[KerbType, Relation] = {
    KerbType.LOWERED: _relation(
        Relationship.COMPATIBLE,
        Specificity.DIFFERENT_PROPERTY,
        "a curb cut beside kerb=lowered: a ramp's presence and a kerb's height agree "
        "without restating each other",
    ),
    KerbType.FLUSH: _relation(
        Relationship.COMPATIBLE,
        Specificity.DIFFERENT_PROPERTY,
        "a curb cut beside kerb=flush: a ramp's presence and a kerb's height agree "
        "without restating each other",
    ),
    KerbType.NONE: _relation(
        Relationship.INCOMPARABLE,
        Specificity.DIFFERENT_PROPERTY,
        "kerb=no says there is no kerb; the City's curb cut presupposes one",
    ),
    KerbType.ROLLED: _relation(
        Relationship.CONFLICT,
        Specificity.DIFFERENT_PROPERTY,
        "a rolled kerb, not wheelchair-traversable, is not a cut down to street level",
    ),
    KerbType.RAISED: _relation(
        Relationship.CONFLICT,
        Specificity.DIFFERENT_PROPERTY,
        "a raised kerb contradicts a curb cut down to street level",
    ),
    KerbType.PRESENT_UNKNOWN: _relation(
        Relationship.SOURCE_ONLY_KITCHENER,
        _NA,
        "OSM records a kerb here but not its height; only the City says a ramp exists",
    ),
}
#: Kerb values that state the kerb's form, so assert something about a ramp.
KERB_FORMS = frozenset(
    {KerbType.LOWERED, KerbType.FLUSH, KerbType.NONE, KerbType.ROLLED, KerbType.RAISED}
)


def osm_kerb(tags: Mapping[str, str]) -> KerbType:
    """A node's kerb, read exactly as PathAble's routing reads it."""
    return read_node_evidence(dict(tags)).kerb


def relate_curb(city_ramp: bool, tags: Mapping[str, str]) -> Relation:
    """A City curb cut (or none) beside the tags of an OSM kerb node."""
    kerb = osm_kerb(tags)
    raw = tags.get("kerb")
    unrecognised = raw is not None and kerb is KerbType.UNKNOWN
    if city_ramp:
        if unrecognised:
            return _relation(
                Relationship.INCOMPARABLE, _NA, f"kerb={raw} is not a recognised kerb value"
            )
        if kerb is KerbType.UNKNOWN:
            return _relation(
                Relationship.SOURCE_ONLY_KITCHENER, _NA, "OSM's node states nothing about a kerb"
            )
        return _KERB_BESIDE_A_CURB_CUT[kerb]
    if kerb in KERB_FORMS or unrecognised:
        return _relation(
            Relationship.SOURCE_ONLY_OSM,
            _NA,
            "only OSM states the kerb's form; the City records no curb cut here, and "
            "CURBCUT = N never means there is none",
        )
    return _relation(
        Relationship.UNKNOWN, _NA, "neither source states a ramp or a kerb's form here"
    )


# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------

#: The City's structure FEATURE_TYPE values: the OSM structure family each is,
#: and the normalized value kept for it.
CITY_STRUCTURE: dict[str, tuple[str, str]] = {
    "STAIRS": ("steps", "steps"),
    "BRIDGE": ("bridge", "bridge"),
    "OVERPASS": ("bridge", "overpass"),
    "UNDERPASS": ("tunnel", "underpass"),
    "BOARDWALK": ("bridge", "boardwalk"),
}
STRUCTURE_FAMILIES = ("bridge", "steps", "tunnel")


def osm_structures(tags: Mapping[str, str]) -> dict[str, tuple[str, str]]:
    """Each structure family OSM tags on a way: family → (tag key, raw value)."""
    found: dict[str, tuple[str, str]] = {}
    if tags.get("highway") == "steps":
        found["steps"] = ("highway", "steps")
    for family, key in (("bridge", "bridge"), ("tunnel", "tunnel")):
        value = tags.get(key)
        if value is not None and value != "no":
            found[family] = (key, value)
    return found


def relate_structure(city: str | None, family: str, osm_value: str | None) -> Relation:
    """The City's FEATURE_TYPE beside OSM's tag for one structure family on one way.

    A City FEATURE_TYPE of another family asserts nothing about this one: a
    City STAIRS record says nothing about whether the steps are on a bridge.
    """
    city_family = CITY_STRUCTURE[city][0] if city in CITY_STRUCTURE else None
    asserts = city_family == family
    if city is None or not asserts or osm_value is None:
        return _alone(asserts, osm_value is not None, what=f"a {family} structure")
    if city == "STAIRS":
        return _relation(*_AGREE, "STAIRS on highway=steps")
    if city == "UNDERPASS":
        if osm_value == "yes":
            return _relation(*_AGREE, "UNDERPASS on tunnel=yes")
        return _relation(
            Relationship.INCOMPARABLE,
            Specificity.DIFFERENT_PROPERTY,
            f"UNDERPASS on tunnel={osm_value}: a different kind of passage",
        )
    if city == "BRIDGE":
        if osm_value == "yes":
            return _relation(*_AGREE, "BRIDGE on bridge=yes")
        return _relation(*_OSM_MORE, f"BRIDGE on bridge={osm_value}, a kind of bridge")
    if city == "OVERPASS":
        if osm_value == "boardwalk":
            return _relation(
                Relationship.INCOMPARABLE,
                Specificity.DIFFERENT_PROPERTY,
                "OVERPASS on bridge=boardwalk: different kinds of structure",
            )
        if osm_value == "yes":
            return _relation(*_CITY_MORE, "OVERPASS on bridge=yes: the City says what it spans")
        return _relation(*_OVERLAP, f"OVERPASS on bridge={osm_value}")
    # BOARDWALK
    if osm_value == "boardwalk":
        return _relation(*_AGREE, "BOARDWALK on bridge=boardwalk")
    if osm_value == "yes":
        return _relation(*_CITY_MORE, "BOARDWALK on bridge=yes")
    return _relation(
        Relationship.INCOMPARABLE,
        Specificity.DIFFERENT_PROPERTY,
        f"BOARDWALK on bridge={osm_value}: different kinds of structure",
    )


# ---------------------------------------------------------------------------
# Railings — kept, never a routing property
# ---------------------------------------------------------------------------

RAILING_PRESENT = "railing_present"


def osm_handrails(tags: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in sorted(tags.items()) if k == "handrail" or k.startswith("handrail:")}


def relate_railing(city_railing: bool, handrail_values: Sequence[str]) -> Relation:
    """A handrail is a railing; a railing — a guard rail — need not be a handrail."""
    if not city_railing or not handrail_values:
        return _alone(city_railing, bool(handrail_values), what="a railing or handrail")
    values = set(handrail_values)
    if "no" in values:
        return _relation(
            Relationship.INCOMPARABLE,
            Specificity.DIFFERENT_PROPERTY,
            "handrail=no does not contradict RAILING = Y: a railing need not be a handrail",
        )
    return _relation(
        Relationship.COMPATIBLE,
        Specificity.OSM_MORE_SPECIFIC,
        "a handrail is one kind of railing",
    )
