"""The single error shape returned by every non-2xx API response.

One shape for all failures means the frontend needs exactly one error branch, and
the generated TypeScript union stays small. Messages are written for humans and
must never contain connection strings, credentials, stack traces or internal
hostnames — see :mod:`pathable_api.core.errors` for how that is enforced.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    """A single field-level problem, used for request-validation failures."""

    model_config = ConfigDict(frozen=True)

    field: str = Field(
        description="Dotted path to the offending input, e.g. 'body.origin.lat'.",
        examples=["query.zoom"],
    )
    message: str = Field(
        description="Human-readable explanation of why this input was rejected.",
        examples=["Input should be less than or equal to 22"],
    )


class ApiErrorResponse(BaseModel):
    """Uniform error envelope."""

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "code": "not_found",
                    "message": "The requested resource does not exist.",
                    "request_id": "9f1c2b7a4e5d4f0aa1b2c3d4e5f60718",
                    "details": None,
                }
            ]
        },
    )

    code: str = Field(
        description=(
            "Stable machine-readable error identifier. Safe to branch on; the "
            "human-readable 'message' is not."
        ),
        examples=["internal_error"],
    )
    message: str = Field(
        description="Human-readable summary, safe to display. Never contains internals.",
        examples=["An unexpected error occurred."],
    )
    request_id: str | None = Field(
        default=None,
        description="Correlation id for this request; quote it when reporting a problem.",
        examples=["9f1c2b7a4e5d4f0aa1b2c3d4e5f60718"],
    )
    details: list[ErrorDetail] | None = Field(
        default=None,
        description="Field-level problems. Populated for validation errors only.",
    )
