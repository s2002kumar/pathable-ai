# Future ML architecture

> ## No machine learning exists in this repository.
>
> There is no model, no training code, no inference service, no dataset and no
> labelled data. Nothing in PathAble is currently learned from data.
>
> This document exists so that when ML does arrive it arrives correctly, and so
> that nobody — including us — is tempted to describe the current system as
> AI-driven before it is.

---

## 1. What is not machine learning

This matters because the industry routinely calls all of the following "AI":

| Not ML                                             | Why it is not                                         |
| -------------------------------------------------- | ----------------------------------------------------- |
| `if highway == 'steps': cost = INF`                | A rule someone wrote. Nothing was learned.            |
| A weighted sum of OSM tags                         | A hand-tuned function, however elaborate.             |
| Dijkstra / A\* over a weighted graph               | A search algorithm. It has no parameters fit to data. |
| Interpolating elevation from a DEM                 | Deterministic geometry.                               |
| A heuristic threshold on grade                     | A constant someone chose.                             |
| Calling a third-party LLM to phrase an explanation | A model, but it does not affect routing.              |

Phase 1's accessibility routing will be **entirely deterministic and
rule-based**, and the interface will describe it that way. A better cost function
is still not a model.

## 2. What would make it machine learning

A model becomes part of PathAble routing only when **all six** hold:

1. **A versioned trained model produces predictions about the physical world that
   were not directly observed** — e.g. inferring a curb cut from imagery where no
   OSM tag and no user report exists.

2. **Those predictions change the routing outcome.** They alter an edge's cost or
   feasibility, such that swapping model versions can produce a different route.
   A model whose output is displayed but never used is not part of routing.

3. **Predictions carry calibrated uncertainty, and the router uses it.** Not a
   raw softmax score — a probability that means what it says, verified with a
   reliability diagram. A 0.55-confidence prediction must never act as a hard
   constraint.

4. **Learned predictions stay distinguishable from observed facts** at every
   layer: separate database columns, separate API fields, distinct presentation.
   Once merged they cannot be unmerged, and the user permanently loses the
   ability to tell knowledge from inference.

5. **Evaluation uses geographic hold-out.** See §5.

6. **Performance is measured and published** against a versioned dataset, failure
   cases included.

Until then, the honest description is "rule-based accessibility routing".

## 3. The four kinds of information, kept separate

The data model must never collapse these into one "accessibility score":

| Kind                   | Example                                    | Properties                                    |
| ---------------------- | ------------------------------------------ | --------------------------------------------- |
| **Deterministic fact** | `kerb=lowered` in OSM; 6.2% grade from DEM | Observed. Has a source and a date.            |
| **Validated report**   | "No curb cut here" confirmed by 3 people   | Observed. Has reporters and a date.           |
| **Learned prediction** | Model v4 infers a curb cut at 0.82         | Inferred. Has a model version and confidence. |
| **User preference**    | "Avoid grades above 5%"                    | Not about the world at all.                   |

Four separate concepts, four separate representations. A single blended number
would be unexplainable, undebuggable and impossible to correct.

**Freshness is orthogonal to all four.** A 2019 observation is not a 2026 fact.
Confidence must decay with age, and the decay must be visible.

## 4. Dataset versioning

Every dataset is immutable and identified:

```
dataset/
  waterloo-curbcuts-v3/
    manifest.json      source, extract date, region bbox, licence, counts
    splits.json        geographic hold-out definition (not random)
    labels.parquet     label, annotator, timestamp, guideline version
    CHANGELOG.md       what changed from v2 and why
```

Requirements:

- A model records the exact dataset version it was trained on. "Trained on the
  latest data" is not reproducible and is therefore not acceptable.
- Labelling guidelines are versioned too. Changing what counts as a "curb cut"
  changes the labels, and a metric compared across a guideline change is
  meaningless.
- Inter-annotator agreement is measured and reported. If humans cannot agree on
  a label, a model's accuracy against it means little.
- Re-labelling produces a new version; labels are never edited in place.

## 5. Geographic leakage-safe evaluation

**A random train/test split will produce impressive and completely false
numbers.**

Street segments are spatially autocorrelated: adjacent segments share
construction era, municipal standards, materials and imagery capture conditions.
Split randomly and the model sees one side of a street in training and the other
in test, effectively memorising neighbourhoods. Reported accuracy then measures
memorisation, not generalisation — and the failure surfaces exactly where it
matters, in a neighbourhood nobody surveyed.

Required instead:

- **Spatial blocking.** Partition into contiguous blocks (grid cells or
  neighbourhoods) and assign whole blocks to splits.
- **Buffer zones** between splits, wide enough that no test segment is adjacent
  to a training segment.
- **Held-out region** for the final report — train on Waterloo, evaluate on a
  city never seen during development.
- Report **both** random-split and spatial-split numbers. The gap between them is
  itself the finding, and hiding it would be dishonest.

The same discipline applies to imagery: images from one capture run of the same
street must not straddle the split.

## 6. Metrics

For any barrier-detection model, all of the following, per class:

| Metric                                 | Why                                                          |
| -------------------------------------- | ------------------------------------------------------------ |
| Precision                              | False "this is passable" strands someone.                    |
| Recall                                 | False "this is blocked" quietly removes viable routes.       |
| F1                                     | Summary only — never reported alone.                         |
| Calibration (ECE, reliability diagram) | The router consumes confidence; it must mean something.      |
| Latency (p50/p95/p99)                  | Routing has a latency budget.                                |
| Per-region breakdown                   | Aggregate accuracy hides a neighbourhood the model fails on. |
| Failure cases                          | Concrete examples, with images, of what it gets wrong.       |

**The two errors are not symmetric.** Predicting "passable" for an impassable
segment can leave a wheelchair user stranded. Predicting "impassable" for a
passable one costs a detour. The cost function, the thresholds and the reporting
must all reflect that asymmetry explicitly rather than optimising a symmetric
loss and hoping.

Route-level metrics matter too, and are not implied by segment metrics: route
feasibility rate, agreement with ground-truthed routes, and detour cost versus
the shortest path.

### Metrics are never invented

No number appears in the README, the interface, a PR or a presentation unless it
came from a recorded evaluation run against a named dataset version. No
placeholder accuracies. No "approximately 90%". No numbers from a paper about a
different city. If it was not measured here, it does not get stated.

## 7. Where a model would live

When Phase 3 arrives, the first implementation should be a **batch pipeline
writing predictions into PostGIS**, not a real-time inference service:

- Accessibility features change on the timescale of construction, not seconds.
- Batch inference is reproducible, auditable, and trivially rolled back by
  reverting to a previous prediction set.
- It keeps the routing hot path free of a network call to a model server.
- It defers the operational cost of a separate service until something needs it.

A separate inference service becomes justified only when predictions must be
produced on demand — for instance from a user-submitted photo. That is a
different phase.

## 8. Rollback

Every model deployment must be revertible to the previous prediction set, and
ultimately to Phase 1's deterministic behaviour, without a code change. If a
model is discovered to be systematically wrong about a neighbourhood, the fix
must be minutes, not a release cycle.

## 9. Before any model affects a real route

- [ ] Dataset versioned, licensed, and documented
- [ ] Labelling guidelines versioned; inter-annotator agreement measured
- [ ] Geographic hold-out evaluation, reported alongside the random-split number
- [ ] Calibration verified, not assumed
- [ ] Asymmetric error costs explicitly encoded
- [ ] Predictions stored separately from facts, tagged with model version
- [ ] Uncertainty surfaced to the user, not hidden
- [ ] Failure cases documented
- [ ] Rollback path tested
- [ ] Evaluated with disabled users, not only offline metrics

Until every box is ticked, PathAble is not an ML product, and must not say it is.
