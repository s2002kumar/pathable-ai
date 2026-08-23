"""Vocabularies for the geospatial data model.

The single most important type here is :class:`TriState`.

OpenStreetMap accessibility tagging is sparse and uneven, and the areas with the
least data are often the least surveyed — which correlates with the areas most
likely to be inaccessible. So the absence of a tag must never be readable as
"fine". A nullable boolean invites exactly that mistake, because `if not
edge.steps` is true for both "no steps" and "nobody has said". A three-valued
type makes the distinction impossible to lose by accident.
"""

from __future__ import annotations

from enum import StrEnum


class TriState(StrEnum):
    """Yes / no / unknown.

    ``UNKNOWN`` is the default for every derived attribute. ``NO`` means there is
    affirmative evidence of absence, not merely a missing tag.
    """

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"

    @property
    def is_known(self) -> bool:
        return self is not TriState.UNKNOWN

    @property
    def is_yes(self) -> bool:
        return self is TriState.YES

    @property
    def is_no(self) -> bool:
        """True only with affirmative evidence of absence — never for unknown."""
        return self is TriState.NO


class AccessValue(StrEnum):
    """OSM access semantics, normalised.

    ``NO`` and ``PRIVATE`` are legal prohibitions rather than difficulty, so they
    become hard constraints; the rest are permissions of varying strength.
    """

    YES = "yes"
    DESIGNATED = "designated"
    PERMISSIVE = "permissive"
    DESTINATION = "destination"
    PRIVATE = "private"
    NO = "no"
    UNKNOWN = "unknown"

    @property
    def is_prohibited(self) -> bool:
        return self in {AccessValue.NO, AccessValue.PRIVATE}


class SurfaceClass(StrEnum):
    """Coarse surface grouping used by the cost model.

    The raw OSM `surface` value is kept alongside this; the class exists so cost
    policy is written against four cases rather than the ~40 values in the wild.
    """

    PAVED = "paved"
    COMPACTED = "compacted"
    ROUGH = "rough"
    UNKNOWN = "unknown"


class SmoothnessClass(StrEnum):
    """Coarse grouping of OSM `smoothness`."""

    EXCELLENT = "excellent"
    GOOD = "good"
    INTERMEDIATE = "intermediate"
    BAD = "bad"
    UNKNOWN = "unknown"


class KerbType(StrEnum):
    """Kerb (curb) treatment where a path meets a road.

    Ordered best to worst for a wheeled user: ``NONE`` (the mapper states there
    is no kerb at all) is the best case, then ``FLUSH``, then ``LOWERED``.

    ``ROLLED`` is its own tier rather than a kind of lowered kerb. The OSM wiki
    is explicit that a rolled kerb is "traversable by large wheeled vehicles,
    such as cars and bicycles, but not wheelchairs" — folding it into ``LOWERED``
    priced a wheelchair barrier at zero.

    ``PRESENT_UNKNOWN`` is "a kerb is definitely here, nobody recorded its
    height" — a `barrier=kerb` node or `kerb=yes`. That is strictly stronger
    evidence than ``UNKNOWN``, which means nothing was mapped at all, and the two
    should not cost the same.
    """

    NONE = "none"
    FLUSH = "flush"
    LOWERED = "lowered"
    ROLLED = "rolled"
    PRESENT_UNKNOWN = "present_unknown"
    RAISED = "raised"
    UNKNOWN = "unknown"


class InclineDirection(StrEnum):
    """Which way a slope runs, when the source gave direction but no magnitude.

    `incline=up` and `incline=down` are about 85% of all incline tagging in
    OpenStreetMap. Discarding them because they carry no percentage throws away
    five of every six mapped slopes — and direction alone is the actionable fact
    for a wheelchair user, who needs to know whether the ramp ahead climbs.

    The sign convention is OSM's own: ``UP`` means rising in the direction of the
    way, so reversing traversal swaps it, exactly as a numeric incline negates.
    """

    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"

    def reversed(self) -> InclineDirection:
        if self is InclineDirection.UP:
            return InclineDirection.DOWN
        if self is InclineDirection.DOWN:
            return InclineDirection.UP
        return self


class DatasetStatus(StrEnum):
    """Lifecycle of a network dataset version.

    Only ``VALIDATED`` may become ``ACTIVE``, and only one dataset per region may
    be ``ACTIVE`` at a time — both enforced in the database, not just in code.
    """

    DRAFT = "draft"
    VALIDATING = "validating"
    VALIDATED = "validated"
    ACTIVE = "active"
    RETIRED = "retired"
    FAILED = "failed"


class IngestionStatus(StrEnum):
    """Outcome of one ingestion attempt."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Severity(StrEnum):
    """Validation finding severity.

    Warnings never block activation. Real OSM data always produces some, and a
    policy that blocked on them would mean no dataset could ever go live.
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class SourceType(StrEnum):
    """Where a dataset came from.

    ``SYNTHETIC`` exists so a fixture can never be mistaken for real survey data,
    in the database or in the API.
    """

    OSM = "osm"
    SYNTHETIC = "synthetic"
