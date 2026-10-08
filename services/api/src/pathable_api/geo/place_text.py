"""How place names and search queries are compared.

One function for both sides. Stored names and typed queries pass through the
same normalisation, so "200 University Ave W" and "200 University Avenue West"
meet in the middle — and so a change here changes both at once, which is why an
index records the gazetteer version that built it.

Kept apart from :mod:`pathable_api.geo.gazetteer` so the API can normalise a
query without importing the extract reader.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

#: Written forms that mean the same thing. The rule is symmetry, not accuracy:
#: "St Jacobs" becomes "street jacobs" on both sides, which is ugly and still
#: matches.
ABBREVIATIONS: Mapping[str, str] = {
    "ave": "avenue",
    "av": "avenue",
    "blvd": "boulevard",
    "cir": "circle",
    "cres": "crescent",
    "ct": "court",
    "dr": "drive",
    "hwy": "highway",
    "ln": "lane",
    "pkwy": "parkway",
    "pl": "place",
    "rd": "road",
    "sq": "square",
    "st": "street",
    "terr": "terrace",
    "trl": "trail",
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
}

#: Removed rather than turned into a space, so "Children's" stays one word
#: instead of becoming "children" and a stray "s" that would read as "south".
_APOSTROPHES = str.maketrans("", "", "'\u2019`")
_NON_WORD = re.compile(r"[^a-z0-9]+")

#: A query longer than this is not a place name; the rest is ignored.
MAX_QUERY_TERMS = 8


def normalise_text(text: str) -> str:
    """Lower-case, unaccented, punctuation-free, abbreviations expanded.

    The output contains only ``[a-z0-9]`` and single spaces, which is what lets
    the search build its patterns from it without escaping anything.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(character for character in decomposed if not unicodedata.combining(character))
    lowered = plain.lower().replace("&", " and ").translate(_APOSTROPHES)
    return " ".join(ABBREVIATIONS.get(token, token) for token in _NON_WORD.split(lowered) if token)


def query_terms(text: str) -> tuple[str, ...]:
    """The distinct normalised words of a query, in the order they were typed."""
    terms: list[str] = []
    for term in normalise_text(text).split():
        if term not in terms:
            terms.append(term)
    return tuple(terms[:MAX_QUERY_TERMS])


# --- What a result is -------------------------------------------------------------
#
# Many small features are named after the place they serve: the taxi stand at the
# Davis Centre is called "Davis Centre", the information board on campus is called
# "University of Waterloo". Matched on text alone they outrank the place itself.
# A tier puts them after it without hiding them.

#: Stops and stations carry the name of what they serve; a person searching for
#: the square usually wants the square, and the stop beside it is still offered.
TRANSIT_CATEGORIES: frozenset[str] = frozenset(
    {
        "transit stop",
        "transit station",
        "transit platform",
        "bus station",
        "station",
        "halt",
        "tram stop",
    }
)

#: Features that are rarely where somebody means to go, however well they match.
INCIDENTAL_CATEGORIES: frozenset[str] = frozenset(
    {
        "artwork",
        "atm",
        "bench",
        "bicycle parking",
        "charging station",
        "clock",
        "drinking water",
        "information",
        "motorcycle parking",
        "parcel locker",
        "parking",
        "parking entrance",
        "parking space",
        "post box",
        "recycling",
        "shelter",
        "taxi",
        "telephone",
        "toilets",
        "vending machine",
        "waste basket",
    }
)


def category_tier(category: str | None) -> int:
    """0 for a place someone is likely going to, 1 for transit, 2 for incidentals."""
    if category in INCIDENTAL_CATEGORIES:
        return 2
    if category in TRANSIT_CATEGORIES:
        return 1
    return 0
