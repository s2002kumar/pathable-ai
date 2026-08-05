"""Global error handling.

Two rules govern everything here:

1. Every non-2xx response body is an :class:`~pathable_api.schemas.errors.ApiErrorResponse`,
   so the client has exactly one error shape to parse.
2. Nothing internal crosses the boundary. Tracebacks, driver messages, connection
   strings, credentials and hostnames are logged server-side with the correlation
   id and replaced with a generic message in the response.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from pathable_api.core.logging import get_logger
from pathable_api.core.request_context import REQUEST_ID_HEADER, get_request_id
from pathable_api.schemas.errors import ApiErrorResponse, ErrorDetail

logger = get_logger(__name__)

#: Returned for any unhandled exception. Intentionally uninformative.
GENERIC_ERROR_MESSAGE = "An unexpected error occurred. Quote the request id when reporting this."


class ApiError(Exception):
    """An error the API intends to expose, with a stable machine-readable code."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: list[ErrorDetail] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def status_to_code(status_code: int) -> str:
    """Derive a stable slug such as ``not_found`` from an HTTP status code."""
    try:
        return HTTPStatus(status_code).phrase.lower().replace(" ", "_").replace("-", "_")
    except ValueError:
        return "error"


def build_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> JSONResponse:
    """Serialise a uniform error body, stamped with the correlation id."""
    request_id = get_request_id()
    payload = ApiErrorResponse(
        code=code,
        message=message,
        request_id=request_id,
        details=details,
    )
    headers = {REQUEST_ID_HEADER: request_id} if request_id else None
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers=headers,
    )


def _format_location(location: tuple[int | str, ...]) -> str:
    return ".".join(str(part) for part in location) or "body"


async def api_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Render an intentional :class:`ApiError`."""
    assert isinstance(exc, ApiError)  # noqa: S101 - handler is registered for this type only
    return build_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def http_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Render framework-raised HTTP errors (404, 405, ...) in the uniform shape."""
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    detail: Any = exc.detail
    message = detail if isinstance(detail, str) and detail else HTTPStatus(exc.status_code).phrase
    return build_error_response(
        status_code=exc.status_code,
        code=status_to_code(exc.status_code),
        message=message,
    )


async def validation_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Render request-validation failures.

    Only ``loc`` and ``msg`` are forwarded. Pydantic also reports ``input`` and
    ``ctx``, which would echo the caller's raw payload back into the response and
    into any log that captured it — omitted deliberately.
    """
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    details = [
        ErrorDetail(field=_format_location(error["loc"]), message=str(error["msg"]))
        for error in exc.errors()
    ]
    return build_error_response(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        code="validation_error",
        message="The request did not match the expected schema.",
        details=details,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last line of defence: log everything, reveal nothing."""
    logger.exception(
        "Unhandled exception while handling request",
        extra={
            "http_method": request.method,
            "http_path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )
    return build_error_response(
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        code="internal_error",
        message=GENERIC_ERROR_MESSAGE,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach every handler to ``app``."""
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
