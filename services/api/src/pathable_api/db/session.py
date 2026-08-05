"""Async engine and session lifecycle.

PathAble uses the async SQLAlchemy 2 engine over psycopg 3. Two reasons drove that
choice (see docs/adr/0004): readiness probes need a timeout that genuinely
*cancels* the in-flight query, which ``asyncio.wait_for`` gives and a thread-pooled
sync call does not; and Phase 1 routing will fan out concurrent reads.

Psycopg 3 serves both drivers from a single ``postgresql+psycopg://`` URL, so
Alembic keeps using a plain synchronous engine built from the very same
``DATABASE_URL`` — no second connection string to keep in sync.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from pathable_api.core.config import Settings
from pathable_api.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class Database:
    """Owns the engine and hands out sessions."""

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session, rolling back if the caller raises."""
        async with self.session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        """Close every pooled connection. Called on application shutdown."""
        await self.engine.dispose()


def build_database(settings: Settings) -> Database:
    """Create the engine for the configured database.

    Raises :class:`~pathable_api.core.config.ConfigurationError` when
    ``DATABASE_URL`` is absent, so the failure names the missing variable rather
    than surfacing as a driver error.
    """
    url = settings.require_database_url()

    engine = create_async_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_max_overflow,
        # Recycle before typical cloud idle-timeouts sever a pooled connection.
        pool_recycle=1800,
        pool_pre_ping=True,
        echo=False,
    )
    logger.info(
        "Database engine created",
        extra={"database_target": settings.safe_database_target()},
    )
    return Database(
        engine=engine,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
    )
