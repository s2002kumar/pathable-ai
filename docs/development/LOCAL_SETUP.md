# Local setup

Reproducible from a clean clone. If a step here does not work, that is a bug —
please report it.

---

## 1. Prerequisites

| Tool           | Version | Check            | Install                                             |
| -------------- | ------- | ---------------- | --------------------------------------------------- |
| Node.js        | ≥ 20.11 | `node -v`        | https://nodejs.org (22 LTS or newer)                |
| pnpm           | ≥ 10    | `pnpm -v`        | `corepack enable`                                   |
| uv             | ≥ 0.12  | `uv --version`   | see below                                           |
| Python 3.13    | 3.13.x  | `uv python list` | `uv python install 3.13` (uv can manage it for you) |
| Docker Desktop | ≥ 4.30  | `docker info`    | https://docker.com/products/docker-desktop          |
| Git            | ≥ 2.40  | `git --version`  | https://git-scm.com                                 |

Install `uv`:

```powershell
# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Docker is optional for frontend and backend unit work. It is required for the
database, and therefore for the integration tests.

---

## 2. Clone and configure

```bash
git clone <repository-url> pathable-ai
cd pathable-ai
```

```bash
cp .env.example .env                 # macOS / Linux
```

```powershell
Copy-Item .env.example .env          # Windows PowerShell
```

The defaults work out of the box. `.env` is git-ignored and must never be
committed.

---

## 3. Install

```bash
pnpm bootstrap
```

That runs, in order:

1. `pnpm install` — the JavaScript workspace
2. `uv sync` in `services/api` — a Python 3.13 virtualenv at `services/api/.venv`
3. `playwright install chromium` — the browser for e2e tests

If the Playwright step fails, everything else is still usable; only `pnpm test:e2e`
is blocked until `pnpm --filter @pathable/web exec playwright install chromium`
succeeds.

> `install` is not exposed as a pnpm script because `install` is a reserved npm
> lifecycle name — defining it would make `pnpm install` recurse into itself.
> `pnpm bootstrap` is the equivalent.

---

## 4. Run it

### Option A — everything in Docker

```bash
docker compose up --build
```

| Service   | URL                                       |
| --------- | ----------------------------------------- |
| Web       | http://localhost:3000                     |
| API       | http://localhost:8000                     |
| API docs  | http://localhost:8000/docs                |
| Readiness | http://localhost:8000/api/v1/health/ready |
| Database  | `localhost:5433`                          |

Startup order is enforced: the database becomes healthy, then the API waits for
it, migrates and starts, then the web container waits for the API.

### Option B — database in Docker, apps on the host

Faster feedback while developing.

```bash
docker compose up -d db
pnpm dev
```

`pnpm dev` runs both services with prefixed output; Ctrl+C stops both.

### Option C — no Docker at all

Frontend and backend unit tests need nothing:

```bash
pnpm --filter @pathable/web dev
uv --directory services/api run uvicorn pathable_api.main:app --reload
```

Readiness will report `not_ready` without a database. Liveness still returns 200,
which is the intended split.

---

## 5. Everyday commands

### Docker

```bash
docker compose up -d              # start in the background
docker compose ps                 # status and health
docker compose logs -f            # follow all logs
docker compose logs -f api        # one service
docker compose restart api        # restart one service
docker compose up -d --build api  # rebuild and restart after a change
docker compose down               # stop — KEEPS the database volume
```

PowerShell equivalents are identical; Docker Compose is the same binary.

### Deleting local database data — deliberate and destructive

```bash
pnpm docker:reset-db     # asks for confirmation
# or, directly:
docker compose down -v
```

`docker compose down` alone never deletes data. Only `-v` does.

### Migrations

```bash
# Applied automatically when the API container starts. Manually:
uv --directory services/api run alembic upgrade head
uv --directory services/api run alembic current
uv --directory services/api run alembic history
uv --directory services/api run alembic downgrade -1

# New migration (review the generated file — always)
uv --directory services/api run alembic revision -m "add pedestrian edges"
```

### Tests

```bash
pnpm test                # unit, frontend + backend. No database needed
pnpm test:integration    # needs PostGIS running
pnpm test:e2e            # needs Chromium. No backend, no internet
pnpm check               # the full non-Docker gate
```

For integration tests, start the database and export the URL:

```bash
docker compose up -d db
export DATABASE_URL='postgresql+psycopg://pathable:pathable_local_dev_only@localhost:5433/pathable'
pnpm test:integration
```

```powershell
docker compose up -d db
$env:DATABASE_URL = 'postgresql+psycopg://pathable:pathable_local_dev_only@localhost:5433/pathable'
pnpm test:integration
```

The suite reads `.env` automatically when run through `uv`, so exporting is only
needed if your shell environment differs.

### Contracts

After changing any Pydantic response model:

```bash
pnpm contracts:generate   # regenerate openapi.json and api.ts
pnpm contracts:check      # verify — this is what CI runs
```

Commit both generated files.

---

## 6. Verifying the stack by hand

```bash
curl http://localhost:8000/api/v1/health/live
# {"status":"ok","service":"pathable-api","version":"0.1.0"}

curl -i http://localhost:8000/api/v1/health/ready
# 200 with "status":"ready" once migrations have run

curl http://localhost:3000/api/healthz
# {"status":"ok","service":"pathable-web"}
```

PowerShell:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/health/live
Invoke-WebRequest http://localhost:8000/api/v1/health/ready | Select-Object StatusCode, Content
```

Then open http://localhost:3000 — the badge should read **API online**.

---

## 7. Troubleshooting

### "port is already allocated"

Change `WEB_PORT`, `API_PORT` or `DB_PORT` in `.env` and restart.

Find the offender:

```powershell
netstat -ano | findstr :5433        # Windows; last column is the PID
Get-Process -Id <PID>
```

```bash
lsof -i :5433                        # macOS / Linux
```

> The database publishes on **5433**, not 5432, precisely because a locally
> installed PostgreSQL usually owns 5432 already.

### Docker Desktop will not start

Symptom:

```
error during connect: ... open //./pipe/dockerDesktopLinuxEngine:
The system cannot find the file specified.
```

The `com.docker.service` helper is not running. It requires elevation and cannot
be started from an ordinary shell.

1. Launch **Docker Desktop** from the Start menu and approve the UAC prompt.
2. Wait for the whale icon to stop animating.
3. `docker info` should print a server version.

If it persists: check `Get-Service com.docker.service`, ensure WSL 2 is healthy
(`wsl --list --verbose`), then restart Docker Desktop with
**Troubleshoot → Restart**.

### `uv: command not found`

Open a new terminal so the updated `PATH` is picked up. The repository's scripts
resolve `uv` from `~/.local/bin` themselves, so `pnpm` commands work regardless.

### Readiness says `postgis extension is not installed`

The database is running but un-migrated:

```bash
uv --directory services/api run alembic upgrade head
```

Or restart the API container, whose entrypoint migrates on start.

### The map shows "This browser cannot display the map"

MapLibre requires WebGL 2. Check `chrome://gpu`; hardware acceleration is
frequently disabled on managed machines. The written pilot description remains
available, which is the intended fallback.

### `pnpm contracts:check` fails

Backend schemas changed without regenerating:

```bash
pnpm contracts:generate
git add packages/contracts
```

### Playwright cannot find a browser

```bash
pnpm --filter @pathable/web exec playwright install chromium
```

### e2e tests time out on a slow machine

The suite runs MapLibre through SwiftShader (software rendering), which is
CPU-bound. Reduce parallelism:

```bash
pnpm --filter @pathable/web exec playwright test --workers=1
```

### Windows line-ending problems in containers

`.gitattributes` forces LF for shell scripts. If a container entrypoint fails
with "no such file or directory" despite the file existing, it has CRLF endings:

```bash
git config core.autocrlf false
git rm --cached -r . && git reset --hard
```

---

## 8. Editor setup

VS Code is the assumed editor. Useful extensions: Python, Pylance, Ruff, ESLint,
Prettier, Docker.

Point the Python interpreter at `services/api/.venv`. Formatting is Ruff for
Python and Prettier for everything else; `.editorconfig` covers indentation and
line endings.
