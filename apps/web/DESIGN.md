# PathAble Frontend Golden Master — v1

Status: **FROZEN FOR PA-UX-04 IMPLEMENTATION**

This file is the semantic handoff for the approved PathAble frontend family. It does not authorize redesign.

## Source-of-truth precedence

When sources disagree, use this order:

1. **Product behavior/data:** current PathAble backend/API contract and route evidence.
2. **Visual appearance:** the canonical Figma Golden Master frame for that state.
3. **Geometry/measurements:** Figma node measurements, spacing, typography, icons and responsive relationships.
4. **Design rules/motion:** this file.

Never hard-code a Figma example value over real backend data.

## Figma

File key: `2ADEbGWbTXHMonAqbAdcPy`

Canonical frames:

| State                                         | Node      | Reference size |
| --------------------------------------------- | --------- | -------------: |
| Desktop planner — route comparison            | `9:1905`  |    1280 × 1152 |
| Desktop landing page                          | `10:2318` |    1280 × 4855 |
| Mobile planner — route comparison             | `17:2865` |     390 × 1549 |
| Mobile landing page                           | `17:3167` |    390 × ~3254 |
| Desktop planner — idle/planning               | `17:3555` |    1280 × 1204 |
| Desktop planner — incomplete data             | `17:3789` |    1280 × 1152 |
| Desktop planner — no route / hard requirement | `17:4041` |    1280 × 1152 |

All older top-level concepts are archived and are **not implementation references**.

## Product character

PathAble is a **consumer navigation product first**, not a GIS dashboard, municipal operations console, research tool, or generic SaaS template.

The product experience is:

`Origin + destination → mobility profile → compare profile route vs shortest pedestrian route → understand why they differ.`

The map is the dominant visual surface. Evidence is progressive and contextual rather than always-on engineering metadata.

## Visual language

- Deep midnight/navy map and UI environment.
- Accessibility/profile route: emerald accent, approximately `#00F090`.
- Derived/informational evidence: restrained sky/cyan, approximately `#38BDF8`.
- Missing/unknown evidence: amber, approximately `#FB923C`.
- Red/coral only for recorded barriers or explicit hard-rule conflicts.
- Inter for UI typography.
- JetBrains Mono only for selective measurements/technical labels.
- Compact floating planner surfaces; large map canvas.
- Subtle glass/elevation only; no crypto/gaming glow aesthetic.
- Do not replace with a generic component-library look.

## Evidence vocabulary

The production UI uses exactly these evidence concepts:

- **Recorded · OSM** — source/map fact.
- **Derived · HRDEM** — deterministic calculation from NRCan elevation.
- **Not recorded** — information is missing; never treated as accessible.
- **Your profile rule** — explicit user/profile constraint.

Rules:

- No aggregate accessibility confidence score.
- No fake confidence percentages.
- Missing ≠ accessible.
- Agreement ≠ independent confirmation.
- Research evidence ≠ production evidence.
- Do not use `verified`, `safe`, `barrier-free`, `AODA compliant`, or equivalent language unless separately proven.

## Production/research boundary

Current production route evidence is OSM + deterministic NRCan HRDEM-derived evidence + profile rules.

Municipal Kitchener evidence remains research-only and must not appear as if it affects live routing until licensing/validation gates explicitly pass.

No ML prediction currently affects routing. Do not use `AI-powered`, model-confidence, or learned-prediction language before Gate C is complete.

## Unsupported product features — do not invent

Unless implementation inspection proves they already exist, do not add:

- turn-by-turn navigation;
- accounts/profile identity;
- saved routes;
- hazard feed;
- crowd reporting / report-field-condition actions;
- live telemetry/feed language;
- automatic municipal evidence integration;
- public deployment badges or fake domains.

## Dynamic route content

Figma route numbers are layout examples. Implementation must render current API results.

A verified Waterloo example available for recruiter/static proof is:

- shortest route: **287.4 m**;
- wheelchair route: **354.1 m**;
- detour: **+66.7 m (23%)**;
- shortest route: **4 recorded stairways**;
- wheelchair route: **0 recorded stairways**;
- **16 recorded steps** across two stairways; two stairways have no recorded step count;
- `gradient_source = derived_elevation`;
- `unknown_data_fraction = 1.0` — meaning at least one assessed accessibility attribute is missing along 100% of route length, not that nothing is known;
- `ml_predictions_used = false`.

Do not infer additional grade, surface, time, kerb or safety numbers from the Figma mockups.

## State behavior

### Desktop/mobile route comparison

- Profile route is visually primary; shortest route remains visible.
- Explain route trade-offs visually through Stairs / Grade / Crossings / Surface.
- Only 2–3 important map annotations should be simultaneously prominent.
- `Route Details` and `View Evidence` are supported interaction concepts.

### Idle/planning

- No result metrics before a route exists.
- Origin, destination, mobility profile and optional custom uphill limit remain the focus.
- Custom uphill limit is off by default unless the state explicitly demonstrates it enabled.

### Incomplete data

- Show category-specific gaps, not one confidence score.
- Missing kerb/surface/other evidence remains unknown.
- No report-field-condition action until product feedback functionality is implemented.

### No route / hard requirement

- Never silently relax a hard requirement to return a route.
- The high-level no-route state is required.
- Specific blocking evidence may appear only if the API actually supplies it; otherwise omit it rather than invent candidate-path diagnostics.

## Responsive model

Desktop:

- full-bleed map with floating planning/result surface;
- map visually owns most of the viewport;
- evidence dock/result surfaces must not obscure key route geometry or attribution.

Mobile:

- map-first upper region;
- route result in a bottom-sheet style document flow;
- no unsupported persistent bottom navigation;
- all primary answer/evidence content remains reachable without horizontal scroll.

## Motion

Motion is restrained and functional:

- map camera fit: `450–600 ms`, decelerating/ease-out;
- result/card entrance: `160–220 ms`, subtle opacity + `4–8 px` translation;
- route highlight/dim: `150–200 ms`;
- sheet/drawer transition: `180–240 ms`, ease-out;
- landing-section reveal: `250–350 ms`, subtle and once-only;
- hover/press/focus transitions: `120–160 ms`;
- no looping glow, parallax, bouncing or large spring animation.

`prefers-reduced-motion` removes nonessential transitions and makes camera movement effectively immediate.

## Accessibility implementation expectations

Design toward WCAG 2.2 AA, but do not claim compliance merely because the mockup was designed that way.

Implementation must verify:

- keyboard reachability;
- visible focus states;
- meaningful landmarks/labels;
- no color-only evidence encoding;
- target sizing appropriate for touch;
- axe/Playwright checks;
- reduced-motion behavior;
- contrast in the actual browser rendering.

## Pixel-parity contract

Claude/implementation work is **pixel-parity implementation, not redesign**.

Do not independently change:

- spacing;
- radii;
- hierarchy;
- route colors;
- typography;
- button placement;
- panel shape;
- map composition;
- icons;
- evidence-card layout.

If a Figma element cannot be supported by the backend/product contract, preserve product truth first and document the discrepancy rather than inventing behavior.

For each state:

1. render at the reference viewport;
2. capture the implementation;
3. compare side-by-side with the canonical Figma frame;
4. use an overlay/image diff where practical;
5. fix visual discrepancies before calling the state complete.

The real recruiter demo must run against the real PathAble backend/dataset; do not use a fake route response for the recorded demo.
