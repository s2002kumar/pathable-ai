# Phases

Each phase names what exists at the end of it, and — as importantly — what still
does not. The "does not exist" column is what keeps the product honest.

---

## Phase 0 — Foundation ✅ _(this batch: P0-A01)_

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

## Phase 0.5 — Geospatial data foundation _(P0-A02, next)_

**Goal.** A real pedestrian graph for Waterloo in PostGIS, queryable but not yet
routed over.

- Bounded OSM extract for the pilot region, with provenance and a fetch date.
- Pedestrian graph schema: nodes, edges, geometry, source tags.
- Idempotent, re-runnable ingestion with versioned snapshots.
- Spatial indexes and a documented query budget.
- Elevation attached to edges from an openly licensed DEM.
- Integration tests over real ingested data.
- API endpoint to inspect the graph for a bounding box.

**Still does not exist.** Routing, costs, profiles, ML.

---

## Phase 1 — Route comparison

**Goal.** The core journey works end to end for Waterloo.

- Origin/destination selection with an openly licensed geocoder.
- Mobility profiles as explicit hard constraints plus weights.
- Shortest pedestrian route.
- Accessibility-aware route from a documented, deterministic cost function.
- Side-by-side comparison stating the trade-off in distance and time.
- Per-segment explanation: what drove the choice, from which source, how old.
- Data coverage and uncertainty shown honestly, including "we do not know".
- A textual route description equivalent to the map view.

**Still does not exist.** Machine learning. The Phase 1 cost function is
deterministic and rule-based, and the interface will say so.

**Definition of done.** For a fixed set of Waterloo pairs, differences between
the two routes are explainable and verifiable on the ground.

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

## Standing rules

1. **Never claim a capability before the phase that builds it.**
2. **Never present a prediction as an observation.**
3. **Never let missing data read as good news.**
4. **Never invent a metric.** If it was not measured, it does not get stated.
5. **Every phase keeps the pilot region configurable.**
