# PA-UX-04 — Golden Master implementation

The frontend implements the seven canonical frames of the frozen Golden Master
(`apps/web/DESIGN.md`, Figma file `2ADEbGWbTXHMonAqbAdcPy`). This page maps each
frame to its route, its components and the API behind it, and lists every place
the implementation departs from the frame and why. Where the backend contract
and the frame disagree, the backend wins (DESIGN.md, "Source-of-truth
precedence").

## Frames, routes and components

| Frame     | State                                     | Route                              | Components                                                                                                         | Data                                                                    |
| --------- | ----------------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| `10:2318` | Landing, desktop                          | `/`                                | `LandingPage`, `RouteVisual`                                                                                       | `verified-route.ts`: one recorded `POST /routes/compare`, dated         |
| `17:3167` | Landing, phone                            | `/` below 720 px                   | the same                                                                                                           | the same                                                                |
| `17:3555` | Planning                                  | `/planner`, no journey             | `PlannerScreen` → `RouteWorkspace` (`plan`) → `PlanPanel`, `ProfileChooser`, `UphillLimitControl`, `MapControls`   | `GET /health/ready`, `GET /routes/profiles`, `GET /geocode/search`      |
| `9:1905`  | Comparison, desktop                       | `/planner`, two different routes   | `ComparePanel` (`CompareControls`, `RouteCards`), `EvidenceDock`, `comparePins`                                    | `POST /routes/compare`                                                  |
| `17:3789` | One route's evidence                      | `/planner`, View Evidence          | `EvidencePanel`, `GapDock`, `gapCallouts`, gap lines                                                               | the same response; one route, nothing re-requested                      |
| `17:4041` | No route for the profile                  | `/planner`, `accessible_route` null | `NoRoutePanel`, `barrierPins`                                                                                     | the same; requirements read from `excluded_by_profile` on the shortest |
| `17:2865` | Comparison, phone                         | `/planner` below 720 px            | `MobileComparison`, `phonePins`                                                                                    | `POST /routes/compare`                                                  |

Not in the Golden Master: the **details sheet** (`RouteDetails`), opened by
Route Details and, on a phone, by View Evidence. It states the whole answer in
text — headline, both routes, every reason with its evidence label, the
per-category record, cautions, dataset, licences.

The old address `/?example=…` redirects to `/planner?example=…`, query intact,
so recorded links keep working.

## Departures from the frames

### Backend truth over the frame

- **Five profiles, not four.** The API serves Wheelchair, Walker or rollator,
  Crutches or cane, Stroller or pram and Reduced mobility, with its own names
  and rules. The frame's "Standard Pedestrian" is not a profile: the shortest
  route is the baseline every answer is compared with.
- **No time for a route the profile cannot use.** The frame shows a time on
  the shortest route; the implementation says "Time unavailable for this
  profile" whenever the response rules that route out, because a time beside a
  stairway reads as a trip a wheelchair user could take.
- **Figures are the response's.** Distances, the detour, stair counts, grades,
  surface shares and the reason line are read from the API. The frames'
  example values ("2.1 km", "34 recorded stairways", "7.8% railway slope",
  place names) are not used anywhere.
- **No route** shows only what the response reports about the shortest route
  it did return — its excluded segments, grouped by reason — never a diagnosis
  of paths it searched. The real no-route state in the captures is the
  verified journey with a 1% uphill limit.
- **Uphill slider runs 1–12% in half-percent steps** (the frame's ticks read
  3–8%). Any other value can be typed on the planning form, and is sent exactly
  as typed.

### Controls the product does not have

The frames draw elevation, satellite, filter, settings and avatar controls and
a locate button. PathAble has no such layers, no accounts and does not read the
viewer's location, so:

- **Layers** opens a menu of PathAble's three real overlays: evidence labels,
  recorded stairways, the shortest route.
- **Locate** becomes **Fit**, which re-frames the routes or points.
- **Compass** resets the map to north.
- The others are omitted.

### Added for use, safety or the licences

- **Set on map** on each endpoint field, so a map click lands where the
  viewer asked rather than in whichever field is empty.
- **Clear** in the comparison header and the phone's editor. The frame has
  none, and without it the only way back to the planning form was reloading.
- **Edit journey or profile** on the phone: the frame shows no controls beside
  a phone answer.
- **The verified example** button on the planning form, with its provenance.
- **The credit line** carries the Open Government Licence – Canada statement
  for HRDEM (grades are on the first screen, so it cannot wait behind Route
  Details) and says the OpenFreeMap development tiles are not approved for
  production (ADR 0005).
- **The bar's region pill** names the service state in a word whenever it is
  not ready; the frame shows only the ready dot, and colour alone is not an
  answer.
- **The phone landing** keeps the "recorded from the implemented routing API …
  one journey, not typical of all" line that 17:3167 drops, because it shows
  the same recorded figures.
- **Windows under 600 px tall** (a laptop at 200% zoom, a phone on its side)
  use the phone's document flow; floating surfaces left the panel no room.

### Rendering

- **The basemap is live**: OpenFreeMap Liberty toned dark at runtime, where the
  frames use an illustration. Its POI icons stay: the basemap rule forbids
  hiding or fading features.
- **The idle veil** is 38%, not 85%: the frame veils a picture, the
  implementation a map somebody is about to click on.
- **Muted text** `#3b4a3f` is lifted to `#849587` for contrast.
- **Inter 4's metrics** wrap a few lines differently from the frames.
- **Phone endpoint dots** use the map's origin and destination colours.
- **The evidence view's zoom stack** sits above the gap dock rather than
  under it.
- **The landing's route drawing** is projected from the recorded geometry of
  the verified example, not the frame's illustrative lines.

### Wording

Copy the frames invented is replaced by API data or the claims ledger:
"180,554 segments", GiST indexes, Dijkstra and A\* agreeing on optimal cost,
sealed datasets. Removed: "routing cluster", "ramp handrails", "Client Graph
Weights", "GeoJSON", "WGS84 GEOID", fabricated place details, "not rendering
constants". Evidence is labelled only Recorded · OSM, Derived · HRDEM, Not
recorded or Your profile rule.

## Evidence

`screenshots/ux-04/` holds the captures, each at its frame's size, taken by
`apps/web/tests/screenshots/ux-04-states.spec.ts` against the local production
envelope (real Waterloo dataset, nothing stubbed), with `observations.json`
recording what each state said and when, and a side-by-side image of each
frame beside its capture.

Re-run:

```sh
docker compose -f infra/production-smoke/compose.yaml up --build -d
SCREENSHOT_BASE_URL=http://localhost:3001 \
PLAYWRIGHT_CHROMIUM_ARGS="--host-resolver-rules=MAP localhost 127.0.0.1" \
  pnpm --filter @pathable/web exec playwright test \
  --config=playwright.screenshots.config.ts ux-04
```
