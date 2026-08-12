"""FastAPI application factory.

Phase 0 exposes health and readiness only. There is no routing engine, no
pedestrian graph and no machine learning in this service — see docs/product/PHASES.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pathable_api import __version__
from pathable_api.api.v1.router import api_router
from pathable_api.core.config import Settings, get_settings
from pathable_api.core.errors import register_exception_handlers
from pathable_api.core.event_loop import configure_event_loop_policy
from pathable_api.core.logging import configure_logging, get_logger
from pathable_api.core.middleware import RequestContextMiddleware, RequestSizeLimitMiddleware
from pathable_api.core.request_context import REQUEST_ID_HEADER
from pathable_api.db.session import Database, build_database
from pathable_api.geo.geocoding import build_geocoder
from pathable_api.routing.graph import GraphRepository

logger = get_logger(__name__)

# Deliberately at import time, not inside create_app(): uvicorn imports this
# module before it creates the event loop, and the policy only affects loops
# created afterwards. No-op off Windows. See core/event_loop.py.
configure_event_loop_policy()

API_DESCRIPTION = """
Backend for **PathAble AI**, an accessibility-aware pedestrian routing project.

Routing compares the shortest walking route against a route that respects a chosen
mobility profile, and explains the difference using attributes recorded in
OpenStreetMap.

**What this is not.** Every routing decision is a deterministic rule over recorded
map attributes. There is no machine learning, no model prediction and no inferred
accessibility score anywhere in this service — `ml_predictions_used` is present on
every route response and is always `false`. Missing accessibility data is reported
as `unknown`, never as evidence that a path is clear, and no route is a guarantee
that a journey is passable.

Map data © OpenStreetMap contributors, ODbL 1.0.
""".strip()

OPENAPI_TAGS = [
    {
        "name": "health",
        "description": "Liveness and readiness probes used by Docker, CI and the web client.",
    },
    {
        "name": "routing",
        "description": (
            "Accessibility-aware pedestrian routing over a versioned OpenStreetMap "
            "network. Requests are not persisted."
        ),
    },
    {
        "name": "geocoding",
        "description": (
            "Optional place-name search, restricted to a pilot region. Disabled unless a "
            "provider is configured."
        ),
    },
]


def _build_lifespan(
    settings: Settings,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Create the lifespan handler bound to a specific settings instance."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "Starting PathAble API",
            extra={
                "environment": settings.environment,
                "version": settings.app_version,
                "database_target": settings.safe_database_target(),
                "allowed_origins": list(settings.allowed_origins),
            },
        )

        # One repository per application, so the loaded graph is shared across
        # requests instead of being rebuilt per call.
        app.state.graph_repository = GraphRepository()

        # Built once so the geocoder's rate limiter is process-wide. One per
        # request would let N concurrent requests each think they had a slot.
        app.state.geocoder = build_geocoder(
            settings.geocoding_provider,
            contact=settings.geocoding_contact,
            user_agent=f"{settings.service_name}/{settings.app_version}",
        )
        logger.info(
            "Geocoding configured",
            extra={"provider": app.state.geocoder.name, "enabled": app.state.geocoder.enabled},
        )

        if settings.database_url:
            app.state.database = build_database(settings)
        else:
            app.state.database = None
            logger.warning(
                "DATABASE_URL is not configured; readiness will report not_ready. "
                "Liveness is unaffected."
            )

        try:
            yield
        finally:
            database: Database | None = getattr(app.state, "database", None)
            if database is not None:
                await database.dispose()
                logger.info("Database engine disposed")
            logger.info("PathAble API stopped")

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    Accepting an explicit ``settings`` keeps tests from having to mutate process
    environment variables to exercise a different configuration.
    """
    resolved = settings or get_settings()

    configure_logging(
        level=resolved.log_level,
        log_format=resolved.log_format,
        service=resolved.service_name,
        version=resolved.app_version,
        environment=resolved.environment,
    )

    app = FastAPI(
        title="PathAble AI API",
        # The contract version is the package version, not the deployed build
        # string, so the generated OpenAPI document stays byte-stable.
        version=__version__,
        description=API_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        docs_url="/docs" if resolved.docs_enabled else None,
        redoc_url="/redoc" if resolved.docs_enabled else None,
        openapi_url="/openapi.json",
        lifespan=_build_lifespan(resolved),
    )

    app.state.settings = resolved

    if resolved.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved.allowed_origins),
            allow_credentials=resolved.cors_allow_credentials,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", REQUEST_ID_HEADER],
            expose_headers=[REQUEST_ID_HEADER],
            max_age=600,
        )

    # Starlette applies middleware in reverse registration order, so this pair
    # runs context-first, size-limit-second. Correlation costs a UUID and no body
    # read, and it means a 413 carries a request id the caller can quote — which
    # a refusal with no way to report it does not.
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router)

    return app


app = create_app()
