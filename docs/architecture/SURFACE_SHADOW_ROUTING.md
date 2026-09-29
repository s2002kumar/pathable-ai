# Municipal surface evidence — shadow-routing impact study (PA-GEO-07)

> **Research counterfactual — not production routing.** Nothing in this
> document describes a route PathAble serves or should serve.

If the City of Kitchener surface assertions PA-GEO-06 found where OSM records
no surface were someday accepted as routing evidence, would they change
anything PathAble tells a traveller? This card answers that offline. It routes
the same journeys twice with PathAble's own router: once on the active OSM-only
graph, and once on a **shadow** copy in which those City surfaces fill the
gaps. Then it compares the two.

Nothing is admitted:

- the production graph, the database and the API are untouched (§9);
- every Kitchener assertion stays `not_routing_eligible`;
- the founder licensing gate stays closed.

**Decision: LIMITED GO** to licensing review and external validation, for a
narrow set of City surface records (§12). The evidence is
[`kitchener-geo07-shadow-routing.json`](../evidence/kitchener-geo07-shadow-routing.json);
representative route changes are drawn in
[`kitchener-geo07-route-changes.html`](../evidence/kitchener-geo07-route-changes.html).

**What the numbers are.**

- Counts over two engineering corpora of journeys (§4).
- The broad corpus is not a sample of real trips, so its rates are not
  prevalence. The targeted corpus is chosen to pass City evidence, so its rates
  describe nothing but itself.
- The City's surfaces are treated as accepted only to measure what accepting
  them would do. None is validated.

## 1. Inputs

| Input      | What                                                                                                                                                        |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| City       | PA-GEO-06's reconciliation artifact, checked file by file against its manifest and against the committed evidence (`6bb58d6f…`): 943 City-only surface rows |
| Graph      | The active Waterloo dataset `51585450…` (180,554 segments), loaded exactly as the routing service loads it, inside `READ ONLY` transactions                 |
| OSM extent | PA-GEO-04's study extract `8391f097…`, cut from the same source file, for each way's node order and length                                                  |
| Router     | `compare_routes` — the path the routing API itself takes — with routing policy version 2 and every production profile                                       |

## 2. How surface moves a route today

This is read from the code (`routing/cost.py`, `routing/profiles.py`), not
assumed. Penalties are multiples of a segment's length, in effective metres:

| Profile                      | Unknown surface | Compacted | Rough | Paved | Rough excluded |
| ---------------------------- | --------------- | --------- | ----- | ----- | -------------- |
| standard                     | —               | —         | —     | —     | no             |
| wheelchair                   | 0.5             | 0.8       | 12.0  | 0     | no             |
| walker                       | 0.4             | 0.5       | 4.0   | 0     | no             |
| crutches                     | 0.35            | 0.4       | 1.6   | 0     | no             |
| stroller                     | 0.3             | 0.4       | 1.5   | 0     | no             |
| reduced mobility             | 0.2             | —         | 1.0   | 0     | no             |
| custom: wheelchair, no rough | 0.5             | 0.8       | 12.0  | 0     | **yes**        |

That gives four mechanisms:

- A known surface class replaces the unknown-surface penalty with its own. A
  City PAVED surface makes a segment cheaper; COMPACTED or ROUGH makes it dearer
  for most profiles.
- Surface is never counted a second time in the missing-data penalty.
- Only a declared requirement excludes. No preset excludes rough surfaces
  (gravel, ground and the like; compacted surfaces are not rough). A custom
  profile that must avoid rough surfaces does, and that is the only way a
  surface can make a segment unusable. The study routes that custom
  profile alongside the five presets and the standard baseline.
- Explanations compare the accessible route with the standard one, so surface
  evidence on either changes what the product says.

The standard profile ignores surface entirely: its route must never move, and
never did.

## 3. The shadow graph

**Policy `surface-shadow-policy-v1` fills missing surfaces and does nothing
else.**

- If OSM records a surface on a segment, OSM's is kept.
- Otherwise, if accepted City-only non-default surfaces of one routing class
  cover at least 90% of the segment, and no other City class covers more than
  10%, the City's surface is used.
- Otherwise the surface stays unknown.

Conflicts, agreements, template defaults (CONCRETE among them), ambiguous
matches, curb ramps, structures, stairs, width, grade and condition are never
read.

**Local scope.** PathAble's import cuts every OSM way at every node, and a
segment's `edge_key` is the index of its first node in the way. So each
segment's extent along its way is exact, in the same metres PA-GEO-05 measured
City extents in.

- Every segment is checked against its way's node order before it is used;
  none in the study failed that check.
- A City record fills a segment only if it covers at least 90% of it. A short
  record cannot describe a long way or a long segment; a test pins that.

**Isolation.** The shadow graph shares every unchanged segment with the loaded
graph and replaces the filled ones in a copy of the adjacency. Nothing is
written back.

### What the overlay fills

Of the 943 City-only assertions:

| Outcome                                               | Assertions |
| ----------------------------------------------------- | ---------- |
| Fill at least one routing segment                     | 888        |
| Cover no segment to 90%                               | 47         |
| A value routing has no class for (BRICK, COBBLESTONE) | 7          |
| Two City classes on one segment                       | 1          |

They fill **1,926 segments, 23.96 km**. By routing class:

- paved: 1,533 segments, 16.8 km;
- compacted: 333 segments, 5.9 km;
- rough: 60 segments, 1.3 km.

The City extents touch 2,295 segments in all:

- 1,949 are covered at least 90%;
- 288 are covered 50–90% and stay unknown;
- 58 are covered less than half.

**Across the whole graph**, 2,049.5 km of segments have a known surface and
1,314.1 km do not. The overlay would add 1.82% of the unknown metres, taking
the counterfactual known surface to 2,073.5 km (+1.17%). This is counterfactual
evidence coverage, not validated coverage.

**Dates.** 880 of the 888 filling assertions are dated only by when the City
captured the record, and 8 not at all; none carries an observation date. Their
capture years: 2012 on 450, 1997 on 74, 2015 on 73, and the rest spread from
2000 to 2026.

## 4. The two corpora

| Corpus   | Journeys | Built                                                                                                                                                                                                                        | sha256      |
| -------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| Broad    | 200      | Origins cycling through a 6 × 6 grid over the pilot, destinations 0.8–3 km away in a straight line, seeded hash order; kept where the standard route exists; reads no City evidence                                          | `05e259dd…` |
| Targeted | 49       | 250 m either side of a filled City record's midpoint, along its direction; up to six records per stratum of routing class × filled length (40 m or more) × density (3 or more other records within 200 m); nine strata occur | `e59edaa9…` |

Each journey is routed for all seven profiles: 1,743 journey-profile pairs.
The pilot also covers the City of Waterloo, where Kitchener's inventory has no
records, which is part of why 144 of the 200 broad journeys meet no filled
segment at all.

## 5. Results

Each journey and profile falls in exactly one category, the most consequential
that applies.

**Broad corpus**, 200 journeys per profile:

| Profile          | Not exposed | Evidence only | Cost only | Route changed | Feasibility changed | No effect | No route either |
| ---------------- | ----------- | ------------- | --------- | ------------- | ------------------- | --------- | --------------- |
| standard         | 144         | 56            | —         | —             | —                   | —         | —               |
| wheelchair       | 142         | 31            | 21        | 3             | —                   | 2         | 1               |
| walker           | 142         | 31            | 21        | 3             | —                   | 2         | 1               |
| crutches         | 143         | 32            | 22        | 2             | —                   | 1         | —               |
| stroller         | 143         | 33            | 19        | 3             | —                   | 1         | 1               |
| reduced mobility | 143         | 29            | 23        | 3             | —                   | 2         | —               |
| custom, no rough | 131         | 31            | 19        | 1             | 1                   | 2         | 15              |

**Targeted corpus**, 49 journeys per profile (not prevalence):

| Profile          | Not exposed | Evidence only | Cost only | Route changed | Feasibility changed | No route either |
| ---------------- | ----------- | ------------- | --------- | ------------- | ------------------- | --------------- |
| standard         | 14          | 35            | —         | —             | —                   | —               |
| wheelchair       | 14          | 8             | 19        | 8             | —                   | —               |
| walker           | 13          | 8             | 20        | 8             | —                   | —               |
| crutches         | 13          | 8             | 18        | 10            | —                   | —               |
| stroller         | 13          | 8             | 21        | 7             | —                   | —               |
| reduced mobility | 14          | 8             | 23        | 4             | —                   | —               |
| custom, no rough | 14          | 8             | 18        | 5             | 3                   | 1               |

"Evidence only" is the same path at the same cost, with what the product says
about surface changed. For accessible profiles it always comes from the
standard route the explanation compares against: in all 235 such pairs, the
chosen route meets no filled segment. Any fill on an accessible route changes
its cost.

## 6. Route changes

61 journey-profile pairs changed path: 16 in the broad corpus (5 of 200
journeys) and 45 in the targeted one (12 of 49). Each is explained from the
cost model itself, with both paths' costs under both graphs and the City
records on each.

- **Size.** In the broad corpus the median move is 5.5 m, and 2 of the 16 move
  by 50 m or more. In the targeted corpus the median is 22.8 m, and 12 of 45
  move by 50 m or more; the largest is 442.8 m.
- **Direction**, from each change's costs: in 46, City evidence makes the new
  path cheaper; in 13, it makes the new path cheaper and the old one dearer; in
  2, it only makes the old path dearer.
- **Dates.** All 61 rest on City assertions dated only by capture.

In 59 of 61 changes, then, City evidence — mostly PAVED, replacing an
unknown-surface penalty — draws the route onto a path. **That is the riskier
direction:** if the City's "paved" is wrong, the route has been drawn onto a
path on the strength of an unvalidated claim.

An example. Journey A016, wheelchair: City surfaces raise the cost of the
baseline path by 2,438.9 effective m and of the alternative by 1,661.8. The
baseline path runs along the City gravel on way 160510594 that blocks the same
journey for the custom profile. The route moves to a path 226.8 m longer.

### Hard feasibility

Four changes are hard, all for the custom profile that must avoid rough
surfaces, and no preset has one:

| Journey | Blocking City records          | City surface     | Way           | Consequence |
| ------- | ------------------------------ | ---------------- | ------------- | ----------- |
| A016    | 416890, 416891, 416900, 416901 | GRAVEL           | way/160510594 | +64.8 m     |
| B014    | 424145                         | NATURAL (ground) | way/33869064  | +48.6 m     |
| B041    | 417790, 417791                 | NATURAL (ground) | way/40585188  | +314.8 m    |
| B048    | 424145                         | NATURAL (ground) | way/33869064  | +22.8 m     |

In each, a City assertion in the rough class makes a segment of the baseline
route unusable, and the route moves. Each record lists the rule, every blocked
segment, its way extent and the City record. This is potential impact only:
the shadow answer rests on an unvalidated assertion and is neither safer nor
more correct.

## 7. Information gain

Surface metres on the chosen routes, where both runs route:

| Corpus, profile      | Baseline unknown | Candidate municipal on shadow routes | Incremental known |
| -------------------- | ---------------- | ------------------------------------ | ----------------- |
| broad, standard      | 171.8 km         | 5.0 km                               | 5.0 km            |
| broad, wheelchair    | 73.5 km          | 1.6 km                               | 1.4 km            |
| broad, walker        | 72.7 km          | 1.5 km                               | 1.3 km            |
| targeted, standard   | 18.3 km          | 5.4 km                               | 5.4 km            |
| targeted, wheelchair | 10.4 km          | 3.9 km                               | 3.6 km            |

Every profile's figures, by routing class, are in the evidence. On the broad
corpus the City would describe 1.8–2.9% of the unknown surface on the chosen
routes, depending on the profile; on the targeted journeys, 30–42%.

## 8. Conflicts — a sensitivity, never a policy

The 257 conflicts are never used by the policy.

- They lie on 493 routing segments. On 252 of them, the City's routing class
  differs from OSM's.
- 40 conflict assertions lie on evaluated baseline routes: 27 where the class
  differs, and 13 where it does not (ASPHALT against OSM concrete, for
  instance, which costs the same).
- Of those 40, 15 OSM values carry an observation date, from 2020 to 2024,
  and 14 of those are later than the City's capture date. The other 25 carry
  none. No City value carries an observation date.

**Were the City's side taken** on conflict extents, as a sensitivity:

- in the broad corpus, 1 route would move for each accessible preset but
  wheelchair, which would see 3. The custom profile would see one hard change.
- no targeted route would move.

Of 1,743 journey-profile pairs, 814 were routed again. The other 929 provably
cannot move: no conflict segment lies on either route the explanation compares,
and none made cheaper is within straight-line reach of the baseline's cost.
That is the bound A\* rests on, tested equal to routing every pair again.
Nothing is resolved.

## 9. Production isolation

- **Database.** Every transaction is `READ ONLY`, enforced by PostgreSQL. The
  active dataset's content checksum is `4a179dc0…` before and after the study.
  An integration test shows PostgreSQL refusing a write inside the study's
  transaction.
- **Loaded graph.** Its segment, node and adjacency fingerprints are unchanged
  after every shadow route. 84 of 84 baseline journeys routed again at the end
  gave identical results.
- **Serving code.** Nothing that serves a route imports the study, and the API
  contract, the frontend and the routing code are unchanged. Static tests
  enforce this (`test_kitchener_isolation.py`).
- **Algorithms.** Dijkstra and A\* agree on the shadow graph for 71 of 71
  checked pairs: every changed route and a fixed sample.

## 10. Validation queue

40 City records to check first, in the field or by someone outside this
repository. Nothing in it has been checked. They are chosen by explicit strata
from measured impact. The strata take turns, so none is crowded out by those
before it:

| Chosen first for                                      | Records |
| ----------------------------------------------------- | ------- |
| A hard requirement changed whether a route may use it | 6       |
| The chosen path moved in at least one journey         | 7       |
| On the chosen route of three or more journeys         | 7       |
| A surface the cost model penalises, on a route        | 7       |
| The longest filled extents any route used             | 7       |
| A conflict whose City side would move a route         | 6       |

- **Every record that blocks a route is in it.** These are 416890, 416891,
  416900 and 416901 (GRAVEL, captured 1997), 417790 and 417791 (NATURAL,
  2006), and 424145 (NATURAL, 2006). 417790 was taken first for its rough
  surface.
- **The six conflicts:**
  - three City ASPHALT where OSM records unpaved: 8186, 87632 and 386354;
  - two City ASPHALT where OSM records gravel: 6474 and 47146;
  - one City GRAVEL where OSM records asphalt: 49954, whose City side would
    block journey A077 for the custom profile.
- **The whole queue:** 21 paved, 11 compacted and 8 rough, on 5.35 km of routing
  segments. Every record is dated only by capture: 13 in 2015, 6 in 2026, 5 in
  1997, and the rest between 2003 and 2024.

Each entry gives:

- the City value, and what OSM records there;
- every way extent and routing segment;
- the capture source and date;
- up to three journeys it affects.

The question for each is whether the surface is what the City says, today, on
that extent. The paved records that pull routes onto a path and the rough ones
that block them come first: they are where a wrong assertion would change what
a traveller is told.

## 11. Performance and determinism

The committed run, on one Windows 11 laptop with Python 3.13.2. These are
shadow-routing timings, not production latency.

| Step                      | Time                                               |
| ------------------------- | -------------------------------------------------- |
| Load the graph, read-only | 93.7 s                                             |
| Plan the overlay          | 5.2 s                                              |
| Build the shadow graph    | 22.1 s (+220 MB)                                   |
| Build both corpora        | 5.7 min                                            |
| Broad corpus              | 66.3 min                                           |
| Targeted corpus           | 1.2 min                                            |
| Conflict sensitivity      | 14.6 min (814 of 1,743 pairs routed again)         |
| Per route, broad          | p50 618 ms, p95 2,372 ms, p99 4,856 ms, max 35.1 s |
| Per route, targeted       | p50 25 ms, p95 121 ms, p99 178 ms, max 234 ms      |
| Whole run                 | 93.1 min, peak memory 1,538 MB                     |

Treat these as orders of magnitude. On the same laptop the same routing took
68.5, 106.9 and 93.1 minutes in three full runs, with a broad per-route p50 of
434, 638 and 618 ms.

**Determinism.** Three full runs gave the same study:

- Runs A (`cdcd0f7`) and C (`12caea3`) have the same results digest,
  `d8264550…`, and the same corpora. `12caea3` changed only the validation
  queue.
- The committed run D (`f89a625`, clean tree) rewords the explanations and
  redraws the page. Every journey-profile outcome, route change and corpus is
  identical to run C's apart from that wording, as `run.determinism` records.
  Its results digest, `421713c9…`, differs for that reason alone.

Run C's tree was marked dirty by documentation being written during the run.
No file under `services/` differed from `12caea3`.

## 12. Decision: LIMITED GO

To the founder's licensing review and to external validation, for a narrow set
of City surface records only — the queue in §10. This is not integration.

**Why not GO.**

- Across ordinary journeys the effect is small: 5 of 200 broad journeys change
  route for any profile, with a median move of 5.5 m.
- Most of the effect is evidence or cost on an unchanged path.
- Every City assertion lacks an observation date. Over half of the filling
  ones carry a 2012 or 1997 capture date, and 846 of the 943 name
  orthoimagery as their capture source.
- 59 of 61 route changes come from City evidence pulling a route onto a path —
  the direction in which a wrong assertion does harm.

**Why not NO-GO.**

- Where the City's data exists, it matters and it is concentrated: the targeted
  journeys change route 8–20% of the time per profile.
- The mapping is exact where it applies.
- No production coupling appeared.
- The records that move routes are few enough to check by hand.

**What should happen next**, in order:

1. The founder decides licensing: whether combining these assertions with the
   OSM-derived database is permissible at all.
2. External or field validation of the queue, paved assertions that attract
   routes first.
3. Only then, a routing-policy card could say whether validated municipal
   surfaces may fill gaps, with what freshness rule.

**Matcher v2 looks like the better next investment for routing value.** The
City-only evidence surfaces could not reach is larger and more
safety-relevant: 1,152 City curb cuts with no OSM kerb node, and stairs OSM
draws as plain footways, where a missing stair is a hard constraint for
several profiles. Matcher v2 remains planned only and needs a new, untouched
holdout.

## 13. Limitations

- **A counterfactual.** The City's surfaces are treated as accepted only to
  measure the effect; none is validated, and no shadow route is advice.
- **The correspondences are PA-GEO-05's frozen matcher's decisions.** They were
  measured once, on a held-out sample against AI labels.
- **The cost weights are engineering judgement,** never validated with the
  people they model. A route change says what this cost model does, not what a
  traveller would choose.
- **The corpora are engineering samples,** not trips.
- **Undated evidence.** The City supplies no observation date for any surface.
- **The 90% coverage rule leaves 346 partly covered segments unknown,** 288
  of them covered 50–90%. That under-claims rather than smears, but it is a
  choice, not a measurement.
- **One dataset, one City snapshot, one laptop.**

## 14. Reproducing

From `services/api`, with `DATABASE_URL` pointing at a database holding the
active dataset, PA-GEO-06's artifact and PA-GEO-04's study extract:

```
pathable kitchener shadow-routing --geo06-artifact <folder> --evidence-dir ../../docs/evidence \
    --extract <study-extract.jsonl.gz> --extract-manifest <manifest.json> \
    --broad-size 200 --per-stratum 6 --json <evidence.json> --html <changes.html> \
    [--compare-to <an earlier run's evidence.json>]
```

The command only reads the database. A full run took 68 to 107 minutes on one
laptop.
