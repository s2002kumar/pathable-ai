# ADR 0007 — Phase 0 frontend: design system, map loading, and honest UI

**Status:** Accepted · 2026-08-05 · Phase 0 (P0-A01)

## Context

The Phase 0 frontend has an unusual brief: it must look like the beginning of a
serious consumer mapping product, while doing almost nothing. It has a map, a
status indicator and some text. Everything a mapping product normally has —
search, route buttons, profile selectors — does not exist.

Two failure modes to avoid:

1. **Ship an unstyled engineering dashboard.** Nothing about it would be reusable
   in Phase 1, and the visual language would be invented later under time
   pressure.
2. **Ship a polished mock.** Add a search box and a "Find route" button because
   they make the screenshot look complete. For a product whose users may rely on
   it to decide whether they can physically make a journey, a control that looks
   live and does nothing is not a harmless placeholder.

There is also a technical constraint: MapLibre needs `window` and a WebGL 2
context, neither of which exists during server rendering.

## Decision

### Design tokens, not a UI framework

Semantic CSS custom properties in `src/styles/tokens.css` — spacing, radii,
typography, shadows, and colours named by role (`--color-text-muted`,
`--color-ok-surface`) rather than by hue. Components reference tokens; a raw hex
value in a component is a bug, because it will not follow the dark theme.

No Tailwind, MUI, Chakra or shadcn. A component library for a header, a card and
a badge would add a dependency, a bundle and a set of opinions to fight, and its
accessibility characteristics would be inherited rather than understood. This
product cannot treat accessibility as inherited.

CSS Modules per component: scoped by default, no runtime, no naming convention to
enforce.

Light and dark themes both ship, via `prefers-color-scheme`. Every text/background
pair targets WCAG AA. **The axe scan caught a real failure here** —
`--color-text-subtle` at 4.32:1 on the sunken surface — which is precisely why
the check is in CI rather than a checklist.

### Layout: map-first, panel-over-map on desktop, stacked on mobile

Desktop (≥ 64rem): the map fills the workspace; the pilot panel floats top-left
as a card, anchored top _and_ bottom so its height is definite and long content
scrolls inside the card. Top-left is chosen deliberately — MapLibre puts
navigation top-right, scale bottom-left and attribution bottom-right, so the
panel never covers the map's own chrome.

Mobile: the map takes 58 dvh and the panel sits below it in normal flow. Nothing
overlaps, so map controls can never sit on top of the written description, and
the page never scrolls sideways (asserted in the e2e suite).

### Map loading: `next/dynamic({ ssr: false })` plus a dynamic import

Both, for different reasons. `next/dynamic` guarantees the component never
renders on the server. The `await import('maplibre-gl')` inside the effect keeps
~800 kB out of the initial bundle _and_ leaves the hook module importable under
jsdom, so the lifecycle is unit-testable without a GPU.

The lifecycle is a four-state machine published on `data-map-state`:

| State          | Shown                                                           |
| -------------- | --------------------------------------------------------------- |
| `initialising` | Spinner, "Loading the map…", pointer to the written description |
| `ready`        | The map, overlay removed                                        |
| `error`        | Explanation + written description (alert)                       |
| `unsupported`  | Browser-level explanation + written description (alert)         |

Design points worth recording:

- **WebGL support is resolved during render, not in an effect.** An unsupported
  browser shows its explanation immediately rather than a spinner that will never
  resolve. It also keeps `setState` out of the effect body.
- **A tile error after `ready` does not downgrade the map.** Replacing a usable
  map with an error screen is worse than a missing tile.
- **A 15-second timeout** catches the case where a style neither loads nor errors.
- **The attribute is the test contract.** Browser tests wait on `data-map-state`
  instead of racing a canvas.

### The written pilot description is not a caption

It is the accessible equivalent of the map: it states the same facts — extent,
landmarks, street types — for anyone who cannot see the map, has no WebGL, or is
on a connection where tiles never arrive. It is referenced from the map region
via `aria-describedby`.

### No fake functionality

No search box, no route button, no mobility selector, no report control. The
Phase 1 preview is a plain unordered list under the heading "Planned for Phase 1",
with no focusable element. The frontend test suite asserts that the shell
contains zero textboxes, searchboxes, comboboxes and radios, and that every link
points at an external reference — so a future contributor cannot quietly add a
decorative control.

A prominent, permanent notice states that there is no routing and no machine
learning, and that nothing shown should be used to plan a journey.

## Consequences

**Positive**

- Tokens, layout primitives and map states carry directly into Phase 1.
- Small bundle; no UI framework.
- Accessibility is owned rather than inherited; contrast is machine-checked.
- Map failure paths are first-class and tested, not afterthoughts.
- The interface cannot mislead about capability, and tests enforce it.

**Negative**

- Building components by hand is slower per component than importing them.
  Acceptable at this component count; revisit if the surface grows quickly.
- Two mechanisms (dynamic component + dynamic import) to keep MapLibre off the
  server, which is mild redundancy — deliberate, and commented in the code.
- The map hook does not reset state when the style URL changes; callers remount
  instead (`key={styleUrl}`). A trade for avoiding cascading renders, documented
  at the hook.

**Reversibility.** High. Tokens can back a component library later; the map
states are independent of the styling approach.

## Alternatives considered

**Tailwind.** Fast, widely known, and would put layout decisions in class strings
rather than in a named design system. For a project where contrast and theming
are product requirements, semantic tokens make the constraint visible.

**A component library (MUI, Chakra, shadcn).** Would supply accessible primitives
this phase does not need, at the cost of a dependency whose accessibility
behaviour is inherited rather than understood.

**Render the map server-side.** Not possible; MapLibre requires WebGL.

**Static map images as a fallback.** Would need a rendering service and a
provider decision. The written description is a better fallback anyway: it works
for screen-reader users, whom a static image does not help at all.

**Include a disabled search box "to show the shape".** Rejected. Disabled
controls still communicate that the feature exists and is momentarily
unavailable, which is not true.
