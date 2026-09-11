"""Loading the routing graph at startup, so readiness can tell the truth about it.

By default a region's graph is loaded on the first route request and cached for
the life of the process (see :class:`~pathable_api.routing.graph.GraphRepository`).
That is fine for development and wrong for a deployment: a freshly started
instance answers ``/health/ready`` with 200 the moment PostgreSQL is reachable,
then spends the next twenty seconds and a gigabyte building a graph before it
can serve a single route. Anything routing traffic on readiness sends users into
that window.

Configuring ``GRAPH_PRELOAD_REGIONS`` makes the load part of startup and makes
readiness wait for it. The load runs as a background task rather than inside the
lifespan handler so liveness answers immediately — an orchestrator that sees no
HTTP response for twenty seconds concludes the process is hung, and would be
right to restart it if it were.

Failure is reported, not hidden. A region with no active dataset, or a load that
raises, leaves the instance permanently not ready with a short safe reason,
because an instance that cannot route is not one that should receive traffic.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import Literal

from pathable_api.core.logging import get_logger
from pathable_api.db.session import Database
from pathable_api.routing.graph import GraphRepository, NoActiveDatasetError
from pathable_api.schemas.health import DependencyCheck

logger = get_logger(__name__)

WarmupState = Literal["pending", "loading", "ready", "failed"]

_LAZY_DETAIL = "graphs load on first request; no regions configured for preload"
_NO_DATABASE_DETAIL = "cannot preload: DATABASE_URL is not configured"


@dataclass(slots=True)
class RegionWarmup:
    """Where one region's preload has got to."""

    slug: str
    state: WarmupState = "pending"
    #: Seconds the load took, once it has finished.
    seconds: float | None = None
    #: Safe to show to an unauthenticated caller: never an exception message.
    detail: str = "pending"


@dataclass(slots=True)
class GraphWarmup:
    """Tracks the startup preload of every configured region."""

    regions: dict[str, RegionWarmup] = field(default_factory=dict)
    _task: asyncio.Task[None] | None = None

    @classmethod
    def for_regions(cls, slugs: tuple[str, ...]) -> GraphWarmup:
        return cls(regions={slug: RegionWarmup(slug=slug) for slug in slugs})

    @property
    def configured(self) -> bool:
        return bool(self.regions)

    @property
    def complete(self) -> bool:
        """Every configured region has either loaded or failed."""
        return all(region.state in {"ready", "failed"} for region in self.regions.values())

    def start(self, database: Database, repository: GraphRepository) -> None:
        """Begin loading in the background. Safe to call once per lifespan."""
        if not self.configured or self._task is not None:
            return
        self._task = asyncio.create_task(self._run(database, repository), name="graph-warmup")

    def fail_without_database(self) -> None:
        """Preload was asked for, but there is no database to load from."""
        for region in self.regions.values():
            region.state = "failed"
            region.detail = _NO_DATABASE_DETAIL

    async def stop(self) -> None:
        """Cancel an in-flight load at shutdown."""
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    async def _run(self, database: Database, repository: GraphRepository) -> None:
        # Sequentially: two regions loading at once would double the transient
        # memory peak, and the point of measuring that peak is to size a host.
        for region in self.regions.values():
            await self._load(region, database, repository)

    async def _load(
        self, region: RegionWarmup, database: Database, repository: GraphRepository
    ) -> None:
        region.state = "loading"
        region.detail = f"loading {region.slug}"
        started = time.perf_counter()
        try:
            async with database.session() as session:
                graph = await repository.active_graph(session, region.slug)
        except NoActiveDatasetError:
            region.state = "failed"
            region.detail = f"{region.slug}: no active dataset"
            logger.error("Graph preload failed: no active dataset", extra={"region": region.slug})
            return
        except asyncio.CancelledError:
            region.state = "failed"
            region.detail = f"{region.slug}: preload cancelled"
            raise
        except Exception as exc:
            # The type is enough for a caller; the traceback goes to the log.
            region.state = "failed"
            region.detail = f"{region.slug}: preload failed ({type(exc).__name__})"
            logger.exception("Graph preload failed", extra={"region": region.slug})
            return

        region.seconds = round(time.perf_counter() - started, 3)
        region.state = "ready"
        region.detail = (
            f"{region.slug}: {graph.node_count} nodes, {graph.segment_count} segments "
            f"loaded in {region.seconds:.1f} s"
        )
        logger.info(
            "Graph preloaded",
            extra={
                "region": region.slug,
                "dataset_id": str(graph.dataset_id),
                "node_count": graph.node_count,
                "segment_count": graph.segment_count,
                "preload_seconds": region.seconds,
            },
        )

    def check(self) -> DependencyCheck:
        """The routing-graph line of the readiness response."""
        if not self.configured:
            return DependencyCheck(status="ok", detail=_LAZY_DETAIL)

        failed = [region for region in self.regions.values() if region.state == "failed"]
        if failed:
            return DependencyCheck(
                status="unavailable", detail="; ".join(region.detail for region in failed)
            )

        unfinished = [region for region in self.regions.values() if region.state != "ready"]
        if unfinished:
            return DependencyCheck(
                status="unavailable", detail="; ".join(region.detail for region in unfinished)
            )

        total_ms = sum(region.seconds or 0.0 for region in self.regions.values()) * 1000.0
        return DependencyCheck(
            status="ok",
            detail="; ".join(region.detail for region in self.regions.values()),
            latency_ms=round(total_ms, 3),
        )
