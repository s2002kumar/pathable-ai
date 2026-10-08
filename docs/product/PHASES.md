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

| Area        | What exists                                                                          |
| ----------- | ------------------------------------------------------------------------------------ |
| Selection   | Click the map, or search a Waterloo place, address or street (local index, ADR 0005) |
| Profiles    | Wheelchair, walker, crutches, stroller, reduced mobility, and narrow custom          |
| Routing     | Shortest walking route and an accessibility-aware route from one engine              |
| Algorithms  | Dijkstra as the correctness baseline, A\* alongside it, proven to agree on cost      |
| Snapping    | To the nearest point _along_ a segment the profile can actually use                  |
| Cost model  | Hard constraints vs penalties, in effective metres — see ADR 0008                    |
| Explanation | Evidence-derived: each statement names something on the route it avoided             |
| Uncertainty | Per-category: "Surface data is missing for 38% of this route", never one score       |
| Provenance  | A gradient says whether a mapper recorded it or a terrain model inferred it          |
| No route    | A profile with no possible route still shows the shortest route and what blocked it  |
| Comparison  | Drawn on the map _and_ written out, so the map is never the only way to read it      |

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

**Not verified here.** Live place-name search. The envelope API answered
`{"provider":"disabled","enabled":false}` by design at the time — no provider
was configured. _Superseded on 2026-10-07:_ search now answers from a local
place index; see "Place search and public documentation" below.

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

### PA-GEO-03 — Kitchener secondary-source freeze and empirical audit _(merged, PR #69)_

**Delivered** — [`KITCHENER_ACTIVE_TRANSPORT.md`](../architecture/KITCHENER_ACTIVE_TRANSPORT.md)

| Area           | What exists                                                                                                            |
| -------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Snapshot       | `pathable kitchener snapshot`: both City publications read by object id, checked request by request, frozen and hashed |
| Licence check  | The licence text served with the data is checked, sentence by sentence, against the terms relied on, on every run      |
| Normalization  | `pathable kitchener normalize`: one byte-reproducible GeoParquet 1.1.0 file, native and CRS84 geometry, no staff names |
| Classification | Value states that keep null, blank, unknown, not-applicable, default and non-default apart; evidence origin per field  |
| Profile        | `pathable kitchener audit`: DuckDB profile, study geography, descriptive overlap, adoption matrix, exit-gate figures   |
| Lineage sample | A deterministic, stratified 80-record sample for PA-GEO-04, reproducible from the snapshot and a documented seed       |
| Safety         | Reads PathAble in a `READ ONLY` transaction, from migration 0005 onward; no Kitchener field reaches routing            |

**What it measured** — see the `kitchener-*` files in
[`docs/evidence/`](../evidence/README.md):

- The City publishes one internal layer through two incomplete services: only
  active records, and the network links in only one of them.
- 11,835 active pedestrian records (686.0 km) intersect the pilot.
- 87.7% of them run within 2 m of an OSM pedestrian way along their whole length,
  and the City permits its data in OSM. Shared lineage is plausible and not
  established, so the geometry is treated as potentially shared-lineage until
  record-level history is inspected.
- 96.1% of sidewalks carry the template 1.5 m width and 98.5% the template
  CONCRETE.
- What is genuinely non-default is located: 6,888 curb-cut segments, 77 stairs
  and 133 railings.

**Decision: LIMITED GO** to PA-GEO-04, for curb cuts, stairs and structures,
non-default surfaces, dated trail condition and the network links' topology —
with OSM lineage settled first.

**Licensing gate.** The City's licence covers this research, and the City
separately permits its data in OpenStreetMap. OSMF LWG approval of the Kitchener
licence is not confirmed. Compatibility is reviewed again, as a founder decision,
before any Kitchener-derived value is incorporated into or redistributed with the
production OSM-derived routing database
([`DATA_SOURCES.md` §11](../licensing/DATA_SOURCES.md)).

**Still does not exist.**

- Any Kitchener value in routing, feasibility, cost, uncertainty or explanations.
- Matching, match thresholds, conflation, reconciliation, or any graph change.
- A cross-source canonical model; §10 of the audit document lists the
  requirements the real source supports.

### PA-GEO-04 — Kitchener ↔ OpenStreetMap geometry and lineage study _(merged, PR #70)_

**Delivered** — [`KITCHENER_OSM_LINEAGE.md`](../architecture/KITCHENER_OSM_LINEAGE.md)

| Area          | What exists                                                                                                                      |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Frozen OSM    | `pathable kitchener lineage-extract`: the routing dataset's own source PBF, SHA-checked, every way with a node in the box whole  |
| Candidates    | Every `highway` way within 25 m of each sampled record, with descriptive signals and the reasons it was generated                |
| Review page   | A static HTML page: an SVG map and tables per record, every label version side by side, a blind variant; nothing fetched         |
| History       | `pathable kitchener lineage-history`: ohsome element history and the planet changeset dump, never the editing API                |
| Imagery       | `pathable kitchener imagery-metadata`: which photographs Esri World Imagery showed over Kitchener, from Esri's archived metadata |
| Lineage rules | Conservative geometry and attribute lineage with a basis per finding; no numeric confidence; absence of a source never counts    |
| Labels        | 80 records labelled, 40 labelled again blind; definitions refined to version 2 and every revision recorded                       |

**What it measured** — see the `kitchener-geo04-*` files in
[`docs/evidence/`](../evidence/README.md). These are proportions of a stratified
sample, not of the City's inventory.

- **Correspondence:** 69 of 80 records have an obvious OSM counterpart, 7 an
  ambiguous one (corner pieces OSM collapses into a junction, and lanes it
  records as road tags), and 4 none.
- **Esri's imagery:** since 2016, its finest layer over Kitchener has been the
  City's and then the Region's own orthophotos.
- **Geometry lineage:** 63 of the 69 counterparts were shaped in OSM edits that
  recorded Esri imagery since then. Their lineage is possibly shared, and the
  City's geometry confirms nothing independently.
- **Attribute lineage:** OSM's kerb values at sampled curb cuts, and most of its
  surfaces, came from StreetComplete surveys.
- **What the City adds:** 6 of 10 sampled curb cuts and 9 of 22 comparable
  surfaces are the City's alone.
- **Repeat labels:** correspondence 40 of 40, topology 30 of 40 before its
  definition was fixed.

**Decision: LIMITED GO** to PA-GEO-05, for curb cuts against OSM kerb nodes,
stairs and structures, and non-default surfaces. The City's geometry goes
forward only as a matching input, never as evidence. The licensing gate of
PA-GEO-03 is unchanged.

**Still does not exist.**

- A matcher, weights, thresholds, or any accuracy figure.
- Any Kitchener value in routing, and any change to the graph.
- Labels by a person: both passes are one AI model's.

### PA-GEO-05 — Kitchener ↔ OpenStreetMap conflation benchmark _(merged, PR #71)_

**Delivered** — [`KITCHENER_CONFLATION.md`](../architecture/KITCHENER_CONFLATION.md)

| Area         | What exists                                                                                                                                      |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Candidates   | Every `highway` way within 25 m and kerb or crossing node within 10 m, sampled every metre: distance, position and angle                         |
| Held-out set | `pathable kitchener holdout`: 193 records in 14 strata, none from the development set, drawn before tuning with a seed bound to both inputs      |
| Labels       | Blind labels by five AI instances, a 60-record repeat by two more, frozen and committed before the matcher saw a held-out record                 |
| Matcher      | Interpretable rules, named thresholds tuned on the development set only, matched / ambiguous / unmatched, local extents, N:M, no confidence      |
| Benchmark    | `pathable kitchener benchmark`: baselines, ablations, per-class and per-stratum metrics, failure causes bound to the decisions by hash           |
| Artifact     | Four GeoParquet/Parquet tables: sources, matches, the City's assertions, both sides' values unresolved; byte-reproducible, never read by routing |

**What it measured**, once, on the held-out sample. The labels are AI labels, and
none of these is a population figure.

- **Overall:** 135 of 154 obvious counterparts got the exact element set. Pair
  precision was 0.955 and recall 0.905; the best single-signal baseline managed
  0.886 and 0.783.
- **Surfaces:** non-default surfaces were exact on 33 of 33.
- **Curb cuts:** kerb nodes matched on 23 of 24, with none false. The way sets
  were exact on only 30 of 44.
- **Abstention:** the matcher abstained on 7 records. The labellers could not
  name the elements on 26, and the matcher matched 21 of those.
- **Failures:** all 43 have a recorded cause. The largest are a class rule that
  excludes crossing ways from curb cuts, stairs OSM draws as plain footways, and
  short pieces at junctions.
- **Full pilot:** 11,547 records in about 80 s on one laptop, with a 1 MB
  artifact. Two runs were byte-identical.

**Decision: LIMITED GO** to PA-GEO-06, reconciliation research only, for three
classes:

- non-default surfaces;
- curb cuts through their kerb node;
- structures OSM tags as such.

Way-level curb-cut sets, short junction pieces and stairs on untagged footways
wait for a fixed matcher and a new holdout. For those stairs, the correspondence
rule is decided (§11 of the doc): a clear physical match to a plain footway is a
correspondence, and the stair is an assertion only the City makes. The licensing
gate stays closed.

**Still does not exist.**

- Any Kitchener value in routing, and any change to the graph.
- Labels by a person, or any field check.

### PA-GEO-06 — Provenance-aware accessibility evidence reconciliation _(merged, PR #72)_

**Delivered** —
[`ACCESSIBILITY_EVIDENCE_RECONCILIATION.md`](../architecture/ACCESSIBILITY_EVIDENCE_RECONCILIATION.md),
[ADR 0011](../adr/0011-accessibility-evidence-reconciliation.md)

| Area           | What exists                                                                                                                                    |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Evidence model | Sources, assertions (raw and normalized value, value state, evidence origin, typed dates), correspondences and reconciliations, each versioned |
| Input contract | PA-GEO-05's artifact read and hash-checked, never re-made; a gate per class; every exclusion with its reason                                   |
| Reconciliation | Per property per local target: agreement, compatible, conflict, incomparable, one source, unknown; no precedence, nothing resolved             |
| Lineage        | OSM's edit history under PA-GEO-04's rules, unchanged: attribute and geometry lineage apart, never a confidence                                |
| Isolation      | Every row `not_routing_eligible` with its blockers; static tests keep routing from the modules and the artifact                                |
| Commands       | `pathable kitchener reconcile-history` and `reconcile`: a byte-reproducible four-table artifact and an evidence summary                        |

**What it measured**, over every correspondence the gate accepts in the full
pilot. None of it is field-verified.

- **Surfaces:** 7,930 targets. OSM asserts a surface on 5,262; the City adds 943
  more, and 257 conflict, all kept open.
- **Curb ramps:** 1,648 City curb cuts beside an OSM kerb node are compatible,
  never agreement; only 13 add a ramp OSM lacks. 1,152 City curb cuts have no
  OSM kerb node and wait for matcher v2.
- **Structures:** 63 accepted, all already tagged in OSM. 45 City structures OSM
  does not tag wait for matcher v2.
- **Lineage:** 1,449 of 1,671 surface agreements are with OSM values whose edit
  states an unrelated source, mostly survey-app edits. Agreement stays
  agreement; it is not independence.
- **Freshness:** the City supplies no observation date; 2,891 OSM values carry
  one, most from 2021.
- **Run:** 10,523 reconciliations in under 25 s on one laptop; two runs were
  byte-identical.

**Decision: LIMITED GO** to routing-evidence integration research for surfaces
only. That is not integration: the founder licensing decision, validation and a
routing policy all come first.

**Matcher v2, planned here, built in PA-GEO-08.** It covers stairs and structures OSM
draws as plain footways, under the correspondence rule already decided;
way-level curb-cut correspondence; abstention for short pieces at junctions,
and better abstention generally; and a redesign of class compatibility. It needs
a new policy version and a new, untouched holdout: PA-GEO-05's is spent.

**Still does not exist.**

- Any Kitchener value in routing, and any change to the graph.
- A routing policy for multi-source evidence.
- Labels by a person, or any field check.

### PA-GEO-07 — Municipal surface evidence shadow-routing impact study _(merged, PR #81)_

**Delivered** —
[`SURFACE_SHADOW_ROUTING.md`](../architecture/SURFACE_SHADOW_ROUTING.md)

| Area        | What exists                                                                                                                                            |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Policy      | `surface-shadow-policy-v1`: OSM's surface is kept; a missing one is filled only from accepted City-only non-default surfaces covering 90% of a segment |
| Mapping     | City extents onto routing segments by their exact position along each OSM way; a short record cannot describe a long way                               |
| Shadow      | A copy of the loaded graph with only the filled segments replaced, built in memory from a read-only session; nothing is written back                   |
| Study       | The routing API's own comparison for seven profiles over a broad and a targeted corpus; every change categorized and explained from the cost model     |
| Sensitivity | What taking the City's side of the 257 conflicts would do, never a policy; provably unaffected pairs are not routed again                              |
| Command     | `pathable kitchener shadow-routing`: evidence JSON and a watermarked page of representative route changes                                              |

**What it measured.** An engineering counterfactual, not validation.

- **Coverage:** 888 City-only assertions would fill 1,926 segments, 23.96 km:
  1.8% of the graph's unknown surface metres.
- **Broad corpus**, 200 journeys: routes change for 5 of them (16
  journey-profile pairs, median move 5.5 m); most exposure is evidence or cost
  on an unchanged path.
- **Targeted corpus**, 49 journeys passing City evidence: routes change for 12
  (45 pairs).
- **Direction:** 59 of 61 changes come from City evidence making a path
  cheaper, the direction in which a wrong assertion does harm.
- **Hard changes:** 4, all for a custom profile that must avoid rough
  surfaces. No preset excludes a surface.
- **Dates:** every City assertion is dated only by capture, or not at all.
- **Isolation:** the database checksum and the loaded graph's fingerprints are
  unchanged; Dijkstra and A\* agree on every checked shadow pair.

**Decision: LIMITED GO** to the founder's licensing review and external
validation of a narrow queue of City surface records. That is not integration.

**Still does not exist.**

- Any Kitchener value in production routing, the API or the application.
- A licensing decision for combining Kitchener and OSM-derived data.
- Validation of any City surface, or a routing policy for municipal evidence.
- Matcher v2, then planned only (built since, in PA-GEO-08).

### PA-GEO-08 — Accessibility conflation matcher v2 and a new held-out benchmark _(PR #82)_

**Delivered** —
[`KITCHENER_MATCHER_V2.md`](../architecture/KITCHENER_MATCHER_V2.md)

| Area       | What exists                                                                                                                                                                     |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Benchmark  | A new 186-record held-out sample from records neither earlier sample holds, stratified on what v1 could not settle; PA-GEO-05's spent holdout is development data               |
| Labels     | Definitions version 2 (stairs on plain footways are correspondences; curb cuts cite the ways they follow); five blind AI labellers and a 60-record repeat                       |
| Matcher v2 | Deterministic rules with named provenance: crossings carry curb cuts, pieces must follow a way, corners and junctions abstain, kerb choice by topology, displaced steps abstain |
| Commands   | `matcher-v2-holdout`, `matcher-v2-review`, `matcher-v2-development-labels`, `matcher-v2-validate-labels`, `matcher-v2-collect-labels`, `matcher-v2-benchmark`                   |

**What it measured**, once, on 186 held-out records scored against AI labels:

- **Against v1:** 149 correct decisions against 116; 105 exact sets against 89;
  15 false attachments against 35; 7 matches where the labeller could not name
  the elements against 25. Pair precision 0.981 against 0.940.
- **Abstention** rises from 12.9% to 25.3%, almost all on records the labellers
  called ambiguous too.
- **Curb cuts improve most**: false attachments 30 to 12. Short pieces stop
  over-committing (7 to 1).
- **Stairs** rest on 17 records: six on plain footways, five matched exactly.
- **Pilot:** 803 of the 1,152 curb cuts PA-GEO-06 could not accept now have a
  local correspondence; 349 abstain at junctions.

**Decision: LIMITED GO** to reconciliation research for curb ramps without an
OSM kerb node, on conditions. Stairs are not established on six records.

**Still does not exist.**

- Any Kitchener value in routing, and any change to the graph.
- Reconciliation of the newly matched curb ramps or stairs.
- Labels by a person, or any field check.

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

**Still open.** A production tile provider (ADR 0005; geocoding was decided on
2026-10-07) — the dark Stitch basemap is a second style for that decision, and the dark
panel theme was not adopted with it. The name is corrected in the interface
only; these documents, the changelog and the README still say "PathAble AI" in
places, and a repository-wide rename was deliberately not part of 03B.

---

## Place search and public documentation (2026-10-07)

A small card after PA-UX-04. It adds no routing capability and moves no phase
gate.

**Place search.** The planner's fields looked searchable and were not: the only
provider was public Nominatim, off by default because its usage policy rules out
application traffic. Search now answers from a local place index read from the
same OpenStreetMap extract as the network ([ADR 0005](../adr/0005-map-and-geocoding-providers.md),
[KI-11](../development/KNOWN_ISSUES.md)): 5,232 places, 26,201 addresses and
1,792 streets for Waterloo, data as of 2026-08-16. Building it on the real
extract found faults the fixture had not — the campus missing, a street
missing, streets split by their sidewalks, a taxi stand ranked first — each now
a regression test. On the production-smoke stack a journey whose two ends were
chosen by search routes live
([`waterloo-place-search.json`](../evidence/waterloo-place-search.json)).

**Public documentation.** Interview coaching left the public tree. The
engineering review (formerly `PROJECT_DEFENSE.md`) and the demo reproduction
guide (formerly `DEMO_SCRIPT.md`) stay. The README leads with the product, the
comparison and the evidence, and says plainly what PathAble is not.

**Branch.** `feat/recruiter-readiness-search`, from `main` at `c091cf2`.

**Not verified here.** A manual screen-reader pass over the search results.
As-you-type suggestions do not exist, by design.

---

## Standing rules

1. **Never claim a capability before the phase that builds it.**
2. **Never present a prediction as an observation.**
3. **Never let missing data read as good news.**
4. **Never invent a metric.** If it was not measured, it does not get stated.
5. **Every phase keeps the pilot region configurable.**
