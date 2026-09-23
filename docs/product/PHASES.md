# Phases

Each phase names what exists at the end of it, and — as importantly — what still
does not. The "does not exist" column is what keeps the product honest.

---

## Phase 0 — Foundation ✅ _(P0-A01, merged and tagged `v0.1.0-foundation`)_

**Goal.** A running, tested, documented system that makes no claim it cannot
support.

**Delivered**

| Area       | What exists                                                                                     |
| ---------- | ----------------------------------------------------------------------------------------------- |
| Repository | pnpm workspace + uv project; formatting, linting, strict typing, CI                             |
| Frontend   | Next.js App Router shell, design tokens, responsive map-first layout                            |
| Map        | MapLibre GL with configurable centre/zoom/style; loading, failure and WebGL-absent states       |
| Backend    | FastAPI with validated configuration, structured logging, request correlation, sanitised errors |
| Health     | `GET /api/v1/health/live` and `GET /api/v1/health/ready`                                        |
| Database   | PostgreSQL 17 + PostGIS 3.5, named volume, Alembic baseline                                     |
| Contracts  | Pydantic → OpenAPI → TypeScript, with a CI drift check                                          |
| Docker     | Multi-stage images, non-root users, health checks, migrate-on-start                             |
| Tests      | Backend unit + PostGIS integration; frontend unit; Playwright e2e with axe                      |
| Docs       | PRD, phases, architecture, ADRs, licensing, threat model, setup, testing                        |

**Explicitly does not exist**

- No routing of any kind. No pedestrian graph. No OSM ingestion.
- No origin/destination search or geocoding.
- No mobility profiles affecting anything.
- No elevation data, no imagery, no user reports.
- No machine learning, trained or otherwise.
- No accounts, no authentication, no personal data.
- No deployment. Local only.

**Done when.** All quality gates pass, the stack starts from a clean checkout,
and the interface states plainly that routing and ML do not exist.

---

## Phase 0.5 — Geospatial data foundation ✅ _(B01)_

**Goal.** A real pedestrian graph for Waterloo in PostGIS, queryable but not yet
routed over. Delivered together with Phase 1 rather than as a separate release.

**Delivered**

| Area       | What exists                                                                       |
| ---------- | --------------------------------------------------------------------------------- |
| Schema     | Pilot regions, dataset versions, ingestion runs, graph nodes and edges            |
| Versioning | A dataset is immutable once activated; ingestion writes a new version and swaps   |
| Ingestion  | `pathable ingest osm` (Overpass) and `pathable ingest pbf` (local extract)        |
| Real data  | 155,714 nodes · 180,554 segments · 3,363.7 km, live since 2026-08-17              |
| Elevation  | NRCan HRDEM 1 m LiDAR, sampled per node with full provenance                      |
| Normalise  | OSM tags → deterministic attributes, with `unknown` as the default everywhere     |
| Validation | Structured findings; errors block activation, warnings do not                     |
| Checksums  | Deterministic over network content, so "has this actually changed?" is answerable |
| Fixture    | A deterministic synthetic network in its own region, for tests and development    |

**Still does not exist.**

- Municipal open data beyond OpenStreetMap.
- A bounding-box graph inspection endpoint.
- **Per-element edit times.** Evidence freshness is currently a dataset-level
  fact — one source timestamp for the whole extract — so the product cannot yet
  say that a particular crossing was last surveyed four years ago.
- **Anything outside the pilot bounding box.** Rim Park, for one, sits in a
  separate 1,887-node component because its connection to the network leaves the
  box and was clipped. Journeys to it correctly return no route.

**What the real data turned out to be.** Measured on the live dataset, not
estimated — see [`docs/evidence/`](../evidence/README.md):

| Category                  | Recorded on                           |
| ------------------------- | ------------------------------------- |
| Surface                   | 55.8% of segments                     |
| Crossing type             | 99.0% of crossings                    |
| Tactile paving            | 46.5% of crossings                    |
| Kerb                      | 41.2% of crossings                    |
| Width                     | 4.5% of segments                      |
| Smoothness                | 2.0% of segments                      |
| Gradient (OSM `incline`)  | **0.03%** of segments — 46 of 180,554 |
| Gradient (from elevation) | 53.8% of segments                     |

That gradient row is why elevation was a gate requirement rather than an
enhancement: without a terrain model the product was silent about slope across
effectively the entire network.

---

## Phase 1 — Route comparison ✅ _(B01)_

**Goal.** The core journey works end to end for Waterloo.

**Delivered**

| Area        | What exists                                                                         |
| ----------- | ----------------------------------------------------------------------------------- |
| Selection   | Click the map to set a start and an end; optional place search                      |
| Profiles    | Wheelchair, walker, crutches, stroller, reduced mobility, and narrow custom         |
| Routing     | Shortest walking route and an accessibility-aware route from one engine             |
| Algorithms  | Dijkstra as the correctness baseline, A\* alongside it, proven to agree on cost     |
| Snapping    | To the nearest point _along_ a segment the profile can actually use                 |
| Cost model  | Hard constraints vs penalties, in effective metres — see ADR 0008                   |
| Explanation | Evidence-derived: each statement names something on the route it avoided            |
| Uncertainty | Per-category: "Surface data is missing for 38% of this route", never one score      |
| Provenance  | A gradient says whether a mapper recorded it or a terrain model inferred it         |
| No route    | A profile with no possible route still shows the shortest route and what blocked it |
| Comparison  | Drawn on the map _and_ written out, so the map is never the only way to read it     |

**Still does not exist.**

- **Machine learning.** The cost function is deterministic and rule-based, and
  every route response says so in `ml_predictions_used: false`.
- Turn-by-turn directions. PathAble compares journeys; it does not navigate.
- Turn restrictions, and pedestrian one-ways beyond what OSM tags state. Waterloo
  happens to contain none at all, so this is untested on real data.
- Validation of the cost weights against how people using these mobility aids
  actually travel. The weights are engineering judgement, and taking this beyond
  a pilot requires that validation.

**Definition of done.** For a fixed set of Waterloo pairs, differences between
the two routes are explainable and verifiable on the ground.

_Explainability is delivered and now measured._ Twenty real journeys were routed
under both the standard and wheelchair profiles: 18 produced a different route,
1 has no route at all, and every difference is attributed to something the route
avoided. Median detour was 86.1 m across the 18 that change, 83.8 m across all
19 routable journeys. (An earlier revision of this paragraph said 70 m; that
figure was never in the corpus and is corrected here.) Full results in
[`docs/evidence/waterloo-routes.json`](../evidence/waterloo-routes.json).

_On-the-ground verification has still not been performed._ Route geometry has
been inspected against the source data — which is how the `foot=no` snapping bug
was found — but nobody has walked these routes.

---

## Phase 2 — Evidence and imagery _(licensing gate)_

**Goal.** Enrich the graph with evidence beyond OSM tags.

- Validated user barrier reports, storable without identifying the reporter.
- Conflict resolution between reports, OSM, and municipal data.
- Data freshness and decay: a two-year-old observation is not a current fact.
- **Imagery ingestion, contingent on an explicit licensing review.** No imagery
  source has been selected. Street-level imagery licences differ sharply in what
  they permit for derived datasets and model training, and the decision requires
  founder approval before any ingestion is written.

**Still does not exist.** Trained models.

---

## Phase 3 — Learned prediction

**Goal.** The first genuine machine learning in the product.

- Versioned, labelled dataset with documented annotation guidance.
- Geographic hold-out evaluation — never a random split, which leaks across
  adjacent street segments.
- Model predicting accessibility features not directly observed, with calibrated
  confidence.
- Predictions stored separately from observed facts, with model version attached.
- Router consumes predictions **and** their uncertainty.
- Published metrics: precision, recall, F1, calibration, latency, failure cases.
- A documented rollback path to Phase 1's deterministic behaviour.

Only on completion of all of the above may PathAble describe itself as
ML-driven. See
[`../architecture/FUTURE_ML_ARCHITECTURE.md`](../architecture/FUTURE_ML_ARCHITECTURE.md).

---

## Phase 4 — Beyond the pilot

Additional regions, ingestion at scale, seasonal effects (snow clearance),
community validation workflows, and — only after evaluation with disabled users —
a public launch.

---

## Recruiting presentation sprint (PA-UX-02)

A short, self-contained sprint: make the engineering visible through the
interface, then publish a truthful showcase. It builds no new routing
capability and moves no phase gate. Status is recorded here rather than in
another roadmap.

| Card      | Deliverable                                                      | Status                                                                            |
| --------- | ---------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| PA-UX-02A | Map-led initial and comparison states, proven in the running app | **In progress** — candidate built, awaiting the founder's visual-direction review |
| PA-UX-02B | The accepted interface finished and merged                       | Blocked on A's acceptance                                                         |
| PA-UX-02C | Static showcase, refreshed demo, interview handoff               | Blocked on B                                                                      |

**Branch / worktree.** `feat/premium-map-experience`, PR #64 (draft), in
`../pathable-ai-wt/premium-map-experience`. Baseline for this sprint: `f099aaf`
(the PA-UX-01/01F candidate). Base `main` at `29a7749`.

**Preview.** Isolated envelope stack — API `8001`, database `5434`, web `3001`.
The dataset is `pathable-envelope-db-data` at migration `0005_kerb_tiers`,
155,714 nodes and 180,554 segments. See `docs/deployment/PRODUCTION_SMOKE.md`.

**Evidence.** `docs/evidence/FRONTEND_POLISH.md` — the PA-UX-02A revision entry
records what changed, at which viewports it was checked, and against which
build.

**Blocker.** One visual-direction review. The founder rejected the previous
composition, so the direction is confirmed on two functioning states before the
rest of the interface is finished.

**Next executable action.** On acceptance, start PA-UX-02B: finish the
remaining states (swap, clear, deep link, no-route, error, map-unavailable)
across devices, then merge through the normal workflow.

---

## Standing rules

1. **Never claim a capability before the phase that builds it.**
2. **Never present a prediction as an observation.**
3. **Never let missing data read as good news.**
4. **Never invent a metric.** If it was not measured, it does not get stated.
5. **Every phase keeps the pilot region configurable.**
