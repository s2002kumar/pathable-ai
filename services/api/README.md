# pathable-api

FastAPI backend for PathAble AI.

**Phase 0 scope.** Configuration validation, structured logging, request
correlation, liveness/readiness endpoints and the PostGIS migration baseline.
There is no routing engine, no pedestrian graph and no machine learning in this
service. See [`docs/product/PHASES.md`](../../docs/product/PHASES.md).

## Endpoints

| Method | Path                   | Notes                                      |
| ------ | ---------------------- | ------------------------------------------ |
| GET    | `/api/v1/health/live`  | No dependencies touched.                   |
| GET    | `/api/v1/health/ready` | Probes PostgreSQL + PostGIS. 200 / 503.    |
| GET    | `/openapi.json`        | Contract source of truth.                  |
| GET    | `/docs`                | Development only (disabled in production). |

## Commands

Run from this directory:

```bash
uv sync                                  # install dependencies
uv run uvicorn pathable_api.main:app --reload
uv run ruff format . && uv run ruff check .
uv run mypy src tests
uv run pytest tests/unit                 # no database required
uv run pytest tests/integration          # requires DATABASE_URL -> PostGIS
uv run alembic upgrade head
```

Or from the repository root: `pnpm lint`, `pnpm typecheck`, `pnpm test:unit`,
`pnpm test:integration`.

## Layout

```
src/pathable_api/
├── api/v1/     HTTP routes (versioned from day one)
├── core/       config, logging, request context, error handling, middleware
├── db/         async engine, session lifecycle, dependency probes
├── schemas/    Pydantic models — the contract source of truth
└── main.py     application factory
migrations/     Alembic; 0001 establishes PostGIS
```
