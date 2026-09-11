"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from pathable_api.core.config import Settings, get_settings
from pathable_api.db.session import Database
from pathable_api.routing.warmup import GraphWarmup


def settings_dependency(request: Request) -> Settings:
    """Resolve application settings.

    Reads the instance the application was actually built with rather than the
    process-wide singleton, so an app created via ``create_app(custom_settings)``
    reports its own identity — and so two apps in one process (as in the test
    suite) cannot shadow each other's configuration.
    """
    configured: Settings | None = getattr(request.app.state, "settings", None)
    return configured if configured is not None else get_settings()


def database_dependency(request: Request) -> Database | None:
    """Return the engine holder, or ``None`` when no database is configured.

    ``None`` is a legitimate state rather than an error: liveness must answer
    without a database, and readiness must be able to report *why* it cannot.
    """
    database: Database | None = getattr(request.app.state, "database", None)
    return database


def warmup_dependency(request: Request) -> GraphWarmup:
    """The startup graph preload, or an unconfigured one outside a lifespan."""
    warmup: GraphWarmup | None = getattr(request.app.state, "graph_warmup", None)
    return warmup if warmup is not None else GraphWarmup()


SettingsDep = Annotated[Settings, Depends(settings_dependency)]
DatabaseDep = Annotated[Database | None, Depends(database_dependency)]
WarmupDep = Annotated[GraphWarmup, Depends(warmup_dependency)]
