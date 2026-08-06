"""Windows event-loop policy configuration.

Regression cover for a bug that only appears on Windows against a real database:
psycopg 3 cannot run in async mode on ``ProactorEventLoop``, so every connection
failed with an ``InterfaceError`` while liveness kept returning 200 and readiness
merely reported "database unreachable". CI runs on Linux, so nothing caught it
until the integration suite was first executed on Windows.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from pathable_api.core.event_loop import configure_event_loop_policy


class TestConfigureEventLoopPolicy:
    def test_is_idempotent(self) -> None:
        # Called at import time of pathable_api.main, and potentially again by a
        # test or an embedding application.
        configure_event_loop_policy()

        assert configure_event_loop_policy() is False

    def test_never_raises(self) -> None:
        for _ in range(3):
            configure_event_loop_policy()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only behaviour")
    def test_selector_policy_is_active_on_windows(self) -> None:
        # The `if` is for mypy, not for pytest: skipif is a runtime marker that
        # type checking does not see, so on Linux mypy would reject
        # `asyncio.WindowsSelectorEventLoopPolicy` as a missing attribute. A
        # `sys.platform` comparison is something mypy narrows on.
        if sys.platform == "win32":
            configure_event_loop_policy()

            # The concrete guarantee psycopg needs: not a Proactor loop.
            assert isinstance(
                asyncio.get_event_loop_policy(),
                asyncio.WindowsSelectorEventLoopPolicy,
            )

    @pytest.mark.skipif(sys.platform == "win32", reason="non-Windows behaviour")
    def test_is_a_no_op_off_windows(self) -> None:
        # Containers and CI run Linux; the policy must not be touched there.
        assert configure_event_loop_policy() is False

    def test_importing_the_app_configures_the_policy(self) -> None:
        # The import side effect is the actual delivery mechanism, because uvicorn
        # imports the app module before creating its loop.
        import pathable_api.main  # noqa: F401

        assert configure_event_loop_policy() is False
