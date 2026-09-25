"""Source identities, parsed exactly as written and never coaxed into a match.

Overture records where each feature came from in ``sources[].record_id``. For
OpenStreetMap that is the element type, id and version run together:
``w1383497096@2`` is version 2 of way 1383497096. The version is the part that
matters most and is easiest to lose — an OSM way id names every revision the
way has ever had, so an id match on its own says "the same object", not "the
same data".

Parsing is strict. An identifier that does not match the documented shape is
malformed and is counted as malformed; it is not trimmed, re-cased or read with
a looser pattern until it produces a match. The same goes for linear ranges:
``between`` is ``null`` when a source covers the whole feature, and anything
that is not a well-ordered pair inside ``[0, 1]`` is recorded as malformed
rather than clamped.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

#: Overture's documented dataset label for OpenStreetMap-derived sources.
OSM_DATASET = "OpenStreetMap"


class OsmElementType(StrEnum):
    NODE = "node"
    WAY = "way"
    RELATION = "relation"


_PREFIXES: dict[str, OsmElementType] = {
    "n": OsmElementType.NODE,
    "w": OsmElementType.WAY,
    "r": OsmElementType.RELATION,
}

#: Element prefix, a positive id and a positive version, with no padding and no
#: whitespace. OSM versions start at 1, so ``@0`` is not a version.
_RECORD_ID = re.compile(r"([nwr])([1-9][0-9]*)@([1-9][0-9]*)")
_VERSION_ZERO = re.compile(r"([nwr])([1-9][0-9]*)@0")

#: How PathAble stores an OSM id: the plain decimal id, no type prefix.
_PATHABLE_OSM_ID = re.compile(r"[1-9][0-9]*")


@dataclass(frozen=True, slots=True, order=True)
class OsmElementRef:
    """One specific revision of one OSM element."""

    element_type: OsmElementType
    element_id: int
    version: int

    def __str__(self) -> str:
        prefix = self.element_type.value[0]
        return f"{prefix}{self.element_id}@{self.version}"


class MalformedReason(StrEnum):
    MISSING = "missing"
    #: A well-formed id with ``@0``. OSM has no version 0; Overture writes it on
    #: some connectors it created at an OSM node (observed 2026-09-25, always
    #: with a null ``update_time``). The id is kept; the "version" is not used.
    VERSION_ZERO = "version_zero"
    UNRECOGNISED_SHAPE = "unrecognised_shape"


@dataclass(frozen=True, slots=True)
class MalformedRecordId:
    raw: str | None
    reason: MalformedReason
    #: The element the id names, when that much is readable (``VERSION_ZERO``).
    element_type: OsmElementType | None = None
    element_id: int | None = None


def parse_osm_record_id(raw: str | None) -> OsmElementRef | MalformedRecordId:
    """Parse an Overture OSM ``record_id`` such as ``w1383497096@2``."""
    if raw is None or raw == "":
        return MalformedRecordId(raw, MalformedReason.MISSING)
    match = _RECORD_ID.fullmatch(raw)
    if match is None:
        zero = _VERSION_ZERO.fullmatch(raw)
        if zero is not None:
            return MalformedRecordId(
                raw, MalformedReason.VERSION_ZERO, _PREFIXES[zero.group(1)], int(zero.group(2))
            )
        return MalformedRecordId(raw, MalformedReason.UNRECOGNISED_SHAPE)
    prefix, element_id, version = match.groups()
    return OsmElementRef(_PREFIXES[prefix], int(element_id), int(version))


def parse_pathable_osm_id(raw: str | None) -> int | None:
    """Read an OSM id as PathAble stores it (``source_way_id``/``source_node_id``).

    ``None`` when the value is not an OSM id at all — the synthetic fixture uses
    names like ``synthetic-003`` precisely so it can never pass for real data.
    PathAble stores no version, which is why this returns a bare id.
    """
    if raw is None or _PATHABLE_OSM_ID.fullmatch(raw) is None:
        return None
    return int(raw)


@dataclass(frozen=True, slots=True, order=True)
class LinearRange:
    """A portion of a feature, as fractions of its length from its start."""

    start: float
    end: float

    def as_list(self) -> list[float]:
        return [self.start, self.end]


@dataclass(frozen=True, slots=True)
class MalformedRange:
    raw: tuple[float, ...]


def parse_between(raw: Sequence[float] | None) -> LinearRange | MalformedRange | None:
    """Interpret an Overture ``between`` value.

    ``None`` means the source applies to the whole feature — Overture's own
    convention, and a different fact from an explicit ``[0, 1]``, so the two are
    kept apart rather than normalised into one another.
    """
    if raw is None:
        return None
    values = tuple(raw)
    if len(values) != 2 or not all(math.isfinite(value) for value in values):
        return MalformedRange(values)
    start, end = values
    if not 0.0 <= start < end <= 1.0:
        return MalformedRange(values)
    return LinearRange(start, end)
