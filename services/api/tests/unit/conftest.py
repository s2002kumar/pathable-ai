"""Unit-test isolation.

Unit tests must produce the same result on a developer's machine — where a
populated ``.env`` and exported variables are normal — as they do in CI. Settings
construction is therefore cut off from both ambient sources: this fixture clears
the environment variables, and every helper passes ``_env_file=None``.

Scoped to tests/unit deliberately. The integration suite *needs* ``DATABASE_URL``
from the environment to find its server.
"""

from __future__ import annotations

import pytest

from tests.conftest import SETTINGS_ENV_VARS


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every PathAble setting from the environment for each unit test."""
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
