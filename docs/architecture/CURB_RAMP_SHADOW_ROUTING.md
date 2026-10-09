# Municipal curb-ramp evidence — reconciliation and shadow-routing impact study (PA-GEO-09)

> **Research counterfactual — not production routing. Unvalidated municipal
> assertions.** Nothing in this document describes a route PathAble serves or
> should serve.

PA-GEO-08 ended with a LIMITED GO to reconciliation research for one class of
City of Kitchener evidence: curb cuts that matcher v2 locates at the metres of
an OpenStreetMap way, where OSM records no kerb node and no kerb tag. This card
asks the next question. If those assertions were conservatively reconciled at
their local matched extents and hypothetically accepted as routing evidence,
would they materially change PathAble's wheelchair and accessibility routes?

The answer has two parts, and the first governs the second.

- **Three quarters of the evidence cannot reach the place routing charges a
  kerb.** PathAble charges a kerb only on a crossing segment. Of 813 candidate
  assertions, 609 name only sidewalk or path extents and so, under this card's
  conditions, have no routing location; 201 reach one crossing segment each.
- **Where it reaches a crossing, routes move, a little, and always in the
  riskier direction.** Across 300 broad journeys the wheelchair route changes
  for 10, by a median 19.7 m; across 48 journeys chosen to cross the evidence,
  for 8. Every one of the 64 changes comes from the new path getting cheaper
  on an unvalidated, undated assertion.

Nothing is admitted: the production graph, the database and the API are
untouched (§10); every reconciliation row stays `not_routing_eligible`; the
founder licensing gate stays closed (§11).

**Decision: LIMITED GO** — to external validation of the 22 City records that
moved a route, and to matcher research on the completeness of curb-cut sets
with a new held-out sample; not to a routing policy and not to integration
(§13). The evidence is
[`kitchener-geo09-curb-ramp-shadow-routing.json`](../evidence/kitchener-geo09-curb-ramp-shadow-routing.json);
representative route changes and refused mappings are drawn in
[`kitchener-geo09-route-changes.html`](../evidence/kitchener-geo09-route-changes.html).

**What the numbers are.** Counts over matcher v2's pilot decisions, over the
active Waterloo routing graph, and over two engineering corpora of journeys.
The correspondences were measured once, on a held-out sample against AI
labels (PA-GEO-08); nothing here re-measures them, and nothing is
field-verified. The broad corpus is not a sample of real trips, so its rates
are not prevalence. The targeted corpus is chosen to cross City evidence, so
its rates describe nothing but itself.

## 1. Inputs, bound to PA-GEO-08

| Input   | What                                                                                                                                                                                                                   |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| City    | PA-GEO-03's snapshot `513094727cc1…`, normalized GeoParquet `ffe042be…`: 11,547 eligible physical pedestrian records, 3,192 of them curb cuts                                                                          |
| OSM     | PA-GEO-04's study extract `8391f097…`, cut from the PBF the active dataset was built from                                                                                                                              |
| Matches | Matcher v2 (`kitchener-geo08-matcher-v2`), run again here over every eligible record. The run refuses to continue unless its decisions hash to the digest PA-GEO-08's committed evidence records, `06440e4f…`; they do |
| Graph   | The active Waterloo dataset `51585450…` (180,554 segments, 11,764 of them crossings), loaded exactly as the routing service loads it, inside `READ ONLY` transactions; content checksum `4a179dc0…` before and after   |
| Router  | `compare_routes` — the path the routing API takes — with routing policy version 2, the standard baseline and the five presets kerb evidence can move                                                                   |

Matcher v1 is run beside v2 over the curb cuts, to recompute PA-GEO-06's
accounting of the 1,152 curb cuts it could not accept. Every count below is
recomputed from these decisions; none is copied from an earlier document.

## 2. How kerb evidence moves a route today

Read from the code (`routing/cost.py`, `routing/profiles.py`,
`geo/features.py`, `geo/node_evidence.py`), not assumed, and written into the
evidence (`kerb_in_routing_today`):

- **A kerb is charged only on a crossing segment.** `_kerb_cost` returns
  nothing unless `features.is_crossing`. A kerb on a sidewalk or path segment
  costs nothing, so an assertion there cannot move a route.
- **The flat penalty is by kerb kind.** `UNKNOWN` has its own rate; `NONE`,
  `FLUSH` and `LOWERED` have none in any profile. In effective metres:

  | Profile          | Unknown | Present, height unrecorded | Rolled | Raised | Lowered / flush / none | Missing-data rate per metre |
  | ---------------- | ------- | -------------------------- | ------ | ------ | ---------------------- | --------------------------- |
  | standard         | —       | —                          | —      | —      | —                      | —                           |
  | wheelchair       | 90      | 160                        | 300    | 400    | 0                      | 0.30                        |
  | walker           | 60      | 100                        | 140    | 200    | 0                      | 0.25                        |
  | crutches         | 20      | 28                         | 25     | 40     | 0                      | 0.20                        |
  | stroller         | 40      | 65                         | 90     | 120    | 0                      | 0.15                        |
  | reduced mobility | 12      | 20                         | 18     | 30     | 0                      | 0.12                        |

- **An unknown kerb is also missing data.** A crossing with an `UNKNOWN` kerb
  counts `kerb` among its missing attributes, charged per metre at the
  profile's uncertainty rate; a known kerb removes that share.
- **Where a crossing segment's kerb comes from.** The crossing way's own
  `kerb` tag, else the worse of the kerb nodes at the segment's two ends
  (`apply_to_crossing`). One kerb node fills the segment.
- **No hard limit reads a kerb.** Kerb evidence can change cost, never
  feasibility. Any feasibility change in this study is a defect, and there
  were none.
- **Explanations** compare the chosen route with the standard one by kerb kind
  and count unrecorded kerbs on the route, so kerb evidence on either route
  changes what the product says even when the path stays.

The City's `CURBCUT = Y` means "a curbcut down to street level"; the City
states no kerb height (PA-GEO-06 §4). For costing, the shadow reads it as the
kerb kind the cost model charges as dropped, `LOWERED`; `FLUSH` would cost the
same in every profile, and a test pins that equivalence. The standard profile
reads no kerb, and its route never moved.

## 3. The reconciliation

PA-GEO-06's model is extended by one thing: a curb ramp may now sit at a
**local way extent** as a candidate whose physical location is the matcher's,
never OSM's. Everything else is PA-GEO-06's: the City's assertion exactly as
published, with its value state, evidence origin, capture source and typed
dates; the matcher's decision exactly as made; `not_routing_eligible` on every
row, with PA-GEO-06's three blockers (licensing, validation, routing policy)
and a fourth this card adds, `blocked_by_correspondence_completeness`.

**Scope.** Every City curb cut whose matcher-v2 decision names no kerb node:
1,408 records, 1,152 of them PA-GEO-06's blocked set. The 194 ambiguous
_between_ kerb nodes and the 1,590 matched with a kerb node are PA-GEO-06's
class and are only counted.

**The conditions**, PA-GEO-08 §11's, applied row by row:

| Condition                                   | How                                                                                                                   | Records |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------- |
| Curb ramps only                             | `CURBCUT = Y`, value state `non_default`; the row's City assertion must be usable or the run refuses                  | 1,408   |
| Attach only to the named extent             | Each `way/<id>` target with its `from_m` and `to_m`, as decided; the way's version, timestamp and tags frozen with it | —       |
| Treat the set as possibly incomplete        | Every matched row carries `possibly_incomplete_set`; nothing is inferred from an element the set omits                | 816     |
| Exclude every abstention                    | `excluded_matcher_abstention`: the junction cases, 349 of them in PA-GEO-06's blocked set                             | 581     |
| No counterpart                              | `excluded_no_counterpart`                                                                                             | 11      |
| Exclude records longer than 20 m            | `excluded_record_over_20m`                                                                                            | 3       |
| Never override an OSM kerb fact (way level) | `excluded_osm_way_kerb_tag` where a named way carries `kerb=*` or `barrier=kerb`                                      | 0       |
| **Candidates for routing mapping**          |                                                                                                                       | **813** |

Of the 1,152 curb cuts PA-GEO-06 could not accept, matcher v2 matches 803 at
way extents and abstains on 349, the counts PA-GEO-08 reported. The 816
matched records here are those 803 and 13 more that matcher v1 had decided
differently.

A run refuses its own rows if any disagrees with what it holds: a
routing-eligible row, an unusable City assertion, a kerb node within 2 m, a
candidate without a matched extent, over 20 m, or on a kerb-tagged way. The
rows and their manifest live in the ignored data folder
(`kitchener-geo09-artifact-v1`), hashed into the evidence; two builds give one
digest.

## 4. Mapping an assertion to a routing location

This is the most important part of the card. The question is not whether the
City's ramp is real but whether the matcher's named extent identifies the
exact crossing segment where the router evaluates a kerb. **The policy,
`curb-ramp-shadow-policy-v1`**, maps an assertion only when all of this holds,
and otherwise leaves it unused and counts why:

1. a named extent lies on a routing segment at all;
2. that segment is a crossing in the production graph — a sidewalk or path
   extent is never given crossing semantics, and no crossing is inferred from
   one nearby;
3. the extent lies on one segment, spilling at most one sample (0.25 m) onto a
   neighbour, so a ramp is never spread along a way or across a junction;
4. the extent reaches within 2 m of one of the segment's end nodes — the
   matcher's own locality for a kerb node, from the label definitions;
5. the segment's production kerb is `UNKNOWN`: an OSM kerb fact, from the way
   or from a node at either end, is never replaced;
6. the record names exactly one such crossing segment: a piece attached to two
   crossings has no single location.

Segments are placed along their way exactly as PA-GEO-07 placed them: the
import cuts every OSM way at every node, so each segment's extent along its way
is known in the same metres the matcher measured in. None of the 180,554
segments failed that check.

**What the 813 candidates do:**

| Outcome                               | Records | What it means                                                                                                         |
| ------------------------------------- | ------- | --------------------------------------------------------------------------------------------------------------------- |
| **Shadow eligible**                   | **201** | One named extent lies on one crossing segment, at its end, where the production kerb is unknown                       |
| No extent on a crossing segment       | 609     | Every named extent is a sidewalk, footway, path, cycleway or traffic-island segment: the router charges no kerb there |
| Existing OSM kerb fact on the segment | 3       | The crossing segment already carries a kerb, from a node at its other end; never replaced                             |
| Extent spans several segments         | 0       |                                                                                                                       |
| Extent not at a segment end           | 0       |                                                                                                                       |
| Several crossing segments             | 0       |                                                                                                                       |
| No routing segment on any extent      | 0       |                                                                                                                       |

- **The eligible 201 are exactly where a kerb would be.** Their crossing
  extents sit a median 0.08 m from the segment's end node (90th percentile
  0.20 m, maximum 1.66 m). 147 of them also name a sidewalk, path, cycleway or
  traffic-island extent, which is left unused; 50 name only the crossing.
- **Each eligible assertion is alone on its segment**: 201 assertions, 201
  crossing segments, 1,195 m, every one asserted at one end only. The other
  end of each crossing is not asserted by it. One ramp fills the segment the
  way one OSM kerb node does in production, and the evidence records
  `ends_asserted` per segment.
- **By crossing type:** 117 unmarked, 55 marked, 18 uncontrolled, 11 with
  traffic signals; 66 are marked or signalised.
- **Across the graph**, 6,919 of the 11,764 crossing segments have an unknown
  kerb (43.3 km). The eligible assertions would describe 201 of them: 2.9%.

### Why 609 reach nothing

The piece that carries a curb cut runs from the end of a sidewalk onto a
crossing. Matcher v2 names a way only where the piece _follows_ it for at
least a quarter of its samples, and PA-GEO-08's failure analysis found this
rule's commonest failure: the crossing is within 2 m and in line, but nearest
to under a quarter of the piece, and is dropped — an incomplete set, never a
wrong element (11 of 37 held-out failures). That is what the 609 are, at
scale. As a diagnostic only, read from the decisions' own signals:

- 491 of the 612 non-eligible candidates had a crossing way within 2 m that
  the decision did not name; for 416 of them the piece's median angle to that
  crossing was 15° or less, the matcher's own follow limit.
- 121 had no crossing way within 2 m.
- The named extents are mostly sidewalks (399), plain footways (70), paths
  (65), cycleways (41) and traffic islands (36).

This card does not use that diagnostic. PA-GEO-08 §11 says nothing may be
inferred from an element the matcher omitted, and the mapping honours it: the
routing location is the matcher's named crossing or none. The consequence is
that the limiting factor for this evidence class is the completeness of
matcher v2's sets, not the routing model. Changing the quarter-share rule is a
new matcher policy version and needs a new, untouched held-out sample;
PA-GEO-08's is spent.

## 5. The shadow graph

The shadow is a copy of the loaded graph in which only the 201 eligible
crossing segments differ: their kerb is `LOWERED` instead of `UNKNOWN`, in
both directions. Nothing else changes — not the surface, the crossing type,
the geometry or any other segment. The copy-and-replace is the mechanism
PA-GEO-07 used for surfaces, now shared by both studies; the baseline object
is never touched, and its segment, node and adjacency fingerprints are the
same before the copy, after every shadow route and at the end (§10).

For an accessible profile, the substitution removes the unknown-kerb flat
penalty and the kerb share of the missing-data penalty on that segment, and
nothing else: for a wheelchair, 90 effective metres plus 0.3 per metre of the
segment. For the standard profile it changes nothing.

## 6. The two corpora

| Corpus   | Journeys | Built                                                                                                                                                                                                                                                                                                                                                                   |
| -------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Broad    | 300      | PA-GEO-07's broad corpus, unchanged and extended: origins cycling through a 6 × 6 grid over the pilot, destinations 0.8–3 km away in a straight line, seeded hash order, kept where the standard route exists. The seed is PA-GEO-07's, and the first 200 journeys hash to PA-GEO-07's corpus, `05e259dd…`: the sample was frozen before any curb-ramp evidence existed |
| Targeted | 48       | For each substituted crossing: 250 m before to 250 m after it, along its own direction; stratified by whether the crossing is marked or signalised and whether three or more other substituted crossings lie within 200 m (every segment is asserted at one end, so that stratum does not split); 12 per stratum in seeded hash order                                   |

Each journey is routed for six profiles — the standard baseline and the five
presets kerb evidence can move — on both graphs: 2,088 journey-profile pairs.
No custom profile is added: no hard limit reads a kerb, so none could make a
difference a preset does not. One broad journey (A115) has no route for the
three profiles that exclude steps, on either graph.

## 7. Results

Each journey and profile falls in exactly one category, the most consequential
that applies: `feasibility_changed`, `route_changed`, `cost_only`,
`evidence_only` (the same path and cost with what the product says about
kerbs changed), `no_effect`, `not_exposed`. There were no feasibility changes
and no change on a journey where neither path met a substituted crossing.

**Broad corpus**, 300 journeys per profile:

| Profile          | Not exposed | Evidence only | Cost only | Route changed | No route either |
| ---------------- | ----------- | ------------- | --------- | ------------- | --------------- |
| standard         | 265         | 35            | —         | —             | —               |
| wheelchair       | 260         | 26            | 3         | 10            | 1               |
| walker           | 262         | 26            | 4         | 7             | 1               |
| crutches         | 263         | 26            | 5         | 6             | —               |
| stroller         | 262         | 26            | 4         | 7             | 1               |
| reduced mobility | 264         | 27            | 6         | 3             | —               |

**Targeted corpus**, 48 journeys per profile (not prevalence):

| Profile          | Not exposed | Evidence only | Cost only | Route changed |
| ---------------- | ----------- | ------------- | --------- | ------------- |
| standard         | 22          | 26            | —         | —             |
| wheelchair       | 19          | 10            | 11        | 8             |
| walker           | 19          | 10            | 11        | 8             |
| crutches         | 20          | 11            | 12        | 5             |
| stroller         | 19          | 10            | 12        | 7             |
| reduced mobility | 21          | 11            | 13        | 3             |

- **Exposure is rare in ordinary journeys.** The wheelchair route meets a
  substituted crossing in 13 of 299 broad journeys; the standard route the
  explanation compares against meets one in 35. In the targeted corpus the
  wheelchair route meets one in 19 of 48.
- **Routes change for 11 of 300 broad journeys** for at least one profile (33
  journey-profile pairs), and for 9 of 48 targeted journeys (31 pairs).
- **Unknown kerbs on the chosen routes.** Across the broad wheelchair routes,
  151 of 485 crossings have an unknown kerb on the baseline and 142 on the
  shadow; across the targeted ones, 40 of 56 against 23. This is the whole of
  the information gain: nine and seventeen crossings.
- **Cost.** Where the wheelchair path moved in the broad corpus, the
  effective cost fell by a median 75.2 (30.9 to 122.5) effective metres while
  the physical distance rose by a median 19.7 m (2.2 to 47.5). Every
  cost-only change is the same path with its own crossing's penalty removed.

## 8. Route changes

64 journey-profile pairs changed path: 33 in the broad corpus and 31 in the
targeted one. Each is explained from the cost model itself, with both paths'
costs under both graphs, the substituted segments on each, and the City
records behind them.

- **Direction.** In all 64, the City's ramp makes the new path cheaper; in 12
  of them the old path also meets a substituted crossing and gets cheaper, but
  by less. **That is the riskier direction:** if the City's ramp is not there,
  the route has been drawn onto a path on the strength of an unvalidated
  claim.
- **Size.** 52 of the 64 moves are to a physically longer path and 12 to a
  shorter one. In the broad corpus the median move is 11.0 m and one is 50 m
  or more; in the targeted corpus the median is 13.5 m and seven are 50 m or
  more. The largest moves are 83.2 m longer (B043, walker) and 112.7 m shorter
  (B042, wheelchair).
- **Records.** 22 City records are behind the 64 changes. Three of them carry
  most of the effect: 389802 (17 pairs, 5 journeys), 389692 (11 pairs, 3
  journeys) and 372652 (9 pairs, 2 journeys). Every one is an administrative
  assertion dated only by capture, from 1997 to 2026.

**Representative changes**, from the evidence and drawn on the page:

- **Strongest.** B010, wheelchair: the baseline path (557 m, one unknown
  kerb) costs 1,179 effective m and the alternative (579 m) 1,198. City ramps
  lower the baseline path by 91.9 and the alternative by 183.6 — two
  substituted crossings, records 389802 and 320707 — so the route moves 21.9 m
  longer for 164.4 effective m less.
- **Largest move.** B042, wheelchair: a 1,389 m baseline against a 1,276 m
  alternative that two unknown kerbs (records 404226 and 337149) had made 98.8
  effective m dearer. With both substituted the shorter path wins by 84.7:
  the route is 112.7 m shorter and has the same number of unknown kerbs.
- **Smallest.** A073, reduced mobility: the alternative path is 11.0 m longer
  and, with one substituted crossing (record 385106), 0.4 effective m
  cheaper. A change this small is the cost model's tie, not a finding.
- **Surprising, and explained.** A010, stroller: the new path has one more
  unknown kerb than the old one (kerb cost 40 against 0) and is still chosen,
  because it is 85.4 m shorter and the substitution (record 86993) removes
  40.7 of its cost; it had been 22.7 effective m behind. The kerb-cost delta
  between the chosen paths rises while the total falls.
- **Refused mappings.** Record 15371: a 4.4 m sidewalk extent only, with no
  crossing named; nothing maps. Record 392668: the named crossing's segment
  already carries an OSM kerb from a node at its other end; never replaced.

## 9. Correctness

- **Dijkstra and A\*** agree on the shadow graph for every changed pair and a
  fixed sample of 20 broad and 20 targeted journeys for each accessible
  profile, and on the baseline graph for every changed pair: 243 of 243
  checks, on feasibility and on the optimal cost within one part in a
  million.
- **Defects, by category.** Feasibility changes: 0, as the cost model
  predicts. Changes on a journey where neither path meets a substituted
  crossing: 0. A changed route whose shadow cost is higher than the baseline's: 0. The standard route never moved.
- **Determinism.** Two full runs from clean trees, `5c4a141` and `9506409`,
  gave the same results digest, the same corpora and the same route changes;
  the committed run is the second, whose `run.determinism` records the
  comparison. Two reconciliation builds give one rows digest.

## 10. Production isolation

- **Database.** Every transaction is `READ ONLY`, enforced by PostgreSQL; an
  integration test shows it refusing a write inside the study's transaction,
  and a whole run of the command on a synthetic dataset leaves its rows and
  content checksum unchanged. The active dataset's content checksum is
  `4a179dc0…` before and after the study.
- **Loaded graph.** Its segment, node and adjacency fingerprints — the
  adjacency one including every directed entry's kerb, crossing flag and
  surface — are unchanged after the shadow is built, after every shadow route
  and at the end. 144 baseline journey-profile pairs routed again afterwards
  gave identical results.
- **Serving code.** Nothing that serves a route imports this study; the
  reconciliation, mapping, study and page modules import neither the database
  nor the API; the API contract, the frontend and the routing code are
  unchanged. The static test (`test_kitchener_isolation.py`) holds the
  PA-GEO-09 modules to the same rule as PA-GEO-07's.
- **Eligibility.** No production flag changed. Every reconciliation row is
  `not_routing_eligible`, and the shadow substitution exists only in the
  in-memory copy for the duration of the run.

## 11. Licensing

Unchanged, and the founder gate stays closed:

1. The City permits PathAble's research use.
2. The City separately permits use of its data in OSM.
3. OSMF LWG approval is not confirmed.

The reconciliation and mapping rows — a combined table of City and OSM
facts — stay in `.kitchener-data/`. The committed evidence holds counts, the
201 substituted OSM segments with their City record numbers, every
candidate's mapping outcome by OSM way, and, for each changed route, the OSM
segments and City records involved; no City geometry. The page draws routes
and named extents over OSM geometry only
([`DATA_SOURCES.md` §11](../licensing/DATA_SOURCES.md)).

## 12. Performance and determinism

The committed run, on one Windows 11 laptop with Python 3.13.2 and 16 GB,
under memory pressure. These are study timings, not production latency.

| Step                                              | Time                                               |
| ------------------------------------------------- | -------------------------------------------------- |
| Load the frozen inputs                            | 5.4 s                                              |
| Matcher v2 over the pilot (and v1 over curb cuts) | 94.6 s                                             |
| Build and write the reconciliation rows           | 1.4 s                                              |
| Load the graph, read-only                         | 35.0 s                                             |
| Map candidates to routing segments                | 1.1 s                                              |
| Build the shadow graph                            | 5.2 s                                              |
| Build both corpora                                | 90.7 s                                             |
| Broad corpus, 1,800 pairs                         | 41.2 min                                           |
| Targeted corpus, 288 pairs                        | 33.8 s                                             |
| Dijkstra against A\*, 243 checks                  | 245.8 s                                            |
| Per route, broad                                  | p50 322 ms, p95 1,223 ms, p99 2,579 ms, max 21.0 s |
| Per route, targeted                               | p50 29 ms, p95 94 ms, p99 132 ms, max 0.2 s        |
| Whole run                                         | 52.9 min, peak memory 1,338 MB                     |

Run A, from `5c4a141`, took 60.1 min with a peak of 1,397 MB; its broad
per-route p50 was 408 ms. Treat both as orders of magnitude.

## 13. Decision: LIMITED GO

To two next steps, each research or validation, neither integration:

1. **External validation of the 22 City records that moved a route**, the
   three that carry most of the effect first (389802, 389692, 372652). The
   question for each is whether a dropped kerb exists today at the end of the
   crossing the matcher named. They are few enough to check by hand, and they
   are exactly where a wrong assertion would change what a traveller is told.
2. **Matcher research on set completeness**, under a new policy version and a
   new, untouched held-out sample: the quarter-share rule that drops the
   crossing a piece runs onto is what keeps 609 of 813 candidates from any
   routing location. PA-GEO-08's sample is spent and may not be used.

The founder's licensing decision remains prior to anything beyond research.

Evaluated separately:

- **A. Correspondence quality.** Measured once by PA-GEO-08 on 54 held-out
  curb cuts without a kerb node: pair precision 0.967, 24 of 26 matches
  naming only labelled elements, 7 of 24 sets incomplete. Not re-measured
  here; AI labels, one model family.
- **B. Exact routing-location quality.** Where the matcher names the
  crossing, the location is exact: 201 extents a median 0.08 m from the
  segment end, none spanning segments, none away from an end. But it names
  the crossing for only 201 of 813 candidates. Coverage, not precision, is the
  weakness.
- **C. Route impact.** Small and concentrated: 11 of 300 broad journeys for
  any profile, 10 of 300 for a wheelchair, median moves of 11–20 m; 9 of 48
  targeted journeys. No feasibility change is possible, so the worst case is
  a longer path, not a stranded traveller. All 64 changes pull the route onto
  a path on an unvalidated claim.
- **D. Validation status.** None. No person, field check or external party
  has checked a correspondence, a mapping or a shadow route.
- **E. Licensing status.** The founder gate is closed; OSMF LWG approval is
  not confirmed.

**Why not GO.** Three quarters of the class cannot be located under the
conditions PA-GEO-08 set; every route change rests on an undated
administrative assertion; each substituted crossing is asserted at one end
only; nothing is validated; the licence question is open.

**Why not NO GO.** Where the mapping holds, it is exact and the effect is
real, bounded and explained; the cost model cannot be made to strand anyone
by this evidence; 22 records are few enough to check; and the reason most of
the class is unusable is a named, fixable matcher rule, not a property of the
data.

## 14. Limitations

- **A counterfactual.** The City's curb ramps are treated as accepted only to
  measure what admitting them would change. None is validated, and no shadow
  route is advice.
- **The correspondences are matcher v2's decisions**, measured once on a
  held-out sample against AI labels, unverified row by row, and every set is
  treated as possibly incomplete.
- **The routing location is the matcher's, not OSM's.** A crossing segment
  the extent reaches at its end; one City ramp fills the segment the way one
  OSM kerb node does in production, and the other end is not asserted.
- **`CURBCUT = Y` is read as a dropped kerb for costing only.** The City states
  no kerb height; lowered and flush cost the same.
- **Undated evidence.** No City curb cut carries an observation date. The 201
  eligible records are dated only by capture — 188 from orthoimagery, with
  capture years from 1997 to 2026 and 12 undated — and 179 carry a 2026
  inspection year, which says an inspection happened, not what it found.
- **The cost weights are engineering judgement**, never validated with the
  people they model. A route change says what this cost model does, not what
  a traveller would choose.
- **The corpora are engineering samples**, not trips.
- **One dataset, one City snapshot, one laptop.**

## 15. Reproducing

From `services/api`, with `DATABASE_URL` pointing at a database holding the
active dataset, PA-GEO-03's normalized snapshot and PA-GEO-04's study extract:

```
pathable kitchener curb-ramp-shadow-routing --normalized <folder> \
    --extract <study-extract.jsonl.gz> --extract-manifest <manifest.json> \
    --evidence-dir ../../docs/evidence --artifact-dir <folder> \
    --broad-size 300 --per-stratum 12 --json <evidence.json> --html <changes.html> \
    [--compare-to <an earlier run's evidence.json>]
```

The command only reads the database. Its first stage — binding to PA-GEO-08's
evidence, the pilot, the rows — needs neither the database nor the network,
and refuses to continue unless the pilot decisions reproduce PA-GEO-08's
digest. A full run took about an hour on one laptop.
