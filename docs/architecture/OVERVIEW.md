# Architecture overview

Phase 0. This describes what exists, plus the shape later phases are expected to
grow into. Where something is planned rather than built, it says so.

---

## Shape

A pnpm + uv monorepo containing a modular monolith backend, a Next.js frontend,
and a generated contract package binding them.

```
pathable-ai/
├── apps/web              Next.js 16 · React 19 · MapLibre GL 6
├── services/api          FastAPI · Pydantic v2 · SQLAlchemy 2 · psycopg 3
├── packages/contracts    openapi.json + generated TypeScript
├── infra/docker          container entrypoints
└── compose.yaml          web + api + db
```

Three runtime services, no more:

```
┌──────────┐   HTTP    ┌──────────┐   SQL    ┌────────────────┐
│   web    │──────────▶│   api    │─────────▶│ PostgreSQL 17  │
│  :3000   │           │  :8000   │          │ + PostGIS 3.5  │
└──────────┘           └──────────┘          └────────────────┘
```

There is no queue, no cache, no worker and no separate inference service. Adding
one before there is load to justify it would buy operational complexity with no
return — see [ADR 0002](../adr/0002-modular-monolith.md).

---

## Frontend

Next.js App Router. The page is a Server Component that validates browser-visible
configuration and renders either the application shell or a configuration-error
page naming every offending variable.

```
src/
├── app/                 route, layout, /api/healthz, page styles
├── components/          AppHeader, PilotPanel, ConfigurationError
├── features/
│   ├── map/             MapLibre lifecycle, WebGL detection, status overlay
│   └── system-status/   readiness probe, status badge
├── lib/                 public config validation, coordinates, cx
└── styles/              design tokens, global CSS
```

**Map.** MapLibre is loaded through `next/dynamic({ ssr: false })` and then
imported dynamically again inside the effect — it needs `window` and a WebGL 2
context, and keeping it out of the initial bundle costs nothing. The lifecycle is
a four-state machine (`initialising`, `ready`, `error`, `unsupported`) published
on a `data-map-state` attribute, which is what browser tests wait on instead of
racing a canvas.

WebGL support is resolved once during render rather than in an effect, so an
unsupported browser shows its explanation immediately instead of a spinner that
will never resolve.

**Status.** The badge probes `/health/ready`, not `/health/live`. Liveness would
show a reassuring green badge while the database is down; readiness distinguishes
_online_, _degraded_ and _unreachable_, which are three different problems for
whoever is debugging.

**Styling.** CSS Modules plus semantic design tokens. Components reference
`--color-text`, never a hex value, which is what makes the dark theme a token
swap. Contrast is verified by the axe scan in CI — it has already caught one real
failure.

---

## Backend

```
src/pathable_api/
├── api/v1/       versioned routes (health today)
├── core/         config, logging, request context, errors, middleware
├── db/           async engine, session lifecycle, dependency probes
├── schemas/      Pydantic models — the contract source of truth
└── main.py       application factory
```

**Configuration** is validated at startup by `pydantic-settings`. Production is
held to stricter rules: `DATABASE_URL` required, at least one explicit CORS
origin, no wildcard, JSON logs. Every problem is reported at once, because
fixing one variable per restart is a bad afternoon.

**Correlation.** Every request gets an id, adopted from a well-formed inbound
`X-Request-ID` or generated. It is bound to a `ContextVar`, so every log line
carries it without being threaded through call signatures, and it is echoed on
the response — including on errors.

Unhandled exceptions are converted inside `RequestContextMiddleware` rather than
being allowed to reach Starlette's `ServerErrorMiddleware`. That middleware sits
_outside_ ours, so by the time it ran the correlation context would already have
been unwound and the 500 body would carry a null `request_id` — precisely the
field a user needs to quote.

**Errors.** One envelope for every non-2xx response: `code`, `message`,
`request_id`, optional `details`. Tracebacks, driver messages and connection
strings are logged and never returned. Validation errors forward only `loc` and
`msg`; Pydantic's `input` and `ctx` would reflect caller-controlled data straight
back out.

**Health.** Liveness touches no dependency, so a database blip never causes an
orchestrator to restart a healthy process. Readiness probes PostgreSQL and
PostGIS under a bounded timeout and returns 200 or 503 with an identical body
shape, so clients parse once.

---

## Data layer

PostgreSQL 17 with PostGIS 3.5, pinned exactly. Async SQLAlchemy over psycopg 3
for the application; a synchronous engine for Alembic — psycopg 3 serves both
from one `postgresql+psycopg://` URL, so there is only ever one connection string
in the system.

The baseline migration creates the PostGIS extension and nothing else. Inventing
graph tables before the routing requirements exist would bake in the wrong shape.

---

## Contracts

```
Pydantic models → app.openapi() → openapi.json → openapi-typescript → api.ts
```

Export is deterministic: fixed settings independent of the environment, sorted
keys, stable indentation. `pnpm contracts:check` regenerates into a temp
directory and compares bytes, so it works on a clean checkout without depending
on git state. CI fails on drift.

The frontend imports `ReadinessResponse` from `@pathable/contracts`. Renaming a
backend field breaks the frontend build — which is the point. A hand-copied type
would keep compiling and fail at runtime.

---

## Local environment

Compose runs `db`, `api` and `web`. The database uses a **named** volume, so
`docker compose down` keeps data and only `down -v` destroys it. The API's
entrypoint waits for the database with a bounded retry budget, applies
migrations, then `exec`s the server so it becomes PID 1 and receives `SIGTERM`
directly.

The database publishes on host port **5433**, not 5432: a locally installed
PostgreSQL commonly owns 5432 already, and the resulting bind failure is opaque.

Both images run as uid 10001 and contain no `.env` and no credentials.

---

## What deliberately does not exist yet

| Not present            | Why                                                          |
| ---------------------- | ------------------------------------------------------------ |
| Routing engine         | Phase 1. Needs the graph from Phase 0.5 first.               |
| Pedestrian graph       | Phase 0.5.                                                   |
| Redis / Celery / Kafka | No workload justifies them. Add when measurement demands it. |
| Separate ML service    | No model exists. See ADR 0002.                               |
| Auth                   | No accounts, no personal data, nothing to protect yet.       |
| Kubernetes             | Nothing is deployed.                                         |

Empty directories for future components are not created. They advertise
capability that does not exist and rot.
