# Known issues

Open defects with reproduction steps and evidence. Fixed issues move to
[`../../CHANGELOG.md`](../../CHANGELOG.md).

---

## KI-1 — The map does not render a real vector basemap

**Status:** Open · found 2026-08-05 during P0-A01 remediation · **blocks Phase 1**

### Symptom

With the configured development style
(`https://tiles.openfreemap.org/styles/liberty`), the map never finishes
initialising. After 30 seconds the lifecycle times out and shows "The map is
unavailable"; the written pilot description remains, so the page is still usable.

The deterministic offline test style is unaffected, which is why the automated
suites are green.

### Evidence

Captured with `pnpm map:evidence` (see
`apps/web/artifacts/screenshots/real-basemap-report.json`):

| Observation           | Value                                         |
| --------------------- | --------------------------------------------- |
| Style document        | HTTP 200                                      |
| TileJSON (`/planet`)  | HTTP 200                                      |
| Sprites               | HTTP 200 ×2                                   |
| Glyphs                | **0 requests**                                |
| Vector tiles (`.pbf`) | **0 requests**                                |
| Console errors        | none from MapLibre                            |
| `error` event         | never fired — the failure is the init timeout |
| Web worker            | created successfully                          |
| Map container size    | 1406×810 after the fix below (was 1406×0)     |

Reproduced identically in a production build and under `next dev`, at zoom 10
and zoom 15, on desktop and mobile viewports.

The provider is healthy: fetching a tile directly from the URL template in the
TileJSON returns real data (a z10 tile is ~60 KB).

So MapLibre loads the style, the TileJSON and the sprites, and then requests no
tiles at all — silently.

### What has been ruled out

- **Provider outage.** Tiles are served correctly when fetched directly.
- **Zero-size container.** This _was_ a real bug and is fixed — the container had
  collapsed to zero height because MapLibre's `.maplibregl-map { position: relative }`
  overrode our absolute positioning. Fixing it did not resolve the tile issue.
- **Turbopack production bundling.** Reproduces under `next dev` too.
- **Web worker failure.** A worker is created.
- **Rendering cost / SwiftShader slowness.** No tiles are _requested_, so this is
  upstream of rasterisation. Zoom 10 behaves the same as zoom 15.

### Not yet ruled out

- A behaviour change or regression in **maplibre-gl 6.1.0**, which is a very new
  major version. The obvious next experiment is to try the 5.x line.
- Something specific to headless Chromium with SwiftShader that fails silently.
  Verifying on a real browser with a GPU would settle this quickly and is the
  cheapest next step.

### Impact

Phase 0's stated scope is a map shell, and the shell, its lifecycle, its fallback
and its accessible alternative all work. But a mapping product whose map does not
draw is not shippable, and Phase 1 route rendering depends on this.

### Suggested next steps

1. Open the app in a normal desktop browser with GPU acceleration and check
   whether the basemap draws. One minute, and it splits the problem in half.
2. If it fails there too, pin `maplibre-gl` to the latest 5.x and retest.
3. If 5.x works, record the finding and a dependency decision; if not, build a
   minimal standalone HTML reproduction against the same style and take it
   upstream.

### Workaround

None needed for Phase 0. The offline test style keeps the automated suites
meaningful, and the failure state is handled gracefully.
