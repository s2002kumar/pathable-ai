"""Request correlation identifiers.

A single request id is generated (or adopted from the caller) at the edge, stored
in a :class:`~contextvars.ContextVar` so every log line emitted while handling the
request carries it, echoed back on the response, and included in error bodies so a
user-visible failure can be traced to exact server logs.
"""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar, Token
from typing import Final

#: Header used to accept and return the correlation id.
REQUEST_ID_HEADER: Final = "X-Request-ID"

#: Inbound ids are echoed into logs and response headers, so they are constrained
#: to an unambiguous, injection-safe charset and a bounded length. Anything else is
#: replaced with a fresh id rather than rejected — a malformed correlation header
#: should never fail an otherwise valid request.
_VALID_REQUEST_ID: Final = re.compile(r"\A[A-Za-z0-9._-]{8,128}\Z")

_request_id: ContextVar[str | None] = ContextVar("pathable_request_id", default=None)


def new_request_id() -> str:
    """Generate a fresh correlation id."""
    return uuid.uuid4().hex


def is_valid_request_id(value: str) -> bool:
    """Return whether an inbound header value is safe to adopt verbatim."""
    return bool(_VALID_REQUEST_ID.fullmatch(value))


def resolve_request_id(inbound: str | None) -> str:
    """Adopt a well-formed inbound id, otherwise mint a new one."""
    if inbound is not None:
        candidate = inbound.strip()
        if is_valid_request_id(candidate):
            return candidate
    return new_request_id()


def set_request_id(value: str) -> Token[str | None]:
    """Bind ``value`` to the current context, returning a token for reset."""
    return _request_id.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous correlation id."""
    _request_id.reset(token)


def get_request_id() -> str | None:
    """Return the correlation id for the current context, if any."""
    return _request_id.get()
