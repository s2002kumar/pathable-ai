# PathAble AI — Product Requirements

Status: draft for Phase 0 · Pilot: Waterloo, Ontario

---

## 1. The problem

Every mainstream routing product answers one question: what is the shortest way
to walk from A to B? For a large group of people that is the wrong question.

A route can be short and unusable. It can have a kerb with no curb cut, a
sidewalk that ends without warning, a 12% grade, construction hoarding that
narrows the path below a wheelchair's width, stairs presented as a "shortcut", or
a crossing with no audible signal. None of this appears in a conventional
pedestrian route, so the person finds out on arrival — sometimes far from home,
sometimes after dark, sometimes with no way back.

The workaround people use today is memory. They learn a small number of known-good
routes and stop going to places they have not already surveyed. That is a
mobility problem, but it is also a participation problem: it shrinks where
someone can work, study, shop and socialise.

The information needed to do better mostly exists — in OpenStreetMap tags,
elevation models, municipal open data, street imagery and, above all, in the
knowledge of people who navigate these streets daily. It is scattered, uneven in
quality, and not assembled into anything a person can use before they leave the
house.

## 2. Target users

**Primary — people whose route feasibility depends on the physical path.**
Wheelchair and scooter users, people using walkers, crutches or canes, people
with limited stamina or chronic pain, blind and low-vision pedestrians, people
pushing strollers, and people with temporary injuries. Their shared need is not
"a nicer route" — it is knowing in advance whether a route is possible.

**Secondary — people who plan on someone else's behalf.** Carers, family members,
accessibility coordinators, event organisers, and campus or municipal staff.

**Tertiary — contributors.** People willing to report a barrier or confirm a
crossing, whose observations become the ground truth the system depends on.

We are not building for the general "fastest walk" case. That is well served.

## 3. Core journey

1. A person opens PathAble and sees a map of the pilot region.
2. They set an origin and a destination.
3. They choose a mobility profile, or tune one.
4. PathAble computes two routes: the ordinary shortest pedestrian route, and a
   route optimised for their profile.
5. Both are shown together, with the difference stated plainly — extra distance,
   extra time, and what was avoided or accepted.
6. Every meaningful segment can be interrogated: _why_ this way, what the
   evidence is, how old it is, and how confident the system is.
7. Where the data is thin, the interface says so rather than filling the gap with
   an assumption.

Step 7 is the product. A confident wrong answer is worse than an honest
uncertain one.

## 4. The Waterloo pilot

Waterloo, Ontario is the first region because it is small enough to survey
properly, varied enough to be a real test, and locally accessible for
ground-truthing.

Within roughly a 3 km radius of the uptown core it contains:

- A dense pedestrian retail corridor (King Street) with frequent crossings.
- A large university campus with an internal path network and winter maintenance.
- Light rail (ION) with platform access, level boarding and tactile edges.
- Mid-century residential streets where sidewalks are intermittent.
- Suburban arterials with long blocks and few safe crossings.
- Genuine winter: snow banks at kerb cuts are a seasonal accessibility failure
  that a summer-only dataset will not capture.

Geography is configuration, never a hard-coded assumption. Centre, zoom, style
and region name are environment variables today, and every later ingestion or
routing component must take a region as a parameter.

## 5. Mobility profiles (future)

Planned profiles, each a set of weights and hard constraints rather than a label:

| Profile           | Hard constraints (examples)                 | Strong preferences                                |
| ----------------- | ------------------------------------------- | ------------------------------------------------- |
| Manual wheelchair | no stairs; minimum width; kerb cut required | avoid grade > 5%; smooth surface                  |
| Power wheelchair  | no stairs; minimum width; kerb cut required | tolerates steeper grade; needs turning space      |
| Walker / rollator | no stairs unless a handrail is present      | avoid grade > 8%; frequent rest points            |
| Crutches / cane   | avoid unstable surfaces                     | shorter distance; fewer level changes             |
| Stroller          | no stairs                                   | kerb cuts; avoid narrow gaps                      |
| Reduced mobility  | —                                           | shortest distance; benches; low grade             |
| Low vision        | —                                           | audible signals; tactile paving; simple crossings |
| Custom            | user-defined                                | user-defined                                      |

**A hard constraint is not a preference.** "Prefers no stairs" and "cannot use
stairs" must never be conflated in the data model, the routing cost function or
the interface.

## 6. Functional requirements

### Phase 0 (this batch)

- F0.1 Public web application, responsive, no login.
- F0.2 Interactive map of a configurable pilot region.
- F0.3 Visible, honest development-status disclosure.
- F0.4 Backend health and readiness endpoints.
- F0.5 Backend status surfaced in the interface.
- F0.6 PostGIS database with a migration baseline.
- F0.7 API contract generated from the backend and consumed by the frontend.
- F0.8 No routing, no ML, and no interface element implying either.

### Phase 1 and beyond (not built)

- F1.1 Origin and destination selection.
- F1.2 Mobility profile selection.
- F1.3 Shortest pedestrian route.
- F1.4 Accessibility-aware route.
- F1.5 Side-by-side comparison with the trade-off stated.
- F1.6 Per-segment explanation with evidence, source and age.
- F1.7 Explicit uncertainty and data-freshness display.
- F1.8 User-reported barriers with validation.
- F1.9 Learned barrier prediction from imagery, versioned and evaluated.

## 7. Accessibility requirements

The product is unusable if the product itself is inaccessible.

- WCAG 2.1 AA minimum for every user-facing surface; AAA where achievable.
- Full keyboard operation with a visible focus indicator throughout.
- Screen-reader support: correct landmarks, accessible names, sensible order.
- **Every map view has a textual equivalent.** A route must be readable as a
  sequence of described segments, not only as a line on a canvas.
- Colour never carries meaning alone.
- Respect `prefers-reduced-motion` and `prefers-color-scheme`.
- Text resizes to 200% without loss of content; zoom is never capped below 500%.
- The interface works without WebGL, degrading to the textual view.
- Touch targets meet minimum size guidance.

Automated checks (axe) run in CI. They are a floor. Manual keyboard and
screen-reader review is required before any public release, and evaluation with
disabled users is required before the product claims to serve them.

## 8. Privacy and safety principles

**Privacy**

- Origin/destination pairs reveal home, workplace, clinic and routine. They are
  treated as sensitive from the first line of code that touches them.
- Collect nothing that is not needed. Phase 0 collects nothing.
- No third-party analytics or advertising trackers.
- No account is required to plan a route.
- Any future report submission must be storable without identifying the reporter.

**Safety**

- Never present an inferred property as an observed fact.
- Never let a low-confidence prediction silently become a hard constraint.
- Missing data is displayed as missing, never as "fine".
- The system advises; it does not certify. No route is ever labelled
  "accessible" without qualification.
- A wrong "this is passable" is more harmful than a wrong "we are not sure",
  and the cost function must reflect that asymmetry.

## 9. Success criteria

**Phase 0** — a contributor can clone the repository and reach a running,
tested, documented stack; the interface makes no false claim; CI enforces the
quality gates.

**Phase 1** — for a set of Waterloo origin/destination pairs, the
accessibility-aware route differs meaningfully from the shortest route where it
should, and the explanation for each difference is verifiable on the ground.

**Long term** — a wheelchair user in Waterloo makes a trip they would otherwise
not have attempted, and the route holds up. That is the only success criterion
that matters; everything else is a proxy.

## 10. What a genuinely ML-driven route means

The phrase is easy to claim and worth defining precisely, because most of what
gets called "AI routing" is not.

Deterministic rules over OpenStreetMap tags — "avoid `highway=steps`", "prefer
`kerb=lowered`" — are **not** machine learning. Neither is a hand-tuned cost
function, however sophisticated. Both are valuable; neither is a model.

A route is ML-driven only when **all** of the following hold:

1. A **versioned, trained model** produces predictions about the physical world
   that were not directly observed — for example, inferring the presence of a
   curb cut from street imagery.
2. Those predictions **change the routing outcome**: they alter an edge's cost or
   feasibility, and a different model version can produce a different route.
3. Each prediction carries **calibrated uncertainty** that the router uses, so a
   low-confidence prediction cannot silently act as a hard constraint.
4. Predictions remain **distinguishable from observed facts** end to end — in
   storage, in the API, and in what the user is shown.
5. The model is **evaluated on held-out geography**, not merely a random split,
   so the reported numbers are not the product of spatial leakage.
6. Its performance is **measured and published** — precision, recall, F1,
   calibration, latency, and the failure cases — against a versioned dataset.

Until every one of these is true, the correct description is "rule-based
accessibility routing", and that is what we will call it. See
[`../architecture/FUTURE_ML_ARCHITECTURE.md`](../architecture/FUTURE_ML_ARCHITECTURE.md).

## 11. Non-goals

Not in scope, now or as currently planned:

- Turn-by-turn navigation or live guidance.
- Indoor routing and indoor accessibility.
- Public-transit trip planning (transit stops are inputs, not routes).
- Driving, cycling or parking.
- Social features, reviews or ratings of places.
- Certifying a venue's accessibility.
- A native mobile application.
- Coverage outside the configured pilot region.
- Any paid map or geocoding provider.
