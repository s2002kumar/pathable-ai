# Overture Maps and GERS

What PathAble reads from Overture, why, and what that reading can and cannot
establish. Every figure here is from the committed evidence —
[`waterloo-overture-linkage-2026-09-23.0.json`](../evidence/waterloo-overture-linkage-2026-09-23.0.json)
unless another release is named — and nothing is projected.

**Status (PA-GEO-01).** Read-only. PathAble inspects a bounded piece of a pinned
Overture release and measures how its own OSM identities appear there. Nothing
is synchronized, no dataset is written or activated, there is no migration, and
routing is unchanged.

---

## 1. Why Overture, and why OpenStreetMap stays the routing source

Overture is introduced for what PathAble does not have: **release-aware
identity** (GERS ids with a registry and a changelog), **change evidence**
between releases, and a cloud-native, release-pinned representation of the
transportation network to engineer against.

It is **not** an independent source of pedestrian accessibility evidence for
Waterloo. Its transportation segments there are built from OpenStreetMap, and
the few that are not carry none of the attributes examined — measured in §7a,
not assumed. An Overture attribute on an OSM-built segment is OpenStreetMap's
evidence under another name, and PathAble never counts it twice.

It does not replace OpenStreetMap as the routing source either, and the observed
schema says why. Overture's transportation `segment` carries `road_surface`,
`width_rules`, `level_rules`, `access_restrictions` and a `subclass` of
`sidewalk` or `crosswalk` — but no kerb, tactile paving, incline, smoothness,
lighting or step count, which are the attributes PathAble's cost model is built
on. And it does not carry indoor corridors or transit platforms: every PathAble
way absent from the 2026-09-23.0 sources (372 of 37,976) is `highway=corridor`
(207) or `highway=platform` (165).

## 2. Release identity

The release and its schema version come from Overture's STAC catalog
(`stac.overturemaps.org`), not a documentation page, and both the requested and
the observed release are recorded, so `latest` never survives into a manifest.

That was forced by the documentation disagreeing with itself. On 2026-09-25 the
[release calendar](https://docs.overturemaps.org/release-calendar/) listed
`2026-09-23.0` with schema `v1.18.0`; the catalog and the
[release notes](https://docs.overturemaps.org/blog/2026/09/23/release-notes/)
both say `2.0.0`. The older `labs.overturemaps.org/data/releases.json` is frozen
at `2026-07-22.0` and says so.

A schema version is a claim; the Parquet schema is the fact. Before reading, the
file schema is checked against a column contract (`geo/overture/contract.py`)
covering identity, provenance, topology, extent and geometry, down to nested
struct fields. A missing column or a changed type stops the run; an added column
is recorded. `2.0.0` was a major version, but its breaking changes were in places
and addresses: the transportation columns read here are identical in `1.18.0`
and `2.0.0`, and both releases were run.

**Retention, observed.** The catalog lists exactly two releases. Every release
file carries S3's lifecycle header — for `2026-09-23.0`,
`expiry-date="Mon, 23 Nov 2026 00:00:00 GMT", rule-id="release data 60 day
retention"`. Bridge files carry no expiry header and are listed back to
`2025-03-19.0-beta.0`, changelogs to `2024-06-13-beta.0`. Anything a GERS-based
pipeline needs from a release has to be captured while it is published.

## 3. What is read, and how it stays bounded

| Artifact     | How it is bounded                                                                  | 2026-09-23.0, Waterloo                                 |
| ------------ | ---------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Segments     | Catalog item bbox (1 of 128 files), then row-group statistics on the `bbox` struct | 29,334 rows of 91,163 in candidate row groups; 18.9 MB |
| Connectors   | The same (1 of 32 files)                                                           | 54,353 rows of 179,442; 9.7 MB                         |
| Changelog    | No catalog; all 640 footers read, row groups pruned on `bbox`                      | 83,732 rows; 54.6 MB                                   |
| Bridge (OSM) | Not bounded (§4). The first 2 of 96 files by name, as a cross-check                | 922 rows; 487.6 MB                                     |

Megabytes are bytes received, from DuckDB's own HTTP log. A feature is kept when
its bbox intersects the region's bounds — a box test, not a clip — and the bounds
are the pilot region's definition in `geo/regions.py`, never a second copy.

Every query is a constant string with bound parameters. The manifest records the
query, the parameters, each source file's ETag, size and expiry, and the SHA-256
of every output; two independent runs produced byte-identical outputs.

## 4. Bridge files: what they can and cannot establish

A bridge row says: this GERS id was built, at least partly, from this source
record. For OSM the `record_id` includes the element type and version —
`w1383497096@2` — and `between` is the part of the _segment_ that record covers.

What a bridge row cannot tell you:

- **Which part of the OSM way.** `dataset_between` is documented "reserved,
  always null", and was null on every sampled row.
- **Whether the source gave geometry or one property.** The bridge has no
  `property` column: 38 of 922 sampled rows were relations that only contributed
  `/routes`, indistinguishable there from a geometry source.
- **Anything about element versions from its `version` column**, which for OSM
  holds the planet label (`2026-09-09`), not an element version.

Bridge files are not spatially ordered — GERS ids are random UUIDs since
`2025-06-25.0` — so a regional read is a 23.4 GB scan. The docs say the bridge
is parsed from the features' own `sources`, so the linkage reads `sources` from
the bounded extract and checks the claim against a sample: all 922 sampled rows
matched a segment source (898 of 898 for `2026-08-19.0`).

## 5. The OSM version problem

PathAble stores an OSM way id per segment and an OSM node id per junction, and
**no version and no edit time**. From its own tables it can only say "Overture
cites the same way id": all 37,604 linked ways are `id_match_version_unknown`.

The dataset does record the SHA-256 of the extract it was built from, and that
file is still on disk. With `--osm-pbf`, and only when the hash matches, versions
are read from it — an OSM `(id, version)` pair never changes once published —
and a different extract is refused.

**A way's version is not its shape.** Moving one of a way's nodes changes the
way's geometry without changing the way's version. Overture's `update_time` on
an OSM way turned out to be the latest edit across the way _and its nodes_:
of 37,398 same-version ways it equalled the way's own edit on 25,387 and a
node's later edit on 11,985, and the remaining 26 were later than anything in
PathAble's snapshot. So `exact_version_match` requires the time to agree too.

**Overture's planet date is a label, not a cutoff.** The latest edit Overture
carries in the Waterloo extract is `2026-09-05T15:19:51Z` for a release labelled
`2026-09-09`, and `2026-08-01T22:45:54Z` for one labelled `2026-08-05`. The first
classifier treated the label as the cutoff and called eight `2026-08-19.0` ways
inconsistent; every one had a node edit on 2026-08-02..04, inside that gap. An
edit Overture does not show is now explained only after the label date,
inconsistent at or before an edit Overture demonstrably saw, and unverified in
between.

| Linked ways                                              | 2026-09-23.0 (24 days after PathAble) | 2026-08-19.0 (11 days before) |
| -------------------------------------------------------- | ------------------------------------: | ----------------------------: |
| `exact_version_match`                                    |                                37,372 |                        37,063 |
| `version_mismatch_pathable_older`                        |                                   206 |                             — |
| `version_mismatch_pathable_newer`                        |                                     — |                           431 |
| `way_version_match_nodes_edited_after_pathable_snapshot` |                                    26 |                             — |
| `way_version_match_nodes_edited_after_overture_snapshot` |                                     — |                            44 |
| `version_match_time_unverified`                          |                                     — |                             8 |
| `version_match_time_inconsistent`                        |                                     0 |                             0 |

## 6. Why GERS is not a graph-edge key

| 2026-09-23.0, Waterloo                                          |  Count |
| --------------------------------------------------------------- | -----: |
| Ways alone in exactly one segment (`one_to_one`)                | 19,449 |
| Ways sharing their only segment with other ways (`many_to_one`) | 16,266 |
| Ways split across 2–19 segments (`one_to_many`)                 |  1,553 |
| Both (`many_to_many`)                                           |    336 |
| Segments merging 2–33 OSM ways                                  |  4,733 |

A PathAble edge is a piece of one OSM way. When that way is split across
segments, picking the right segment needs the edge's position along the way,
which PathAble does not store: 28,162 of 180,554 edges are in that position, and
another 871 are on ways Overture does not carry. So the relationship is a
relation between identities, with its ranges kept, never a GERS column on an edge.

## 7. Other things the real data contained

- **Segments with no OSM identity.** 325 come only from TomTom (`provider=tomtom`,
  `resource=orbis`, licence `ODbL-1.0`, no `record_id`) and are reported as
  unresolved.
- **OSM records without a version.** `2026-08-19.0` has 48 way records like
  `w1546784695` with no `@version` and a null `update_time`; `2026-09-23.0` has
  none. They are counted as malformed and never matched.
- **Connectors without an OSM element.** 494 connectors cite OpenStreetMap with a
  null `record_id`, and 72 cite a node at `@0`, which is not an OSM version (169
  in `2026-08-19.0`). The id is kept; the "version" is not used.
- **The changelog agrees with the release.** Every current segment and connector
  in the region appears in the changelog as added, changed or unchanged; the
  extract checks this on every run. Of the segments linked to PathAble, 414
  changed data and 24 were added in `2026-09-23.0`.

## 7a. Does Overture add accessibility evidence independent of OSM?

Not in the Waterloo extracts measured. The linkage report's `source_independence`
section classifies every segment by the datasets behind its feature-level
sources, then counts where five examined attributes appear:

| 2026-09-23.0, Waterloo                             | Segments | On OSM-only segments | On segments with no OSM source |
| -------------------------------------------------- | -------: | -------------------: | -----------------------------: |
| Feature source: OpenStreetMap only                 |   29,009 |                    — |                              — |
| Feature source: TomTom only                        |      325 |                    — |                              — |
| Feature source: mixed                              |        0 |                    — |                              — |
| `road_surface` present                             |   16,006 |               16,006 |                              0 |
| `width_rules` present                              |      513 |                  513 |                              0 |
| `access_restrictions` present                      |    5,858 |                5,858 |                              0 |
| `subclass` sidewalk or crosswalk                   |    2,575 |                2,575 |                              0 |
| `class` steps                                      |      374 |                  374 |                              0 |
| Property-level contributions from non-OSM datasets |        0 |                    — |                              — |

`2026-08-19.0` gives the same answer: 28,971 OSM-only and 295 TomTom-only
segments, and no examined attribute on any of the TomTom ones. The only
property-level sources in either release are OSM route relations (`/routes`).
PathAble's own kerb, tactile-paving, incline, smoothness, lighting and
step-count attributes have no column in the observed segment schema at all.

**Scope.** One region, two releases, five attributes. This says nothing about
Overture in other regions, where other providers may contribute.

## 8. What later cards have to decide

Recorded so the schema follows the data rather than the other way round.

- **Dataset lifecycle (next).** The gaps this work surfaced
  ([KI-10](../development/KNOWN_ISSUES.md)), and capturing OSM element versions
  and edit times — including each way's latest member edit — at ingestion, so
  version evidence stops depending on a retained file.
- **Canonical evidence model.** How an external reference is keyed: source,
  source record id and version, GERS id where there is one, and both linear
  ranges, with cardinality as data rather than a column on `graph_edges`. It is
  a source-independent model; Overture's schema stays an intake format.
- **Synchronization.** Where upstream releases, fetched artifacts and their
  checksums live, and how Overture's changelog and PathAble's own snapshot diff
  are stored side by side as change events. Releases leave S3 after about 60
  days, so what a sync needs from one must be captured while it is published.
