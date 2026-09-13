# Demo screenshot provenance

**These are not pictures of a deployment. PathAble is not deployed anywhere.**
Every image below was captured from the production container images running on
one laptop, against the real Waterloo dataset, with the routes computed live by
the engine at capture time.

|                  |                                                                                                                                                                                                                           |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Commit           | `1af7c331dc05ba292e2fdc635b0620f90d1bf881` (branch `feat/recruiter-demo`)                                                                                                                                                 |
| Captured         | 2026-09-13                                                                                                                                                                                                                |
| Environment      | Isolated Compose project `pathable-envelope` — API and web production images built from that commit, PostGIS 17.5, all on `localhost`. See [`docs/deployment/PRODUCTION_SMOKE.md`](../../deployment/PRODUCTION_SMOKE.md). |
| Not a deployment | No cloud provider, no public URL, no custom domain, no hosting account. The web container was reachable only at `http://localhost:3001`.                                                                                  |
| Dataset          | `51585450-8ff5-409d-a02e-66d5a3c5e260`                                                                                                                                                                                    |
| Dataset checksum | `51e75f7896ab725d29120fe4363c607bea68eed260d830482d6677f827d2e906`                                                                                                                                                        |
| Network          | 155,714 nodes · 180,554 physical segments · 361,108 directed edges, from Geofabrik's Ontario extract                                                                                                                      |
| Elevation        | NRCan HRDEM 1 m LiDAR                                                                                                                                                                                                     |
| Journey          | `campus-library-to-student-life` from the committed twenty-journey corpus: Davis Centre library (−80.5424, 43.4728) to the Student Life Centre (−80.5449, 43.4715)                                                        |
| Profile          | Wheelchair                                                                                                                                                                                                                |
| Basemap tiles    | OpenFreeMap, a development convenience that is not approved for production                                                                                                                                                |

## What the engine returned at capture time

Read from the `POST /api/v1/routes/compare` response the browser received, not
from the screenshots:

|           | Shortest walking route | Wheelchair route |
| --------- | ---------------------: | ---------------: |
| Distance  |                287.4 m |          354.1 m |
| Segments  |                     43 |               47 |
| Stairways |                      4 |                0 |

Extra distance 66.67 m (23%). `ml_predictions_used: false`. These match
[`waterloo-routes.json`](../waterloo-routes.json) for the same journey, which is
the point of using a corpus journey: the demo shows a result that was already
published and can be checked.

## The files

| File                             | Viewport            | What it shows                                                                                              |
| -------------------------------- | ------------------- | ---------------------------------------------------------------------------------------------------------- |
| `demo-desktop-01-landing.png`    | 1440 × 900          | The page before any interaction: the example offered, the map ready, attribution in place                  |
| `demo-desktop-02-comparison.png` | 1440 × 900          | One press later — both routes drawn and distinguishable without colour, and the comparison in the viewport |
| `demo-desktop-03-panel.png`      | 1440 × 900          | The whole planner panel, including the parts a viewer reaches by scrolling                                 |
| `demo-mobile-01-landing.png`     | 412 × 839 (Pixel 7) | The same page on a phone                                                                                   |
| `demo-mobile-02-comparison.png`  | 412 × 839           | The comparison on a phone                                                                                  |
| `demo-mobile-03-panel.png`       | 412 × 839           | The whole panel on a phone                                                                                 |

The `-03-panel` captures are element screenshots of the scrollable panel, so they
show content that is below the fold in the viewport captures. They are included
precisely so the evidence does not imply that everything fits on one screen: on
both viewports the "Not recorded" evidence line sits below the fold and is
reached by scrolling.

## Reproducing them

With the stack up (see the smoke guide), from `apps/web`:

```bash
DEMO_WEB_URL=http://localhost:3001 DEMO_API_URL=http://localhost:8001 \
DEMO_SHOTS=../../docs/evidence/screenshots \
  node audit-after.mjs
```

The capture script is kept with the PA-RR-06 working notes rather than committed:
it is a one-off measurement harness, not a supported command, and
[`DEMO_SCRIPT.md`](../DEMO_SCRIPT.md) plus the full-stack Playwright suite are
the maintained ways to reproduce the journey.
