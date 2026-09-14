# Changelog

Notable changes to PathAble AI. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[semantic versioning](https://semver.org/) once releases begin.

This project is private and unreleased. See [`LICENSING.md`](LICENSING.md).

---

## [Unreleased]

### Fixed

- **Four published claims that the evidence did not support.** Building the
  claims ledger meant checking every number against the file behind it, which
  caught them. The median detour across the twenty-journey corpus was published
  as 70 m and is 86.1 m across the eighteen journeys that change, 83.8 m across
  all nineteen routable — recomputing from the corpus at the commit that first
  published 70 m gives the same 86.05, so it was wrong when written rather than
  left behind. Backend coverage was quoted as 89.13% with no measurement
  context; it is 89.09% in CI and 89.13% locally on Windows, where one
  platform-specific test is skipped, and the README now says which. The
  full-stack demo suite was described as skipping eight of nine tests in CI when
  the guard skips all nine. And `06-snapped-away-from-the-chosen-point.png` was
  listed in the evidence index as a distinct capture when it was byte-identical
  to `05-missing-evidence.png` — the spec's no-route attempt produced a route —
  so the file is deleted and the index says what happened. None of the four
  changes an argument, which is exactly why they survived until something
  checked them.

### Added

- **A recruiter-facing evidence package, and a ledger that governs it.** The
  README now opens with what PathAble does, a 67-second recording of the real
  production containers answering a real request
  (`docs/evidence/media/pathable-demo.webm`), and a table in which every figure
  links to the run that produced it. `docs/PROJECT_DEFENSE.md` is the
  interview-depth account — architecture, the cost model, three debugging
  stories told with their evidence, the trade-offs and what breaks at 10x.
  `docs/CLAIMS_LEDGER.md` maps each claim to its exact supportable wording, its
  evidence, the conditions it was measured under and the overstatement it is one
  word away from, followed by a prohibited-claims list: no deployment, no users,
  no production latency, no certification, no machine learning.
  `docs/INTERVIEW_EXPLANATIONS.md` holds drafts at thirty seconds, two minutes
  and ten. Nothing in the package asserts anything the repository cannot show.

- **A publication policy, and a public-release safety gate that produced it.**
  PathAble's source code is **source-visible and all rights reserved**
  (© Sandeep Kumar) — deliberately not open source, because a permissive licence
  is a one-way door and this keeps it open. The data is licensed separately and
  more generously: OpenStreetMap under ODbL 1.0, elevation under the Open
  Government Licence – Canada, and the OSM-derived measurement files in
  `docs/evidence/` labelled as such. `LICENSING.md` states the policy;
  `docs/security/PUBLIC_RELEASE_SAFETY.md` records the scans, dependency audits,
  licence inventory and attribution verification behind it. Git history is
  preserved unchanged; future commits use a GitHub `noreply` address.

- **`pathable benchmark load`**, a committed, repeatable measurement of the
  cold-start cost: it times loading a region into the routing graph, measures
  peak Python heap and process memory, records the machine conditions, marks a
  run invalid rather than averaging it in when the process was mostly not
  running, and fingerprints every node and segment so two loaders can be shown
  to have built the same graph. Results live in `docs/evidence/`.
- **A real Waterloo network, ingested from a published extract.** 155,714 nodes
  and 180,554 physical segments (361,108 routable directed edges, 3,363.7 km) read
  from Geofabrik's Ontario extract, whose published MD5 matched the download
  exactly. `pathable ingest pbf` reads a local `.osm.pbf` with pyosmium and
  normalises it through the identical functions the Overpass path uses, so a
  route cannot change because of how the data arrived.
- **Elevation, from NRCan HRDEM 1 m LiDAR.** Chosen by measurement rather than
  availability: over 50 m segments a 30 m global model has RMSE 4.06 percentage
  points against a true median grade of 1.78%, so its error exceeds the signal.
  100% of nodes now carry an elevation with full provenance; gradient is known
  for 53.8% of segments, against 0.03% from OpenStreetMap alone.
- **A\* alongside Dijkstra.** Identical cost on all 19 routable journeys of the
  Waterloo corpus, expanding 1,970 nodes at the median against Dijkstra's 7,409.
  Wall-clock is a wash at this scale — 200.6 ms against 197.7 ms at p50 — so A\*
  is not presented as faster.
- **Data-coverage and route-evaluation reporting.** `pathable coverage` counts
  each accessibility category separately and refuses to combine them into a
  score; `pathable evaluate` routes a fixed corpus of twenty real journeys and
  reports every outcome, including the ones where nothing changed.

### Changed

- **Graph loading reads narrow Core columns instead of ORM entities**, takes
  geometry as WKB, and leaves the OSM tag blob in the database. On the Waterloo
  dataset, peak Python heap fell from 1,381 MB to 701 MB and the median load
  from 46.8 s to 22.1 s on the same laptop; the loaded graph and every route in
  the evaluation corpus are unchanged. KI-6 stays open at the new baseline.

- **The route panel says which fact is missing, not how much is.** "Length with
  missing accessibility data: 38%" is replaced by per-category sentences such as
  "Surface data is missing for 38% of this route", because two routes missing
  completely different things produced the same number. A route also now says
  whether its gradient was recorded by a mapper or inferred from a terrain model.

### Fixed

- A segment's `name` is taken from the OSM tag only when it is a JSON string.
  The SQL extraction would otherwise have rendered a number or an OSMnx-merged
  list of names as text, where the previous loader dropped them.

- **The map now renders a real vector basemap (KI-1).** MapLibre 6 loads its tile
  worker as a separate module chunk and derives the URL from `import.meta.url`,
  returning an **empty string** once bundled. `new Worker('')` resolves to the
  HTML page, so the worker never answered: the style, TileJSON and sprites all
  loaded, no vector tile was ever requested, and nothing threw. Fixed by serving
  MapLibre's own worker from `/maplibre/` and passing an absolute URL to
  `setWorkerUrl()`.

  Verified in Chrome 150 with a real GPU: 20 vector tiles (all HTTP 200) on
  desktop and 11 on mobile after pan and zoom, attribution visible, container
  filling its frame after resize, no unexpected console errors, and a
  recognisable Waterloo basemap in both screenshots.

- Added an app icon, removing the only remaining `/favicon.ico` 404.

### Added

- `scripts/sync-maplibre-worker.mjs`, run on `predev`/`prebuild`, keeps the served
  worker matched to the installed MapLibre version.
- Regression cover for KI-1: unit tests pinning the absolute-URL property, and an
  e2e check that the worker asset is actually served — nothing else would notice
  it going missing, because the offline test style needs no worker.
- Documented manual real-basemap verification, since CI deliberately cannot catch
  a regression of this class.

---

## [0.1.0-foundation] — 2026-08-05

The Phase 0 engineering foundation. **There is no routing and no machine
learning in this release**, and the interface says so. Nothing here should be
used to plan a journey or to judge whether a route is accessible.

### Added

**Frontend**

- Next.js 16 App Router shell with React 19 and strict TypeScript.
- MapLibre GL map with configurable centre, zoom, style and region name;
  Waterloo, Ontario as the default.
- Four-state map lifecycle — initialising, ready, error, unsupported — published
  on `data-map-state`, with a written pilot-area description as the accessible
  equivalent of the map.
- WebGL-absent fallback that explains itself in browser terms.
- Backend status badge distinguishing online, degraded and unreachable.
- Design tokens with light and dark themes, visible focus indicators, skip link
  and reduced-motion support.
- Configuration error page naming every invalid `NEXT_PUBLIC_*` variable.

**Backend**

- FastAPI service with validated configuration; production additionally requires
  a database URL, explicit CORS origins, no wildcard origin and JSON logging.
- `GET /api/v1/health/live` — no dependencies touched.
- `GET /api/v1/health/ready` — probes PostgreSQL and PostGIS under a bounded
  timeout, returning 200 or 503 with an identical body shape.
- Structured JSON logging with request correlation ids.
- A single sanitised error envelope; no traceback, DSN or driver message can
  reach a client.
- `python -m pathable_api` entry point.

**Data**

- PostgreSQL 17 + PostGIS 3.5 through Docker Compose, on a named volume.
- Alembic baseline migration enabling PostGIS, with a working downgrade.

**Contracts**

- Deterministic OpenAPI export from the Pydantic models, generating committed
  TypeScript consumed by the frontend, with a CI drift check.

**Engineering**

- Multi-stage Docker images running as a non-root user, with health checks and a
  migrate-on-start entrypoint.
- 168 backend unit tests, 15 PostGIS integration tests, 124 frontend unit tests,
  54 deterministic browser tests and 5 full-stack browser tests.
- GitHub Actions for CI and security, with every third-party action pinned to a
  commit SHA, and Dependabot across four ecosystems.
- `pnpm check` (fast) and `pnpm check:full` (includes real PostGIS and browser
  tests, and fails rather than skipping when the database is absent).

**Documentation**

- PRD, phase definitions, architecture overview, data flow, future ML
  architecture, seven ADRs, licensing, threat model, local setup and testing.

### Fixed

Found during P0-A01 remediation, once the integration and full-stack suites were
actually executed rather than merely written:

- **The map never rendered a real basemap.** The map container collapsed to zero
  height because MapLibre's own `.maplibregl-map { position: relative }`
  overrode the absolute positioning. The failure was invisible: the frame's
  background still showed, and a source-less test style fires `load` at any size,
  so the lifecycle reported `ready`. Now covered by a regression test asserting
  the container fills the frame.
- **The API could not reach a database on Windows.** psycopg 3 cannot run in
  async mode on `ProactorEventLoop`, and uvicorn 0.36+ selects it explicitly via
  a loop factory that ignores the asyncio policy. Every connection failed while
  liveness kept returning 200, so the documented native-Windows development path
  was unusable. Fixed by running the server with an explicit selector loop
  factory.
- **Alembic could not run under the test suite.** A missing `path_separator`
  raised a `DeprecationWarning`, which `filterwarnings = error` turned into a
  failure. It would also have mis-split Windows paths.
- **`pytest` upgraded to ≥ 9.0.3** for CVE-2025-71176 (predictable
  `/tmp/pytest-of-{user}` path), found by `pip-audit`.

### Changed

- **Removed the Apache-2.0 licence.** It was added by default without founder
  approval. The project is private, unreleased and unlicensed; see
  [`LICENSING.md`](LICENSING.md). Third-party obligations are unaffected.
- Map initialisation timeout raised from 15s to 30s — a real vector basemap on a
  slow connection legitimately exceeds 15s, and the map recovers on its own if
  `load` arrives late.
- `httpx` replaced by `httpx2` for the test client, after verifying provenance;
  recorded in [`docs/development/DEPENDENCY_DECISIONS.md`](docs/development/DEPENDENCY_DECISIONS.md).

### Known issues

- **The map does not render a real vector basemap.** With the OpenFreeMap
  development style, MapLibre 6.1.0 loads the style, TileJSON and sprites, then
  requests no vector tiles and never fires `load`. Reproduced in both production
  and dev builds, at zoom 10 and 15, with no console error. The provider is
  healthy (a z10 tile returns 60 KB). Unresolved; the deterministic offline test
  style is unaffected.
- Docker images have never been built and the Compose stack has never been
  started — the daemon was unavailable in the development environment.
