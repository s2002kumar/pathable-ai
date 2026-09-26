# Production smoke: the real images, an empty database, the real dataset

How to stand up PathAble's production containers on a laptop, prove they work
from nothing, and measure what they need. Everything here runs against an
isolated Compose project — its own name, volume and ports — so it can never
touch the development database.

The numbers this produced are in
[`docs/evidence/production-envelope.json`](../evidence/production-envelope.json)
and the decision they led to is
[ADR 0009](../adr/0009-deployment-architecture.md).

## What "production" means here

`infra/production-smoke/compose.yaml` starts the same two images the root
Compose file builds — API `services/api/Dockerfile`, web `apps/web/Dockerfile`,
both `runtime` targets — with the API under `ENVIRONMENT=production`. That
setting makes the API refuse to start without an explicit origin list, JSON
logs and a database URL, which is the contract a real deployment has to meet.
`GRAPH_PRELOAD_REGIONS=waterloo` loads the pilot region's graph at startup, so
`/health/ready` stays 503 until routes can actually be served.

| Knob                                           | Default                  | Use                                                      |
| ---------------------------------------------- | ------------------------ | -------------------------------------------------------- |
| `ENVELOPE_API_MEMORY_LIMIT`                    | `2g`                     | The container memory limit the measurement turns         |
| `ENVELOPE_API_COMMAND`                         | `python -m pathable_api` | Override to test worker counts                           |
| `ENVELOPE_PRELOAD_REGIONS`                     | `waterloo`               | Empty string measures the lazy, load-on-first-route path |
| `ENVELOPE_DB_PORT` / `_API_PORT` / `_WEB_PORT` | `5434` / `8001` / `3001` | Distinct from the development stack                      |

Project name `pathable-envelope`; volume `pathable-envelope-db-data`. The
development volume `pathable-db-data` is never referenced.

## 1. Empty database to migrated head

```bash
docker compose -f infra/production-smoke/compose.yaml build
docker compose -f infra/production-smoke/compose.yaml up -d db

# The API entrypoint waits for the database, runs `alembic upgrade head`, then
# execs whatever command it was given — here, a query of the current revision.
docker compose -f infra/production-smoke/compose.yaml run --rm --no-deps api alembic current
# -> 0005_kerb_tiers (head)

# Run it again: an already-migrated database is a no-op, not an error.
docker compose -f infra/production-smoke/compose.yaml run --rm --no-deps api alembic current
```

**Migration failure must fail the start, not hide it.** Point the database at a
revision that does not exist and start the API:

```bash
docker exec pathable-envelope-db-1 psql -U pathable -d pathable \
  -c "update alembic_version set version_num='9999_not_a_revision'"
docker compose -f infra/production-smoke/compose.yaml up -d --no-deps api
sleep 20
docker inspect --format '{{.State.Status}} exit={{.State.ExitCode}} restarts={{.RestartCount}}' pathable-envelope-api-1
# -> restarting exit=255 restarts=N ; /health/live never answers
docker exec pathable-envelope-db-1 psql -U pathable -d pathable \
  -c "update alembic_version set version_num='0005_kerb_tiers'"
docker compose -f infra/production-smoke/compose.yaml rm -sf api
```

The entrypoint runs under `set -e`; Alembic's non-zero exit ends the container
before the server ever binds, and `restart: unless-stopped` keeps retrying
without ever serving traffic.

## 2. The Waterloo dataset, reproducibly

There is no dump in the repository and there must never be one. The bounded
dataset is populated by one of two supported paths:

**Path A — ingest from the published extract (the canonical path).** Documented
in the README: `pathable regions seed`, `pathable ingest pbf`, `pathable
elevation apply --provider hrdem`. It downloads the Geofabrik Ontario extract
(~970 MB) and samples NRCan HRDEM over S3; it takes hours on a laptop and is
the path a real deployment should use once, then keep the result.

**Path B — logical export of the five map-fact tables from an existing
main-compatible database.** Used for this measurement because Path A had
already been run on this machine. It copies rows only — the schema always
comes from `main`'s migrations — and it explicitly excludes any table that is
not in `main`'s schema, so nothing from an unmerged branch can travel with it.

```bash
# Export (read-only against the source database; pg_dump 17.5):
docker exec <source-db-container> pg_dump -U pathable -d pathable \
  --data-only --no-owner --no-privileges --format=custom \
  --table=pilot_regions --table=dataset_versions --table=ingestion_runs \
  --table=graph_nodes --table=graph_edges > waterloo-main-data.dump
sha256sum waterloo-main-data.dump
```

Restore with the committed script, which needs no privilege a managed
PostgreSQL service withholds:

```bash
infra/production-smoke/restore-dataset.sh \
  --dump waterloo-main-data.dump \
  --container pathable-envelope-db-1 \
  --user pathable_app --db pathable_managed
```

### Why not `--disable-triggers`

The obvious restore is `pg_restore --data-only --disable-triggers`, and it is
the wrong habit to build. `--disable-triggers` switches off _system_ triggers —
the ones that enforce foreign keys — and PostgreSQL reserves that for
superusers. Managed services do not give you one. Run as an ordinary owner
role, it fails exactly like this:

```
pg_restore: error: could not execute query: ERROR:  permission denied:
    "RI_ConstraintTrigger_a_21027" is a system trigger
Command was: ALTER TABLE public.pilot_regions DISABLE TRIGGER ALL;
```

The flag exists because pg_dump cannot promise a working order for every
schema — circular foreign keys have none. This schema is a tree, so an order
exists, and the script states it rather than hoping for it:

    pilot_regions -> dataset_versions -> ingestion_runs -> graph_nodes -> graph_edges

That order is handed to `pg_restore --use-list` and applied with
`--single-transaction`, so a failure leaves an empty database rather than half
a network. (Measured aside: pg_dump's own ordering for this archive already
worked. Pinning it means that stays true instead of being a coincidence.)

The script refuses an archive carrying tables it does not know, refuses one
carrying schema objects, refuses a database that is not migrated, refuses a
database that already has rows, and verifies counts, foreign keys, the
`incline_direction` check and geometry validity before reporting success.

### Approximating a managed database locally

Managed PostgreSQL gives you a role that owns its databases and is not a
superuser — DigitalOcean's is `doadmin`. These three statements, run by the
platform's own admin, are what the platform does for you; everything after
them is done as the restricted role:

```bash
docker exec pathable-envelope-db-1 psql -U pathable -d postgres \
  -c "create role pathable_app login password '<local placeholder>' \
      nosuperuser nocreatedb nocreaterole nobypassrls noreplication noinherit" \
  -c "create database pathable_managed owner pathable_app"
# The platform installs PostGIS; CREATE EXTENSION is superuser-only in vanilla
# PostgreSQL, and migration 0001 uses CREATE EXTENSION IF NOT EXISTS so an
# ordinary owner can run the migrations afterwards.
docker exec pathable-envelope-db-1 psql -U pathable -d pathable_managed \
  -c "create extension if not exists postgis"

# Migrate as the restricted role, then restore as it.
docker run --rm --network pathable-envelope_default \
  -e DATABASE_URL="postgresql+psycopg://pathable_app:<password>@db:5432/pathable_managed" \
  --entrypoint sh pathable-envelope-api:local -c 'cd /app && alembic upgrade head'
```

Point the API at it with `ENVELOPE_DATABASE_URL` and the rest of this guide
works unchanged.

### What the recorded run produced

Dump 31,240,046 bytes, SHA-256
`20d3ad955636f56e5700c6627ccfa2eafa7f023f29bd6449e674c0794bff5e7e`. Migration
from zero as the restricted role 6.1 s; restore 18 s; 33.9 s end to end
including verification. Dataset `51585450-8ff5-409d-a02e-66d5a3c5e260`,
checksum `51e75f78…d2e906`, 155,714 nodes and 180,554 segments — 361,108
directed edges once loaded, matching what the API builds. Zero orphaned rows,
zero invalid geometries, all four foreign keys and all twelve check
constraints in place, PostGIS 3.5.2, 186 MB. The synthetic fixture rows ride
along because they live in the same tables; they are 9 nodes and 13 segments
in their own region. Keep the dump outside the repository and delete it
afterwards.

## 3. Measure

```bash
python infra/production-smoke/measure.py --runs 3 --memory-limits 2g \
  --label one-worker --json docs/evidence/production-envelope.json

# Memory limits, two cold starts each; a run that never becomes ready is
# recorded as invalid with the reason, never averaged in.
python infra/production-smoke/measure.py --runs 2 --memory-limits 1g,1.25g,1.5g \
  --label one-worker-limits --concurrency "" --skip-restart --append \
  --json docs/evidence/production-envelope.json

# Two uvicorn workers: the graph is built once per process.
python infra/production-smoke/measure.py --runs 2 --memory-limits 4g --label two-workers \
  --command "uvicorn pathable_api.main:app --host 0.0.0.0 --port 8000 --workers 2" \
  --skip-restart --append --json docs/evidence/production-envelope.json
```

Standard library only; any Python 3.11+ on the host will do. The script's
docstring explains exactly what each field means. Two things worth knowing
before reading the output:

- **Time starts when `compose up` is issued on the host**, measured on the
  host's monotonic clock. Docker Desktop's VM clock was a day adrift from the
  host while this was written, so container timestamps are recorded but never
  subtracted from host ones. About a second of `compose` overhead is inside
  every start-to-live and start-to-ready figure.
- **Memory is the sum of VmRSS over every process in the container**, sampled
  once a second, with `docker stats` beside it because a hosting limit is
  enforced against the cgroup, not the Python heap. `hwm_sum_at_ready_mb` is
  the sum of each process's own lifetime peak (VmHWM), which cannot be missed
  by sampling.

## 4. Measure the web container

The frontend has its own harness, because its hosting tier is a separate
question from the API's and a much smaller one:

```bash
python infra/production-smoke/measure_web.py --runs 3 --memory-limit 512m \
  --json docs/evidence/production-envelope.json --append
```

Each run recreates the web service alone and checks that it becomes healthy,
serves the landing page, keeps its security headers, carries the right baked
API origin, runs the production standalone server rather than a dev server,
and is never OOM-killed or restarted — recording container RSS and the cgroup
figure throughout. A run that fails any of those is recorded as failed with
the reason; the script exits non-zero if any did.

Then drive the real browser through the containers:

```bash
FULLSTACK_TARGET=compose FULLSTACK_WEB_URL=http://localhost:3001 \
FULLSTACK_API_URL=http://localhost:8001 \
  pnpm --filter @pathable/web exec playwright test --config=playwright.fullstack.config.ts
```

That is the only configuration where the request path is
`browser -> web container -> api container -> postgis container`.

On a Windows host where `localhost` resolves to `::1` first and Docker
Desktop's IPv6 proxy resets the connection, every request in that chain dies
before IPv4 is tried and the whole suite reports `ECONNRESET`. Point the URLs
at `127.0.0.1` and pin the browser to IPv4 for the page's own calls to the API
origin baked into the image:

```bash
PLAYWRIGHT_CHROMIUM_ARGS="--host-resolver-rules=MAP localhost 127.0.0.1" \
FULLSTACK_TARGET=compose FULLSTACK_WEB_URL=http://127.0.0.1:3001 \
FULLSTACK_API_URL=http://127.0.0.1:8001 \
  pnpm --filter @pathable/web exec playwright test --config=playwright.fullstack.config.ts
```

`PLAYWRIGHT_CHROMIUM_ARGS` is read only by the full-stack configuration and
only appends flags to the browser launch (several are separated by `;`); CI
leaves it unset.

The web image is Next.js standalone output served by `node apps/web/server.js`
as uid 10001, with npm, corepack and the Next CLI removed — so a development
server cannot be started in it. The map worker is in
`apps/web/public/maplibre/`. Its `NEXT_PUBLIC_API_BASE_URL` is baked at build
time, so the image is specific to the API origin it was built for.

## 5. Tear down

```bash
docker compose -f infra/production-smoke/compose.yaml down        # keeps the volume
docker compose -f infra/production-smoke/compose.yaml down -v     # deletes pathable-envelope-db-data only
```
