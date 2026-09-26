"""What a Kitchener value means, and what it does not.

Three classifications, all for analysis only — none of them is a routing rule.

**Field state.** A value is exactly one of: not published, null, blank, an
explicit unknown code, an explicit not-applicable code, the layer's template
default, a non-default value from the domain, or a value outside the domain.
Defaults and domains are read from the snapshot's own layer description, not
typed in here, so the classification follows the source if the City changes
its schema. A value equal to the default is kept apart from every other value,
because nothing in the data can tell a deliberate ``CONCRETE`` from a template
that nobody edited.

**Network role and lifecycle.** Physical infrastructure, virtual street
crossings, unofficial connections and non-pedestrian facilities are separated
using the City's own definitions (layer metadata, "History"). A record with
any virtual signal is never counted as physical: where the signals disagree
it is ``unresolved``.

**Evidence origin.** For each field, what the City's documentation says the
value is — surveyed, asserted, derived by a script, or a record-keeping
timestamp — refined per record by the field state. Where the documentation
says nothing, the origin is ``unresolved``; it is not guessed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class FieldState(StrEnum):
    NOT_PUBLISHED = "not_published"
    NULL = "null"
    BLANK = "blank"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    TEMPLATE_DEFAULT = "template_default"
    NON_DEFAULT = "non_default"
    OUT_OF_DOMAIN = "out_of_domain"


#: Coded values that mean "not known", per field. ``CURBCUT`` spells it ``U``.
UNKNOWN_CODES: dict[str, frozenset[str]] = {
    "CURBCUT": frozenset({"U"}),
}
_UNKNOWN_DEFAULT = frozenset({"UNKNOWN"})

#: Coded values that mean "does not apply to this record".
NOT_APPLICABLE_CODES = frozenset({"NA", "NA (VIRTUAL LINK)"})


@dataclass(frozen=True, slots=True)
class FieldSchema:
    """What the layer description says about one field."""

    name: str
    esri_type: str
    default: Any
    #: Coded-value domain, when the field has one.
    domain: frozenset[Any] | None


def schemas_from_layer(layer: Mapping[str, Any]) -> dict[str, FieldSchema]:
    schemas: dict[str, FieldSchema] = {}
    for item in layer.get("fields") or []:
        domain = item.get("domain") or {}
        codes = (
            frozenset(value.get("code") for value in domain.get("codedValues") or [])
            if domain.get("type") == "codedValue"
            else None
        )
        schemas[str(item["name"])] = FieldSchema(
            name=str(item["name"]),
            esri_type=str(item.get("type")),
            default=item.get("defaultValue"),
            domain=codes,
        )
    return schemas


def field_state(schema: FieldSchema | None, value: Any, *, published: bool = True) -> FieldState:
    """Classify one value. The order of the checks is the definition."""
    if not published or schema is None:
        return FieldState.NOT_PUBLISHED
    if value is None:
        return FieldState.NULL
    if isinstance(value, str) and not value.strip():
        return FieldState.BLANK
    if isinstance(value, str):
        if value in UNKNOWN_CODES.get(schema.name, _UNKNOWN_DEFAULT):
            return FieldState.UNKNOWN
        if value in NOT_APPLICABLE_CODES:
            return FieldState.NOT_APPLICABLE
    if schema.default is not None and _same(value, schema.default):
        return FieldState.TEMPLATE_DEFAULT
    if schema.domain is not None and not any(_same(value, code) for code in schema.domain):
        return FieldState.OUT_OF_DOMAIN
    return FieldState.NON_DEFAULT


def _same(value: Any, other: Any) -> bool:
    if isinstance(value, bool) or isinstance(other, bool):
        return value is other
    if isinstance(value, int | float) and isinstance(other, int | float):
        return float(value) == float(other)
    return bool(value == other)


# ---------------------------------------------------------------------------
# Network role, lifecycle and physical/virtual class
# ---------------------------------------------------------------------------


class NetworkRole(StrEnum):
    PEDESTRIAN_WAY = "pedestrian_way"
    PEDESTRIAN_CROSSING = "pedestrian_crossing"
    CYCLING_CROSSING = "cycling_or_shared_crossing"
    CYCLING_FACILITY = "cycling_facility"
    MAINTENANCE_ACCESS = "maintenance_access"
    VIRTUAL_LINK = "virtual_link"
    UNOFFICIAL_CONNECTION = "unofficial_connection"
    UNRESOLVED = "unresolved"


#: The City's metadata: "Links (virtual street crossings)".
VIRTUAL_LINK_SUBCATEGORIES = frozenset({"LINK (PEDESTRIAN)", "LINK (MUT)", "LINK (CYCLING)"})
#: The City's metadata: "Connections (unofficial routes along roads or driveways
#: connecting separate facilities)".
UNOFFICIAL_CONNECTION_SUBCATEGORIES = frozenset({"DRIVEWAY CONNECTION", "ON-ROAD CONNECTION"})
PEDESTRIAN_WAY_SUBCATEGORIES = frozenset(
    {"SIDEWALK", "CONTINUOUS SIDEWALK", "WALKWAY", "MUT", "BMUT", "MAJOR TRAIL", "MINOR TRAIL"}
)
PEDESTRIAN_CROSSING_SUBCATEGORIES = frozenset(
    {"CROSSWALK", "TRAIL CROSSING", "RAISED TRAIL CROSSING"}
)
#: Crossings the City's metadata does not define. Whether a pedestrian may use
#: a crossride is not stated, so these are not counted as pedestrian crossings.
CYCLING_CROSSING_SUBCATEGORIES = frozenset(
    {"CROSSBIKE", "SEPARATE CROSSRIDE", "COMBINED CROSSRIDE", "MIXED CROSSRIDE"}
)
CYCLING_FACILITY_SUBCATEGORIES = frozenset(
    {
        "BICYCLE LANE",
        "BICYCLE LANE (CONTRAFLOW)",
        "BICYCLE LANE (SEPARATED)",
        "CYCLE TRACK",
        "PAVED SHOULDER",
        "MARKED SHARED-USE",
        "NEIGHBOURHOOD BIKEWAY",
        "SIGNED ROUTE",
        "TRANSITION TO BMUT",
        "SINGLE TRACK",
    }
)
MAINTENANCE_SUBCATEGORIES = frozenset({"SANITARY AND STORMWATER UTILITIES"})

#: Which category each subcategory is filed under when the two agree.
EXPECTED_CATEGORY: dict[frozenset[str], frozenset[str]] = {
    VIRTUAL_LINK_SUBCATEGORIES | UNOFFICIAL_CONNECTION_SUBCATEGORIES: frozenset({"NETWORK LINKS"}),
    frozenset({"SIDEWALK", "CONTINUOUS SIDEWALK", "WALKWAY", "CROSSWALK"}): frozenset(
        {"SIDEWALKS AND WALKWAYS"}
    ),
    frozenset(
        {"MUT", "BMUT", "MAJOR TRAIL", "MINOR TRAIL", "TRAIL CROSSING", "RAISED TRAIL CROSSING"}
    ): frozenset({"PATHWAYS"}),
    CYCLING_CROSSING_SUBCATEGORIES: frozenset({"PATHWAYS", "CYCLING"}),
    CYCLING_FACILITY_SUBCATEGORIES: frozenset({"CYCLING"}),
    MAINTENANCE_SUBCATEGORIES: frozenset({"MAINTENANCE ACCESS"}),
}

VIRTUAL_CODE = "NA (VIRTUAL LINK)"
STRUCTURE_TYPES = frozenset({"STAIRS", "BRIDGE", "OVERPASS", "UNDERPASS", "BOARDWALK"})


@dataclass(frozen=True, slots=True)
class RoleDecision:
    role: NetworkRole
    #: Why a record is unresolved, or the category disagreement a resolved one carries.
    note: str | None = None


def network_role(
    category: str | None,
    subcategory: str | None,
    feature_type: str | None,
    surface_material: str | None,
) -> RoleDecision:
    """The role a record plays, from its subcategory, never optimistic.

    A link subcategory is virtual whatever category it is filed under. An
    unofficial connection is its own class — the City codes most of them with
    the virtual-link surface, which is recorded as a note, not a conflict. A
    physical subcategory that carries a virtual code, or is filed under
    ``NETWORK LINKS``, could be either, so it is ``unresolved`` — it is never
    counted as physical. Any other category disagreement is kept as a note.
    """
    virtual_codes = [
        name
        for name, present in (
            ("feature_type", feature_type == VIRTUAL_CODE),
            ("surface_material", surface_material == VIRTUAL_CODE),
        )
        if present
    ]
    if subcategory in VIRTUAL_LINK_SUBCATEGORIES:
        return RoleDecision(NetworkRole.VIRTUAL_LINK, _category_mismatch(category, subcategory))
    if subcategory is None:
        return RoleDecision(NetworkRole.UNRESOLVED, "no subcategory")
    if subcategory in UNOFFICIAL_CONNECTION_SUBCATEGORIES:
        notes = [_category_mismatch(category, subcategory)]
        if virtual_codes:
            notes.append(f"virtual code in {', '.join(virtual_codes)}")
        return RoleDecision(
            NetworkRole.UNOFFICIAL_CONNECTION, "; ".join(n for n in notes if n) or None
        )
    if virtual_codes:
        return RoleDecision(
            NetworkRole.UNRESOLVED,
            f"subcategory {subcategory!r} with a virtual code in {', '.join(virtual_codes)}",
        )
    if category == "NETWORK LINKS":
        return RoleDecision(
            NetworkRole.UNRESOLVED, f"subcategory {subcategory!r} filed under NETWORK LINKS"
        )
    for subcategories, role in (
        (PEDESTRIAN_WAY_SUBCATEGORIES, NetworkRole.PEDESTRIAN_WAY),
        (PEDESTRIAN_CROSSING_SUBCATEGORIES, NetworkRole.PEDESTRIAN_CROSSING),
        (CYCLING_CROSSING_SUBCATEGORIES, NetworkRole.CYCLING_CROSSING),
        (CYCLING_FACILITY_SUBCATEGORIES, NetworkRole.CYCLING_FACILITY),
        (MAINTENANCE_SUBCATEGORIES, NetworkRole.MAINTENANCE_ACCESS),
    ):
        if subcategory in subcategories:
            return RoleDecision(role, _category_mismatch(category, subcategory))
    return RoleDecision(NetworkRole.UNRESOLVED, f"subcategory {subcategory!r} is not classified")


def _category_mismatch(category: str | None, subcategory: str) -> str | None:
    for subcategories, categories in EXPECTED_CATEGORY.items():
        if subcategory in subcategories:
            if category in categories:
                return None
            return f"subcategory {subcategory!r} filed under category {category!r}"
    return None


class Lifecycle(StrEnum):
    ACTIVE = "ACTIVE"
    PLANNED = "PLANNED"
    POTENTIAL = "POTENTIAL"
    CLOSED = "CLOSED"
    UNDESIGNATED = "UNDESIGNATED"
    NULL = "null"
    NOT_PUBLISHED = "not_published"


def lifecycle(status: str | None, *, published: bool) -> Lifecycle:
    if not published:
        return Lifecycle.NOT_PUBLISHED
    if status is None:
        return Lifecycle.NULL
    try:
        return Lifecycle(status)
    except ValueError:
        return Lifecycle.NULL


class PhysicalClass(StrEnum):
    PHYSICAL_ACTIVE = "physical_active"
    PHYSICAL_STATUS_NOT_PUBLISHED = "physical_status_not_published"
    VIRTUAL_LINK = "virtual_link"
    UNOFFICIAL_CONNECTION = "unofficial_connection"
    PLANNED = "planned_or_potential"
    CLOSED = "closed"
    UNRESOLVED = "unresolved"


def physical_class(role: NetworkRole, state: Lifecycle) -> PhysicalClass:
    """One summary class per record. Lifecycle first: a closed link is closed."""
    if state is Lifecycle.CLOSED:
        return PhysicalClass.CLOSED
    if state in (Lifecycle.PLANNED, Lifecycle.POTENTIAL):
        return PhysicalClass.PLANNED
    if role is NetworkRole.VIRTUAL_LINK:
        return PhysicalClass.VIRTUAL_LINK
    if role is NetworkRole.UNOFFICIAL_CONNECTION:
        return PhysicalClass.UNOFFICIAL_CONNECTION
    if role is NetworkRole.UNRESOLVED or state in (Lifecycle.UNDESIGNATED, Lifecycle.NULL):
        return PhysicalClass.UNRESOLVED
    if state is Lifecycle.NOT_PUBLISHED:
        return PhysicalClass.PHYSICAL_STATUS_NOT_PUBLISHED
    return PhysicalClass.PHYSICAL_ACTIVE


def structure(feature_type: str | None) -> str | None:
    return feature_type if feature_type in STRUCTURE_TYPES else None


# ---------------------------------------------------------------------------
# Evidence origin
# ---------------------------------------------------------------------------


class Origin(StrEnum):
    OBSERVED_SURVEY = "observed_survey"
    OBSERVED_EVENT = "observed_event"
    ADMINISTRATIVE_ASSERTION = "administrative_assertion"
    DERIVED = "derived"
    TEMPLATE_DEFAULT = "template_default"
    UNKNOWN = "unknown"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class DocumentedOrigin:
    """What the City says a field's non-default value is, and where it says so."""

    origin: Origin
    basis: str


#: From the City's field documentation (``metadata_walkability`` in the snapshot)
#: and, for the slope fields, from the value of ``SLOPE_GRADIENT_SOURCE`` itself.
DOCUMENTED_ORIGINS: dict[str, DocumentedOrigin] = {
    "STATUS": DocumentedOrigin(
        Origin.ADMINISTRATIVE_ASSERTION,
        "Lifecycle set by the City; new sidewalks enter as pending and become Active when "
        "houses are built (metadata: Maintenance).",
    ),
    "CATEGORY": DocumentedOrigin(
        Origin.ADMINISTRATIVE_ASSERTION, "Major branch of Active Transportation mode."
    ),
    "SUBCATEGORY": DocumentedOrigin(
        Origin.ADMINISTRATIVE_ASSERTION,
        "Further breakdown; reflects the 2020 Cycling and Trails Master Plan.",
    ),
    "FEATURE_TYPE": DocumentedOrigin(
        Origin.ADMINISTRATIVE_ASSERTION,
        "Locations of bridges and other non-standard asset types; default SURFACE.",
    ),
    "SURFACE_MATERIAL": DocumentedOrigin(
        Origin.ADMINISTRATIVE_ASSERTION,
        "Type of surface material of the asset; default CONCRETE.",
    ),
    "WIDTH_M": DocumentedOrigin(
        Origin.ADMINISTRATIVE_ASSERTION,
        "Width of facility in metres from a coded list; documented 'default width 1.8m', "
        "schema default 1.5.",
    ),
    "CURBCUT": DocumentedOrigin(
        Origin.ADMINISTRATIVE_ASSERTION,
        "Whether the facility is a curbcut down to street level; default N, U is unknown.",
    ),
    "RAILING": DocumentedOrigin(
        Origin.ADMINISTRATIVE_ASSERTION, "Presence of railing along the segment; default N."
    ),
    "SURFACE_CONDITION": DocumentedOrigin(
        Origin.OBSERVED_SURVEY,
        "Surface condition 'as found in the 2015 Trail inventory project'; default GOOD. "
        "Dated by the documentation, not per record.",
    ),
    "GRADE": DocumentedOrigin(
        Origin.DERIVED, "Maximum slope along the facility 'as calculated through a script'."
    ),
    "SLOPE_GRADIENT_PERCENT": DocumentedOrigin(
        Origin.DERIVED, "SLOPE_GRADIENT_SOURCE names an FME workspace (CalculateTrailGradient)."
    ),
    "SLOPE_GRADIENT_CLASS": DocumentedOrigin(
        Origin.DERIVED, "SLOPE_GRADIENT_SOURCE names an FME workspace (CalculateTrailGradient)."
    ),
    "SLOPE_GRADIENT_MAX": DocumentedOrigin(
        Origin.DERIVED, "SLOPE_GRADIENT_SOURCE names an FME workspace (CalculateTrailGradient)."
    ),
    "SLOPE_GRADIENT_MIN": DocumentedOrigin(
        Origin.DERIVED, "SLOPE_GRADIENT_SOURCE names an FME workspace (CalculateTrailGradient)."
    ),
    "SLOPE_GRADIENT_AVG": DocumentedOrigin(
        Origin.DERIVED, "SLOPE_GRADIENT_SOURCE names an FME workspace (CalculateTrailGradient)."
    ),
    "GRADE_CATEGORY_MAX": DocumentedOrigin(
        Origin.UNRESOLVED, "Undocumented. Not attributed to any process by the City."
    ),
    "CONDITION_SCORE": DocumentedOrigin(
        Origin.DERIVED, "'Calculated condition score from Cityworks'."
    ),
    "CONDITION_DATE": DocumentedOrigin(
        Origin.DERIVED, "'Date of calculated condition score from Cityworks'."
    ),
    "LAST_INSPECTION_YEAR": DocumentedOrigin(
        Origin.OBSERVED_EVENT,
        "'Last year feature was inspected through the sidewalker inspection program in "
        "Engineering or Operations trail inspections'. Records that an inspection happened, "
        "not what it found.",
    ),
    "INSTALLATION_YEAR": DocumentedOrigin(
        Origin.ADMINISTRATIVE_ASSERTION,
        "'Year the asset was installed. Usually a database maintained field.'",
    ),
}

#: States that carry no information about the facility at all.
_NO_EVIDENCE = frozenset(
    {
        FieldState.NOT_PUBLISHED,
        FieldState.NULL,
        FieldState.BLANK,
        FieldState.UNKNOWN,
        FieldState.NOT_APPLICABLE,
    }
)


def value_origin(field_name: str, state: FieldState) -> Origin:
    """The origin of one value, from the field's documentation and its state."""
    if state in _NO_EVIDENCE:
        return Origin.UNKNOWN
    if state is FieldState.TEMPLATE_DEFAULT:
        return Origin.TEMPLATE_DEFAULT
    documented = DOCUMENTED_ORIGINS.get(field_name)
    if documented is None or state is FieldState.OUT_OF_DOMAIN:
        return Origin.UNRESOLVED
    return documented.origin


# ---------------------------------------------------------------------------
# SOURCE vocabulary
# ---------------------------------------------------------------------------


class SourceClass(StrEnum):
    ORTHOIMAGERY = "orthoimagery"
    ENGINEERING_PLAN = "engineering_plan"
    TRAIL_INVENTORY_2015 = "trail_inventory_2015"
    PROJECT_OR_PROGRAMME = "project_or_programme"
    STAFF_ASSERTION = "staff_assertion"
    PERSONAL_OBSERVATION = "personal_observation"
    STREET_LEVEL_IMAGERY = "street_level_imagery"
    PLACEHOLDER = "placeholder"
    OTHER = "other"
    NULL = "null"


#: Checked in order; the first match wins.
_SOURCE_PATTERNS: tuple[tuple[SourceClass, re.Pattern[str]], ...] = (
    (SourceClass.PERSONAL_OBSERVATION, re.compile(r"PERSONAL OBSERVATION", re.IGNORECASE)),
    (SourceClass.STREET_LEVEL_IMAGERY, re.compile(r"STREET\s?VIEW", re.IGNORECASE)),
    (SourceClass.ORTHOIMAGERY, re.compile(r"\bORTHO\b", re.IGNORECASE)),
    (
        SourceClass.TRAIL_INVENTORY_2015,
        re.compile(r"^2015 TRAIL INVENTORY PROJECT$", re.IGNORECASE),
    ),
    (SourceClass.STAFF_ASSERTION, re.compile(r"\bSTAFF\b", re.IGNORECASE)),
    (SourceClass.ENGINEERING_PLAN, re.compile(r"PLAN|AS BUILT|^SP\d{5}", re.IGNORECASE)),
    (
        SourceClass.PROJECT_OR_PROGRAMME,
        re.compile(r"PROJECT|INVENTORY|CTMP|ATMP|VISION ZERO|GRADING", re.IGNORECASE),
    ),
    (SourceClass.PLACEHOLDER, re.compile(r"^TO INPUT$", re.IGNORECASE)),
)

#: Classes whose raw values may be published verbatim in committed evidence.
#: The City's documentation says SOURCE may name "specific staff member[s]", so
#: personal observations and unclassified values are published as counts only.
PUBLISHABLE_SOURCE_CLASSES = frozenset(
    {
        SourceClass.ORTHOIMAGERY,
        SourceClass.ENGINEERING_PLAN,
        SourceClass.TRAIL_INVENTORY_2015,
        SourceClass.PROJECT_OR_PROGRAMME,
        SourceClass.STAFF_ASSERTION,
        SourceClass.STREET_LEVEL_IMAGERY,
        SourceClass.PLACEHOLDER,
    }
)

_YEAR = re.compile(r"\b(19[5-9]\d|20\d{2})\b")


def source_class(value: str | None) -> SourceClass:
    if value is None or not value.strip():
        return SourceClass.NULL
    for kind, pattern in _SOURCE_PATTERNS:
        if pattern.search(value):
            return kind
    return SourceClass.OTHER


def source_year(value: str | None) -> int | None:
    """The year named in an orthoimagery source ("ORTHO 2012"), if there is one."""
    if value is None or source_class(value) is not SourceClass.ORTHOIMAGERY:
        return None
    match = _YEAR.search(value)
    return int(match.group(1)) if match else None


#: Account names in ``UPDATE_BY`` that name a system, not a person. Anything
#: else is reduced to "named_account" before it leaves the raw snapshot.
SYSTEM_ACCOUNTS = frozenset({"GIS_DATA", "AGOL_USER"})


def update_account(value: str | None) -> str | None:
    if value is None:
        return None
    return value if value in SYSTEM_ACCOUNTS else "named_account"
