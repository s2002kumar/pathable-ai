"""Windows asyncio event-loop compatibility.

psycopg 3 cannot run in async mode on Windows' ``ProactorEventLoop``. Every
connection attempt fails with::

    psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in
    async mode.

That breaks the native-Windows development path documented in
docs/development/LOCAL_SETUP.md, and it is invisible until something actually
reaches the database: liveness still returns 200, and readiness reports the
database as merely "unreachable", which looks like an ordinary connection problem
rather than a platform incompatibility. Linux and macOS are unaffected, so
containers and CI never see it.

Two mechanisms are needed, because two different things create event loops:

* :func:`configure_event_loop_policy` covers anything that honours the asyncio
  policy — pytest-asyncio, and plain ``asyncio.run``.
* :func:`selector_loop_factory` covers uvicorn, which since 0.36 **ignores the
  policy** and returns ``asyncio.ProactorEventLoop`` directly from
  ``uvicorn.loops.asyncio:asyncio_loop_factory``. Only an explicit loop factory
  overrides that.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable


def configure_event_loop_policy() -> bool:
    """Install the selector event loop policy on Windows.

    Returns whether the policy was changed, which keeps this testable without
    asserting on global interpreter state. Only affects loops created afterwards,
    and only helps callers that consult the policy — notably **not** uvicorn.
    """
    if sys.platform != "win32":
        return False

    selector_policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if selector_policy is None:  # pragma: no cover - non-Windows interpreters
        return False

    if isinstance(asyncio.get_event_loop_policy(), selector_policy):
        return False

    asyncio.set_event_loop_policy(selector_policy())
    return True


def selector_loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    """Return an explicit selector loop factory on Windows, otherwise ``None``.

    ``None`` means "use the default", which is correct everywhere except Windows.
    Pass the result to ``asyncio.run(..., loop_factory=...)`` — this is precisely
    the remedy psycopg's own error message recommends.
    """
    if sys.platform != "win32":
        return None
    return asyncio.SelectorEventLoop
