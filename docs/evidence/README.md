# Evidence

Measurements and captures from the real Waterloo dataset. Every number here came
from a run that actually happened; nothing is estimated or projected.

**Attribution, and whose work this is.** Every route, coverage figure and
screenshot here derives from OpenStreetMap data — © OpenStreetMap contributors,
ODbL 1.0 — and the JSON files that carry map-derived content are themselves
**ODbL-derived data, not PathAble's own work**. Gradients come from NRCan HRDEM:
_Contains information licensed under the Open Government Licence – Canada._
PathAble's source code is separately © Sandeep Kumar, all rights reserved; the
two licences are independent and neither overrides the other. See
[`LICENSING.md`](../../LICENSING.md).

**Overture-derived files.** The four `waterloo-overture-*` files hold counts,
identifiers and a few examples derived from Overture Maps transportation data,
which is ODbL 1.0: _© OpenStreetMap contributors. Available under the Open
Database License. Data from TomTom. Overture Maps Foundation, overturemaps.org._
See [`DATA_SOURCES.md` §10](../licensing/DATA_SOURCES.md).

**Kitchener-derived files.** The `kitchener-*` files hold the City of Kitchener's
published schema, counts and distributions from its Active Transportation
inventory, and 80 sampled records with their geometry: _Contains information
licensed under the Open Government Licence – The Corporation of the City of
Kitchener._ Credit is optional under that licence and given voluntarily. Their
proximity figures also read PathAble's OpenStreetMap graph, and PA-GEO-04's
lineage, label and review files hold OSM ways, tags and findings from OSM edit
history: © OpenStreetMap contributors, ODbL 1.0. PA-GEO-04's Esri imagery file
holds facts from Esri's imagery metadata, cited to Esri, and no imagery.
PA-GEO-05's sample, label, benchmark and failure files hold City records and
the OSM ways, nodes and tags they were matched against. See
[`DATA_SOURCES.md` §11 and §12](../licensing/DATA_SOURCES.md).

**Every file here is regenerated after any change that could move it.** Two were
briefly wrong and are worth naming: the coverage report was first run before
elevation had been applied, so it recorded 0% for elevation-derived grade; and
the geometry inspection was first run before the snapped-segment fix, so it
recorded 12 failures. Both were regenerated against the final code. Evidence
that lags the thing it describes is worse than no evidence, because it is
believed.

**Dataset under test**

|                   |                                                                                 |
| ----------------- | ------------------------------------------------------------------------------- |
| Dataset           | `51585450-8ff5-409d-a02e-66d5a3c5e260`                                          |
| PathAble checksum | `51e75f7896ab725d29120fe4363c607bea68eed260d830482d6677f827d2e906`              |
| Source            | Geofabrik `ontario-latest.osm.pbf`, 969,572,077 bytes                           |
| Source SHA-256    | `cee90e3725139c41ef939f726730b4dfb6fd45e624d2797dac4be38a69145ef3`              |
| Publisher MD5     | `77f4f43c811a9161f4bf0ecae42ebaab` — matched the publisher's own listing        |
| Extract timestamp | 2026-08-16T23:08:23Z                                                            |
| Ingested          | 2026-08-17                                                                      |
| Size              | 155,714 nodes · 180,554 physical segments · 361,108 directed edges · 3,363.7 km |
| Elevation         | NRCan HRDEM `hrdem-mosaic-1m-dtm`, 1 m LiDAR, sampled 2026-08-17                |

---

## Files

| File                                                                                 | What it is                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `waterloo-coverage.json`                                                             | What OpenStreetMap records for the region, per category. Produced by `pathable coverage --region waterloo`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `waterloo-routes.json`                                                               | Twenty real journeys under the standard and wheelchair profiles, plus the Dijkstra/A\* comparison and the unknown-penalty ablation. Produced by `pathable evaluate --region waterloo --algorithms --ablate`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `waterloo-performance.json`                                                          | Latency, memory and throughput measured on this machine. Its `graph_load` block is the 2026-08-17 figure, measured under tracemalloc; superseded by the file below.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `waterloo-graph-load.json`                                                           | Cold-start cost: loading the dataset into the routing graph, three timed runs plus one under tracemalloc, with the machine conditions and a content fingerprint. Produced by `pathable benchmark load --region waterloo --json docs/evidence/waterloo-graph-load.json`.                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `waterloo-graph-load-before.json`                                                    | The same command run at `1ee1d65`, whose loader is identical to `main`'s, minutes before the Core-column loader was applied. Kept so the before/after pair can be checked, not only asserted.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `production-envelope.json`                                                           | The production API image measured in an isolated Compose stack from an empty database: migration, cold start to live and to ready, graph preload, resident memory per process and per cgroup, memory-limit and worker-count runs, warm and concurrent route latency, restart and shutdown — plus three frontend cold starts under a 512 MiB cap (`measure_web.py`) and the managed-hosting restore, performed as a role that is not a superuser (`restore-dataset.sh`). Produced by `python infra/production-smoke/measure.py`; procedure in [`docs/deployment/PRODUCTION_SMOKE.md`](../deployment/PRODUCTION_SMOKE.md), decision in [ADR 0009](../adr/0009-deployment-architecture.md). |
| `waterloo-overture-extract-2026-09-23.0.json`                                        | Reproducibility manifest for one bounded read of Overture release `2026-09-23.0` (schema `2.0.0`) over the Waterloo pilot box: requested and observed release, the column-contract result, every source file with its ETag, size and S3 expiry, the exact query and parameters, rows, bytes received, and the SHA-256 of each output. Produced by `pathable overture extract --region waterloo --release 2026-09-23.0`; the regional Parquet it describes stays out of git.                                                                                                                                                                                                              |
| `waterloo-overture-extract-2026-08-19.0.json`                                        | The same for release `2026-08-19.0` (schema `1.18.0`), which Overture removes from public distribution about 60 days after release.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `waterloo-overture-linkage-2026-09-23.0.json`                                        | How the dataset's stored OSM identities appear in that release's own provenance: identity, cardinality with linear ranges, version and edit-time status, malformed and unresolved source rows, source independence, and changelog and bridge cross-checks. Produced by `pathable overture link --region waterloo --extract <folder> --osm-pbf <source extract> --json …`, reading PathAble in a read-only transaction.                                                                                                                                                                                                                                                                   |
| `waterloo-overture-linkage-2026-08-19.0.json`                                        | The same against `2026-08-19.0`, whose OSM snapshot is older than PathAble's rather than newer.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `kitchener-active-transport-snapshot.json`                                           | Manifest of one frozen snapshot of the City of Kitchener's `Active_Transportation` and `Walkability` publications: portal items, layer schema with template defaults and domains, edit dates, the column-contract result, completeness per publication, every raw page's SHA-256, the licence check, and the archived documents with their hashes. Produced by `pathable kitchener snapshot`; the snapshot folder it describes stays out of git.                                                                                                                                                                                                                                         |
| `kitchener-active-transport-normalized.json`                                         | Manifest of the GeoParquet 1.1.0 file normalized from that snapshot: input hashes, output SHA-256, the `geo` metadata, the CRS pipeline and its stated accuracy, columns, and join results. Produced by `pathable kitchener normalize`.                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `kitchener-active-transport-profile.json`                                            | PA-GEO-03's profile: value states per field, the default-value investigation, provenance and freshness, evidence origin, plausibility, physical and virtual classes, the study area and descriptive overlap with PathAble's graph, the field adoption matrix and the exit-gate figures. Produced by `pathable kitchener audit`, reading PathAble in a read-only transaction.                                                                                                                                                                                                                                                                                                             |
| `kitchener-geo04-sample.geojson`                                                     | The deterministic, stratified 80-record sample for PA-GEO-04's manual geometry and OSM-lineage inspection, with its method, seed and strata in the file.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `kitchener-geo04-lineage.json`                                                       | PA-GEO-04's evidence: the frozen inputs on both sides, every OSM candidate within 25 m of each sampled record with its signals, the reviewer's labels, topology facts, attribute comparisons, geometry and attribute lineage from OSM history, repeat-label consistency, what the labels say about each matching signal, and in-area proximity context. Produced by `pathable kitchener lineage-study`.                                                                                                                                                                                                                                                                                  |
| `kitchener-geo04-labels.json`                                                        | The labels the study's results use: the first pass with label definitions version 2 applied to all 80 records, and one error the repeat review found corrected. Each of the six revisions carries its reason and its before and after.                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `kitchener-geo04-first-pass-labels.json`                                             | The first manual pass over all 80 records, as labelled under definitions version 1, with who labelled them, how, and the two refinements made during the pass.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `kitchener-geo04-repeat-labels.json`                                                 | The second pass over a deterministic 40-record subset, labelled blind to the first, as labelled.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `kitchener-geo04-repeat-refined-labels.json`                                         | The same 40 records, re-reviewed by the second pass under definitions version 2, still blind to the first pass.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `kitchener-geo04-review.html`                                                        | The static review page: one map and one set of tables per record, drawn from the two datasets — no basemap, no imagery, nothing fetched. Open it in a browser.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `kitchener-geo04-esri-imagery.json`                                                  | Which photographs Esri World Imagery's finest layer showed over Kitchener, now and in the first and last archived release of each year since 2014, at three points: source, credit, date and resolution, cited to Esri. Metadata only; no imagery was retrieved. Produced by `pathable kitchener imagery-metadata`.                                                                                                                                                                                                                                                                                                                                                                      |
| `kitchener-geo05-holdout.geojson`                                                    | PA-GEO-05's held-out sample: 193 eligible records, none from the development set, drawn in 14 strata before any tuning, with the seed, strata and size rationale in the file. Produced by `pathable kitchener holdout`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `kitchener-geo05-labelling-guide.md`                                                 | The label definitions and instructions the blind labellers worked under, frozen before labelling.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `kitchener-geo05-holdout-review.html`                                                | The blind review page for the held-out records: maps and candidate tables, no strata, no labels, no matcher output. Produced by `pathable kitchener holdout-review`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `kitchener-geo05-development-labels.json`                                            | PA-GEO-04's labels for the 58 eligible development records in PA-GEO-05's schema, with four recorded conversions. The only labels any threshold was tuned on.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `kitchener-geo05-holdout-labels.json`                                                | The frozen blind labels for all 193 held-out records, by five AI instances (one pack each), with every pack's inputs hashed. Committed before the matcher saw a held-out record. AI labels, not human ground truth.                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `kitchener-geo05-holdout-repeat-labels.json`                                         | A 60-record subset labelled again, blind, by two more AI instances: the consistency of the procedure, not inter-rater reliability.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `kitchener-geo05-benchmark.json`                                                     | PA-GEO-05's evidence: the development check, candidate recall, baselines, the frozen matcher and its ablations per class, stratum and labelling pack, every failure with its cause, repeat-label consistency, attributes after matching, and the full-pilot dry run. Produced by `pathable kitchener benchmark`.                                                                                                                                                                                                                                                                                                                                                                         |
| `kitchener-geo05-failure-analysis.json`                                              | One cause for each of the 43 held-out failures, written after the single evaluation and bound to its decisions by hash.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `kitchener-geo05-errors.html`                                                        | Every held-out failure drawn: the City record, what the labeller named, what the matcher named. Open it in a browser.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `kitchener-geo06-reconciliation.json`                                                | PA-GEO-06's evidence: the inputs and versions it is bound to, the accepted-input accounting per class, every reconciliation outcome per topic, lineage, typed dates, potential coverage, every observed value pair, all 257 conflicts in full, routing blockers, and the artifact's hashes. Produced by `pathable kitchener reconcile`.                                                                                                                                                                                                                                                                                                                                                  |
| `kitchener-geo07-shadow-routing.json`                                                | PA-GEO-07's evidence: the inputs it is bound to, how surface enters routing today, the overlay's accounting per City assertion and segment, both corpora, every journey-profile category, every route change with its cause, the hard-constraint records, information gain, the conflict sensitivity, the validation queue, algorithm agreement, production isolation and timings. Produced by `pathable kitchener shadow-routing`.                                                                                                                                                                                                                                                      |
| `kitchener-geo07-route-changes.html`                                                 | Representative shadow route changes drawn over OSM geometry, watermarked as a research counterfactual. Open it in a browser.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `kitchener-geo08-holdout.geojson`                                                    | PA-GEO-08's new held-out sample: 186 records from records neither earlier sample holds, 18 strata, the situation signals each was drawn on, and why the sample is the size it is. Produced by `pathable kitchener matcher-v2-holdout`.                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `kitchener-geo08-labelling-guide.md`                                                 | Definitions version 2, as the blind labellers read them.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `kitchener-geo08-holdout-review.html`                                                | The blind review page for the held-out records: no stratum, no matcher output, candidates in OSM-id order.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `kitchener-geo08-development-labels.json`                                            | PA-GEO-04's and PA-GEO-05's labels re-read under definitions version 2, with all 15 changes recorded: matcher v2's development set.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `kitchener-geo08-holdout-labels.json` / `kitchener-geo08-holdout-repeat-labels.json` | The blind held-out labels, five packs, and the 60-record repeat pass, bound to the sample, the guide and the blind material by hash.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `kitchener-geo08-matcher-v2.json`                                                    | PA-GEO-08's evidence: the development check, candidate recall, baselines, matcher v1 frozen, matcher v2 and its ablations per class and stratum, every failure with its cause, repeat-label consistency, and the full-pilot dry run with its potential evidence. Produced by `pathable kitchener matcher-v2-benchmark`.                                                                                                                                                                                                                                                                                                                                                                  |
| `kitchener-geo08-failure-analysis.json`                                              | One cause for each of matcher v2's 37 held-out failures, written after the single evaluation and bound to its decisions by hash.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `kitchener-geo08-errors.html`                                                        | Every matcher-v2 held-out failure drawn: the City record, what the labeller named, what v2 named.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `waterloo-geometry-inspection.json`                                                  | Every routable journey checked against its own geometry: continuity, seams, drawn-vs-reported length, and profile violations.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `waterloo-dataset-lifecycle.json`                                                    | PA-GEO-02 on the real dataset, in a disposable database: the 0006 upgrade over the legacy rows, the legacy content checksum recorded from its rows, a candidate rebuilt from the same extract with OSM edit provenance, refused a seal until elevated, sealed to the legacy checksum exactly, judged identical on 120 route comparisons, activated, rolled back, the database refusing edits to sealed rows, and the restore script run as a role that is not a superuser. Every figure is parsed from the run's own command output or read back from the database, none typed in; the procedure is the command sequence in the README. ODbL-derived.                                    |
| `screenshots/`                                                                       | The real product answering from this dataset. The `demo-*` captures are the PA-RR-06 recruiter journey; their provenance is in [`screenshots/DEMO_PROVENANCE.md`](screenshots/DEMO_PROVENANCE.md).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `media/`                                                                             | `pathable-demo.webm` — a 67-second recording of one real browser session against the real production containers, captured by Playwright's video recorder, not edited or spliced — and `pathable-demo.gif`, a 13.5-second excerpt of it cut for the README, because GitHub will not preview a video that size in the browser. Provenance, capture command and licence obligations in [`screenshots/DEMO_PROVENANCE.md`](screenshots/DEMO_PROVENANCE.md).                                                                                                                                                                                                                                  |
| `FRONTEND_POLISH.md`                                                                 | The PA-UX-01 map-first frontend candidate: what changed and why, before/after captures at desktop, tablet and phone sizes, the measurement procedure and its local results, and what the candidate does not claim.                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `DEMO_SCRIPT.md`                                                                     | How to show the product in about sixty seconds on the local production stack, and what may and may not be claimed while doing it.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |

---

## Overture linkage (PA-GEO-01)

**Version evidence comes from outside the database.** PathAble stores no OSM
versions. The linkage files establish them from the dataset's own source extract,
`ontario-latest.osm.pbf`, which the command refuses to read unless its SHA-256
matches the one recorded at ingestion (`cee90e37…`, above). Without that file the
same command reports every identity match as `id_match_version_unknown`, and the
report carries that view too (`by_version_status_from_stored_identities_only`).

**Reproducing.** Extraction needs network access to Overture's public bucket and
no database; linkage needs the database and no network. Both files record the
commit, DuckDB and `httpfs` versions, machine and peak process memory. Three
extractions of `2026-09-23.0` and two of `2026-08-19.0` produced byte-identical
outputs. The releases themselves leave Overture's bucket about 60 days after
publication — `2026-09-23.0` on 2026-11-23 by its S3 lifecycle header — after
which the manifests remain an exact record of what was read, but the read cannot
be repeated.

**Scope.** What these files show, and do not, is stated inside each linkage file
(`what_this_shows`, `what_this_does_not_show`, `source_independence.scope`) and in
[`OVERTURE_GERS.md`](../architecture/OVERTURE_GERS.md).

---

## Kitchener source audit (PA-GEO-03)

**Reproducing.** From `services/api`:

```
pathable kitchener snapshot
pathable kitchener normalize --snapshot <snapshot> --out <new folder>
pathable kitchener audit --region waterloo --snapshot <snapshot> --normalized <folder> \
    --json <profile.json> --sample <sample.geojson>
```

`snapshot` needs the network and no database; `normalize` needs neither. `audit`
needs the database, read in a `READ ONLY` transaction using only columns that
exist from migration 0005 on. This run read the production-smoke database, which
is still at 0005 and was not migrated.

**Which run produced what.**

- The snapshot and normalized manifests come from clean commit `65ba0d4`.
- The profile and sample come from clean commit `4a68d4f`.
- Between the two commits only a printed message and the wording of adoption
  rationales changed. The snapshot and normalization code is identical.
- The profile was last regenerated to carry the corrected geometry rationale.
  Compared with the previous run, only that rationale and the content hash
  covering it changed; every measured figure is identical, and the sample is
  byte-identical.

**Reproduced.**

- **Snapshot.** Two retrievals 40 s apart gave identical feature files, raw pages
  and documents.
- **Normalization.** Three normalizations of the one snapshot gave byte-identical
  GeoParquet files.
- **Audit.** Every audit of the one snapshot gave the same profile content hash,
  and a byte-identical sample.
- **PathAble's data.** The dataset rows of the database read were compared before
  and after, and had not changed.

**Scope.** What these files show, and do not, is stated inside the profile
(`what_this_shows`, `what_this_does_not_show`, and the `label` of every proximity
figure) and in
[`KITCHENER_ACTIVE_TRANSPORT.md`](../architecture/KITCHENER_ACTIVE_TRANSPORT.md).

---

## Kitchener lineage study (PA-GEO-04)

**Reproducing.** From `services/api`, with the PA-GEO-03 snapshot normalized and
the dataset's own source extract at hand:

```
pathable kitchener lineage-extract --region waterloo --pbf <ontario-latest.osm.pbf> \
    --out <study-extract.jsonl.gz> --json <manifest.json>
pathable kitchener lineage-study --sample ../../docs/evidence/kitchener-geo04-sample.geojson \
    --sample-sha256 5c8f5e3548a4f7cf31fd23e1ab7634d8ce9118b71c30ae249a08ca3bef0b4d2c \
    --normalized <folder> --extract <study-extract.jsonl.gz> --extract-manifest <manifest.json> \
    --json <candidates.json> --full-json <candidates-full.json>
pathable kitchener lineage-history --study <candidates-full.json> --extract <…> \
    --extract-manifest <…> --dump <changesets-260921.osm.bz2> --out <history.json>
pathable kitchener imagery-metadata --json <esri-imagery.json>
pathable kitchener lineage-study <the same inputs> --history <history.json> \
    --labels ../../docs/evidence/kitchener-geo04-labels.json \
    --first-pass-labels ../../docs/evidence/kitchener-geo04-first-pass-labels.json \
    --repeat-labels ../../docs/evidence/kitchener-geo04-repeat-labels.json \
    --repeat-refined-labels ../../docs/evidence/kitchener-geo04-repeat-refined-labels.json \
    --json <lineage.json> --html <review.html>
```

What each command needs:

- **`lineage-extract`** needs the database, which it reads in a `READ ONLY`
  transaction, and the PBF whose SHA-256 the dataset recorded.
- **`lineage-history`** needs the network for ohsome, and the planet changeset
  dump on disk (8.8 GB). It keeps ohsome's answers by request hash, so a re-run
  reads nothing it has already read.
- **`imagery-metadata`** needs only the network.
- **`lineage-study`** needs neither.

The history file holds changeset comments and stays out of git. So do the
extract, the dump and its stream index.

**Which run produced what.** The committed lineage evidence and review page came
from the code at commit `8544a85`, with the label files committed beside them.
Two runs gave the same content hash (`b216e21e…`) and byte-identical review
pages. That commit changed only the wording of the lineage definition and the
scope statement: every measured figure is identical to the run at `f3ab6dd`
(`2b093d52…`). The Esri metadata was read at `dc9fca3`; the later commits did
not change the metadata command. Two study extracts from the source PBF were
byte-identical.

**Scope.** What the study shows, and does not, is stated inside the evidence
file (`scope`), on the review page, and in
[`KITCHENER_OSM_LINEAGE.md`](../architecture/KITCHENER_OSM_LINEAGE.md). The
labels are an AI model's, made twice. Every proportion describes a stratified
sample, not the City's inventory.

---

## Kitchener conflation benchmark (PA-GEO-05)

**Reproducing.** The commands are in
[`KITCHENER_CONFLATION.md`](../architecture/KITCHENER_CONFLATION.md) §13. None
needs the database or the network. `benchmark` reads the committed sample and
label files from this folder, refuses labels made for another sample or under
another guide, and refuses to score unless the development grid still selects
the frozen policy.

**Which run produced what.** The held-out sample came from `e9c22d9` and the
labels were frozen at `8e27133`. The single held-out evaluation ran from
`08e2dd6` with a clean tree: decisions `0145279b…`. A second run from the same
commit attached the failure analysis. It reproduced every decision, every
metric and all four research-artifact files byte for byte, and its content hash
is `6b43fac3…`. The artifact itself stays in the ignored data folder.

**Dates in the PA-GEO-04 and PA-GEO-05 files.** Both cards formatted the City's
`SOURCE_DATE` and `CREATE_DATE` in the laptop's time zone (America/Toronto).
The City stores `SOURCE_DATE` at midnight UTC, so in these files it reads one
day early, and `CREATE_DATE` is local time. PA-GEO-06 found and fixed this
(`fe55f20`). The files are left as produced. No match, label or metric reads
a date; PA-GEO-04's rule that an OSM shape older than the City's record is
independent compares against the date, and can be off by that day.

**Scope.** Counts over a stratified sample scored against AI labels. They are
not proportions of the City's inventory and not field-verified accuracy.
Intervals are sampling uncertainty conditional on the labels.

## Accessibility evidence reconciliation (PA-GEO-06)

**Reproducing.** The commands are in
[`ACCESSIBILITY_EVIDENCE_RECONCILIATION.md`](../architecture/ACCESSIBILITY_EVIDENCE_RECONCILIATION.md)
§14. `reconcile-history` reads the ohsome API and the local planet changeset
dump; `reconcile` needs neither the network nor the database. It refuses a
PA-GEO-05 artifact whose files do not match its manifest, and inputs other than
those the artifact was made from.

**Which run produced what.** Two runs from `fe55f20`, with a clean tree and the
same history file (`9f382a3b…`), wrote byte-identical artifacts. The second
recorded the comparison, and both have content hash `6bb58d6f…`. The artifact
— City and OSM values in one table — stays in the ignored data folder.

**Scope.** Every correspondence the class gates accept in the full pilot, as
PA-GEO-05's frozen matcher decided them. None of it is field-verified.
Relationships come from the written vocabulary, and lineage is what OSM's edit
metadata states. Coverage is potential evidence coverage, not validated or
routing coverage.

---

## Municipal surface evidence shadow routing (PA-GEO-07)

**Reproducing.** The command is in
[`SURFACE_SHADOW_ROUTING.md`](../architecture/SURFACE_SHADOW_ROUTING.md) §14.
It reads the active dataset inside read-only transactions, PA-GEO-06's artifact
(refused unless its files match both its manifest and the committed evidence)
and PA-GEO-04's study extract. It writes nothing to the database.

**Which run produced what.** Both files come from one run, from `f89a625` on
a clean tree: content hash `7f1371f5…`, results digest `421713c9…`. Its
`run.determinism` compares it with an earlier run from `12caea3`. Every
journey-profile outcome, route change and corpus is identical, and only the
wording of the explanations differs, which `f89a625` corrected. That earlier
run had the same results digest and corpora as a third, from `cdcd0f7`.
Neither earlier run is committed.

**Scope.** A counterfactual: the City's surfaces are treated as accepted only to
measure what accepting them would do. None is validated, both corpora are
engineering samples rather than trips, and no shadow route is advice. The
evidence names OSM segments and City record numbers but holds no City geometry;
the page draws a few routes over OSM geometry.

---

## Accessibility conflation matcher v2 (PA-GEO-08)

**Reproducing.** The commands are in
[`KITCHENER_MATCHER_V2.md`](../architecture/KITCHENER_MATCHER_V2.md) §13; none
needs the database or the network. The benchmark refuses labels made for another
sample or guide, and a failure analysis made for other decisions.

**Which run produced what.** The single held-out evaluation ran from `2d4d5f0`
with a clean tree (decisions `5c64cc03…`). The committed evidence is a second
run from `3728dba`, with the failure analysis attached: it reproduced those
decisions, every metric and the pilot's decisions (`06440e4f…`).

**Scope.** 186 records weighted to what matcher v1 could not settle, scored
against blind AI labels, not people. Nothing is field-verified, no figure is a
population rate, and nothing reaches routing.

---

## Screenshots

Captured by `apps/web/tests/screenshots/real-waterloo.spec.ts` (removed in PA-UX-04 with the
interface it drove; last present at `cd54879`) against the running API and the active dataset.
The current interface's captures are in `screenshots/ux-04/`, from `ux-04-states.spec.ts`. No API responses are stubbed — a screenshot of a
synthetic fixture would be a picture of nothing.

| File                        | What it shows                                                                                                                                                                            |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `01-desktop-wheelchair.png` | A 366 m wheelchair route on real network, with per-category evidence gaps                                                                                                                |
| `02-mobile-wheelchair.png`  | The same journey at 390 px wide                                                                                                                                                          |
| `03-desktop-stroller.png`   | A second profile on a different journey                                                                                                                                                  |
| `04-route-difference.png`   | A journey where the accessible route differs measurably                                                                                                                                  |
| `05-missing-evidence.png`   | A journey where the map is substantially silent — and, in the same frame, the snapping caution: the route begins at the nearest mapped path, some distance from the point the user chose |

Screenshots were re-captured after the geometry fix below, so every line shown
is continuous.

**A gap worth naming, and a duplicate removed.** The screenshot spec's sixth
capture is meant to show a genuine no-route case. There is a real one —
`conestoga-to-rim-park` in `waterloo-routes.json` — but it cannot be reproduced
through the interface: Rim Park sits in a separate 1,887-node component because
its connection to the rest of the network leaves the pilot bounding box and was
clipped, and placing a point there needs the map driven to specific coordinates,
which the app has no deep-link for. The two points the spec uses instead do
route, so the capture came out **byte-identical to `05-missing-evidence.png`**.
It was committed anyway under the name
`06-snapped-away-from-the-chosen-point.png` and listed here as a separate
capture, which it was not.

That file has been deleted and its description folded into the row above, which
is the frame that actually carries both statements. The no-route case remains
real, measured and reported in the route corpus; only a screenshot of it is
missing, and nothing here should be read as supplying one.

---

## Recording

`media/pathable-demo.webm` — 66.8 s, VP9, 1152x684, 2,227,364 bytes.

`media/pathable-demo.gif` — 13.5 s, 720x428, 6 fps, 2,132,771 bytes. The same recording from t=10.5 s: the offer
on screen, the press, and the answer arriving. It exists because GitHub's blob view refuses to preview a video
this size and its raw URL downloads rather than plays, so a linked video is a dead end for anyone reading the
README. A GIF renders inline for an anonymous visitor with no click at all. It is an excerpt, not a separate
capture, and it is not the evidence — the WebM is.

One continuous browser session, recorded by Playwright's video recorder while
the page drove the production containers over HTTP. There is no editing, no
splice and no re-take stitched in: what the engine returned is what the
recording shows, and had it returned something else the recording would show
that instead. The capture script, the commit it ran at, and the basemap
attribution obligations are in
[`screenshots/DEMO_PROVENANCE.md`](screenshots/DEMO_PROVENANCE.md).

It is a recording of a **local production-build stack**, not of a deployment.
Nothing in it is reachable from the internet.

---

## Headline findings

**Loading the graph now takes about half the time and half the heap.** The
same 180,554 segments load with a peak Python heap of **700.7 MB against
1,381.3 MB** before (−49%), and in a **median 22.1 s against 46.8 s** on the
same laptop, same dataset, the same afternoon — best run to best run, 21.4 s
against 35.0 s (−39%). Resident memory settles at about 850 MB after a load,
with a transient peak near 1.1 GB while the rows stream in. Every run started
with under 10% of physical memory free, which each report flags, so the
conservative figure is the best-run one and the wall-clock is this laptop's,
not a server's. Both loads carry the same SHA-256 fingerprint of every node
and every segment (`88f63bcaed9ce3ce…` / `972e3e41d4728b3b…`), and the
twenty-journey corpus routes identically. The change is a narrow Core-column
read instead of ORM entities, WKB instead of WKT, and leaving the 765,290-entry
OSM tag blob in the database where it is provenance. The 97.5 s previously
recorded in `waterloo-performance.json` was measured under tracemalloc, which
the new command shows costs 2.5–6× on this load; it never described the
service's real cold start.

**Grade was effectively absent before elevation.** OpenStreetMap records an
`incline` on 46 of 180,554 segments — 0.03%. After sampling HRDEM, 97,131
segments (53.8%) carry a derived grade, kept in a separate column from the OSM
value and never allowed to overwrite it.

**Vehicle one-ways would have wrongly restricted 13,579 segments.** Waterloo's
data contains no `oneway:foot`, no `conveying`, and no `foot:forward` /
`foot:backward` at all, so the correct number of pedestrian one-ways is zero —
and the only thing the directionality work does on this region is decline to
apply 13,579 vehicle restrictions to people on foot.

**Node-level kerb evidence reaches 4,829 crossings** that carry no kerb tag of
their own — 41% of the region's 11,764 crossings. Without reading node tags they
would all have been "unknown".

**A\* is not faster here.** It expands 1,970 nodes at the median against
Dijkstra's 7,409, and returns identical cost on every routable journey — but
wall-clock is 200.6 ms against 197.7 ms at p50. The heuristic's per-node cost
cancels the saving at this scale in this implementation.

**The unknown-data penalty is not saturated, but it is doing one job.** Removing
it changes 3 of 20 routes; removing only the missing-gradient term changes the
same 3. See ADR 0008.

**Inspecting geometry found a bug nothing else would have.** 12 of the 19
routable journeys drew a discontinuous polyline — gaps of up to 93 m — and one
ended 15 m from the point the user chose, while the _reported_ distance stayed
plausible throughout. A snap-split segment was stored reversed and also marked
reversed, so it was flipped twice and drawn backwards. All 19 are now continuous,
end where the traveller was snapped, and draw a length matching what they report.
That is the whole argument for §16 of the task card: a number can look right
while the thing on the screen is wrong.

**A municipal inventory is not independent evidence just because it is
municipal.** In the pilot area, 87.7% of the City of Kitchener's pedestrian
records run within 2 m of an OpenStreetMap pedestrian way along their whole
length, and the City has given permission for its data to be used in OSM. That
does not establish independent geometry: until record-level history is
inspected, the geometry is treated as potentially shared-lineage. Its most
attractive fields are template defaults: 96.1% of sidewalks carry the default
1.5 m width, and 98.5% the default CONCRETE. What it records beyond its defaults
is located — 6,888 curb-cut segments, 77 stairs, 133 railings. Whether even those
are new to OSM is PA-GEO-04's question.

**Both maps were most likely drawn on the same photographs.**

- Since 2016, the finest layer of Esri World Imagery over Kitchener has been the
  City's own orthophotos, then the Region of Waterloo's. The City's records name
  photographs of the same years as their source.
- In PA-GEO-04's 80-record sample, 63 of the 69 records with an obvious OSM
  counterpart were shaped in OSM edits that recorded Esri imagery since then.
- Before Esri's metadata was read, the same rules had called 47 of those records
  independently mapped. The final figure is 3.
- OSM's accessibility values are another matter. All five kerb values found at
  sampled curb cuts were set by StreetComplete surveys.

So the City's geometry confirms nothing, while its curb cuts, stairs and surfaces
can still add what OSM lacks.
