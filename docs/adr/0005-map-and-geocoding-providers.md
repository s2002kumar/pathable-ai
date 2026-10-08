# ADR 0005 — Map tile and geocoding providers

**Status:** Accepted · tiles: a development choice, production provider still open ·
geocoding: decided 2026-10-07, a bounded local gazetteer · 2026-08-05 · Phase 0 (P0-A01)

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

### Geocoding: a bounded local gazetteer (decided 2026-10-07)

Phase 0 had no search, and until 2026-10-07 the only implemented provider was
public Nominatim behind an opt-in flag. With the default off, the planner's
origin and destination fields looked searchable and were not, which is worse
than having no field.

**Decision.** Search answers from a **place index for the pilot region, read out
of the same OpenStreetMap extract the routing network was built from**, stored in
PostGIS beside the network, and queried by the API itself. It is the default
provider (`GEOCODING_PROVIDER=local`).

- **What it holds.** Named places (amenities, shops, parks, campus buildings,
  stations, squares — from nodes, ways and multipolygon relations), addresses
  (house number and street wherever mapped), and named streets, one entry per
  connected stretch. Each is one point: a node, a point guaranteed inside an
  outline, or the middle of a street. Only points inside the region's extent.
- **How it matches.** Stored names and queries are normalised the same way
  (accents, punctuation, `St`/`Ave`/`N`/`W`). Every word typed must start a word
  in the entry, and a house number must match whole. Exact, then prefix, then
  places before streets before addresses (addresses first when the query starts
  with a number), then trigram similarity. A `pg_trgm` word-similarity pass runs
  only when that finds nothing, so a typo still finds the place without fuzzy
  matches crowding out exact ones. At most five results.
- **Kept apart from routing.** A result is a coordinate, which the routing
  endpoint snaps like a map click. The index is not part of a dataset version,
  is not sealed or checksummed with the network, and references no edge. It is
  replaced whole, in one transaction, by `pathable gazetteer build`.
- **Provenance.** The index records the extract's file name, SHA-256 and the
  date its data is current to (from the extract's own header, never the read
  time). Every result set carries "Places from OpenStreetMap as of _date_.
  © OpenStreetMap contributors, ODbL 1.0", and the build reports whether the
  extract is the one the active network came from.
- **Still submit-only.** One request per search, not per keystroke, so the same
  client stays correct against any provider.

**Why this and not a service.** It is the lead this ADR recorded in August, and
it needs nothing new: the data is already held and already licensed (ODbL, with
attribution already shown), PostgreSQL and `pg_trgm` already run, and nobody
else's servers are called. `pg_trgm` is a trusted extension from PostgreSQL 13,
so the managed-hosting restore path (KI-8) still needs no superuser.

| Option                         | Why not, for one pilot city                                                                                         |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| Public Nominatim               | Its usage policy rules out application traffic. Kept as an opt-in development provider only.                        |
| Self-hosted Nominatim / Photon | A second stateful service with its own index and update cycle: changes the costed operations in ADR 0009.           |
| Pelias                         | Heavier still to operate.                                                                                           |
| Paid (Geoapify, LocationIQ, …) | Costs money, needs an account, and their terms restrict storing or displaying results. Would need founder approval. |

**What it does not do.** No address interpolation along a street, so a house
number nobody mapped is not found. No postcodes. No as-you-type suggestions.
Coverage and freshness are exactly the extract's — see
[KI-11](../development/KNOWN_ISSUES.md).

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
- Place search is one more thing built from each extract: `pathable gazetteer build`
  after an import, or search keeps describing the previous map (KI-11).

**Reversibility.** High for tiles — one environment variable. High for
geocoding too: the provider is a setting, and the index is two tables that
nothing else references.

## Open decision for the founder

Before any public deployment:

1. **Production tile provider.** Self-host (control, operational cost) or use a
   free public service (no cost, no guarantee) or a paid provider (cost, needs
   approval)?
2. ~~**Geocoding.**~~ Decided 2026-10-07 (above): the local gazetteer needs no
   provider, account or spend. Revisit only if search must cover more than the
   pilot region or needs address interpolation.

The tile decision does not block development.

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
