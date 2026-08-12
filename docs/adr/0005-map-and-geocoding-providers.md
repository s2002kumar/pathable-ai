# ADR 0005 — Map tile and geocoding providers

**Status:** Accepted for development · **Production provider is an open decision**
· 2026-08-05 · Phase 0 (P0-A01)

## Context

The application needs raster or vector map tiles now, and will need geocoding in
Phase 1. Both are constrained by a hard project rule: **no paid provider, and
nothing requiring founder credentials or a billing relationship.**

That rules out Mapbox, Google Maps and HERE outright — not because they are bad,
but because they require an account, a key, and a billing method, and because
their terms restrict what may be done with derived data.

The remaining options are OpenStreetMap-derived, which introduces a distinction
that is easy to miss and important to get right:

> **OpenStreetMap _data_ and OpenStreetMap-_operated services_ are separate
> considerations.** The data is ODbL-licensed and free to use with attribution.
> The tile servers and Nominatim instance run by the OSM Foundation are a
> donated, rate-limited community resource with their own usage policies, and
> using them for an application's traffic is not covered by the data licence.

## Decision

### Rendering library: MapLibre GL JS

Open source (BSD-3), no account, no key, no telemetry, vector tiles, and a
provider-agnostic style specification. Swapping tile providers is a URL change.

### Development tiles: OpenFreeMap

`https://tiles.openfreemap.org/styles/liberty` — OSM-derived vector tiles, no
account, no API key, no rate limit published for reasonable use, self-hostable.

Configured via `NEXT_PUBLIC_MAP_STYLE_URL`, so it is a variable rather than a
constant in the code.

> **This is a development choice and has not been approved for production.**
> A free community service carries no availability guarantee and no support
> relationship. Depending on one for a product people use to plan whether they
> can physically make a journey is a different risk decision, and it is the
> founder's to make.

### Tests: a local, source-less style

`apps/web/public/map-styles/offline-test-style.json` contains a single background
layer and no sources. MapLibre reaches its `load` event with **zero network
requests**, so the e2e suite is deterministic, works offline, and cannot fail
because a tile server is having a bad day.

No test in this repository depends on public tile availability.

### Geocoding: deferred to Phase 1, not decided

Phase 0 has no search. When it arrives, the leading candidates are:

| Option                | Notes                                                                                                                |
| --------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Self-hosted Nominatim | Full control, no rate limit, no third-party dependency. Heavy to operate.                                            |
| Self-hosted Photon    | Lighter than Nominatim, good for autocomplete. Still an OSM extract to maintain.                                     |
| Public Nominatim      | **Not acceptable for application traffic** — its usage policy is explicit that it is for occasional, low-volume use. |
| Pelias                | Flexible, heavier operationally.                                                                                     |

Because the pilot is a single city, the pragmatic Phase 1 answer is likely a
**bounded local gazetteer** built from the same OSM extract that produces the
pedestrian graph: no external service, no rate limit, and it only needs to cover
the pilot region. Recorded here as a lead, not a decision.

## Consequences

**Positive**

- No cost, no credentials, no vendor account for Phase 0.
- Provider is a configuration value, so switching is a `.env` change.
- Browser tests are hermetic and offline-capable.
- Attribution is present in two places: the MapLibre control on the map, and the
  written attribution in the pilot panel.

**Negative**

- The default provider has no SLA. Documented in the README, the pilot panel and
  here, rather than quietly assumed.
- Vector tiles need WebGL 2, which some managed and older machines lack. Handled
  by an explicit unsupported state with a written description, not a blank canvas.
- The geocoding decision is deferred, so Phase 1 begins with an open question.

**Reversibility.** High for tiles — one environment variable. Lower for
geocoding, since self-hosting implies infrastructure.

## Open decision for the founder

Before any public deployment:

1. **Production tile provider.** Self-host (control, operational cost) or use a
   free public service (no cost, no guarantee) or a paid provider (cost, needs
   approval)?
2. **Geocoding.** Same question, plus the operational weight of an OSM extract.

Neither blocks Phase 0 or Phase 1 development.

## Attribution obligations

OpenStreetMap data is ODbL. Any product using it must credit
"© OpenStreetMap contributors" visibly, and a derived database that is published
must be shared under the same licence. Full detail in
[`../licensing/DATA_SOURCES.md`](../licensing/DATA_SOURCES.md).

## Alternatives considered

**Mapbox / Google Maps / HERE.** Excluded by the no-paid-provider rule; also
require credentials and restrict derived-data use.

**Raster OSM tiles from tile.openstreetmap.org.** Explicitly prohibited for
application traffic by the OSM tile usage policy.

**Self-hosting tiles now.** Correct eventually, disproportionate for Phase 0:
a tile pipeline is a project in itself and would consume the batch.

**Leaflet instead of MapLibre.** Simpler, but raster-oriented; vector styling and
per-segment route rendering — which Phase 1 needs — are markedly better in
MapLibre.
