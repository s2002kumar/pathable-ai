"""HTTP middleware: request correlation and access logging."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from pathable_api.core.errors import unhandled_exception_handler
from pathable_api.core.logging import get_logger
from pathable_api.core.request_context import (
    REQUEST_ID_HEADER,
    reset_request_id,
    resolve_request_id,
    set_request_id,
)

logger = get_logger(__name__)


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
