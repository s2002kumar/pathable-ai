# Data flow

What actually moves through the system today, and what is planned. Anything
marked _planned_ does not exist in this repository.

---

## 1. Page load

```
Browser ──GET /──────────────────▶ Next.js server
                                    │
                                    ├─ validate NEXT_PUBLIC_* configuration
                                    │    invalid → configuration error page
                                    │    valid   → application shell
                                    ▼
Browser ◀─ HTML + CSS ─────────────┘
   │
   ├─ hydrate
   ├─ dynamic import: MapLibre chunk (client only)
   └─ fetch GET {API_BASE}/api/v1/health/ready
```

Configuration is validated on the server, so a bad `.env` produces a page that
names every offending variable rather than a blank screen. Because Next inlines
`NEXT_PUBLIC_*` at build time, a change requires a rebuild.

## 2. Map initialisation

```
detectWebGl()
   │
   ├─ no WebGL 2 ──▶ state = unsupported ──▶ explanation + textual pilot description
   │
   └─ WebGL 2 ok
        │
        ├─ import('maplibre-gl')          ─ fails ─▶ state = error
        ├─ new Map({ style, center, zoom })
        ├─ addControl: attribution, navigation, scale
        │
        ├─ 'load'  ──▶ state = ready
        ├─ 'error' ──▶ state = error   (only while not yet ready)
        └─ timeout ──▶ state = error   (15 s)
```

The state is published as `data-map-state`, which browser tests wait on.

Two deliberate behaviours:

- A tile failure **after** the map is ready does not flip it to an error. A
  degraded map beats an error screen replacing a usable one.
- The effect never resets its own state synchronously; changing the style
  remounts the component instead (`key={styleUrl}`), which avoids cascading
  renders.

No map tile ever passes through the PathAble backend. The browser talks to the
tile provider directly, which is why the provider choice is a licensing question
rather than an infrastructure one.

## 3. Backend status

```
Browser ──GET /api/v1/health/ready──▶ FastAPI
                                       │
                                       ├─ RequestContextMiddleware
                                       │    adopt or generate X-Request-ID
                                       │
                                       ├─ readiness handler
                                       │    │
                                       │    ├─ no DATABASE_URL ──▶ not_ready
                                       │    │
                                       │    └─ asyncio.wait_for(timeout):
                                       │         SELECT 1
                                       │         SELECT extversion FROM pg_extension …
                                       │
                                       ▼
Browser ◀─ 200 ready | 503 not_ready ──┘  (identical body shape)
```

The badge maps this to three visible states:

| Backend result          | Badge                                       |
| ----------------------- | ------------------------------------------- |
| 200 `ready`             | API online                                  |
| 503 `not_ready`         | API degraded, naming the failing dependency |
| network error / timeout | API offline                                 |

Driver exceptions never reach the browser. psycopg failure messages routinely
embed host, port, database and user, and readiness is typically unauthenticated;
the exception is logged with the correlation id and the caller receives a fixed
string.

## 4. Correlation

```
inbound X-Request-ID
   │
   ├─ matches [A-Za-z0-9._-]{8,128}  ──▶ adopted
   └─ otherwise                       ──▶ fresh uuid4 hex
   │
   ▼
ContextVar ──▶ every log line for this request
           ──▶ X-Request-ID response header
           ──▶ request_id in any error body
```

A malformed correlation header replaces the id rather than failing the request:
it is not the caller's problem to fix mid-flight. The charset bound also stops a
newline from being injected into a log line.

## 5. Contract generation

```
schemas/*.py (Pydantic)
   │  create_app(fixed export settings)
   ▼
app.openapi()
   │  json.dumps(sort_keys, indent=2, trailing newline)
   ▼
packages/contracts/openapi.json        ← committed
   │  openapi-typescript
   ▼
packages/contracts/src/generated/api.ts ← committed
   │  type-only import
   ▼
apps/web
```

`pnpm contracts:check` reruns the whole pipeline into a temporary directory and
compares bytes. Determinism matters: export settings are fixed rather than read
from the environment, so the document is identical on a laptop and in CI.

## 6. Container startup

```
docker compose up
   │
   ├─ db: initdb → pg_isready healthcheck → healthy
   │
   ├─ api (waits for db healthy)
   │    entrypoint:
   │      ├─ poll SELECT 1, bounded retries
   │      ├─ alembic upgrade head        (idempotent)
   │      └─ exec uvicorn                (becomes PID 1)
   │    healthcheck: /health/live  ← liveness, not readiness
   │
   └─ web (waits for api healthy)
        healthcheck: /api/healthz
```

The API's healthcheck uses liveness deliberately: the process is legitimately up
while the database is still starting, and marking it unhealthy for that would
trigger a pointless restart loop.

## 7. Planned — routing (Phase 1, not built)

```
origin, destination, mobility profile
   │
   ▼
snap to nearest pedestrian graph nodes (PostGIS)
   │
   ├─▶ shortest path        (distance cost)
   └─▶ accessible path      (profile cost + hard constraints)
   │
   ▼
compare: extra distance, extra time, what was avoided
   │
   ▼
per-segment explanation: evidence, source, age, confidence
```

Two invariants the schema must carry from the first table:

1. **Hard constraints and preferences are different columns.** "Cannot use
   stairs" and "prefers no stairs" must never collapse into one weight.
2. **Observed facts and inferred predictions are different columns**, and stay
   separate through the API to the interface. Once merged, they cannot be
   unmerged, and the user loses the ability to tell what is known from what is
   guessed.

## 8. Planned — learned prediction (Phase 3, not built)

```
imagery (licence-reviewed) ──▶ labelled dataset (versioned)
                                  │
                                  ├─ geographic hold-out split
                                  ▼
                              trained model (versioned)
                                  │
                                  ▼
                     predictions + calibrated confidence
                                  │
                                  ▼
                    edge attributes, tagged with model version
                                  │
                                  ▼
                    router consumes value *and* uncertainty
```

A low-confidence prediction must never act as a hard constraint. See
[`FUTURE_ML_ARCHITECTURE.md`](FUTURE_ML_ARCHITECTURE.md).

---

## Data not collected

Phase 0 collects nothing. No accounts, no location, no analytics, no cookies, no
third-party trackers. The only outbound request the browser makes to a
non-PathAble host is for map tiles, and that is a documented licensing
consideration rather than an accident.
