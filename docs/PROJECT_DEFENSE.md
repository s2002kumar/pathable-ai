# Defending this project

Written to be interrogated. Every section says what was built, why that way, what it cost, and where it stops.
If an interviewer pushes on any claim here, the answer should be a file, a command or a number — never a
adjective. Where something is not known or not done, this document says so rather than reaching for a phrase
that sounds like it was.

The companion documents are the [claims ledger](CLAIMS_LEDGER.md), which fixes the exact wording that may be
used for each claim, and the [evidence index](evidence/README.md), which holds the numbers.

---

## 1. What the product is for

Somebody who uses a wheelchair, pushes a pram, or walks with a stick does not want the shortest route. They want
a route they can physically complete, and — more than that — they want to know what is _unknown_ about it before
they leave the house. Existing pedestrian routers optimise distance and are silent about the rest.

PathAble compares the two routes side by side and explains the difference from recorded evidence. Its hardest
design constraint is not the routing: it is that **an absence of data must never read as a clearance**. A router
that quietly treats "nobody recorded a kerb here" as "there is no kerb here" will eventually strand somebody at
an unramped kerb after dark. Everything below follows from taking that seriously.

**Pilot region:** Waterloo, Ontario — configuration, not an assumption ([ADR 0006](adr/0006-configurable-waterloo-pilot.md)).

---

## 2. Architecture, and why it is this shape

A modular monolith ([ADR 0002](adr/0002-modular-monolith.md)): a Next.js frontend, a FastAPI service, PostGIS,
and an in-memory graph. Not microservices — there is one deployable unit's worth of work here, and the operational
cost of splitting it would buy nothing measurable.

The contract runs one way only. Pydantic response models generate `openapi.json`, which generates the frontend's
TypeScript types, and CI fails if the committed output drifts ([ADR 0003](adr/0003-openapi-contract-source.md)).
This means the frontend cannot silently disagree with the backend about a field, and it means adding an API field
is a deliberate act with a regenerated artefact in the diff.

**Why PostGIS and not a graph database** ([ADR 0004](adr/0004-postgis-and-runtime-graph.md)): the data is both
spatial (nearest-segment snapping, bounding boxes, geodesic length) and relational (edges reference nodes,
datasets reference regions, everything references provenance). One store answers both. A graph database would
have handled traversal well and everything else badly, and traversal is the part that does not need a database —
it happens in memory, in the application, over a graph small enough to hold.

---

## 3. The data pipeline

**Ingestion, two paths, one normaliser.** `pathable ingest pbf` reads a local Geofabrik extract with pyosmium;
`pathable ingest osm` reads Overpass. Both feed the _identical_ normalisation functions, so a route cannot change
because of how the data arrived. The PBF path is the one used for the live dataset: Overpass is a donated service
with strict rate limits, and a city-wide unsimplified query is impractically slow.

**Normalisation is where the honesty is enforced.** OSM tags become typed attributes with `unknown` as a
first-class value, never a default of `false`. `surface=asphalt` becomes `SurfaceClass.PAVED`; an absent
`surface` becomes `unknown` and stays that way through the cost model and into the response.

**Elevation.** NRCan HRDEM, 1 m LiDAR bare-earth, sampled per node. Chosen by measurement, not availability: over
50 m segments a 30 m global model has RMSE 4.06 percentage points against a true median grade of 1.78% — the
error exceeds the signal. The 898 GB mosaic is never downloaded; it is a cloud-optimised GeoTIFF read by byte
range. `GDAL_DISABLE_READDIR_ON_OPEN` is not optional there: without it GDAL lists the entire bucket prefix before
reading a byte.

A derived gradient is kept in a _separate column_ from any OSM-recorded `incline` and is never allowed to
overwrite it. HRDEM describes the ground, not the path laid on it, so it cannot see a ramp, a step or a bridge
deck — and the interface says which source a gradient came from.

**Coverage, measured rather than assumed.** Surface 55.8% of segments; crossing type 99.0% of crossings; kerb
41.2%; width 4.5%; smoothness 2.0%; OSM `incline` **0.03%** — 46 segments out of 180,554. That last number is why
elevation was a gate requirement rather than an enhancement.

---

## 4. Dataset versioning and activation

Ingestion never edits an activated dataset version. It writes a **new** version, validates it, and swaps
activation inside one transaction; a failed import cannot degrade the live network, and a database constraint —
not application discipline — enforces that only one dataset per region is active.

This is what makes the in-memory cache safe — with one exception still open: elevation sampling writes into an
existing dataset, the live one by default, so a running API keeps its pre-elevation graph until it restarts
([KI-10](development/KNOWN_ISSUES.md)). The graph is keyed by dataset version id, so a new dataset is a new key
and, apart from that exception, a cached graph cannot go stale. It also makes "what answered this request?" answerable — every route
response carries the dataset id, its checksum, and the upstream publication timestamp.

**Checksums are over content**, computed deterministically from the network payload, so "has this actually
changed?" has an answer that survives re-ingestion.

---

## 5. What PostGIS does, and what it does not

It does: storage, spatial indexing (GiST on geometry), `ST_X`/`ST_Y`/`ST_AsBinary` at load time, bounding-box and
containment checks during ingestion validation, and the readiness probe's extension check.

It does **not** do traversal. There is no `pgRouting`. Routing happens in the application over an in-memory
graph, because the graph is small enough to hold, the traversal is iterative, and a round trip per expanded node
would dominate everything else.

---

## 6. Graph representation, and directed versus physical edges

180,554 **physical segments** become 361,108 **directed edges**. A two-way footpath is one segment and two
directed edges; a one-way segment contributes one. Keeping both counts distinct matters in three places: the
evidence files report segments (what the map contains), the routing graph reports directed edges (what the search
traverses), and a bug that conflated them would silently halve or double either.

The structure is a NetworkX `MultiDiGraph` keyed by OSM node id — multi, because two nodes can be joined by more
than one distinct segment, and collapsing those would discard the very alternative the accessibility comparison
exists to find.

**Pedestrian directionality is not vehicle directionality.** Waterloo's data contains no `oneway:foot`, no
`conveying` and no `foot:forward`/`foot:backward` at all, so the correct number of pedestrian one-ways in the
region is zero. The only thing the directionality work does here is decline to apply **13,579** vehicle
restrictions to people on foot — which is exactly the kind of borrowed assumption that would make a route wrong.

---

## 7. Snapping

A user clicks a point that is not on the network. Snapping attaches it to the nearest point _along_ a segment the
chosen profile can actually use — not the nearest node, and not the nearest segment regardless of profile. A
wheelchair request that snapped onto a flight of steps would begin the journey with the obstacle it was asked to
avoid.

Every evaluation result records how far the point moved, so a case whose endpoint landed 60 m away is visible as
such rather than folded into the distance. The interface says so too: one of the committed screenshots exists
specifically to show the route starting somewhere other than where the user clicked.

---

## 8. Routing: Dijkstra, A\*, and an honest result

Dijkstra is the correctness baseline. A\* runs alongside it with a geodesic-distance heuristic, and the two are
proven to agree on optimal cost across the corpus.

**A\* is not faster here, and the repository says so.** It expands 1,970 nodes at the median against Dijkstra's
7,409 — a 3.8× reduction in work — and comes out at 195 ms against 213 ms at p50. The heuristic's per-node cost
very nearly cancels the saving at this scale in this implementation. Reporting that as a performance win would
have been the easy thing; the number is in
[`waterloo-performance.json`](evidence/waterloo-performance.json) either way.

That result is worth having: it says the bottleneck is not the search.

---

## 9. The accessibility cost model

Fully specified in [ADR 0008](adr/0008-accessibility-cost-model.md). Two mechanisms, deliberately separated:

- **Hard constraints** remove an edge from consideration entirely — a wheelchair profile cannot traverse steps.
- **Penalties** inflate an edge's cost in _effective metres_, a unit chosen so the trade-off is legible: "this
  profile will walk 40 extra metres to avoid this" is a sentence a person can argue with.

The campus journey shows both: the 4 stairways are a hard constraint, and the resulting route is 287.4 m of
shortest path turned into 354.1 m of effective 601.0 m once penalties are counted.

**Unknown data carries a penalty, not a pass.** An unrecorded surface is treated as a risk, which is the only
setting consistent with the product's central claim. That penalty was **ablated** rather than assumed: removing
it changes 3 of 20 corpus routes — so it is not saturated — but removing _only_ the missing-gradient term changes
the same 3, meaning one term is currently doing all the work. That is recorded in the ADR as a known weakness,
not smoothed over.

**The weights are engineering judgement.** They have not been validated against how people using these mobility
aids actually travel. Taking this beyond a pilot requires that validation, and no amount of testing substitutes
for it.

---

## 10. Deterministic explanations

Each explanation names something concrete on the route that was avoided, with the evidence it came from —
`avoids_stairs` carries the stairway count, the step count, and the segment identifiers. The frontend does not
paraphrase; it sorts the statements by provenance and renders them.

Uncertainty is reported **per category**, never as one score. "Surface data is missing for 38% of this route" is
actionable. A single combined figure is not: two routes missing completely different things produce the same
number and are completely different journeys. That change came out of a real failure — see §16.

There is deliberately **no accessibility score**. A region with excellent kerb data and no surface data would
average to "moderate", which describes nothing.

---

## 11. Caching and readiness

The graph is loaded once per dataset version into an LRU cache of capacity 2, behind an `asyncio.Lock` so two
simultaneous first requests cannot each build it.

Loading is not free — see §14 — so `GRAPH_PRELOAD_REGIONS` makes it part of startup and holds `/health/ready` at
503 until the configured region is routable. Liveness answers immediately, because an orchestrator that sees no
HTTP response for twenty seconds concludes the process is hung and would be right to restart it.

The readiness contract has three checks: PostgreSQL, PostGIS, and the graph. A region with no active dataset, or
a preload that raised, leaves the instance **permanently** not ready with a short safe reason — the exception
type, never its message, because the endpoint is unauthenticated and driver messages carry hostnames.

---

## 12. Route-quality evaluation

Twenty real Waterloo journeys, fixed **before** any route was computed, spanning campus paths, arterial crossings,
a ravine footbridge, a rail corridor, and distances from two blocks to a few kilometres. Every one is reported
whatever it did.

Results: 18 of 20 route differently under a wheelchair profile, 1 has no route at all, median detour 86.1 m
across the 18 that change (83.8 m across all 19 routable journeys). The
no-route case is real and correct — Rim Park sits in a separate 1,887-node component because its connection to
the network leaves the pilot bounding box and was clipped.

`pathable evaluate --region waterloo --algorithms --ablate` regenerates the whole corpus, the Dijkstra/A\*
comparison and the ablation in one command.

---

## 13. Geometry inspection, and why it exists

Route geometry is checked against itself: continuity between consecutive segments, seams, drawn length against
reported length, and profile violations. This caught a bug nothing else would have — see §16.

**Nobody has walked these routes.** On-the-ground verification has not been performed, and the evidence index
says so.

---

## 14. The graph-load optimisation

Loading the Waterloo dataset was the clearest scaling limit in the system. Profiling first, then one change.

The measured result, best run to best run on the same machine the same afternoon:

|                   | Before     | After               |
| ----------------- | ---------- | ------------------- |
| Load, median of 3 | 46.83 s    | **22.14 s**         |
| Peak Python heap  | 1,381.3 MB | **700.7 MB** (−49%) |

The cause was SQLAlchemy building a full ORM entity per edge — 147.5 s against 5.0 s for the same rows as narrow
Core columns, with an identity map and change tracking a read-only graph never uses. Geometry moved from WKT to
WKB (2.5× faster to parse, a third of the bytes), and `raw_tags` — a JSONB blob of 765,290 OSM tags across the
region, from which the runtime read exactly one key — is no longer loaded at all; the name is extracted in SQL.

**Proving it changed nothing** was the harder half: SHA-256 fingerprints over every node position and every
segment (id, endpoints, length, name, both foot flags, WKB geometry, every feature field) are identical before
and after, and all 20 corpus journeys return identical routes, detours and explanations.

`pathable benchmark load --region waterloo` is committed, so the numbers are reproducible by someone else. It
records machine conditions and refuses to average in a run where the process was mostly not running.

---

## 15. Memory, cold start, and what is still wrong

[KI-6](development/KNOWN_ISSUES.md) is open. In the production container, one worker:

- is routable **18.7 s** after `compose up` (median; graph preload 14.6 s of that),
- holds **997 MB** resident with a **1,064 MB** lifetime peak,
- and **duplicates the graph per worker** — two workers measured 2.04 GB resident, 2.17 GB peak.

The remaining cost is NetworkX edge insertion and Python object construction: 180,554 `EdgeFeatures` and 361,108
`DirectedEdge` instances. Halving it again needs a different in-memory representation — a struct-of-arrays layout,
or a serialised graph cached on disk — which is a real architectural change and wants its own measurement rather
than being bundled into a query fix.

A 1 GB container limit _survived_ two cold starts with 6% headroom. That is the argument against sizing at the
observed peak: it works on the day it is measured and fails on the day a second region is added.

---

## 16. Three things that went wrong

### 16a. The route that was drawn backwards

**Symptom.** 12 of 19 routable journeys drew a discontinuous polyline — gaps of up to 93 m — while the _reported_
distance stayed plausible throughout. One route ended 15 m from the point the user had chosen.

**Investigation.** Nothing in the numbers looked wrong, which is why no existing test caught it. The geometry
inspection was written specifically to compare the drawn line against itself: does each segment's last coordinate
equal the next segment's first, and does the drawn length match the reported length?

**Evidence.** [`waterloo-geometry-inspection.json`](evidence/waterloo-geometry-inspection.json), which recorded 12
failures on its first run and 0 after the fix.

**Root cause.** A snap-split segment was stored reversed _and also_ marked reversed, so it was flipped twice and
drawn backwards. The distance was computed from the segment's own length, which is direction-independent — hence
a correct number attached to a wrong line.

**Fix.** Narrow: correct the double flip at the point where a snapped segment is emitted.

**Regression protection.** The geometry inspection runs over the whole corpus and asserts continuity, endpoint
agreement and drawn-versus-reported length. All 19 pass; the screenshots were re-captured afterwards.

**Remaining limitation.** It checks geometry against itself, not against the ground. A route can be perfectly
continuous and still wrong about the world.

### 16b. The loader that spent a gigabyte on objects it threw away

**Symptom.** Loading the Waterloo graph took ~47 s and peaked at 1.38 GB of Python heap. Warm request latency was
fine (p50 195 ms), so this only hurt at startup — but it meant a cold instance could not serve a route for the
better part of a minute, and two cached datasets cost 2.6 GB.

**Investigation.** Profiled before changing anything. The load decomposes into the database read, NetworkX
insertion, and Python object construction. Timing the read in isolation gave 147.5 s for mapped entities against
5.0 s for the same rows as narrow Core columns.

**Evidence.** [`waterloo-graph-load-before.json`](evidence/waterloo-graph-load-before.json) and
[`waterloo-graph-load.json`](evidence/waterloo-graph-load.json), both produced by the committed
`pathable benchmark load`.

**Root cause.** The loader selected the mapped `GraphEdge` entity. SQLAlchemy built a full ORM object per edge
with identity map and change tracking, for a graph that is read-only for its entire life — plus a JSONB tag blob
that was loaded in full to read one key from it.

**Fix.** Select 34 named Core columns plus `raw_tags->>'name'` and `ST_AsBinary(geometry)`. No change to the
graph structure, the cost model, or any route.

**Regression protection.** Node and segment SHA-256 fingerprints, asserted identical before and after; the
20-journey corpus asserted identical with timing stripped; a regression test pinning that a segment `name` is
taken only when the tag is a JSON string, because the SQL extraction would otherwise render a number or an
OSMnx-merged list as text where the old loader dropped them.

**Remaining limitation.** 997 MB resident is still the dominant hosting cost, and the fix does not touch it.

### 16c. The migration that quietly dropped a constraint

**Symptom.** An autogenerated Alembic migration on an unmerged branch ended with
`op.drop_constraint('ck_graph_edges_edge_incline_direction', 'graph_edges')` — under a banner reading "auto
generated by Alembic — please adjust".

**Investigation.** Why would a migration adding perception tables drop a check on the map-fact table? Because the
check had been added by an earlier migration but never declared on the ORM model, so autogenerate saw a
constraint the metadata did not know about and proposed removing it.

**Evidence.** The constraint exists in `0005_kerb_tiers` and is absent from `GraphEdge.__table_args__`, which
lists `_enum_check` for six other columns.

**Root cause.** Divergence between hand-written DDL and ORM metadata — the failure mode autogenerate has by
design.

**Fix.** None applied: the finding was that this must not reach `main`, and the branch was left alone. It is
recorded so the same diff is not merged by someone who trusts the generator.

**Regression protection.** The managed-restore script now asserts the constraint exists by name after every
bootstrap, and every restore verifies it.

**Remaining limitation.** The general problem — autogenerate proposing to drop things the ORM does not declare —
is still there. The durable fix is to declare every constraint on the model.

---

## 17. Test strategy

Protect behaviour, not coverage percentages.

- **Unit tests** cover what would be expensive to get wrong: feature normalisation, unknown-versus-false, cost
  functions, hard constraints, dataset lifecycle, the graph warmup state machine.
- **Integration tests run against real PostgreSQL/PostGIS**, in a throwaway database created and dropped per
  test. Migrations, spatial behaviour and the dataset lifecycle are only meaningfully testable against the real
  thing; mocking them would test the mock.
- **Browser tests come in two flavours.** The default suite stubs the API at the network layer, which makes it
  deterministic. The full-stack suite stubs _nothing_ — browser to Next.js to FastAPI to PostGIS — because a
  deterministic suite proves the frontend is self-consistent, not that the two halves agree.
- **Accessibility is asserted, not assumed**: axe runs over the real pages.
- **A regression test names the bug it exists for.**

Counts are reported per suite. Adding them together would produce a bigger number describing less, since the
suites deliberately overlap.

---

## 18. Production container design

Multi-stage builds; runtime images carry no build tools, no dev dependencies, and no package manager — pip is
removed from the API image, npm and corepack from the web image, which also means a development server cannot be
started in the web container. Both run as uid 10001. No environment file and no credential is baked in; every
secret arrives at runtime.

The API entrypoint waits for the database with a bounded retry budget, runs `alembic upgrade head`, then `exec`s
the server so it becomes PID 1 and receives SIGTERM directly. Migration failure is a **startup** failure: under
`set -e`, a bad revision ends the container before it ever binds a port, verified by pointing the database at a
nonexistent revision and watching it exit 255 in a restart loop while liveness never answered.

`ENVIRONMENT=production` makes the settings model refuse to start without an explicit CORS origin list, JSON logs
and a database URL, reporting every problem at once. Credentialed CORS is structurally impossible. Interactive
docs are disabled.

---

## 19. The proposed deployment architecture

[ADR 0009](adr/0009-deployment-architecture.md), sized from the container measurements: DigitalOcean App Platform
in Toronto, one 2 GiB API container with one worker, one 512 MiB frontend, one 1 GiB Managed PostgreSQL with
PostGIS, the provider's hostname, single node throughout. **USD 45.15 / CAD 62.61 a month.**

**It is a proposal. Nothing is deployed, no account exists, nothing has been purchased.** Four candidate
architectures were compared from official pricing pages with access dates; scale-to-zero hosting, serverless
functions and free database tiers that pause were ruled out on the measurements before price was considered.

---

## 20. Trade-offs I would defend

| Decision                             | Cost                                                                   | Why it is still right                                                                                           |
| ------------------------------------ | ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Graph in memory, not in the database | ~1 GB per worker; 19 s cold start                                      | Traversal is iterative; a round trip per expanded node would dominate. The cost is bounded and measured.        |
| One worker for the pilot             | Serialised long routes; 8 concurrent clients wait ~3.5 s at the median | A second worker is a second gigabyte. For a pilot shown to individuals, the memory is better spent on headroom. |
| Deterministic rules, no ML           | No inference of unrecorded attributes                                  | Every statement is traceable to a recorded fact. Gate C exists precisely to do this properly rather than early. |
| Unknown penalised, not ignored       | Longer routes; occasionally a detour a person would not have chosen    | The opposite error strands somebody. The two errors are not symmetric.                                          |
| Per-category uncertainty, no score   | More words on screen                                                   | A single number describes nothing and invites being read as confidence.                                         |
| PostGIS over a graph database        | Traversal is hand-written                                              | One store for spatial and relational; the traversal was never the hard part.                                    |

---

## 21. Limitations, stated plainly

- **One city.** Waterloo. The architecture is region-configurable and has never been run on a second region.
- **Not deployed.** No hosting, no URL, no users, no production traffic.
- **The cost weights are unvalidated** against real mobility-aid users.
- **Nobody has walked these routes.**
- **Evidence freshness is dataset-level** ([KI-7](development/KNOWN_ISSUES.md)): the product can say the extract
  was published on a date; it cannot say a particular crossing was surveyed four years ago.
- **The unknown-data penalty is doing one job** — removing the gradient term alone has the same effect as
  removing all of it.
- **The managed-hosting restore is proven against a stand-in**, not a real provider ([KI-8](development/KNOWN_ISSUES.md)).
- **Wall-clock figures come from one memory-pressured laptop** and are shapes, not service levels.
- **No accessibility certification of any kind.** PathAble advises; it does not certify.

---

## 22. What would change at 10× scale

**10× the region** (a province, not a city). The in-memory graph stops fitting: 1.5 M segments is roughly 10 GB
per worker at the current representation. Three options in order of preference — a compact struct-of-arrays edge
representation (the measured next step from §15); tiling the graph by region and loading only what a request
needs; or moving traversal into the database and accepting the round trips. The measurement that decides it is
peak RSS per region, which the committed benchmark already produces.

**10× the traffic.** Nothing here is I/O-bound, so the answer is horizontal: more single-worker instances behind
a load balancer, each holding its own graph, with readiness already gating traffic correctly during the load
window. The cost is linear in memory, which is why the per-worker duplication in §15 is the number that matters.

**10× the data richness** (user reports and model predictions alongside OSM). This is the one that changes the
architecture rather than the sizing. Predictions are already designed to live in their own table keyed by stable
source identity, never as columns on `graph_edges`, so a model's belief can never be mistaken for a surveyor's
assertion. Evidence freshness (KI-7) stops being deferrable the moment a second source of evidence exists,
because "how old is this claim?" becomes a question about more than one thing at once.

---

## What I must understand without AI

This section is for me, not for a reader. If I cannot explain these from memory, in my own words, at a whiteboard,
I should not be claiming them.

**Concepts**

- Why `unknown ≠ false`, and one concrete way conflating them injures somebody.
- Physical segments versus directed edges, and why 180,554 becomes 361,108.
- Hard constraint versus penalty, and what "effective metres" means.
- Why a random split leaks and a geographic hold-out does not (relevant to Gate C, not yet implemented).
- Why A\* expanded 3.8× fewer nodes and still was not faster.
- What ODbL share-alike attaches to (the derived database), versus what only needs attribution (a produced work).
- Why an in-memory graph is safe to cache: dataset immutability plus version-keyed cache.

**Code paths I should be able to trace on a whiteboard**

- `POST /api/v1/routes/compare` → `GraphRepository.active_graph` → `load_graph` → snap → `compute_route` ×2 →
  `compare_routes` → explanation assembly → response.
- `pathable ingest pbf` → `geo/pbf.py` → `normalise_edge` → validation → `ingest_network` → activation.
- Startup: entrypoint → alembic → lifespan → `GraphWarmup.start` → readiness flipping 503 → 200.
- `load_graph`'s Core-column select, and why each of the 34 columns is there.

**Commands I should be able to run and interpret from memory**

- `pathable ingest pbf`, `pathable elevation apply`, `pathable evaluate --algorithms --ablate`,
  `pathable benchmark load`, `pathable coverage`.
- `docker compose -f infra/production-smoke/compose.yaml up -d` and what readiness reports while it starts.
- `uv run pytest --cov=src/pathable_api --cov-fail-under=86`, and the four browser/unit suites separately.
- `infra/production-smoke/restore-dataset.sh` and why `--disable-triggers` is absent from it.

**Numbers I should know cold**

155,714 / 180,554 / 361,108. 287.4 m with 4 stairways versus 354.1 m with 0, +66.67 m (23%). 46.83 s → 22.14 s,
1,381.3 MB → 700.7 MB. 997 MB steady, 1,064 MB peak, 18.7 s to ready. OSM `incline` on 0.03% of segments.
18 of 20 journeys change. USD 45.15/month proposed.

**Weaknesses I must volunteer before being asked**

The cost weights are judgement, not validation. Nobody has walked the routes. One city. One worker. The
unknown-data penalty is carried by a single term. Not deployed. The A\* result is a wash. All of these are more
persuasive said first than extracted.
