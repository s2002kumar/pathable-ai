"""Request and response models for route comparison.

Everything a client can learn about a route is declared here, which means it also
appears in the OpenAPI document and in the generated TypeScript. Three shapes are
deliberate:

* Accessibility values are ``"yes" | "no" | "unknown"`` rather than booleans. A
  boolean cannot express "nobody has recorded this", and a client that receives
  ``false`` will render "no steps" for a segment nobody has ever surveyed.
* ``ml_predictions_used`` is always present and always ``false``. PathAble
  contains no model; stating that explicitly stops a client from inferring
  otherwise from silence, and makes the day it changes a visible change.
* Cost is reported both as real distance and as effective metres, with the
  components that produced it. A route people are asked to trust has to be able
  to show its working.
"""

from __future__ import annotations

from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from pathable_api.geo.enums import KerbType, SmoothnessClass, SurfaceClass, TriState
from pathable_api.routing.profiles import SELECTABLE_PROFILE_KEYS

#: Waterloo sits near (-80.52, 43.47); the ranges here are the WGS84 limits, and
#: region membership is checked separately against the pilot boundary.
Longitude = Annotated[float, Field(ge=-180.0, le=180.0)]
Latitude = Annotated[float, Field(ge=-90.0, le=90.0)]

ProfileKey = Literal["wheelchair", "walker", "crutches", "stroller", "reduced_mobility", "custom"]


def _check_profile_keys_match_registry() -> None:
    """Fail at import if the wire enum and the profile registry disagree.

    The literal above is what generates the client's TypeScript union. A profile
    added to the registry but not here would be unreachable from the frontend,
    and the mismatch would surface as a puzzling 422 rather than a clear error.
    """
    declared = set(get_args(ProfileKey))
    missing = set(SELECTABLE_PROFILE_KEYS) - declared
    if missing:
        msg = f"Mobility profiles missing from the API schema: {', '.join(sorted(missing))}"
        raise RuntimeError(msg)


_check_profile_keys_match_registry()


class Coordinate(BaseModel):
    """A WGS84 position."""

    model_config = ConfigDict(frozen=True)

    longitude: Longitude = Field(description="Degrees east of the prime meridian.")
    latitude: Latitude = Field(description="Degrees north of the equator.")


class CustomProfileOptions(BaseModel):
    """Overrides for the ``custom`` profile.

    Deliberately narrow. Exposing every cost weight would let a client build a
    model nobody has reasoned about, and the resulting route would still carry
    PathAble's name.
    """

    model_config = ConfigDict(frozen=True)

    base: Literal["wheelchair", "walker", "crutches", "stroller", "reduced_mobility"] = Field(
        default="wheelchair",
        description="Preset the custom profile starts from.",
    )
    exclude_steps: bool | None = Field(default=None, description="Treat stairways as impassable.")
    max_incline_percent: Annotated[float, Field(ge=0.0, le=45.0)] | None = Field(
        default=None,
        description="Steepest recorded gradient to allow. Unrecorded gradients are never excluded.",
    )
    min_width_m: Annotated[float, Field(ge=0.0, le=5.0)] | None = Field(
        default=None,
        description="Narrowest recorded width to allow. Unrecorded widths are never excluded.",
    )
    avoid_rough_surface: bool | None = Field(
        default=None, description="Treat gravel, dirt and cobblestone as impassable."
    )


class RouteCompareRequest(BaseModel):
    """Ask for the shortest route and an accessibility-aware alternative."""

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "region": "waterloo",
                    "origin": {"longitude": -80.5449, "latitude": 43.4643},
                    "destination": {"longitude": -80.5204, "latitude": 43.4723},
                    "profile": "wheelchair",
                }
            ]
        },
    )

    region: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")] = Field(
        default="waterloo", description="Pilot region slug."
    )
    origin: Coordinate
    destination: Coordinate
    profile: ProfileKey = Field(
        default="wheelchair", description="Mobility profile for the accessible route."
    )
    custom: CustomProfileOptions | None = Field(
        default=None,
        description="Only used when `profile` is `custom`; ignored otherwise.",
    )


class CostComponentModel(BaseModel):
    """One contribution to a segment's cost."""

    model_config = ConfigDict(frozen=True)

    code: Literal[
        "distance",
        "surface",
        "smoothness",
        "incline",
        "steps",
        "kerb",
        "crossing",
        "width",
        "uncertainty",
    ]
    effective_metres: float = Field(description="Effective metres this contribution added.")
    detail: str = Field(description="Plain-language reason, derived from recorded attributes.")


class RouteSegmentModel(BaseModel):
    """One mapped segment as traversed by a route."""

    model_config = ConfigDict(frozen=True)

    edge_identity: str = Field(description="Stable identity of this segment within the dataset.")
    name: str | None = Field(default=None, description="Street or path name, when OSM records one.")
    length_m: float
    effective_metres: float = Field(
        description="What this segment cost the chosen profile, in effective metres."
    )
    coordinates: list[tuple[float, float]] = Field(
        description="[longitude, latitude] positions, oriented along travel."
    )
    highway: str | None = None
    surface: str | None = Field(default=None, description="Raw OSM surface value, if recorded.")
    surface_class: SurfaceClass
    smoothness_class: SmoothnessClass
    steps: TriState = Field(
        description="Whether this segment is a stairway. `unknown` means nobody has recorded it."
    )
    step_count: int | None = None
    incline_percent: float | None = Field(
        default=None, description="Recorded gradient. Null means unrecorded, not flat."
    )
    kerb: KerbType
    is_crossing: bool
    width_m: float | None = Field(
        default=None, description="Recorded width. Null means unrecorded, not narrow."
    )
    unknown_attributes: list[str] = Field(
        description="Routing-relevant attributes nobody has recorded for this segment."
    )
    cost_components: list[CostComponentModel]


class SnappedPointModel(BaseModel):
    """Where a requested coordinate joined the network."""

    model_config = ConfigDict(frozen=True)

    longitude: float
    latitude: float
    distance_m: float = Field(
        description="How far the requested point was from the nearest mapped path."
    )


class RouteModel(BaseModel):
    """A computed route."""

    model_config = ConfigDict(frozen=True)

    profile: str = Field(description="Profile key this route was computed for.")
    profile_display_name: str
    distance_m: float = Field(description="Real ground distance.")
    effective_distance_m: float = Field(
        description="Distance weighted by this profile's cost model. Not a physical distance."
    )
    estimated_duration_seconds: float = Field(
        description=(
            "Rough planning estimate from distance and obstacle counts. Not measured, and not "
            "specific to any individual."
        )
    )
    coordinates: list[tuple[float, float]] = Field(
        description="[longitude, latitude] polyline for the whole route."
    )
    segments: list[RouteSegmentModel]
    origin: SnappedPointModel
    destination: SnappedPointModel
    stairway_count: int
    step_count: int = Field(description="Recorded steps across all stairways on this route.")
    crossing_count: int
    unknown_kerb_crossing_count: int
    steepest_incline_percent: float | None
    unknown_data_fraction: float = Field(
        ge=0.0,
        le=1.0,
        description="Share of this route's length whose accessibility attributes are unrecorded.",
    )
    evidence_coverage: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Share of this route with no record, per category (surface, smoothness, gradient, "
            "width, kerb). Kerb is measured over crossings only, since it is a fact about "
            "crossings. Reported per category because one combined figure cannot be acted on."
        ),
    )
    gradient_source: str | None = Field(
        default=None,
        description=(
            "Where gradient information came from: 'osm_incline' (recorded by a mapper), "
            "'derived_elevation' (inferred from a terrain model), 'mixed', or null when the "
            "route has no gradient information at all."
        ),
    )
    computation_ms: float


class ExplanationModel(BaseModel):
    """An evidence-backed statement about why the accessible route differs."""

    model_config = ConfigDict(frozen=True)

    code: str
    summary: str
    evidence: dict[str, object] = Field(
        default_factory=dict,
        description="The recorded values this statement was derived from.",
    )


class CautionModel(BaseModel):
    """Something to weigh before relying on the route."""

    model_config = ConfigDict(frozen=True)

    code: str
    summary: str
    evidence: dict[str, object] = Field(default_factory=dict)


class DatasetProvenance(BaseModel):
    """Which network answered this request."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    region: str
    checksum: str = Field(description="Content hash of the dataset that produced this route.")
    source_type: Literal["osm", "synthetic"]
    source_name: str
    acquired_at: str = Field(
        description="When PathAble obtained this dataset, ISO 8601. Not how old the map is."
    )
    source_timestamp: str | None = Field(
        default=None,
        description=(
            "When the upstream source published this data, ISO 8601. This is the figure that "
            "says how current the map is; `acquired_at` only says when it was fetched. Null "
            "when the source published no timestamp."
        ),
    )
    evidence_age_days: int | None = Field(
        default=None,
        description=(
            "Whole days between the upstream publication and this response. Null when the "
            "source published no timestamp. A route cannot say a particular crossing was "
            "surveyed years ago — OpenStreetMap element timestamps are not yet ingested — so "
            "this is the age of the dataset, not of any individual fact in it."
        ),
    )
    attribution: str = Field(
        description="Required credit for the underlying map data.",
        examples=["© OpenStreetMap contributors, ODbL 1.0"],
    )
    elevation_attribution: str | None = Field(
        default=None,
        description=(
            "Required credit for the elevation model behind any derived gradient in this "
            "response. Null when the dataset carries no elevation at all, in which case every "
            "gradient shown was recorded by a mapper or is unknown."
        ),
        examples=[
            # The licence's own wording uses an en dash.
            "Contains information licensed under the Open Government Licence – Canada."  # noqa: RUF001
        ],
    )


class RouteCompareResponse(BaseModel):
    """The shortest route, the accessible route, and the difference between them."""

    model_config = ConfigDict(frozen=True)

    profile: str
    profile_display_name: str
    profile_description: str
    standard_route: RouteModel | None = Field(
        default=None, description="Shortest walking route. Null when none exists."
    )
    accessible_route: RouteModel | None = Field(
        default=None,
        description="Route meeting the chosen profile. Null when no such route exists.",
    )
    standard_failure: str | None = Field(
        default=None, description="Why the shortest route could not be computed."
    )
    accessible_failure: str | None = Field(
        default=None, description="Why no route satisfies the chosen profile."
    )
    extra_distance_m: float | None = Field(
        default=None, description="How much further the accessible route is."
    )
    extra_distance_fraction: float | None = None
    explanations: list[ExplanationModel]
    cautions: list[CautionModel]
    dataset: DatasetProvenance
    routing_policy_version: int = Field(
        description=(
            "Which cost and constraint policy produced this route. Bumped whenever a "
            "change would move a route, so two results can be compared meaningfully."
        )
    )
    ml_predictions_used: Literal[False] = Field(
        default=False,
        description=(
            "Always false. PathAble's routing is deterministic rules over recorded map "
            "attributes; no model prediction contributes to any cost or constraint."
        ),
    )


class MobilityProfileModel(BaseModel):
    """A profile a client can offer."""

    model_config = ConfigDict(frozen=True)

    key: str
    display_name: str
    description: str
    excludes_steps: bool = Field(
        description="Whether stairways are excluded outright for this profile."
    )
    max_incline_percent: float | None = Field(
        default=None,
        description=(
            "A hard limit: recorded gradients above this are excluded. Null for every "
            "preset — a preset expresses gradient as preference, not impossibility."
        ),
    )
    min_width_m: float | None = Field(
        default=None, description="A hard limit: recorded widths below this are excluded."
    )
    prefers_gradient_under_percent: float | None = Field(
        default=None,
        description=(
            "Guidance, not a limit. Steeper segments cost far more but remain available "
            "when the only alternative is no route."
        ),
    )
    prefers_width_over_m: float | None = Field(default=None, description="Guidance, not a limit.")
    hard_requirements: list[str] = Field(
        default_factory=list,
        description="Plain statements of what this traveller cannot use. Empty when nothing is excluded.",
    )


class MobilityProfileListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    profiles: list[MobilityProfileModel]
