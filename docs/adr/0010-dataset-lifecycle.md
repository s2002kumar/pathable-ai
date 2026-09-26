# ADR 0010 — Sealed candidates, a route-regression gate, and rollback

- **Status**: Accepted
- **Date**: 2026-09-26
- **Supersedes**: nothing; replaces the activation behaviour described in the README
  ("ingestion swaps activation in one transaction")
- **Related**: [KI-10](../development/KNOWN_ISSUES.md), [KI-7](../development/KNOWN_ISSUES.md),
  migration `0006_dataset_lifecycle`

## Context

The lifecycle promised that a network dataset is immutable once live, and the
serving cache is keyed by dataset id on that promise. PA-GEO-01 found four ways
it was not (KI-10): elevation was written into the live Waterloo dataset seven
minutes after activation; the checksum was computed at ingest and could not see
elevation or derived grade; a retired dataset could not be reactivated; and
nothing required a route regression before a dataset went live.

Overture synchronization (PA-GEO-03 onwards) will produce candidates far more
often than a hand-run import does. It cannot be built on a lifecycle whose
guarantee is a docstring.

## Decision

### A candidate is built, enriched, then sealed

Ingestion writes a **draft** and stops. It records what enrichment the
candidate requires (`ingestion_configuration.enrichment`; elevation is required
unless the operator says otherwise). Elevation is sampled into the draft — the
CLI resolves "the region's candidate" and never falls back to the live dataset.

**Sealing** validates the rows as stored (counts, topology within the dataset,
geometry, elevation recorded with its source, no grade without both endpoint
elevations, the required enrichment actually present), computes the content
checksum and moves the dataset to `validated`. A refusal leaves a fixable draft.

### The database enforces immutability

Triggers from migration 0006, not application discipline:

- graph rows may be inserted or updated only while their dataset is `draft`
  (or the transient `validating`), and deleted only while it is unreleased;
- a sealed dataset's defining columns cannot change, and its content checksum
  can be recorded once and never rewritten;
- status moves only along `draft → validated → active → retired → active`
  (plus `failed`), a dataset cannot be created active, and the live one cannot
  be deleted;
- the three evidence tables are append-only.

A restore into an empty database has to write sealed rows. It sets
`pathable.allow_sealed_writes = on` for its own session; that setting needs no
privilege and is used only by `restore-dataset.sh`. It is an escape hatch for
moving data, documented as such — any role that owns the tables could equally
drop the triggers, so this is protection against accident and against the
application, not against the database owner.

### Content checksum v2

A SHA-256 over canonical lines computed from the **stored rows after
enrichment**: every column routing reads, elevation and its source, derived
grade, the normalised conflict list and the name a route reports. Rows are
ordered by code point in PostgreSQL and the hasher refuses anything out of
order; floats are written exactly; geometry as little-endian WKB. Excluded
deliberately: lifecycle state and timestamps, row ids, raw tag blobs, the time
elevation was sampled, and OSM edit provenance — so activation cannot change
what a dataset _is_, and a rebuild that only adds provenance is recognisably the
same network. A unit test fails if a column is added to the graph tables
without being placed in or out of the contract.

The ingest `checksum` keeps its meaning and stays in the public API; the content
checksum is a second, versioned column. Changing the contract is version 3,
never an edit to version 2.

### Activation is gated on stored evidence, in three steps

1. **Evaluate** (expensive, outside the switch): route the region's journey
   corpus under the standard profile and every selectable profile, on the
   candidate and on the live dataset, and store both outcomes and every
   field-level difference against both content checksums, the corpus
   fingerprint (journeys, profiles, routing policy version, compared fields)
   and the app version.
2. **Accept**, only when routes differ or there is no live dataset: a person
   records a reason of at least 15 characters. There is no `--force`.
3. **Activate** (short, per-region `SELECT … FOR UPDATE`): re-read the candidate
   and the live dataset, refuse if the run is for other content, another
   corpus fingerprint or a live dataset that has since changed, then retire,
   activate and write an event. No routing, hashing or enrichment inside.

### Rollback reactivates; it never rebuilds

`datasets rollback` names a retired dataset that was once live (by default the
one the current dataset replaced), re-hashes its rows **before** the switch and
refuses unless they match the checksum it was sealed with, then switches in one
short transaction and records the reason. The serving cache may hand back the
graph it already holds for that id — correct, because the content under that id
cannot have changed.

### OSM edit provenance is captured at ingest, never invented

The PBF path records each node's version and edit time, each way's version and
edit time, and the latest edit across a way and every node it references
(unknown if any of them is). Elements written without metadata report version
0 and the epoch; both are stored as unknown. OSMnx queries Overpass with
`out;`, which returns no metadata, so the Overpass path records provenance as
not captured. Existing rows keep NULL.

## Consequences

- Measured once on the real Waterloo network
  ([`waterloo-dataset-lifecycle.json`](../evidence/waterloo-dataset-lifecycle.json)):
  a candidate rebuilt from the same extract and HRDEM mosaic sealed to the live
  dataset's content checksum exactly, its regression run found 120 of 120
  comparisons identical in 243 s, activation switched in 33.8 ms and rollback in
  31.7 ms after an 11.56 s re-hash.

- The legacy live dataset has no content checksum until an operator records one
  from its rows (`datasets checksum --record`); nothing can be compared against
  it or rolled back to until then. That is visible, not silent.
- Evaluation loads two city graphs one after the other, so a regression run
  costs roughly two graph loads plus the corpus; it is an operator step, not a
  request path.
- The route endpoint now takes its provenance from the dataset of the graph it
  routed on, not from a second read of "active" that an activation between the
  two reads would answer differently.
- There is no authentication, so acceptances and rollbacks record _why_ and
  _when_, not _who_. That is stated rather than faked with an invented user.
- Nothing here synchronizes Overture, updates a graph incrementally, conflates
  sources or makes a deployment zero-downtime.
