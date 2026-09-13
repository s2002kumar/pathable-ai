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

**Status: RESOLVED (routed around)** · environment limitation, not a code defect ·
2026-08-12 · closed 2026-08-17

**How it was closed.** Not by waiting for the block to lift. Overpass did become
reachable again, but a city-wide unsimplified query then ran for 45 minutes
without producing output, which made it impractical regardless of the block. The
real fix was `pathable ingest pbf`: a published extract needs no live service, is
re-readable as often as you like, and produced the live 180,554-segment dataset.
Overpass remains supported as a second acquisition path, and a parity test pins
that both paths interpret the same OSM facts identically.

The original diagnosis follows, because it is still the right procedure for
telling a network fault apart from a code defect.

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

**Status: RESOLVED** · 2026-08-12 · fixed 2026-08-17

Snapping now attaches to the nearest point _along_ a segment, splitting it for
that request only — the cached graph is shared and version-keyed, so it is never
mutated. An STRtree indexes the segments; building it over 180,554 segments takes
0.16 s and is amortised by the dataset cache.

Two further defects surfaced once this ran on real data, both found by evaluating
twenty real journeys rather than by any unit test.

**Snapping ignored whether the traveller was allowed on the segment.** A point in
Waterloo Park landed 12.4 m onto a `highway=cycleway` carrying `foot=no`. That
segment is correctly closed to pedestrians, so every route to that point failed —
while a walkable path sat a few metres further on. Connectivity analysis put both
endpoints in the same 152,935-node component, which is what proved it a bug
rather than a limit of the data. Snapping now takes a predicate and searches
outward through widening windows when everything nearby is closed to the profile.
Unroutable journeys in the corpus went from 3 of 20 to 1.

**A snapped segment was drawn backwards.** The halves of a split were stored
already reversed _and_ marked as reversed, so `DirectedEdge.coordinates()` flipped
them a second time. Twelve of the nineteen routable journeys drew a polyline with
a gap of up to 93 m, and one ended 15 m from the point the user had chosen — while
the reported distance stayed entirely plausible. Only checking drawn geometry
against the source could have caught it. The regression tests cover the reverse
traversal specifically, because a forward-only route drew correctly throughout.

---

## KI-5 — `unknown_data_fraction` may saturate on real OSM data

**Status: RESOLVED** · raised 2026-08-12 · measured and addressed 2026-08-17

The hypothesis was right about the cause and wrong about the consequence.

`incline` really is almost absent: OpenStreetMap records it on **46 of 180,554**
Waterloo segments, 0.03%. So before elevation, essentially every segment counted
as having missing data and the headline figure sat near 100% on every route —
exactly as predicted, and exactly as useless.

Two things changed. Sampling NRCan HRDEM gives a derived grade on 53.8% of
segments, so the gradient term discriminates again. And the reported figure was
replaced outright: instead of one any-attribute-missing share, a route now
reports per-category shares — "Surface data is missing for 38% of this route" —
because two routes missing completely different things produced the same number
and are completely different journeys.

The underlying penalty was ablated rather than assumed. Over the twenty-journey
corpus it still changes 3 of 20 routes, so it is not saturated. But removing only
the missing-gradient term has exactly the same effect as removing every term, so
one term is currently doing all the work. Recorded in ADR 0008.

---

## KI-6 — Loading the graph takes 20 seconds and 700 MB of heap

**Status: Open, reduced** · measured 2026-08-17 · re-measured 2026-09-02

Loading the active Waterloo dataset into the routing graph — 155,714 nodes and
180,554 segments — now measures a **median 22.1 s** with a **700.7 MB** peak
Python heap, against 46.8 s and 1,381.3 MB for the previous loader on the same
machine and dataset the same afternoon (best run to best run, 21.4 s against
35.0 s). Every run started with under 10% of physical memory free, and the
wall-clock is a laptop's, so the time is a direction and a rough size, not a
service-level figure; the heap and the fingerprint are exact. Both figures come from
`pathable benchmark load --region waterloo`, which records the conditions and
refuses to average in a run that was not really running; the pair is kept in
[`docs/evidence/`](../evidence/README.md). The change was measurement-led:
profiling showed SQLAlchemy building a full ORM entity per edge, so the loader
now reads narrow Core columns, takes geometry as WKB, and leaves the OSM tag
blob in the database.

The originally recorded 97.5 s was measured with tracemalloc on for the whole
load, which the new command shows inflates wall-clock 2.5–6×. It was never the
service's real cold start.

Still open, because it is still the clearest scaling limit in the system:

- A cold API instance cannot serve a route for about twenty seconds after start.
- Resident memory after a load is about 850 MB, with a transient peak near
  1.1 GB while the rows stream in. Memory scales with the region, and Waterloo
  is one mid-sized city.
- Two datasets resident in the cache is roughly 1.7 GB.

The remaining cost is NetworkX edge insertion and Python object construction
— 180,554 `EdgeFeatures` and 361,108 `DirectedEdge` instances. Halving that
again needs a different in-memory representation, which is a real
architectural change and wants its own measurement rather than being bundled
into a query fix.

**In the production container** (measured 2026-09-11 on the real image, empty
database, isolated stack — see [ADR 0009](../adr/0009-deployment-architecture.md)
and [`docs/evidence/production-envelope.json`](../evidence/production-envelope.json)):
one worker reaches readiness a median 18.7 s after `compose up` on this laptop,
with the graph preload itself 14.6 s; resident memory is **997 MB steady** with
a **1,064 MB** lifetime peak, so a 2 GB tier is the smallest defensible size
and a 1 GB limit ran with 6% headroom. **Every uvicorn worker holds its own
copy**: two workers measured 2.04 GB resident, 2.17 GB peak. `GRAPH_PRELOAD_REGIONS`
now makes the load part of startup and holds readiness at 503 until it is
done, so an orchestrator no longer routes users into the load window; the
window itself is unchanged.

**Check when:** a deployment target with a memory budget exists, or a second
region is added.

---

## KI-7 — Evidence freshness is a dataset-level fact

**Status: Open** · 2026-08-17

Every routing-relevant fact carries where it came from and when — but "when" is
the timestamp of the whole extract, not of the individual element. The product
can say the network was published on 2026-08-16; it cannot say that a particular
crossing was last surveyed four years ago.

That distinction matters for exactly the facts this product depends on. A kerb
mapped in 2019 and a kerb mapped last week are not equally trustworthy, and a
route that cannot tell them apart cannot warn about the difference.

**The data exists**: OSM elements carry `timestamp` and `version`, and pyosmium
exposes both. It was not wired through because the coverage report and the
freshness policy would both have to change shape at the same time, and doing that
with no use for the number yet would be building ahead of need.

**Check when:** a second source of evidence arrives — user reports, or model
predictions — at which point "how old is this claim" becomes a question the
product must answer about more than one thing at once.

---

## KI-8 — The managed-hosting bootstrap is proven against a stand-in, not a provider

**Status: Open** · 2026-09-12

The dataset restore no longer needs a PostgreSQL superuser. It was demonstrated
against a role created to look like the one a managed service hands out —
`superuser=f createdb=f createrole=f bypassrls=f replication=f`, owning its own
database, with PostGIS installed by the platform's admin beforehand — and the
old `pg_restore --disable-triggers` command was run as that role first, failing
with `permission denied: "RI_ConstraintTrigger_a_21027" is a system trigger`,
which is what would have happened on the provider.

**That is a stand-in, not the thing itself.** A real managed database differs
in ways this cannot rehearse: the exact grants DigitalOcean gives `doadmin`,
whether `CREATE EXTENSION postgis` is permitted directly or must go through
their console, connection limits and pooler behaviour under `pgbouncer`,
whether an idle transaction is cut short mid-restore, and how long a 31 MB
archive takes over the network rather than over a loopback socket. Any of those
could need a change to
[`infra/production-smoke/restore-dataset.sh`](../../infra/production-smoke/restore-dataset.sh).

**Check when:** the first real managed database exists. Run the script against
it before believing the bootstrap works, and record what differed.
