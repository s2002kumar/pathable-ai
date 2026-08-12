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

---

## KI-3 — Overpass became unreachable from this network mid-session

**Status: Open** · environment limitation, not a code defect · 2026-08-12

### Symptom

`pathable ingest osm --region waterloo` cannot reach any Overpass endpoint. TCP
connections to every published address time out, while everything else on the
same machine is fine:

```
200 0.5s https://api.openstreetmap.org/api/versions
200 0.2s https://nominatim.openstreetmap.org/status
200 0.3s https://tiles.openfreemap.org/styles/liberty
200 0.3s https://github.com
FAIL 30.0s https://overpass-api.de/api/status   ConnectTimeout
```

Overpass **was** reachable earlier in the same session — a status query and a
POST to `/api/interpreter` both returned 200 in about a second. It then began
returning `429 Too Many Requests` on every attempt, and shortly afterwards
stopped accepting connections from this host altogether.

### Diagnosis

The 429s were earned. Diagnosing an unrelated fault (below) involved repeated
requests in quick succession, which is exactly what Overpass's slot management
exists to stop. The subsequent connection timeouts are consistent with a
temporary block at the service, and are expected to lapse.

### What this did and did not affect

The ingestion path itself is implemented and its conversion logic is covered by
tests, but **no real Waterloo dataset has been ingested on this machine**, so
there are no measurements over real OSM data. Routing has been exercised against
the synthetic fixture in PostGIS and characterised for scale against an in-memory
lattice; neither is a substitute.

### A real fix that came out of it

OSMnx pins the Overpass hostname to a single IP for the duration of an import —
it calls `socket.gethostbyname` once and patches `getaddrinfo` — so its
rate-limit accounting and its query reach the same backend. Correct for slot
management, but it means a round-robin name with one unreachable member is a coin
flip, and losing it hangs the whole import until the request timeout. Observed
here: `overpass-api.de` resolves to `162.55.144.139` (reachable at the time) and
`65.109.112.52` (not, from this network), and an import that pinned the second
stalled for over an hour before it was killed.

`select_overpass_endpoint` now probes every address an endpoint resolves to and
only accepts one where all of them answer, so whichever OSMnx pins will work. The
CLI now fails in about fifteen seconds with an actionable message instead of
hanging.

**Unblock:** wait for the block to lapse, then re-run the import. Use
`--overpass-url` to point at another instance if needed.

**If Overpass access stays unreliable**, the sanctioned channel for bulk OSM data
is a pre-built extract rather than a live query, and both providers are reachable
from here (checked 2026-08-12: `download.geofabrik.de` 200 in 0.9 s,
`extract.bbbike.org` 200 in 1.0 s). That path needs a PBF reader — `pyrosm` or
`osmium` — which is a dependency decision worth making deliberately rather than
adding at the end of a batch, so it is recorded here instead of implemented.

---

## KI-4 — Origins snap to the nearest junction, not the nearest point on a path

**Status: Open** · known limitation, deliberate for the MVP

A requested coordinate is matched to the nearest graph **node**. Splitting an edge
at an arbitrary point means synthesising two half-edges with derived geometry and
costs, which is real work that buys a bounded improvement — the error is capped by
the distance between junctions.

The consequence is visible rather than hidden: every route reports how far each
endpoint was from where it actually joined the network, the API refuses a point
more than 300 m from any mapped path, and the UI raises a caution past 50 m.

Snapping is also a linear scan over node positions. At the ten-thousand-node
scale measured so far it is a small share of a request; on a larger network it
would need a spatial index.

**Fix when:** either the reported snap distances or the request latency stop being
acceptable on a real city network.

---

## KI-5 — `unknown_data_fraction` may saturate on real OSM data

**Status: Open, unverified** · 2026-08-12

A route's `unknown_data_fraction` counts a segment if **any** routing-relevant
attribute is unrecorded. `incline` is one of those attributes, and OpenStreetMap
records it on very few ways.

If that holds for Waterloo, nearly every real segment will count as having
missing data and the figure will sit near 100% on every route — accurate, but
useless as a signal, because a number that never varies cannot distinguish a
well-surveyed route from a poorly surveyed one.

This is **not confirmed**. It cannot be, until a real dataset can be ingested
(see KI-3), and changing the measure against an unmeasured hypothesis would be
guessing. The cost model itself is unaffected either way: the uncertainty penalty
is per-attribute and per-metre, so it still discriminates between a segment
missing one attribute and a segment missing four.

**Check when:** the first real Waterloo dataset is ingested. If the fraction does
saturate, the likely fix is to report the count of missing attributes per metre
rather than a binary any-missing share — keeping the same underlying facts and
making the headline number discriminate again.
