# Explaining PathAble out loud

Three lengths, all drawn from the [claims ledger](CLAIMS_LEDGER.md). Nothing here says anything that file does
not support. **These are drafts for review, not final résumé wording** — the résumé bullets are a PA-RR-08
decision.

Read the ledger's prohibited-claims table before using any of this. The fastest way to lose a technical
interviewer is one unsupportable sentence in an otherwise good answer.

---

## Thirty seconds — a recruiter, a careers fair, a first phone screen

> PathAble is a pedestrian router for people who can't take the shortest path. You pick two points in Waterloo
> and a mobility profile — wheelchair, walker, stroller — and it shows you the ordinary walking route next to one
> that respects that profile, and explains the difference from what OpenStreetMap actually records: steps,
> surfaces, kerbs, gradients.
>
> On the example I demo, the shortest route is 287 metres with four flights of stairs; the wheelchair route is
> 354 metres with none. Sixty-seven metres to avoid four stairways.
>
> The part I'm proudest of isn't the routing. It's that when the map doesn't know something, the product says so
> instead of guessing. On that same route, OpenStreetMap has no accessibility detail for 100% of it, and the
> interface tells you that before it tells you the distances.
>
> It runs locally against a real 180,000-segment network. It isn't deployed — I have a costed hosting plan and
> haven't spent the money.

**If they ask "is it AI?"** — No. It's deterministic rules over recorded map data. Every response literally
carries `ml_predictions_used: false`. There's a plan for a learned component, and the bar I set for it is that a
prediction has to change a real route before I'd call the project ML-driven.

---

## Two minutes — a hiring manager or an engineer

> **The problem.** Every pedestrian router optimises distance. If you use a wheelchair, distance is the wrong
> objective and, worse, silence is dangerous: a router that treats "nobody recorded a kerb here" as "there's no
> kerb here" will eventually strand somebody at an unramped kerb after dark. The two errors aren't symmetric.
>
> **What I built.** A full stack: OSM ingestion into PostGIS with dataset versioning, an in-memory routing graph,
> an accessibility cost model, and a frontend that explains the result. Waterloo is loaded — 155,714 nodes,
> 180,554 segments, 361,108 directed edges — with 1 m LiDAR elevation from NRCan, because OpenStreetMap records a
> gradient on 0.03% of segments. Forty-six out of 180,000.
>
> **How the routing works.** Dijkstra as the correctness baseline, A\* alongside it, proven to agree on cost. The
> cost model separates hard constraints — a wheelchair can't traverse steps, so those edges are removed — from
> penalties measured in "effective metres", so the trade-off is legible: this profile will walk forty extra
> metres to avoid that. Unknown data carries a penalty rather than a pass.
>
> **What I'd point at in a code review.** Three things. First, the loader: profiling showed SQLAlchemy building a
> full ORM object per edge, 147 seconds against 5 for the same rows as narrow Core columns. Fixing it halved
> memory — 1,381 MB to 700 — and I proved it changed no route by hashing every node and segment before and after
> and re-running a twenty-journey corpus. Second, a geometry inspection I wrote because the numbers looked right:
> twelve of nineteen routes were drawing discontinuous lines with plausible distances, because a snapped segment
> was stored reversed _and_ marked reversed and got flipped twice. Third, A\* expands 3.8× fewer nodes and is
> still not faster at this scale — 195 ms against 213 — and the repository says so, because the alternative was
> reporting a win I hadn't got.
>
> **Where it stops.** One city. Not deployed. Nobody has walked these routes. The cost weights are my judgement,
> not validated against real mobility-aid users — that's the thing I'd want a partner organisation for before
> anyone relies on it.

---

## Ten minutes — technical deep dive

An outline to talk from, not a script. Each beat has an artefact behind it; the parenthesis says which.

**1 · The constraint that shapes everything (1 min)**
`unknown ≠ false`, end to end — database, API, UI. Ask them to hold onto it; three later decisions fall out of it.
(_[PHASES.md](product/PHASES.md) standing rules_)

**2 · Data pipeline (2 min)**
Two ingestion paths, one normaliser, so a route can't change with how data arrived. Tags → typed attributes with
`unknown` as a value. Elevation chosen by measurement — 30 m model RMSE 4.06 pp against a 1.78% median grade, so
the error exceeds the signal — and read from an 898 GB COG by byte range, never downloaded. Derived gradient kept
in its own column, never overwriting a mapper's. (_[DATA_SOURCES.md §5](licensing/DATA_SOURCES.md)_)

**3 · Versioning, and why the cache is safe (1 min)**
Immutable dataset versions, activation swapped in one transaction, one-active-per-region enforced by a database
constraint. Graph cached by version id, so a cached graph can't go stale — a new dataset is a new key.
(_`geo/datasets.py`_)

**4 · Graph and search (1.5 min)**
180,554 physical segments → 361,108 directed edges; why both counts exist. MultiDiGraph because two nodes can be
joined by more than one segment and collapsing them would discard the alternative the product exists to find.
Snapping to a point _along_ a profile-usable segment — snapping a wheelchair onto steps would start the journey
with the obstacle. Dijkstra/A\* agreement, and the honest A\* result.
(_[`waterloo-performance.json`](evidence/waterloo-performance.json)_)

**5 · Cost model (1.5 min)**
Hard constraints vs penalties in effective metres. The campus journey as the worked example: 287.4 m/4 stairways
→ 354.1 m/0, effective 601 m. The unknown penalty was ablated, not assumed — removing it changes 3 of 20 routes,
but removing only the gradient term changes the same 3, so one term is doing all the work. That's a weakness I
volunteer. (_[ADR 0008](adr/0008-accessibility-cost-model.md)_)

**6 · Explanations and uncertainty (1 min)**
Each explanation names something concrete that was avoided, with its evidence. Uncertainty per category, never
one score, because two routes missing different things produce the same number. No accessibility score, ever.
(_live response; `RouteDifference.tsx`_)

**7 · The debugging story — pick one, tell it fully (1.5 min)**
Default to the reversed geometry: symptom (plausible distances, broken lines), why no test caught it (the numbers
were right), the inspection written to compare the drawn line against itself, the double flip, the narrow fix,
the regression that now runs over all nineteen routes, and the limitation — it checks geometry against itself,
not against the ground. (_[defence §16a](PROJECT_DEFENSE.md)_)

**8 · Production reality (1 min)**
Containers measured from an empty database: routable 18.7 s after start, 997 MB steady, 1,064 MB peak, graph
duplicated per worker. Readiness holds 503 until the graph loads so nothing routes traffic into the window.
Migration failure is a startup failure, verified by pointing at a bad revision. A costed proposal at USD 45/month
that hasn't been bought. (_[`production-envelope.json`](evidence/production-envelope.json), [ADR 0009](adr/0009-deployment-architecture.md)_)

**9 · Testing (0.5 min)**
Per-suite counts, never a grand total. Integration against real PostGIS, never mocks. Full-stack browser tests
that stub nothing. Regression tests named after their bug.

**10 · Limits and 10× (1 min)**
One city, not deployed, weights unvalidated, nobody has walked the routes. At 10× region the in-memory graph
stops fitting and the next step is a struct-of-arrays representation — already identified and measured toward.
At 10× traffic it's horizontal, and per-worker memory is the number that matters. At 10× data richness,
predictions live in their own table so a model's belief can never be mistaken for a surveyor's assertion.

**Questions to invite**
"Where would this break first?" · "What would you throw away?" · "How do you know the optimisation didn't change
a route?" Each has a real answer above.
