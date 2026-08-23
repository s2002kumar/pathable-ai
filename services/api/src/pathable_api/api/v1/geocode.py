"""Address search.

A POST, like route comparison, and for the same reason: "wheelchair-accessible
entrance, 200 King Street" is a statement about a person, and it does not belong
in a URL, an access log or browser history.

Search is optional. When no provider is configured the endpoint says so plainly
rather than returning an empty list, because "we found nothing" and "we did not
look" lead a user to do different things.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from pathable_api.core.errors import ApiError
from pathable_api.core.logging import get_logger
from pathable_api.geo.geocoding import MAX_QUERY_LENGTH, MAX_RESULTS, GeocodingError
from pathable_api.geo.regions import region_definition

logger = get_logger(__name__)

router = APIRouter(prefix="/geocode", tags=["geocoding"])


class GeocodeRequest(BaseModel):
    """Look up a place name within a pilot region."""

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={"examples": [{"region": "waterloo", "query": "Waterloo Public Square"}]},
    )

    region: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")] = Field(
        default="waterloo", description="Pilot region slug; results are restricted to its extent."
    )
    query: Annotated[str, Field(min_length=1, max_length=MAX_QUERY_LENGTH)] = Field(
        description="Place name or address to look for."
    )
    limit: Annotated[int, Field(ge=1, le=MAX_RESULTS)] = MAX_RESULTS


class GeocodeMatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str = Field(description="Human-readable description, as the provider wrote it.")
    longitude: float
    latitude: float
    category: str | None = Field(
        default=None, description="What the provider called this — a road, a building, a suburb."
    )


class GeocodeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = Field(description="Which geocoder answered, or 'disabled'.")
    enabled: bool = Field(
        description=(
            "False when no geocoder is configured. An empty `matches` with `enabled: false` "
            "means nothing was searched, not that nothing was found."
        )
    )
    matches: list[GeocodeMatch]
    attribution: str | None = Field(
        default=None, description="Credit the provider's licence requires."
    )


NOMINATIM_ATTRIBUTION = "Search by Nominatim, © OpenStreetMap contributors, ODbL 1.0"


@router.post(
    "/search",
    response_model=GeocodeResponse,
    summary="Find coordinates for a place name",
    description=(
        "Searches for a place within a pilot region's extent. Submit-only: there is no "
        "as-you-type endpoint, because per-keystroke queries against a donated geocoding "
        "service are forbidden by its usage policy. Nothing about the request is stored."
    ),
    operation_id="searchPlaces",
    responses={
        HTTPStatus.NOT_FOUND: {"description": "The region does not exist."},
        HTTPStatus.SERVICE_UNAVAILABLE: {"description": "The geocoding provider failed."},
    },
)
async def search(payload: GeocodeRequest, request: Request) -> GeocodeResponse:
    provider = request.app.state.geocoder

    try:
        definition = region_definition(payload.region)
    except KeyError as error:
        raise ApiError(
            status_code=HTTPStatus.NOT_FOUND,
            code="unknown_region",
            message=f"Pilot region {payload.region!r} does not exist.",
        ) from error

    if not provider.enabled:
        return GeocodeResponse(provider=provider.name, enabled=False, matches=[])

    try:
        results = await provider.search(
            payload.query, bounds=definition.bounds, limit=payload.limit
        )
    except GeocodingError as error:
        raise ApiError(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            code="geocoding_unavailable",
            message=str(error),
        ) from error

    # The query itself is deliberately absent from this log line.
    logger.info(
        "Place search served",
        extra={"region": payload.region, "provider": provider.name, "matches": len(results)},
    )

    return GeocodeResponse(
        provider=provider.name,
        enabled=True,
        matches=[
            GeocodeMatch(
                label=result.label,
                longitude=result.longitude,
                latitude=result.latitude,
                category=result.category,
            )
            for result in results
        ],
        attribution=NOMINATIM_ATTRIBUTION if provider.name == "nominatim" else None,
    )
