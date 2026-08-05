"""Pydantic response models.

These models are the single source of truth for the HTTP contract: the OpenAPI
document is generated from them, and the frontend's TypeScript types are generated
from that document. Never hand-write an equivalent type on the client.
"""

from pathable_api.schemas.errors import ApiErrorResponse, ErrorDetail
from pathable_api.schemas.health import (
    DependencyCheck,
    LivenessResponse,
    ReadinessChecks,
    ReadinessResponse,
)

__all__ = [
    "ApiErrorResponse",
    "DependencyCheck",
    "ErrorDetail",
    "LivenessResponse",
    "ReadinessChecks",
    "ReadinessResponse",
]
