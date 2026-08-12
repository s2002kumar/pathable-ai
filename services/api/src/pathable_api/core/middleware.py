"""HTTP middleware: request-size limits, request correlation and access logging."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from http import HTTPStatus

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from pathable_api.core.errors import build_error_response, unhandled_exception_handler
from pathable_api.core.logging import get_logger
from pathable_api.core.request_context import (
    REQUEST_ID_HEADER,
    reset_request_id,
    resolve_request_id,
    set_request_id,
)

logger = get_logger(__name__)

#: Largest request body the API will read, in bytes.
#:
#: Every endpoint takes a small fixed structure — two coordinates and a profile
#: name, or a short search string — so 64 KiB is generous by three orders of
#: magnitude. Without a cap, an unauthenticated caller can make the server buffer
#: an arbitrarily large body before validation ever runs, which is a
#: denial-of-service primitive that costs the attacker almost nothing.
MAX_REQUEST_BODY_BYTES = 64 * 1024


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject over-large request bodies before they are read.

    A declared `Content-Length` is checked up front, which stops the common case
    without buffering anything. A chunked request without that header is not
    rejected here: Starlette would have to consume the stream to measure it,
    which is the cost this exists to avoid. Bounding those is the job of whatever
    reverse proxy eventually sits in front of this service, and is recorded in
    the threat model.

    This sits *inside* the correlation middleware, so a 413 carries a request id.
    Correlation costs a UUID and reads no body, and a refusal the caller cannot
    quote in a report is worse than that.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                length = int(declared)
            except ValueError:
                length = -1
            if length > self._max_bytes:
                logger.warning(
                    "Rejected oversized request body",
                    extra={"declared_bytes": length, "limit_bytes": self._max_bytes},
                )
                return build_error_response(
                    status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    code="request_too_large",
                    message=(
                        f"The request body is larger than the "
                        f"{self._max_bytes // 1024} KiB this API accepts."
                    ),
                )

        return await call_next(request)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a correlation id to the request and log its outcome.

    The id is adopted from an inbound ``X-Request-ID`` header when it is
    well-formed — which lets a future gateway or the frontend correlate a user
    report with server logs — and generated otherwise. It is always echoed back on
    the response, error responses included.

    Unhandled exceptions are converted here rather than being allowed to reach
    Starlette's ``ServerErrorMiddleware``. That middleware sits *outside* this one,
    so by the time it ran, the correlation context would already have been reset
    and the 500 body would carry a null ``request_id`` — precisely the field a user
    needs to quote when reporting the failure.
    """

    def __init__(self, app: ASGIApp, *, log_requests: bool = True) -> None:
        super().__init__(app)
        self._log_requests = log_requests

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        token = set_request_id(request_id)
        started = time.perf_counter()

        try:
            try:
                response = await call_next(request)
            except Exception as exc:
                # Logs the traceback server-side and returns a sanitised body.
                response = await unhandled_exception_handler(request, exc)

            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            response.headers[REQUEST_ID_HEADER] = request_id

            if self._log_requests:
                logger.info(
                    "Request completed",
                    extra={
                        "http_method": request.method,
                        "http_path": request.url.path,
                        "http_status": response.status_code,
                        "duration_ms": duration_ms,
                    },
                )
            return response
        finally:
            reset_request_id(token)
