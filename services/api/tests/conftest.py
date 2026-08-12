"""Shared test fixtures.

Settings are always constructed with ``_env_file=None`` so a developer's local
``.env`` can never change a test outcome.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pathable_api.core.config import Environment, LogFormat, LogLevel, Settings
from pathable_api.main import create_app

#: Every environment variable Settings reads. Cleared by the ``clean_env`` fixture
#: so a developer's shell can never influence a configuration test.
SETTINGS_ENV_VARS = (
    "ENVIRONMENT",
    "SERVICE_NAME",
    "APP_VERSION",
    "API_HOST",
    "API_PORT",
    "DATABASE_URL",
    "ALLOWED_ORIGINS",
    "READINESS_TIMEOUT_SECONDS",
    "DB_POOL_SIZE",
    "DB_POOL_MAX_OVERFLOW",
    "LOG_LEVEL",
    "LOG_FORMAT",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every PathAble setting from the process environment."""
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


def settings_from(values: dict[str, Any]) -> Settings:
    """Build settings from a raw mapping, ignoring every ambient source.

    ``_env_file=None`` disables .env discovery, and the ``isolate_environment``
    autouse fixture in tests/unit clears the environment variables. Both are
    needed: ``Settings.model_validate`` does *not* bypass pydantic-settings'
    sources, so a developer with a populated .env would otherwise see different
    results from CI.

    Raw values (strings) are passed deliberately, so the real field validators —
    including comma-separated CORS parsing and driver normalisation — are the
    thing under test.
    """
    return Settings(_env_file=None, **values)


def build_settings(
    *,
    environment: Environment = "test",
    service_name: str = "pathable-api",
    app_version: str = "0.1.0",
    api_host: str = "127.0.0.1",
    api_port: int = 8000,
    database_url: str | None = None,
    allowed_origins: tuple[str, ...] = ("http://localhost:3000",),
    readiness_timeout_seconds: float = 2.0,
    log_level: LogLevel = "WARNING",
    log_format: LogFormat = "console",
) -> Settings:
    """Construct settings for a test, ignoring the ambient environment."""
    return Settings(
        _env_file=None,
        environment=environment,
        service_name=service_name,
        app_version=app_version,
        api_host=api_host,
        api_port=api_port,
        database_url=database_url,
        allowed_origins=allowed_origins,
        readiness_timeout_seconds=readiness_timeout_seconds,
        log_level=log_level,
        log_format=log_format,
    )


@pytest.fixture
def settings() -> Settings:
    """Default test settings: no database configured."""
    return build_settings()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """An application instance with no database."""
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """A client that runs the application lifespan.

    ``raise_server_exceptions=False`` so tests can assert on the *response* an
    unhandled error produces, which is the behaviour real clients see.
    """
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
