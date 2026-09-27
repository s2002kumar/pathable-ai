# ADR 0011 — Accessibility evidence from several sources is kept as assertions, never merged

- **Status**: Accepted
- **Date**: 2026-09-27
- **Supersedes**: nothing
- **Related**: [`ACCESSIBILITY_EVIDENCE_RECONCILIATION.md`](../architecture/ACCESSIBILITY_EVIDENCE_RECONCILIATION.md),
  [`KITCHENER_CONFLATION.md`](../architecture/KITCHENER_CONFLATION.md) §11,
  [ADR 0008](0008-accessibility-cost-model.md), [`DATA_SOURCES.md`](../licensing/DATA_SOURCES.md) §11

## Context

PathAble routes on OpenStreetMap. PA-GEO-03 to -05 found a second source, the
City of Kitchener's Active Transportation inventory. It holds non-default
surfaces, curb cuts and structures, and a matcher can say which OSM elements a
City record describes. Sooner or later, some City assertions may be proposed as
routing evidence.

Three easy designs would each lose something that cannot be recovered:

- **merging** into one value per property — a precedence rule such as "City over
  OSM" — loses the other source's claim and hides every conflict;
- **agreement as confirmation** — PA-GEO-04 found most OSM geometry in Kitchener
  may share the City's own photographs, so two sources agreeing is often one
  source counted twice;
- **one "updated" date** — the City's `UPDATE_DATE` is a bulk maintenance day,
  and an OSM edit time is when OSM changed, not when anyone looked.

## Decision

1. **Each source's claim is an assertion.** It keeps the raw attribute and
   value, a normalized value only where the mapping is defensible, its value
   state, its evidence origin, typed dates and its source. A template default
   is kept and is never evidence.
2. **Reconciliation describes; it does not choose.** For one property at one
   local target, the assertions of each source sit side by side under a
   semantic relationship: agreement, compatible (with its specificity),
   conflict, incomparable, one source, or unknown. No source outranks another.
   A conflict stays open.
3. **Agreement and independence are separate fields.** The lineage relationship
   comes from OSM's edit history. It is never folded into the semantic
   relationship or turned into a confidence score.
4. **Physical correspondence and attribute agreement are separate questions.**
   A City stair may correspond to an OSM way tagged only `highway=footway` when
   geometry and topology make the identity clear. The stair is then an
   assertion only the City makes, because OSM's footway asserts nothing about
   steps. Ambiguity is about physical identity, not about the sources
   disagreeing.
5. **Scope stays local.** A curb cut attaches to its kerb node, and a surface
   to the metres of a way its record covers — never to a whole way.
6. **Dates keep their meaning.** Capture, observation, inspection, record
   maintenance and OSM edit times are different fields. Only an observation
   date is read as freshness.
7. **Nothing reaches routing by default.** Every reconciliation carries
   `not_routing_eligible` and the blockers that apply: licensing, validation,
   the absence of a routing policy, not a routing property. Research artifacts
   live outside anything routing reads, and static tests enforce it.

## Consequences

- Routing on any City assertion needs a later, explicit decision: the founder's
  licensing review, a validation step, and a routing policy saying which
  evidence classes may change feasibility or cost, and when. This ADR does not
  make that decision.
- A future routing policy can still weigh evidence classes differently — say,
  a surveyed OSM kerb over an undated administrative record — because nothing
  was merged away.
- The cost is size and some complexity. Assertions are stored per source, and
  a consumer must read relationships and lineage, not one value.
- Matcher v2 must implement decision 4 with a new, untouched held-out sample.
  PA-GEO-05's holdout is spent.
