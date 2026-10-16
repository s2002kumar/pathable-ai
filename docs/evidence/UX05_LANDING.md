# PA-UX-05 — the landing experience

The landing page (`/`) rebuilt to tell the verified Waterloo journey on one stage. A presentation card:
no routing, API, dataset or evidence rule changed, and the planner is untouched apart from an
entrance animation when the landing page's own links open it. Branch `feat/premium-landing`, from
`main` at `a3f6448`.

![Before and after at 1440 by 900 pixels. Before: copy above a window-framed picture of the
recorded routes on a grid. After: the copy and the answer in figures on the left; on the right the
recorded routes drawn over the campus pedestrian network, with the four recorded stairways
marked.](screenshots/ux-05/before-after-desktop-1440.png)

## What the page is now

- **One stage, one journey.** The recorded routes from Davis Centre library to the Student Life
  Centre, drawn in ground metres over the routing graph PathAble ingested around them. The stage
  sits beside the hero and the story (above them on a phone) and is sticky while they scroll.
- **Four story steps.** The routes leave together; the shortest takes four recorded stairways; the
  wheelchair profile rules them out; what nobody recorded stays unknown. As each step crosses the
  middle of the screen the stage follows: highlights, labels, a camera move. Scrolling drives the
  state; nothing drives scrolling.
- **An evidence explorer.** Both routes drawn to scale as strips, one cell per segment, recoloured
  by lens: stairs, gradient, surface, width and smoothness. Radios and `:has()`, no script.
- **Engineering, measured.** The claims ledger's figures with their conditions, and the pipeline
  as a line from open data to this interface, with the Kitchener research data shown off the line.
- **Principles** set as three large statements, then **into the planner** by a view transition.

## Design rationale

- **Only PathAble's own imagery.** The one picture is the recorded journey on the network it ran
  on. No basemap tiles (so no third-party request, no tile-licence question, and the page works
  offline), no decorative AI or glow imagery. The network is real data, so nothing on the stage is
  placed by eye, and it is credited on the drawing (`Paths © OpenStreetMap contributors`).
- **Motion carries a sentence.** Every camera move or highlight belongs to the step beside it.
  Routes draw once on load, shortest first, so the divergence is the first thing the eye follows.
  The full motion specification is in [`apps/web/DESIGN.md`](../../apps/web/DESIGN.md), "Landing
  motion (PA-UX-05)".
- **The planner's colour semantics, everywhere.** Orange dashed is the shortest route, emerald
  solid the profile route, coral only a recorded stairway, amber something not recorded, sky
  something derived. The previous landing page drew the shortest route in the barrier coral; that
  is corrected. Every colour also has a second carrier: a dash pattern, a glyph on the evidence
  tag, or the figure in text.
- **Display typography with room.** A 38–56 px headline at −0.035 em, section titles to 46 px,
  JetBrains Mono kept for measurements.
- **No parallax.** The backdrop is the routing graph; sliding it against the routes would put a
  route on the wrong path. Depth comes from the camera, which settles from a tilted view to plan
  view on load and eases between steps.

**Kept from PA-UX-04:** the palette and tokens, Inter and JetBrains Mono, the verified example
and its provenance line, the four-part evidence vocabulary, the integrity principles, the header
structure and the footer's attribution. **Removed:** the window chrome around the picture, the
duplicated route HUD, the uniform card grids, and the two trade-off cards, whose figures now live
in the story and the explorer.

`DESIGN.md` records that this card overrides the Golden Master's pixel-parity contract and motion
limits for the landing page only. Figma frames `10:2318` and `17:3167` are now historical; the
Figma file itself was not updated.

## The data behind the drawing

`scripts/landing-data.mjs` regenerates both assets from the local production envelope
([`PRODUCTION_SMOKE.md`](../deployment/PRODUCTION_SMOKE.md)); CI never runs it.

- **`route`** re-records the campus example from one `POST /api/v1/routes/compare` (wheelchair)
  into `apps/web/src/features/landing/verified-route.ts`, now with every segment's length, stairs,
  step count, surface, width, smoothness, recorded incline and derived grade, and the API's own
  coverage figures. It refuses a response from any dataset but `51e75f78`, one in which a model
  took part, or one whose segments are not the straight pieces between consecutive coordinates.
  The 2026-10-13 run reproduced the 2026-10-05 record on every field; seven coordinates differ by
  10⁻⁶ degrees (about 10 cm) because the earlier hand copy truncated where the script rounds.
- **`network`** writes `apps/web/public/landing/campus-paths.svg`: 2,096 routable segments within
  ±340 m east–west and ±240 m north–south of a point at the journey's centre, from dataset
  `51e75f78` (source timestamp 2026-08-16), merged and simplified, in the same metre frame as the
  stage. 23.2 KiB, 9.7 KB gzipped. A unit test fails if the script, the file and `stage-frame.ts`
  ever disagree on the frame.

`journey.ts` derives every figure the page states from the record, and its tests hold the
per-segment reading to the API's coverage figures: surface, width, smoothness and the three
gradient shares, for both routes. A figure on the page and the cells drawn beside it cannot
disagree without a test failing. A further unit test fails on any number in the Engineering
section that `docs/CLAIMS_LEDGER.md` does not contain.

## Accessibility

| Requirement                       | How it is met                                                                                                                                                                                                | Checked by                                                                                                                                        |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `prefers-reduced-motion`          | No settle, draw, pulse or reveal; the stage still follows the story but every change is instant and the camera never moves; view transitions off.                                                            | `landing.spec.ts` (the camera transform is identical at every step); a regression found this way: the override first lost on specificity.         |
| Understandable with motion off    | Every figure and statement on the stage is also in the text; the stage is one labelled image to assistive technology.                                                                                        | `page.test.tsx`; reduced-motion and no-script captures                                                                                            |
| Works with no script              | The stage renders the whole answer; nothing is hidden; the lens switches by CSS alone.                                                                                                                       | `landing.spec.ts`, JavaScript off                                                                                                                 |
| Keyboard                          | Native links and a native radio group (arrow keys move between lenses); a visible label focus ring; skip link unchanged.                                                                                     | `landing.spec.ts` (lenses by keyboard alone; skip link)                                                                                           |
| Semantic headings                 | One `h1`; an `h2` per section; an `h3` per story step and principle.                                                                                                                                         | `accessibility.spec.ts`, `page.test.tsx`                                                                                                          |
| Colour never the only carrier     | Dash patterns on the routes and gaps, a distinct glyph on each evidence tag, figures in text beside every strip.                                                                                             | Review                                                                                                                                            |
| Contrast                          | Rendered contrast checked by axe; no serious or critical violation.                                                                                                                                          | `accessibility.spec.ts`, desktop and Pixel 7                                                                                                      |
| Phone and reflow                  | Stacked layout with a sticky stage; no horizontal scroll; on a short screen (200% zoom, landscape) the stage is not sticky. Labels wrap rather than run off a small stage, and the camera holds still there. | `landing.spec.ts` (every label inside the stage at every step, desktop and phone — labels were cut mid-word during the build); captures at 390 px |
| No scroll hijacking               | The story follows native scrolling through an IntersectionObserver band; no snapping, no wheel or touch handling.                                                                                            | `LandingMotion.tsx`, `landing-motion.test.tsx`                                                                                                    |
| Nothing essential in canvas alone | No canvas. The stage is SVG plus HTML labels, and is described in text.                                                                                                                                      | Review                                                                                                                                            |

Not verified here: a manual screen-reader pass (still the pre-deployment item from PA-UX-04), and
Safari or Firefox — the browser suites run Chromium only. View transitions and the scroll-tied
pipeline line are progressive; a browser without them simply navigates and draws the line.

## Performance

**Method.** Both builds served by `next start` side by side, `main` (`a3f6448`) and this branch,
loaded alternately by Playwright Chromium, eight cold loads each per profile, medians. Desktop is
1440×900 unthrottled; the phone is a Pixel 7 emulation with the CPU throttled 4×. Load-phase
blocking time sums long tasks over 50 ms up to 4.5 s after `load`; scroll-phase blocking covers
one pass down the whole page. One Windows laptop with about 0.7 GB of memory free and other
applications open: a shape, not a service level, and the spread between runs is wide.

Final run, on `43b7851` (every sample in
[`performance-interleaved.json`](screenshots/ux-05/performance-interleaved.json)):

| Profile   | Build  | FCP    | LCP    | Blocking, load | Longest task | Blocking, scroll |   CLS | Transferred |
| --------- | ------ | ------ | ------ | -------------- | ------------ | ---------------- | ----: | ----------: |
| Desktop   | main   | 480 ms | 688 ms | 59 ms          | 81 ms        | 0 ms             | 0.001 |    283.1 KB |
| Desktop   | branch | 398 ms | 416 ms | 73 ms          | 101 ms       | 0 ms             | 0.003 |    281.5 KB |
| Phone, 4× | main   | 730 ms | 802 ms | 442 ms         | 492 ms       | 0 ms             | 0.000 |    275.1 KB |
| Phone, 4× | branch | 904 ms | 904 ms | 367 ms         | 339 ms       | 168 ms           | 0.002 |    287.6 KB |

An earlier interleaved run of the same design on `839afd9` (identical but for the reveal fix and
the on-stage credit) put the phone's LCP at 516 ms against 720 ms, load blocking at 295 ms against
226 ms, and scroll blocking at 307 ms; desktop LCP at 296 ms against 396 ms. Read together: the
desktop LCP is better in both runs; the phone's LCP and load blocking moved in opposite directions
between runs and are within this machine's noise; the scroll-phase work is new. It is the
deferred layout of the sections below the story and the story's own state changes, and the
previous page, at about a third of the length, had none.

**What it weighs** (one load each, encoded bytes, desktop, measured on `839afd9`): HTML
21.7 → 24.0 KB (116.8 → 152.0 KB decoded), JavaScript 141.8 → 142.2 KB (one client island, the
story and reveal observer), CSS 8.8 → 12.1 KB, fonts unchanged at 89.6 KB, images 20.1 → 13.5 KB
(fewer icon masks; the network backdrop is 9.7 KB of that). **No dependency was added**:
`package.json` and the lockfile are unchanged. Everything is CSS, SVG and React's built-in
`<ViewTransition>`.

**A regression found and fixed on the way.** The first complete build, measured sequentially,
took the phone's LCP from 412 ms to 1,768 ms and its blocking time from 159 ms to 716 ms. Tracing
it found: both LCP candidates (the headline, the stage) faded in from opacity 0; the route drawing
repaints on the main thread every frame; the backdrop covered 1,120 × 680 m when no stage shows
more than about 590 m across; the reveal setup asked every block for its position, forcing a
layout of the whole page during hydration. The fixes, all in this branch: a transform-only stage
settle and an unfaded headline; the backdrop cut to what a stage can show and kept on its own
layer; each route path defined once and reused; masks bounded to the drawing; no stroke drawing on
phone-width stages; `content-visibility: auto` below the story; reveal positions from
IntersectionObserver rather than a forced layout.

## Captures and recording

In [`screenshots/ux-05/`](screenshots/ux-05/), from a production build against the real API on
the local production envelope (dataset `51e75f78`), Chromium:

- `before-*`: `main` at `a3f6448`, desktop 1440×900 and phone 390×844.
- `desktop-1440-00-hero` to `-07-principles`: the hero after the stage settles, each story step,
  the surface lens, engineering and principles.
- `desktop-1440-reduced-motion-stairs`: the stairs step with reduced motion.
- `laptop-1280x720-hero`, `tablet-820-stairs`, `phone-390-*`: other sizes.
- `transition-into-planner`, `planner-after-transition`: frames from the recording.

[`media/pathable-ux05-landing.webm`](media/pathable-ux05-landing.webm) — 47 s, VP8, 1280×800,
5,571,126 bytes: one unedited Playwright session on GPU ANGLE. The page loads and settles, the
four story steps are scrolled, three lenses are chosen, then "Open the verified journey" carries
it into the planner, which computed 287.4 m against 354.1 m live on dataset `51e75f78`. Step
times are in [`session.json`](screenshots/ux-05/session.json).

## Tests

Added: `stage-frame.test.ts`, `journey.test.ts` and `landing-motion.test.tsx` (unit), the
rewritten landing page test, and seven browser tests in `landing.spec.ts` — the stage following
the story, every label inside the stage, reduced motion, the lenses by keyboard, the live
hand-off into the planner, a fast scroll leaving nothing hidden, and the page with JavaScript off.

Local runs on `4e3acf6`, this laptop: web unit 512 passed in 30 files, 93.9% statements and
83.75% branches against 80% floors; the stubbed browser suite 172 passed and 2 skipped, desktop and
Pixel 7, against a production build; typecheck, ESLint, the repository-wide Prettier check and
`contracts:check` clean. The README's suite counts and ledger 6.1 come from CI only, so they are
refreshed from this branch's CI run, not from these. Earlier in the card one full browser run
failed the planner's ODbL-overlap test once under load; it passed six times alone and in the
final run, and it measures planner code this card does not change.

## Remaining concerns

- The landing page is no longer pixel-parity with Figma `10:2318`/`17:3167`; whether to update
  the Figma file or treat the code as the reference is the founder's call.
- Phone performance was measured in emulation on a loaded laptop, not on a phone.
- The record and the backdrop are dated. If the dataset or the routing policy changes, re-run
  `scripts/landing-data.mjs`; the page names the dataset and policy it shows.
- A section skipped by `content-visibility` takes its estimated height until it has been seen once,
  so a jump from the header's links can land a little off before the browser corrects it.
