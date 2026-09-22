# Frontend polish (PA-UX-01): a map-first candidate

What changed in the interface, why, what it was measured against, and what it
is not. Everything visual here was checked in a real browser at the sizes named
below; every number came from a run on this laptop and is a local figure, not
a field measurement.

**Baseline:** `main` at `29a77491431fc9c6574b7fc84b9bf4db664c3b1b`
(`v0.3.0-public-release`), production web image built from that commit.
**Candidate:** branch `feat/premium-map-experience`. The routing engine, the API
contract and the dataset (`51e75f78…`) are unchanged; nothing below touches a
route's numbers.

## The direction: quiet, precise cartography

The page is a navigation instrument. Warm ivory surfaces, ink-coloured text, one
restrained teal for controls, and the two route lines are the only saturated
marks on the screen. Every panel change is a 150–200 ms decelerating transition;
the map camera is capped at 600 ms; both collapse to nothing under
`prefers-reduced-motion`. Typography is the platform UI face — already
installed, already hinted, zero bytes — with tabular digits on every figure so
"287 m" and "354 m" sit in the same column. No font was added.

### What moved, and why

| Before                                                                                           | After                                                                                                                                                       | Why                                                                                                                                                                                        |
| ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A four-line introduction above the map on every viewport                                         | One line of title; two sentences of purpose and a "How it works" disclosure, placed after the answer                                                        | The two sentences that matter — missing data is not a clear path, no route is a guarantee — stay visible. The rest is there for whoever opens it, and the answer reaches the first screen. |
| Desktop: a floating card over the map's left third                                               | A stable 340–400 px planner column beside the map; the map takes the rest and nothing floats over it                                                        | A fitted route was tucked under the card (visible in the baseline capture). Now the fit uses the whole map area.                                                                           |
| Mobile: map at 52 dvh, then the planner                                                          | Map at 36 dvh (never under 13 rem), then a sheet in normal document flow                                                                                    | The sheet looks like one and behaves like a page: nothing to drag, no competing scroll region, and the figures plus the uncertainty line fit on the first screen at 390 × 844.             |
| Liberty basemap as served: saturated parks, yellow primaries, extruded 3D buildings at high zoom | The same style, toned at runtime by layer ID: ivory ground, muted greens and water, softer casings, extrusions off. Labels, icons and attribution untouched | The style stays on OpenFreeMap's CDN (it is theirs, not ours to copy). At campus zoom the extrusions hid paths behind them and cost the software renderer dearly.                          |
| Two plain lines, 5–6 px                                                                          | Each line cased in the surface colour, a pale halo under each endpoint marker, marker labels in a font the style actually serves                            | Legible over any road. The default label font requested a glyph range OpenFreeMap does not host; every route logged a 404.                                                                 |
| Figures in a definition list                                                                     | Two figure cards with a "Highlight on map" control each, then the extra distance, then the uncertainty line, in one block with the headline                 | The map and the numbers read as one result. Highlighting dims the other line to 28%; it never removes it, and the note beside it says neither route is certified.                          |
| "No accessibility detail for 100% of this route"                                                 | "At least one accessibility attribute is unrecorded on 100% of this route; the largest single gap is surface condition, unrecorded for 100%"                | See below. The old sentence contradicted the four recorded stairways on the same screen.                                                                                                   |
| Route detail and provenance always expanded                                                      | "What is on this route" and "Where this comes from" as labelled `<details>`                                                                                 | Nothing removed; the no-model statement and OSM/elevation attribution stay in the page, the rest is a click away.                                                                          |
| `pathable-api v0.1.0` on the status badge                                                        | Kept in the badge for assistive tech and as a tooltip; visually hidden                                                                                      | A build version is a diagnostic, not part of a route's hierarchy.                                                                                                                          |

### What the "100%" means

`unknown_data_fraction` is computed in `routing/engine.py` as the share of the
route's **length** over segments whose `unknown_attributes` tuple is non-empty.
That tuple (`geo/features.py`) lists, per segment: `surface` if unclassified,
`smoothness` if unclassified, `incline` if neither an OSM incline nor a derived
grade exists, `kerb` if the segment is a crossing with no kerb record, and
`steps` if the steps state is unknown. So the figure is "at least one of these
is missing here", weighted by length — **not** "nothing is known here". On the
verified campus journey every segment lacks at least one of them (surface
condition and width are missing on 100%), while the four stairways are fully
recorded. The interface now says exactly that, and names the largest single gap
from `evidence_coverage`, which is reported per category for this reason.

Not changed, and worth knowing: the backend caution
`missing_accessibility_data` still reads "OpenStreetMap has no accessibility
details for most of this route (100% of its length)". It is shown verbatim
under "Before you rely on this". Its wording has the same ambiguity and is a
backend string; this card did not touch the API.

## States

Initial · selecting (start set, end awaited: the row is outlined and the status
line says what the next click sets) · preparing (badge reads "Preparing routes";
a request during that window fails with the API's message and a retry) ·
loading · success · coincident (headline says same length; a note says the two
lines overlap and the dashed one sits underneath) · no route (the API's reason,
the standard route still drawn) · API error (message plus "Try again", points
kept) · search empty / disabled · map unavailable (overlay, planner still
usable). The stubbed browser suite exercises each of these against fixed
responses.

## Measurements

Same production build mode (the `runtime` Docker target), same dataset, same
laptop, same harness. Browser: Playwright Chromium with SwiftShader, so the map
is rasterised on the CPU and every number is slower than a real GPU would be.
Network: the API and web containers on loopback; basemap tiles from
`tiles.openfreemap.org` over the internet; a fresh browser context per run, so
tiles were fetched, not cached, on every run.

### Captures

Before is the `v0.3.0-public-release` web image; after is this branch's image,
both running in the isolated production-smoke stack against the same API and
dataset, screenshotted by the same script after the network went idle. Files
are in [`screenshots/polish/`](screenshots/polish/); the raw per-viewport
results, including the in-viewport checks, are
[`frontend-polish-baseline.json`](frontend-polish-baseline.json) and
[`frontend-polish-candidate.json`](frontend-polish-candidate.json).

| Viewport               | Before                                                                             | After                                                                            |
| ---------------------- | ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| 1440 × 900, landing    | ![before, desktop landing](screenshots/polish/before-desktop-01-landing.png)       | ![after, desktop landing](screenshots/polish/after-desktop-01-landing.png)       |
| 1440 × 900, comparison | ![before, desktop comparison](screenshots/polish/before-desktop-02-comparison.png) | ![after, desktop comparison](screenshots/polish/after-desktop-02-comparison.png) |
| 1024 × 768, comparison | ![before, tablet comparison](screenshots/polish/before-tablet-02-comparison.png)   | ![after, tablet comparison](screenshots/polish/after-tablet-02-comparison.png)   |
| 390 × 844, comparison  | ![before, phone comparison](screenshots/polish/before-mobile-02-comparison.png)    | ![after, phone comparison](screenshots/polish/after-mobile-02-comparison.png)    |
| 320 × 568, comparison  | ![before, narrow comparison](screenshots/polish/before-narrow-02-comparison.png)   | ![after, narrow comparison](screenshots/polish/after-narrow-02-comparison.png)   |

What is on the first screen after one press, without scrolling or opening a
disclosure — both figures, the extra distance and the uncertainty line, each
measured as a whole element inside the viewport:

| Viewport   | Before                | After                      |
| ---------- | --------------------- | -------------------------- |
| 1440 × 900 | all four              | all four                   |
| 1024 × 768 | uncertainty line only | all four                   |
| 390 × 844  | none                  | all four                   |
| 320 × 568  | none                  | none (reachable by scroll) |
| 844 × 390  | none                  | none (reachable by scroll) |

Console: the baseline logged one 404 per page load (a glyph range the
basemap does not serve, requested by the marker-label layer). The candidate
logs nothing.

A recording of the main interaction — load, press, the comparison arriving,
highlight one route, open a disclosure, change profile — is
[`media/pathable-polish-interaction.webm`](media/pathable-polish-interaction.webm)
(1280 × 800, 17.7 s, Playwright's recorder, unedited).

### Interaction timings

Two warm interactions, measured from the browser: **press** is from the click
on the example to the comparison block being visible; **deep link** is from
navigation to `/?example=…` to the comparison block being in the document.
Fresh browser context every run.

The first pass ran one image and then the other, and its numbers disagreed
with each other from run to run by more than the difference between the
images — desktop press ranged 229–3001 ms on the candidate and 322–1549 ms on
the baseline in six runs. That is the software renderer and a laptop, not the
page. So the figure reported here is an **interleaved A/B**: eight rounds,
each round serving the baseline image and then the candidate image on the same
port, same stack, one run apiece:

| Metric              | Baseline median (min–max) | Candidate median (min–max) | Change |
| ------------------- | ------------------------: | -------------------------: | -----: |
| Press, 1440 × 900   |          460 ms (336–999) |           390 ms (341–621) |   −15% |
| Press, 390 × 844    |          296 ms (237–406) |           212 ms (154–454) |   −29% |
| Deep link, 1440×900 |          590 ms (407–793) |           547 ms (527–615) |    −7% |
| Deep link, 390×844  |          318 ms (294–581) |           288 ms (261–529) |    −9% |

The card's review trigger — a repeatable warm regression over 20% — fired on
the sequential passes (desktop press +41% in one six-run pass; phone deep link
+46% in one ten-run pass) and did not survive interleaving, where every metric
is equal or slightly better and the ranges overlap. The honest reading is
**equivalent performance with better presentation**; the negative deltas are
within this machine's noise and are not claimed as an improvement.

Actions to the comparison: one press, before and after.

### Bundle

First-load JavaScript, compressed as served (`content-encoding: gzip`), eleven
script responses on the deep-link load:

| Before        | After         | Change       |
| ------------- | ------------- | ------------ |
| 548,686 bytes | 550,666 bytes | +1,980 bytes |

No dependency was added. The largest responses are unchanged: the MapLibre
chunk (262 KB) and its worker's shared module (139 KB).

### Main-thread trace of the press

A Chromium trace (`devtools.timeline`) of the press on 1440 × 900, one run
each, summarised as main-thread task time: baseline 1,733 ms of tasks with
279 ms scripting and six tasks over 50 ms (longest 555 ms); candidate 1,637 ms
with 237 ms scripting and six over 50 ms (longest 595 ms). The long tasks are
MapLibre rasterising tiles on the CPU, not React. One run each; a shape, not
a measurement to quote.

### Cold start of the web container

`docker run` of each image to a 200 from `/api/healthz` and from `/`, three
times each, host clock:

| Image     | healthz (s)      | page (s)         |
| --------- | ---------------- | ---------------- |
| Baseline  | 2.69, 1.68, 2.24 | 2.80, 1.91, 2.33 |
| Candidate | 3.01, 1.60, 1.75 | 3.26, 1.78, 2.07 |

The API container was not rebuilt and its cold start is not re-measured here;
the previously recorded figure (18.7 s to routable, one worker) stands as its
own evidence and is not restated as current.

### Reproducing

The harness lives outside the repository (a one-off, like the demo capture
script before it). The commands that matter are the repository's own: the
production-smoke stack per
[`PRODUCTION_SMOKE.md`](../deployment/PRODUCTION_SMOKE.md), the stubbed
browser suite (`pnpm --filter @pathable/web test:e2e`, which now includes
`tests/e2e/layout.spec.ts`), and the full-stack suite against the Compose
stack. Chromium on this laptop needs
`--host-resolver-rules=MAP localhost 127.0.0.1`; see the smoke guide.

## Verification

All on this branch at its final commit, on this laptop, observed rather than
inferred.

| Gate                                                    | Result                                                                       |
| ------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `tsc --noEmit`, ESLint, Prettier                        | clean                                                                        |
| Frontend unit (Vitest, coverage)                        | 249 passed, 17 files; statements 93.9%, branches 87.2% (floor 80%)           |
| Stubbed browser suite (desktop + Pixel 7, axe included) | 100 passed (80 existing + 20 in `layout.spec.ts`)                            |
| Full-stack against the Compose stack, real Waterloo     | 16 passed, 0 skipped (9 recruiter-demo + 7 stack)                            |
| Contract drift                                          | generated contracts match the backend schemas                                |
| Production build / Docker web image                     | built; the candidate image is what every "after" figure above was taken from |
| CI on the final SHA                                     | see the pull request checks (recorded in the PR, not here)                   |

Checked by hand in the captures and the recording, not by a machine:
keyboard reach to the example and to both highlight controls; visible focus on
every control; the map key naming a highlighted route in words; attribution
uncovered at every size; reduced motion collapsing panel transitions and the
camera move; no horizontal overflow at 320 px; the two-pane layout giving way
to document flow at 720 × 450 (the size 200% zoom leaves a 1440 × 900 window).
Automated axe passing is a floor, not a claim of accessibility compliance.

## Limitations

- Local figures on one machine under a software renderer. Not Core Web Vitals,
  not production latency.
- The design was checked by the author in a browser. No user with a mobility
  aid, and nobody outside the repository, has reviewed it.
- The basemap is still OpenFreeMap's development service, toned at runtime.
  Nothing here changes its licence position or approves it for production.
- The full-stack real-data suite runs locally against the production-smoke
  stack; CI still loads the synthetic fixture and skips those tests (KI-9).
