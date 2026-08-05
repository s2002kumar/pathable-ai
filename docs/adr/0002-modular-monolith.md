# ADR 0002 — Modular monolith backend

**Status:** Accepted · 2026-08-05 · Phase 0 (P0-A01)

## Context

PathAble will eventually do several distinguishable things: serve an HTTP API,
ingest and maintain a pedestrian graph, compute routes, and (much later) run
model inference over imagery. Those are often built as separate services.

The temptation is to anticipate that split now — an API service, an ingestion
worker, a routing service, an inference service, a queue between them — on the
grounds that retrofitting boundaries later is painful.

Against that: there are no users, no measured load, no latency budget derived
from anything real, and one part-time developer. Every additional service is a
deployment, a health check, a network hop, a failure mode, a set of logs to
correlate and a local development dependency. Distributed systems make some
problems easier and _many_ problems much harder, and none of the problems they
solve exist here yet.

## Decision

One FastAPI application, internally modular:

```
src/pathable_api/
├── api/v1/    HTTP layer — routing and serialisation only
├── core/      config, logging, request context, errors
├── db/        engine, sessions, dependency probes
└── schemas/   Pydantic models (the contract)
```

Future capabilities become **packages inside this application** —
`pathable_api/graph/`, `pathable_api/routing/` — not new services. Long-running
ingestion runs as a CLI command against the same codebase, not a queue worker.

Explicitly excluded until measurement demands them: Redis, Celery, Kafka,
Airflow, Prefect, a feature store, a graph database, a separate inference
service, Kubernetes.

The discipline that makes this safe is that module boundaries are respected as if
they were network boundaries: `api/` does not reach into `db/` internals, and
domain packages do not import HTTP types. A boundary that is already clean can be
extracted in an afternoon. A boundary that was never enforced cannot be extracted
at all, regardless of how many repositories it is spread across.

## Consequences

**Positive**

- Local development is `docker compose up`. Three containers, one of which is
  Postgres.
- One process to profile, one log stream to read, one place a request can fail.
- Transactions are transactions, not sagas.
- Refactoring a boundary is a rename, not a migration.

**Negative**

- No independent scaling. Irrelevant with no traffic; when routing becomes
  CPU-bound, that measurement is the trigger to extract it.
- A slow request can occupy a worker. Bounded timeouts (readiness already has
  one) are the mitigation until it is measured.
- Requires ongoing discipline about internal boundaries, which a network boundary
  would enforce for free.

**Reversibility.** High, if the boundaries stay clean. The extraction trigger is
a measurement — a routing computation that exceeds its latency budget, or an
ingestion job that starves the API — not a preference.

## Alternatives considered

**Microservices from the start.** Would multiply the operational surface roughly
fivefold in exchange for scaling properties nothing currently needs. The usual
justification, "we will need it later", assumes the eventual boundaries are
already known. They are not: whether routing and graph maintenance are one
service or two depends on how the routing algorithm ends up using the graph, and
that is unknown until Phase 1.

**Serverless functions.** Poor fit. Routing is stateful in the sense that it
wants a warm graph in memory; cold starts and per-invocation limits are hostile
to that, and local development gets meaningfully worse.

**A separate inference service now.** There is no model. An empty service
directory would advertise a capability that does not exist — which this project
has specific reasons to avoid.
