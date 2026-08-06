# Known issues

Open defects with reproduction steps and evidence. Resolved issues stay here with
their diagnosis, because the reasoning is usually more valuable than the fix.

---

## KI-1 — The map did not render a real vector basemap

**Status: RESOLVED** · found 2026-08-05 · fixed 2026-08-06

### Symptom

With the real development style, the map never finished initialising and showed
"The map is unavailable". The deterministic offline test style was unaffected, so
every automated suite was green.

### Root cause

MapLibre 6 runs tile parsing in a **separate module worker** and derives its URL
from its own `import.meta.url`:

```js
let e = import.meta.url;
if (!/^https?:/.test(e)) return ""; // <- here
return new URL("./maplibre-gl-worker.mjs", e).href;
```

Once MapLibre is bundled, `import.meta.url` is no longer an `http(s)` URL, so
that returns an **empty string** and MapLibre calls `new Worker('')`. An empty
worker URL resolves to the current document, so the browser starts a worker whose
script is the HTML page. It loads, it never answers, and **nothing throws**.

The result: the style document, TileJSON and sprites were all fetched
successfully, then not one vector tile was ever requested, `style.load` never
fired, and the console stayed clean.

Two things hid it:

- The map frame's own background still showed, so screenshots looked plausible.
- The offline test style has **no sources**. With nothing to parse the worker is
  never needed, so `load` fires anyway and the lifecycle reported `ready` over a
  map that had never drawn a tile.

### How it was found

Controlled experiments, each isolating one variable:

| Experiment                                                 | Environment           | Vector tiles   | Result                            |
| ---------------------------------------------------------- | --------------------- | -------------- | --------------------------------- |
| **Control A** — official MapLibre demo style, minimal page | Chrome 150, real GPU  | **6, all 200** | `style.load`@993ms, `load`@1363ms |
| **Control B** — OpenFreeMap style, minimal page            | Chrome 150, real GPU  | **8, all 200** | `style.load`@843ms, `load`@2911ms |
| **Control C** — minimal page, unbundled MapLibre           | Chrome 150, real GPU  | works          | worker URL resolved correctly     |
| Application, bundled by Next/Turbopack                     | Chrome 150 + headless | **0**          | worker URL was the page origin    |

MapLibre 6.1.0, the OpenFreeMap style and the browser were therefore all fine.
The single difference was the worker URL, and the empty-string branch above
explains it exactly.

The provider was independently confirmed healthy: a z10 tile fetched directly
returns ~60 KB.

### Fix

Serve MapLibre's own worker chunk from our origin and pass an absolute URL to
`setWorkerUrl()` before constructing any map.

- `scripts/sync-maplibre-worker.mjs` copies `maplibre-gl-worker.mjs` and the
  `maplibre-gl-shared.mjs` it imports out of node_modules into
  `apps/web/public/maplibre/`, on `predev` and `prebuild`. Generated rather than
  committed, so it cannot drift from the installed version.
- `src/features/map/worker-url.ts` resolves and applies the URL.

### Verification

Real application, real style, Chrome 150 with a real GPU
(ANGLE / Intel Arc / D3D11):

|                                    | Desktop                            | Mobile (Pixel 7) |
| ---------------------------------- | ---------------------------------- | ---------------- |
| Map state                          | `ready`                            | `ready`          |
| Vector tiles on load               | 8, all HTTP 200                    | 4, all HTTP 200  |
| Vector tiles after pan + zoom      | 20                                 | 11               |
| Worker URL                         | `/maplibre/maplibre-gl-worker.mjs` | same             |
| Attribution visible                | yes                                | yes              |
| Pan / zoom                         | working                            | working          |
| Container fills frame after resize | yes                                | n/a              |
| Unexpected console errors          | none                               | none             |

Screenshots: `apps/web/artifacts/screenshots/real-basemap-{desktop,mobile}.png`
(default Waterloo view) and `…-after-interaction.png` (after pan and zoom).

### Regression cover

- `src/features/map/worker-url.test.ts` — the URL handed to MapLibre is always an
  absolute `http(s)` URL and never an empty string.
- `tests/e2e/app-shell.spec.ts` — the worker asset and its shared chunk are
  actually served. Nothing else would notice if the sync script stopped running,
  because the offline style needs no worker.

### Standing risk

CI still exercises the map with the source-less offline style, deliberately: a
green build must not depend on a third-party tile server. **That means CI cannot
catch a regression of this class.** Real-basemap rendering must be verified in a
normal browser before any release — see
[`TESTING.md`](TESTING.md#manual-real-basemap-verification).

---

## KI-2 — Docker has never been exercised on this machine

**Status: Open** · environment limitation, not a code defect

`com.docker.service` cannot be started without Windows administrator rights, and
this development environment has none (`IsAdmin: False`). Docker images have
never been built, the Compose stack has never started, and container health,
networking, the migrate-on-start entrypoint and non-root runtime users are all
unverified.

Everything Docker would provide has been exercised natively instead: real
PostgreSQL 17.6 + PostGIS 3.6.2, migrations, all integration tests, and a
full-stack browser suite with no stubs. That is not a substitute for container
verification.

**Unblock:** launch Docker Desktop and approve the UAC prompt, then
`docker info`, `docker compose build --pull`, `docker compose up -d`.
