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

| File                                | What it is                                                                                                                                                                                                   |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `waterloo-coverage.json`            | What OpenStreetMap records for the region, per category. Produced by `pathable coverage --region waterloo`.                                                                                                  |
| `waterloo-routes.json`              | Twenty real journeys under the standard and wheelchair profiles, plus the Dijkstra/A\* comparison and the unknown-penalty ablation. Produced by `pathable evaluate --region waterloo --algorithms --ablate`. |
| `waterloo-performance.json`         | Latency, memory and throughput measured on this machine.                                                                                                                                                     |
| `waterloo-geometry-inspection.json` | Every routable journey checked against its own geometry: continuity, seams, drawn-vs-reported length, and profile violations.                                                                                |
| `screenshots/`                      | The real product answering from this dataset.                                                                                                                                                                |

---

## Screenshots

Captured by `apps/web/tests/screenshots/real-waterloo.spec.ts` against the running
API and the active dataset. No API responses are stubbed — a screenshot of a
synthetic fixture would be a picture of nothing.

| File                                        | What it shows                                                                                                  |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `01-desktop-wheelchair.png`                 | A 366 m wheelchair route on real network, with per-category evidence gaps                                      |
| `02-mobile-wheelchair.png`                  | The same journey at 390 px wide                                                                                |
| `03-desktop-stroller.png`                   | A second profile on a different journey                                                                        |
| `04-route-difference.png`                   | A journey where the accessible route differs measurably                                                        |
| `05-missing-evidence.png`                   | A journey where the map is substantially silent                                                                |
| `06-snapped-away-from-the-chosen-point.png` | The snapping caution: the route begins at the nearest mapped path, some distance from the point the user chose |

Screenshots were re-captured after the geometry fix below, so every line shown
is continuous.

**A gap worth naming.** §18 of the task card asks for a screenshot of a genuine
no-route case. There is a real one — `conestoga-to-rim-park` in
`waterloo-routes.json` — but it cannot currently be reproduced through the
interface. Rim Park sits in a separate 1,887-node component, because its
connection to the rest of the network leaves the pilot bounding box and was
clipped; placing a point there needs the map driven to specific coordinates, and
the app has no deep-link for that. The failure is real, measured and reported in
the route corpus; only the screenshot of it is missing.

---

## Headline findings

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
