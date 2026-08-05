# ADR 0006 — Waterloo is a configured default, never a hard-coded assumption

**Status:** Accepted · 2026-08-05 · Phase 0 (P0-A01)

## Context

The pilot region is Waterloo, Ontario. The obvious shortcut is to write its
coordinates into the map component and move on — it is one city, and Phase 0 has
no multi-region requirement.

That shortcut is how software becomes accidentally single-region. The constants
do not stay in the map component: they spread into ingestion bounding boxes, test
fixtures, seed data, cost-function tuning and default zoom levels. By the time a
second city is wanted, "make the region configurable" is a refactor touching
every layer, and it is always scheduled after something more urgent.

The cost of avoiding it now is close to zero. The cost of avoiding it in Phase 3
is a sprint.

There is also a product reason. PathAble exists because accessibility routing is
missing everywhere, not because it is missing in Waterloo. A codebase that can
only ever describe one city contradicts its own premise.

## Decision

**Every geographic value is configuration, with Waterloo as the default.**

Phase 0 surface:

| Variable                        | Default             | Validation                        |
| ------------------------------- | ------------------- | --------------------------------- |
| `NEXT_PUBLIC_PILOT_CENTER_LAT`  | `43.4668`           | finite, −90 … 90                  |
| `NEXT_PUBLIC_PILOT_CENTER_LON`  | `-80.5164`          | finite, −180 … 180                |
| `NEXT_PUBLIC_PILOT_ZOOM`        | `14`                | 0 … 22                            |
| `NEXT_PUBLIC_PILOT_REGION_NAME` | `Waterloo, Ontario` | 1 … 80 characters                 |
| `NEXT_PUBLIC_MAP_STYLE_URL`     | OpenFreeMap Liberty | absolute http(s) or root-relative |

The region name flows through to the page heading, the pilot chip, the map's
accessible name (`Interactive map of {region}`) and the written area description.
Nothing renders the string "Waterloo" from a literal in a component.

Invalid values do not fall back silently — they render a configuration error page
naming every offending variable. A silent fallback would put the map somewhere
plausible-looking and wrong, which for a routing product is worse than an error.

### Extends to every later phase

- **Ingestion** takes a region bounding box as a parameter; no hard-coded extent.
- **Graph tables** carry a region identifier from the first migration that
  creates them.
- **Datasets** record their region in the manifest.
- **Model evaluation** uses a held-out _region_, which is only possible if region
  is a first-class dimension (see the ML architecture document).

That last point is the strongest argument: leakage-safe evaluation requires
geography to be a real dimension in the data model. Hard-coding the pilot would
make honest evaluation structurally impossible later.

## Consequences

**Positive**

- Repointing the application at another city is an environment change.
- Region is a first-class concept, which geographic hold-out evaluation requires.
- Tests can use other regions to prove nothing is Waterloo-specific — the
  frontend suite asserts this with Vancouver.
- The accessible map name is correct for whatever region is configured.

**Negative**

- Slightly more configuration than a single-city build needs today, and one more
  validation path.
- `NEXT_PUBLIC_*` values are inlined at build time, so changing the region needs
  a rebuild. Acceptable: region changes are rare and deliberate.

**Reversibility.** Not applicable in the usual sense — this is a constraint that
gets cheaper to keep and more expensive to add later.

## What is _not_ claimed

Configurable ≠ supported. Pointing the map at Vancouver renders Vancouver, and
nothing else works there: no graph, no data, no routing. The interface does not
suggest otherwise, and the pilot description is written for the configured region
rather than implying coverage.

## Alternatives considered

**Hard-code Waterloo, generalise later.** Cheapest today, and the refactor cost
compounds across every layer that quietly adopts the constant. Rejected.

**A regions table in the database now.** The right eventual shape, premature in
Phase 0 — there is no ingestion and no graph for a region row to describe. The
environment variables are the same concept at the current scale, and migrate
naturally into a table in Phase 0.5.

**A build-time region config file per city.** More structure than one region
needs; revisit when there are three.
