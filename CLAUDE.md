# PathAble AI — implementation guidance

Persistent guidance for Claude sessions working in this repository.

## Mission

Build PathAble as a real, public, accessibility-aware pedestrian-routing product
— not a demo, not a notebook, not a prototype that only works in a screenshot.
People may one day use it to decide whether they can physically make a journey.

## Source of truth

When guidance conflicts, follow this order:

1. The current explicit task card
2. This file
3. Current repository architecture and ADRs (`docs/adr/`)
4. Older documentation

A current task card overrides conflicting older guidance. Say so when you notice
the conflict; do not silently follow the stale version.

## Product integrity

These are not style preferences. They are what makes the product safe to use.

- **Missing accessibility information is `unknown`, never evidence of
  accessibility.** `unknown ≠ false`. An edge with no `surface` tag is not a
  smooth edge.
- **Never make a safety guarantee.** PathAble advises; it does not certify. No
  route is "accessible" without qualification.
- **Keep four things distinguishable** end to end — in the database, in the API,
  and in the UI: deterministic map facts, validated user reports, learned
  predictions, and user preferences. Once merged they cannot be unmerged.
- **Do not call the system ML-driven** until versioned model predictions actually
  change an edge's cost or feasibility. Deterministic rules over OSM tags are not
  machine learning, however sophisticated the cost function becomes.
- **Never invent a metric.** No accuracy, latency, coverage or evaluation number
  appears anywhere unless it came from a run you actually performed.
- **Preserve attribution and provenance.** OpenStreetMap data is ODbL and
  requires visible credit. Every dataset records where it came from and when.
- The two routing errors are not symmetric: telling someone a blocked path is
  passable is far worse than the reverse. Cost policy should reflect that.

## The gates

Gate A–E are the governing product outcomes. Each is defensible only on real
data, and none of them is complete because its code exists.

- **Gate A — real system.** A real regional OSM network, ingested from more than
  one acquisition path, with **elevation** as a required component and derived
  grade kept distinguishable from OSM-reported incline. _Passed 2026-08-20._
- **Gate B — hard differentiator.** Accessibility-aware routing that defensibly
  beats a shortest path. Dijkstra is the correctness baseline and **A\* is
  required** alongside it; the two must be proven to agree on optimal cost. Real
  route evaluation, real performance measurement and manual geometry inspection
  are part of the gate, not extras. _Passed 2026-08-20._
- **Gate C — ML credibility.** Requires versioned real imagery with a defensible
  licence chain, a labelled dataset, **geographic hold-out** (never a random
  split), a baseline before the model, **calibration**, failure analysis, a
  **rollback path**, and predictions that actually change an edge's cost. A model
  that trains but changes no route has not reached this gate.
- **Gate D — production credibility.** Requires observability, load testing, and
  backup, restore and rollback that have actually been exercised rather than
  documented.
- **Gate E — external credibility.** Requires genuine external validation —
  somebody outside this repository — plus a demo or video, published
  architecture and benchmarks, a technical article, and a research-style
  artifact. Nothing here may be claimed before it exists.

**Evidence and uncertainty are a required system layer, not a gate of their
own.** Every routing-relevant fact carries where it came from, whether it was
observed or derived, and when. A two-year-old observation is not a current fact,
and a route must be able to say so. Missing information is never evidence a path
is clear.

**A learned prediction never overwrites a deterministic map fact.** They are
stored apart, costed apart, and shown apart, so "OpenStreetMap says" and "a model
thinks" stay distinguishable in every response.

## Implementation approach

- **Bias hard toward working implementation.** A route that computes beats
  another page of architecture prose.
- Avoid premature infrastructure. No Redis, Celery, Kafka, Kubernetes, Airflow,
  Prefect, feature store or graph database until measurement demands one.
- Do not scaffold directories or services for future phases. Empty scaffolding
  advertises capability that does not exist.
- Keep the architecture modular but practical — a modular monolith, extracted
  only when a measurement justifies it (ADR 0002).
- Fix bugs you hit within scope rather than reporting an avoidable failure.
- Work through a task card's workstreams continuously. Do not stop at the first
  green milestone and ask what to do next.

## Testing

Protect behaviour, not coverage percentages.

- Test domain logic that would be expensive to get wrong: feature normalization,
  unknown-vs-false, cost functions, hard constraints, dataset lifecycle.
- Test migrations and geospatial behaviour against **real PostGIS**, not mocks.
- Keep the critical browser workflows covered, and keep them deterministic —
  no test may depend on a public tile server, a geocoder, or live OSM.
- Add a regression test whenever a real bug is found. Name the bug in the test.
- **Do not pad test counts.** A test that cannot fail is worse than no test.
- Maintain the existing gates: Ruff, mypy strict, ESLint, TypeScript strict,
  Prettier, coverage floors, contract drift, Docker build, security workflows.
  Do not weaken a gate because the codebase grew.

## GitHub workflow

- One feature branch per task card or coherent batch.
- Logical conventional commits. Tests ship with the implementation they cover, or
  in the commit immediately after.
- Push at meaningful checkpoints so CI runs throughout — not once at the end.
- Draft PR early; mark ready only when required checks are green.
- Never fabricate history, contributors, reviews or activity.
- Never force-push published work without explicit justification.
- The repository stays private until the founder decides otherwise.
- **No `Co-Authored-By: Claude` trailers and no "Generated with Claude Code"
  footers** in commits, PRs or issues unless the founder asks for them. This is
  the founder's work history, not a promotional surface.

## Documentation

- Keep it lean and useful. Update docs when behaviour, setup, architecture, data
  lineage or a consequential decision actually changes.
- ADRs are for consequential decisions only. If an existing ADR covers it, update
  that ADR rather than adding a near-duplicate.
- Delete stale documentation when you find it.
- Do not polish prose while product functionality is unfinished.

## When to interrupt the founder

The founder is usually studying. Interrupt **only** for:

- Credentials or accounts
- Anything that costs money
- Legal or licensing decisions (including choosing an open-source licence)
- Major irreversible architecture or product changes
- Material privacy or safety policy
- Making the repository public, or deploying it publicly

Everything else: decide, implement, document the important ones, keep going.

## Completion evidence

Every large card reports: starting and final SHA, commits, features, tests,
real measurements, architecture decisions, known limitations, external blockers,
and a recommended next milestone.

Never report a command as passing unless you observed it pass. Never infer a CI
result from a local run, a Docker result from a native run, or a current result
from a previous commit.

## Current state

**Gate A and Gate B are passed**, merged and tagged `v0.2.0-gate-ab`. PathAble
routes over a real 180,554-segment Waterloo network with 1 m LiDAR elevation.

Gate C work is on `feature/c01-ml-production-readiness`, alongside the Gate D
production track. See `docs/product/PHASES.md` for what exists and — more
importantly — what deliberately does not.
