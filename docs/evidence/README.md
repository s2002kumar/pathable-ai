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

| File                                          | What it is                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `waterloo-coverage.json`                      | What OpenStreetMap records for the region, per category. Produced by `pathable coverage --region waterloo`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `waterloo-routes.json`                        | Twenty real journeys under the standard and wheelchair profiles, plus the Dijkstra/A\* comparison and the unknown-penalty ablation. Produced by `pathable evaluate --region waterloo --algorithms --ablate`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `waterloo-performance.json`                   | Latency, memory and throughput measured on this machine. Its `graph_load` block is the 2026-08-17 figure, measured under tracemalloc; superseded by the file below.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `waterloo-graph-load.json`                    | Cold-start cost: loading the dataset into the routing graph, three timed runs plus one under tracemalloc, with the machine conditions and a content fingerprint. Produced by `pathable benchmark load --region waterloo --json docs/evidence/waterloo-graph-load.json`.                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `waterloo-graph-load-before.json`             | The same command run at `1ee1d65`, whose loader is identical to `main`'s, minutes before the Core-column loader was applied. Kept so the before/after pair can be checked, not only asserted.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `production-envelope.json`                    | The production API image measured in an isolated Compose stack from an empty database: migration, cold start to live and to ready, graph preload, resident memory per process and per cgroup, memory-limit and worker-count runs, warm and concurrent route latency, restart and shutdown — plus three frontend cold starts under a 512 MiB cap (`measure_web.py`) and the managed-hosting restore, performed as a role that is not a superuser (`restore-dataset.sh`). Produced by `python infra/production-smoke/measure.py`; procedure in [`docs/deployment/PRODUCTION_SMOKE.md`](../deployment/PRODUCTION_SMOKE.md), decision in [ADR 0009](../adr/0009-deployment-architecture.md). |
| `waterloo-overture-extract-2026-09-23.0.json` | Reproducibility manifest for one bounded read of Overture release `2026-09-23.0` (schema `2.0.0`) over the Waterloo pilot box: requested and observed release, the column-contract result, every source file with its ETag, size and S3 expiry, the exact query and parameters, rows, bytes received, and the SHA-256 of each output. Produced by `pathable overture extract --region waterloo --release 2026-09-23.0`; the regional Parquet it describes stays out of git.                                                                                                                                                                                                              |
| `waterloo-overture-extract-2026-08-19.0.json` | The same for release `2026-08-19.0` (schema `1.18.0`), which Overture removes from public distribution about 60 days after release.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `waterloo-overture-linkage-2026-09-23.0.json` | How the dataset's stored OSM identities appear in that release's own provenance: identity, cardinality with linear ranges, version and edit-time status, malformed and unresolved source rows, source independence, and changelog and bridge cross-checks. Produced by `pathable overture link --region waterloo --extract <folder> --osm-pbf <source extract> --json …`, reading PathAble in a read-only transaction.                                                                                                                                                                                                                                                                   |
| `waterloo-overture-linkage-2026-08-19.0.json` | The same against `2026-08-19.0`, whose OSM snapshot is older than PathAble's rather than newer.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `waterloo-geometry-inspection.json`           | Every routable journey checked against its own geometry: continuity, seams, drawn-vs-reported length, and profile violations.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `waterloo-dataset-lifecycle.json`             | PA-GEO-02 on the real dataset, in a disposable database: the 0006 upgrade over the legacy rows, the legacy content checksum recorded from its rows, a candidate rebuilt from the same extract with OSM edit provenance, refused a seal until elevated, sealed to the legacy checksum exactly, judged identical on 120 route comparisons, activated, rolled back, the database refusing edits to sealed rows, and the restore script run as a role that is not a superuser. Every figure is parsed from the run's own command output or read back from the database, none typed in; the procedure is the command sequence in the README. ODbL-derived.                                    |
| `screenshots/`                                | The real product answering from this dataset. The `demo-*` captures are the PA-RR-06 recruiter journey; their provenance is in [`screenshots/DEMO_PROVENANCE.md`](screenshots/DEMO_PROVENANCE.md).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `media/`                                      | `pathable-demo.webm` — a 67-second recording of one real browser session against the real production containers, captured by Playwright's video recorder, not edited or spliced — and `pathable-demo.gif`, a 13.5-second excerpt of it cut for the README, because GitHub will not preview a video that size in the browser. Provenance, capture command and licence obligations in [`screenshots/DEMO_PROVENANCE.md`](screenshots/DEMO_PROVENANCE.md).                                                                                                                                                                                                                                  |
| `DEMO_SCRIPT.md`                              | How to show the product in about sixty seconds on the local production stack, and what may and may not be claimed while doing it.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |

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

## Screenshots

Captured by `apps/web/tests/screenshots/real-waterloo.spec.ts` against the running
API and the active dataset. No API responses are stubbed — a screenshot of a
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
