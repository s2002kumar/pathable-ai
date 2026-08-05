"""Process entry point: ``python -m pathable_api``.

This module exists because ``uvicorn.run()`` cannot be made to work with psycopg
on Windows.

Since uvicorn 0.36, the event loop is created from an explicit *loop factory*
rather than from the asyncio policy, and on Windows that factory returns
``asyncio.ProactorEventLoop`` — which psycopg 3 refuses to run on. Setting the
event-loop policy has no effect, because uvicorn never consults it.

The fix is to construct the server ourselves and hand ``asyncio.run`` an explicit
selector loop factory. Running the API through this module is therefore the
supported way to start it. A bare ``uvicorn pathable_api.main:app`` still works on
Linux and macOS, which is what the container image uses.
"""

from __future__ import annotations

import asyncio

import uvicorn

from pathable_api.core.config import get_settings
from pathable_api.core.event_loop import configure_event_loop_policy, selector_loop_factory


def build_server() -> uvicorn.Server:
    """Construct the uvicorn server from validated application settings."""
    settings = get_settings()

    config = uvicorn.Config(
        "pathable_api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
        access_log=True,
    )
    return uvicorn.Server(config)


def main() -> None:
    """Start the API server on an event loop psycopg can actually use."""
    # Helps anything in-process that does consult the policy; harmless elsewhere.
    configure_event_loop_policy()

    server = build_server()
    loop_factory = selector_loop_factory()

    if loop_factory is None:
        # Off Windows, let uvicorn choose (it will prefer uvloop when installed).
        server.run()
        return

    asyncio.run(server.serve(), loop_factory=loop_factory)


if __name__ == "__main__":
    main()
