# ADR 0004 — PostGIS as the spatial store; graph held in the database, routed in the application

**Status:** Accepted · 2026-08-05 · Phase 0 (P0-A01)

## Context

PathAble is a geospatial routing product. Two decisions follow from that, and
they are entangled enough to record together:

1. Where does spatial data live?
2. Where does graph traversal happen?

The pedestrian graph for a city is not large — Waterloo's walkable network is on
the order of tens of thousands of edges — but it is spatial (nearest-node
snapping, bounding-box queries, geodesic distance) and it is relational (edges
reference nodes, attributes reference sources, reports reference edges).

## Decision

### PostgreSQL 17 + PostGIS 3.5 as the single store

PostGIS provides geometry and geography types, spatial indexing (GiST), geodesic
distance, and a mature ecosystem for OSM ingestion — while remaining an ordinary
relational database for everything that is not spatial. One store, one backup,
one transaction boundary.

Pinned exactly (`postgis/postgis:17-3.5`), never `latest`: an unannounced major
PostgreSQL bump changes the on-disk format and would break a developer's volume
with no warning.

### Async SQLAlchemy 2 over psycopg 3, sync engine for Alembic

Async because the readiness probe needs a timeout that genuinely _cancels_ the
in-flight query — `asyncio.wait_for` does; a thread-pooled sync call leaves the
thread blocked — and because Phase 1 routing will fan out concurrent reads.

Psycopg 3 serves both drivers from a single `postgresql+psycopg://` URL, so
Alembic uses a plain synchronous engine built from the identical `DATABASE_URL`.
That avoids Alembic's async boilerplate _and_ avoids a second connection string
to keep in sync — a common source of "migrations ran against the wrong database".

### Graph traversal in the application, not in SQL

Phase 1 will load the pedestrian graph from PostGIS and run pathfinding in
Python, rather than using `pgRouting`.

Routing cost in this product is not distance. It is a function of mobility
profile, hard constraints, deterministic facts, validated reports, data freshness
and (eventually) model confidence. Expressing that in SQL means encoding product
logic in a cost expression that is hard to test, hard to debug, and hard to
explain per segment — and per-segment explanation is a core requirement, not a
nice-to-have.

In application code, the cost function is ordinary testable code, the explanation
falls out of the traversal, and swapping profiles is a parameter rather than a
query rewrite.

### Baseline migration creates the extension and nothing else

`0001_postgis` enables PostGIS. It creates no application tables. Designing graph
tables before the routing requirements exist would bake in a shape we would then
have to migrate away from.

## Consequences

**Positive**

- One database for spatial and relational data; one transaction boundary.
- The routing cost function is testable Python, not a SQL expression.
- Per-segment explanations are a natural by-product of traversal.
- Alembic and the application share one validated connection string.
- Migrations from an empty database are proven in CI against real PostGIS.

**Negative**

- The graph must be loaded into memory. At Waterloo's scale this is tens of MB;
  at national scale it would not be, and that is the trigger to revisit.
- Application-side traversal is slower per-edge than a tuned C extension. The
  latency budget is unmeasured; if Phase 1 misses it, `pgRouting` for the
  distance-only baseline is a targeted fallback.
- Async SQLAlchemy has sharper edges than sync (session lifetime, greenlet
  errors). Contained by keeping the session surface small.

**Reversibility.** Store choice: low reversibility, deliberately — PostGIS is the
obvious answer and moving off it later would be expensive. Traversal location:
high — the graph is already in SQL, so a `pgRouting` baseline can be added
alongside without moving data.

## Alternatives considered

**A graph database (Neo4j, Memgraph).** Genuinely good at traversal, poor at
geospatial predicates, and a second store to operate and back up. The graph is
also not the hard part — the cost function is.

**pgRouting for everything.** Fast and mature for weighted shortest paths. Would
push the accessibility cost function into SQL, where it becomes difficult to test
and nearly impossible to explain per segment. Kept as a fallback for the
distance-only baseline route.

**SQLite + SpatiaLite.** Attractive for a single-developer project, but a poor
fit once there are concurrent readers and a deployment, and the migration later
would be worse than starting here.

**Separate spatial store plus a relational store.** Two stores, two backups, no
transactional consistency between an edge and the report attached to it.
