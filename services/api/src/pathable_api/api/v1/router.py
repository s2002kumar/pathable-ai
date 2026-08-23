"""Aggregates every v1 route under a single mountable router."""

from typing import Any

from fastapi import APIRouter

from pathable_api.api.v1 import geocode, health, routes
from pathable_api.schemas.errors import ApiErrorResponse

API_V1_PREFIX = "/api/v1"

#: Declared on the router so the uniform error envelope appears in
#: ``components.schemas`` and therefore in the generated TypeScript. Without this,
#: the frontend would have a typed success path and an untyped failure path.
COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: {
        "model": ApiErrorResponse,
        "description": "The request did not match the expected schema.",
    },
    500: {
        "model": ApiErrorResponse,
        "description": "Unexpected server error. Quote the request id when reporting.",
    },
}

api_router = APIRouter(prefix=API_V1_PREFIX, responses=COMMON_ERROR_RESPONSES)
api_router.include_router(health.router)
api_router.include_router(routes.router)
api_router.include_router(geocode.router)

__all__ = ["API_V1_PREFIX", "COMMON_ERROR_RESPONSES", "api_router"]
