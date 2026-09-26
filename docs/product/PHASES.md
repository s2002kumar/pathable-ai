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

| Area       | What exists                                                                                                                                                                            |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Schema     | Pilot regions, dataset versions, ingestion runs, graph nodes and edges                                                                                                                 |
| Versioning | Candidates are enriched, sealed and judged by route regression before a locked switch; sealed rows are frozen by the database; rollback ([ADR 0010](../adr/0010-dataset-lifecycle.md)) |
| Ingestion  | `pathable ingest osm` (Overpass) and `pathable ingest pbf` (local extract)                                                                                                             |
| Real data  | 155,714 nodes · 180,554 segments · 3,363.7 km, live since 2026-08-17                                                                                                                   |
| Elevation  | NRCan HRDEM 1 m LiDAR, sampled per node with full provenance                                                                                                                           |
| Normalise  | OSM tags → deterministic attributes, with `unknown` as the default everywhere                                                                                                          |
| Validation | Structured findings; errors block activation, warnings do not                                                                                                                          |
| Checksums  | Deterministic over network content, so "has this actually changed?" is answerable                                                                                                      |
| Fixture    | A deterministic synthetic network in its own region, for tests and development                                                                                                         |

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
| PA-UX-02A | Map-led initial and comparison states, proven in the running app | **Done** — interaction direction approved 2026-09-23; the finish was not approved |
| PA-UX-02B | The accepted interface finished and merged                       | **Done** — approved and merged through PR #64                                     |
| PA-UX-02C | Static showcase, refreshed demo, interview handoff               | Not started                                                                       |

**What was approved, exactly.** The founder approved the interaction direction
— Start → Destination → Travel profile → Compare → Explore why, with stronger
colour and a more refined map — and authorised building the complete
candidate. In their own words that "is not a claim that the finished visual
result has already been accepted": PA-UX-02B returned for one further visual
review, and the founder approved it for merging on 2026-09-26.

**Branch / worktree.** `feat/premium-map-experience`, PR #64, in
`../pathable-ai-wt/premium-map-experience`. Baseline for this sprint: `f099aaf`
(the PA-UX-01/01F candidate). Base `main` at `29a7749`.

**Preview.** Isolated envelope stack — API `8001`, database `5434`, web `3001`.
Open it at **`http://127.0.0.1:3001`**, not `localhost:3001`: Docker Desktop's
IPv6 proxy resets the connection on this host, and the browser does not fall
back. From that address the page reaches the API with no flags; the status
badge reads "API online". The dataset is `pathable-envelope-db-data` at
migration `0005_kerb_tiers`, 155,714 nodes and 180,554 segments. See
`docs/deployment/PRODUCTION_SMOKE.md`.

**Evidence.** `docs/evidence/FRONTEND_POLISH.md` — the PA-UX-02A revision entry
records what changed, at which viewports it was checked, and against which
build.

**Not verified here.** Live place-name search. The envelope API answers
`{"provider":"disabled","enabled":false}` by design — `GEOCODING_PROVIDER` is
unset — and choosing a provider is a founder decision ADR 0005 leaves open.
The search fields are covered by stubbed provider responses and degrade
honestly in the preview.

**Next executable action.** PA-UX-02C, when it is scheduled.

---

## Geospatial data lane (PA-GEO)

A research lane: can PathAble combine pedestrian datasets from more than one
source, keep provenance and uncertainty, and show with numbers whether the result
carries better accessibility information than OpenStreetMap alone? It moves no
phase gate and changes no route until a card says otherwise.

### PA-GEO-01 — Overture release intake and OSM/GERS identity evidence _(merged, PR #66)_

**Delivered**

| Area            | What exists                                                                                                  |
| --------------- | ------------------------------------------------------------------------------------------------------------ |
| Release intake  | `pathable overture extract`: release and schema from Overture's STAC catalog, column contract, bounded reads |
| Reproducibility | A manifest per run: files, ETags, S3 expiry, query and parameters, bytes received, output SHA-256            |
| Linkage         | `pathable overture link`: identity, cardinality with linear ranges, version and edit-time status             |
| Independence    | Which accessibility attributes, if any, Overture carries from a source other than OSM                        |
| Safety          | Reads PathAble in a `READ ONLY` transaction; writes nothing, activates nothing                               |

**What it measured** — see [`OVERTURE_GERS.md`](../architecture/OVERTURE_GERS.md)
and the `waterloo-overture-*` files in [`docs/evidence/`](../evidence/README.md):
Overture cites 37,604 of PathAble's 37,976 Waterloo ways; the relationship is
many-to-many; version status needs evidence PathAble does not store; and in
Waterloo, Overture adds **no** accessibility evidence independent of OSM for the
attributes examined.

**Still does not exist.**

- Any synchronization with Overture, or any Overture data in the routing graph.
- A second, independent pedestrian source, a source-independent evidence model,
  conflation, or any coverage improvement.

### PA-GEO-02 — Dataset lifecycle integrity and OSM version provenance _(merged, PR #68)_

**Delivered** — [ADR 0010](../adr/0010-dataset-lifecycle.md)

| Area            | What exists                                                                                                  |
| --------------- | ------------------------------------------------------------------------------------------------------------ |
| Candidates      | Ingestion writes a draft; elevation goes only into a draft; sealing validates the stored rows                |
| Immutability    | Migration 0006 triggers: a sealed dataset's rows and defining columns cannot change; evidence is append-only |
| Content hash    | Content checksum v2 over the stored, enriched rows; lifecycle state and provenance excluded                  |
| Activation gate | Stored route regression (20 journeys × 6 profiles) against the live dataset; a reason when routes differ     |
| Rollback        | `datasets rollback` re-hashes and reactivates a retired dataset; never rebuilds                              |
| History         | `datasets history`: every activation and rollback, with its run, acceptance or reason                        |
| OSM provenance  | Node and way version and edit time, and each way's latest member edit, from PBF extracts                     |

**What it measured** — see
[`waterloo-dataset-lifecycle.json`](../evidence/waterloo-dataset-lifecycle.json):
a Waterloo candidate rebuilt from the same extract and HRDEM mosaic reproduced
the live dataset's content checksum exactly and routed all 120 comparisons
identically; activation switched in 33.8 ms and rollback in 31.7 ms after an
11.56 s re-hash.

**Still does not exist.**

- Any use of per-element edit times in routing, the coverage report or the UI.
- Synchronization, incremental graph updates, multi-source conflation, or
  external-source enrichment.
- Zero-downtime deployment. The switch is short and measured; a running API
  picks up a new dataset on its next request, which has not been load-tested.

---

## Stitch Route Planner integration (PA-UX-03)

The founder approved a Stitch design — the Route Planner screen of Stitch
project `17093004989141973251` — as the visual and product target, after a
capability audit of every feature it shows. It is its own card rather than more
of PA-UX-02, because making it truthful needs backend fixes and additions to the
API contract, and PA-UX-02 builds no routing capability.

| Card      | Deliverable                                                                                       | Status                           |
| --------- | ------------------------------------------------------------------------------------------------- | -------------------------------- |
| PA-UX-03A | Correctness and API foundation: defects D1–D8, gradient summary, evidence basis, comparable times | **Done** — merged through PR #65 |
| PA-UX-03B | The Stitch frontend, on that foundation                                                           | **Done** — merged through PR #67 |

**Founder decisions (2026-09-24).** The product is named PathAble — not
WayPoint, not "PathAble AI", and never "AI-powered". Only the five real
profiles; the design's "Standard" and "Gentle" do not ship. The custom
maximum-slope control defaults to Off. No aggregate "% verified" or "% known"
figure — per-category recorded and estimated coverage only. PathAble is a route
planner, not turn-by-turn navigation. Unlike time estimates are never presented
as comparable. A detour's explanation names every constraint responsible, not
stairs alone. The uncommitted pan-pad work on `feat/premium-map-experience` was
discarded; a clean Fit/Recenter Route action belongs to 03B.

**PA-UX-03A.** No route moved: `routing_policy_version` stays 2, and the twenty
corpus journeys return identical routes, distances and nodes expanded before and
after (dataset `51e75f78`, 2026-09-25). What changed is what the API says about
a route — see the changelog — and the four places the existing interface
misstated it (D1, D5, D6, D7). The founder approved 03A and 03B for merging on
2026-09-26.

**Branch / worktree.** `feat/stitch-route-planner` in
`../pathable-ai-wt/stitch-route-planner`, branched from `feat/premium-map-experience`
at `01e26da`; its PR was stacked on PR #64 and retargeted to `main` when #64
merged.

**PA-UX-03B.** The Stitch information architecture on the 03A contract, in the
existing light token system. What a person sees first is the verdict, the two
routes as a keyboard radio group, the reason that decided the route and how much
of it the map is silent about; every statement below carries the label of what it
rests on — Recorded, Estimated from elevation, Not recorded, Your profile rule.
A route the chosen profile cannot use gets no travel time ("Time unavailable for
this profile"), read from `excluded_by_profile`, never from a stairway count.
Coverage is per category against its own denominator, kerbs per crossing, with no
total. Recorded stairways are always drawn; what the profile rules out and the
steepest climb are pinned to the map as text. Profile rules come from
`/routes/profiles`; the uphill limit is off until the traveller sets it, and is
sent exactly as typed as a custom profile the API builds. The interface is named
PathAble. Routing is untouched: no backend file changed. Evidence:
`docs/evidence/FRONTEND_POLISH.md`, "The Stitch route planner (PA-UX-03B)".

**Branch / worktree (03B).** `feat/stitch-route-planner-ui` in
`../pathable-ai-wt/stitch-route-planner-ui`, from the 03A head after it took PR
#64's final commit; its PR was stacked on PR #65 and retargeted to `main` when
#65 merged.

**Still open.** A production geocoder and a production tile provider (ADR 0005)
— the dark Stitch basemap is a second style for that decision, and the dark
panel theme was not adopted with it. The name is corrected in the interface
only; these documents, the changelog and the README still say "PathAble AI" in
places, and a repository-wide rename was deliberately not part of 03B.

---

## Standing rules

1. **Never claim a capability before the phase that builds it.**
2. **Never present a prediction as an observation.**
3. **Never let missing data read as good news.**
4. **Never invent a metric.** If it was not measured, it does not get stated.
5. **Every phase keeps the pilot region configurable.**
