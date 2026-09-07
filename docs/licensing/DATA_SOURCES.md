# Data sources and licensing

Status: Gate A+B. The application now ingests **OpenStreetMap data** (from a
published extract) and **NRCan HRDEM elevation**, and serves map tiles from a
public style. Imagery and user-contributed reports remain unstarted and gated.

> This document records engineering understanding of the licences involved. It is
> **not legal advice**. Before any public deployment, and before any imagery is
> ingested, the obligations below should be reviewed properly.

---

## 1. The distinction that matters most

**OpenStreetMap _data_ and OpenStreetMap-_operated services_ are two separate
things with two separate sets of rules.**

|                                | OpenStreetMap data                    | OSMF-operated services                                                        |
| ------------------------------ | ------------------------------------- | ----------------------------------------------------------------------------- |
| What                           | The map database itself               | `tile.openstreetmap.org`, `nominatim.openstreetmap.org`                       |
| Governed by                    | ODbL 1.0                              | The OSMF usage policies                                                       |
| Cost                           | Free                                  | Free, donated, **rate-limited**                                               |
| May an application rely on it? | Yes, with attribution and share-alike | **No** — the policies are explicit that these are not for application traffic |

Conflating the two is the standard mistake. Being permitted to use OSM data does
not permit using OSM's servers to deliver it.

---

## 2. OpenStreetMap data — ODbL 1.0

**Licence:** [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/)

Three obligations:

1. **Attribution.** Credit "© OpenStreetMap contributors" visibly wherever the
   data is shown.
2. **Share-alike.** If a _derived database_ is publicly used, it must be offered
   under ODbL. A pedestrian graph built from OSM is a derived database.
3. **No technical restriction** on redistribution of the database.

### What this means for PathAble

- The Phase 0.5 pedestrian graph will be a **derived database**. If PathAble is
  publicly deployed, that graph must be available under ODbL. This is a
  deliberate consequence, not an accident — it should be treated as a
  contribution back rather than an obligation to work around.
- **Produced Works** — a rendered map image, or a route displayed to a user — do
  not themselves have to be ODbL, but must carry attribution.
- Mixing in an incompatibly licensed dataset could make the derived database
  undistributable. **Every new dataset must be checked for ODbL compatibility
  before ingestion.**

### Current attribution

- On the map: MapLibre `AttributionControl`, non-compact, always visible.
- In the interface: the pilot panel's attribution line, linking to the OSM
  copyright page, and the route panel's footer.
- In every route response: `dataset.attribution`, so a client cannot show a
  route without holding the credit; `dataset.elevation_attribution` carries the
  Open Government Licence – Canada statement whenever a derived grade is present
  (§5).
- In the repository: the README and `docs/evidence/README.md`.

---

## 3. Tile provider

### Currently configured (development only)

`NEXT_PUBLIC_MAP_STYLE_URL=https://tiles.openfreemap.org/styles/liberty`

[OpenFreeMap](https://openfreemap.org/) serves OSM-derived vector tiles with no
account, no API key and no billing relationship. The style and software are open;
the underlying data is OSM under ODbL.

> **Not approved for production.** A free community service offers no
> availability guarantee, no support relationship and no capacity commitment.
> PathAble is intended to help people decide whether they can physically make a
> journey; depending on an unguaranteed third party for that is a risk decision
> the founder must take explicitly. See [ADR 0005](../adr/0005-map-and-geocoding-providers.md).

### Explicitly not used

| Provider                  | Why not                                                                                                            |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `tile.openstreetmap.org`  | The [tile usage policy](https://operations.osmfoundation.org/policies/tiles/) prohibits application traffic.       |
| Mapbox, Google Maps, HERE | Require an account, credentials and billing. Excluded by project rule; their terms also restrict derived-data use. |

### For tests

`apps/web/public/map-styles/offline-test-style.json` — one background layer, no
sources, no network. **No test in this repository depends on a public tile
server.**

### Production options, unresolved

1. **Self-host** (Planetiler + a tile server): full control, no third-party
   dependency, real operational cost.
2. **Continue with a free public service**: no cost, no guarantee.
3. **A paid provider**: requires founder approval for cost and credentials.

---

## 4. Geocoding — implemented, optional, and off by default

Place-name search exists behind a provider abstraction and is **disabled unless a
deployment turns it on** (`GEOCODING_PROVIDER`). Choosing points on the map needs
no geocoder, so search is a convenience rather than a dependency.

One provider is implemented: public Nominatim. This revises the Phase 0
assessment below, which recorded a blanket "no" for it. The
[usage policy](https://operations.osmfoundation.org/policies/nominatim/) does not
forbid application traffic outright — it forbids **bulk** geocoding and
**autocomplete**, and requires at most one request per second and an identifying
User-Agent. PathAble's implementation is built to those terms:

- one request per second, process-wide, enforced by a lock rather than by
  convention;
- **submit-only** — there is no as-you-type endpoint, and the UI does not search
  on keystrokes;
- every request carries a User-Agent naming the project and a contact address,
  and startup fails if that contact is not configured;
- searches are bounded to the pilot region's viewbox.

**This is adequate for a pilot and not for public launch.** Real user traffic at
any volume needs self-hosted Nominatim or Photon, or a local gazetteer built from
the pilot extract. Attribution — "Search by Nominatim, © OpenStreetMap
contributors, ODbL 1.0" — is returned with every result set so a client cannot
display results without it.

| Option                                     | Licence                              | Viable?                                                                                       |
| ------------------------------------------ | ------------------------------------ | --------------------------------------------------------------------------------------------- |
| Public Nominatim                           | Data ODbL; service under OSMF policy | **For a pilot**, within the rate and identification terms above. Not for public launch volume |
| Self-hosted Nominatim                      | ODbL data, GPL software              | Yes; heavy to operate                                                                         |
| Self-hosted Photon                         | ODbL data, Apache-2.0 software       | Yes; lighter, good for autocomplete                                                           |
| Local gazetteer from the pilot OSM extract | ODbL                                 | Yes; likely the pragmatic Phase 1 answer for a single city                                    |
| Google / Mapbox geocoding                  | Proprietary                          | No — cost, credentials, and terms restricting storage of results                              |

Note the trap in proprietary geocoders: several forbid storing results, which is
incompatible with caching an origin/destination pair — and caching is exactly
what a routing product wants to do.

---

## 5. Elevation — selected and implemented

Required for grade, which is a first-order accessibility factor.

**Selected: NRCan HRDEM (CanElevation), 1 m LiDAR bare-earth DTM.**

| Source                               | Licence                                  | Status                                                                |
| ------------------------------------ | ---------------------------------------- | --------------------------------------------------------------------- |
| **NRCan HRDEM / CanElevation**       | **Open Government Licence – Canada**     | **In use.** 1 m LiDAR; commercial use and redistribution permitted    |
| Ontario DTM (Lidar-Derived)          | Open Government Licence – Ontario        | Same underlying survey, clumsier access path. Useful as a cross-check |
| OpenTopoData (SRTM / ASTER)          | MIT software; source data public domain  | Implemented as a fallback for areas HRDEM does not cover              |
| Copernicus DEM GLO-30                | Free with attribution (ESA COP-DEM)      | Not used — 30 m, and a DSM, so it includes buildings and trees        |
| Open-Elevation                       | **No published licence or terms**        | Rejected. Also ~175 m effective cell, measured                        |
| Municipal LiDAR (Region of Waterloo) | Varies — **must be checked per dataset** | Not needed; HRDEM already covers the pilot area at 1 m                |

### Why not a 30 m global model

Resolution is not a detail here. Grade error was measured against the 1 m LiDAR
over 400 randomly placed segments per length in the Waterloo study area:

| Segment length | 30 m bare earth | Copernicus GLO-30 |
| -------------- | --------------- | ----------------- |
| 20 m           | RMSE 3.01 pp    | RMSE 5.91 pp      |
| 50 m           | RMSE 1.63 pp    | RMSE 4.06 pp      |
| 100 m          | RMSE 0.75 pp    | RMSE 2.23 pp      |

The true median grade over 50 m in this area is 1.78%. **A 30 m global model's
error is larger than the signal.** Classified against the 5% running-slope
threshold ADA and AODA use, GLO-30 got 86% of 50 m segments right — and the 18
segments it wrongly called acceptable are exactly the error this product must
not make.

### Obligations

- **Attribution, on every surface showing a derived grade:** _"Contains
  information licensed under the Open Government Licence – Canada."_
- OGL-Canada permits commercial use, redistribution and adaptation, royalty-free
  and in perpetuity, so it does not conflict with ODbL share-alike on the
  derived pedestrian database.
- The 898 GB mosaic is **not** redistributed or stored. It is read in place from
  NRCan's public S3 bucket by byte range; only the sampled elevations for the
  pilot region are stored, each with its source, dataset, resolution and
  acquisition time.

### What it still cannot do

HRDEM is a **bare-earth** model. It describes the ground, not the path laid on
it, so it cannot see a ramp, a step, a boardwalk or a bridge deck. A grade
derived from it is therefore never allowed to overwrite an `incline` recorded by
a mapper, and where the two disagree the disagreement is surfaced rather than
resolved. This limitation is stated to the user, not just recorded here.

---

## 6. Street imagery — reviewed 2026-08-18, still blocked

**No imagery has been acquired, no model trained, and nothing may be ingested
without founder approval and legal advice.** This section records a licensing
review only.

The review changed the shape of the question. The risk is not "which licence
requires attribution" — it is that **there is no free street-level source
covering Waterloo that can lawfully feed a private, commercial, CV-derived
dataset behind a public routing product.** Every path has a defect.

### The four major platforms are out, explicitly

Not by interpretation — several name this exact use case in their own worked
examples.

| Source                 | Blocking clause                                                                                                                                                                                                                                                                                                                                                                                       |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Google Street View     | [GMP ToS](https://cloud.google.com/maps-platform/terms) §3.2.3(c) forbids using content to "improve machine learning and artificial intelligence models, including to train, test, validate or fine-tune", and gives "construct an index of tree locations within a city from Street View imagery" as a prohibited example. §3.2.3(a) separately bans bulk download. Only panorama IDs may be cached. |
| Bing Streetside        | [ToU](https://www.bingmapsportal.com/terms) §2(c) bans "tracing or extracting features from Microsoft's maps, including imagery". Microsoft's own OSM guidance calls CV harvesting from Streetside an "invalid use". Platform retires 2028.                                                                                                                                                           |
| Apple Look Around      | No API returns imagery at all. The consumer terms ban "training of any model"; the developer agreement bans a "secondary or derived database".                                                                                                                                                                                                                                                        |
| HERE / Amazon Location | [HERE Platform Terms](https://legal.here.com/en-gb/terms/here-platform-terms) §6.4(f) bans use "in connection with a machine learning or artificial intelligence system". AWS Location has no street imagery and its §82.4(d) forbids exposing data to open-database licences.                                                                                                                        |

### Mapillary is conditional, on two independent grounds

Mapillary's [terms](https://www.mapillary.com/terms) §12 do expressly permit
commercial "training… of products, algorithms, datasets". But:

1. **§5(1) forbids use "for or in connection with real-time navigation or route
   guidance"** — which lands directly on what PathAble is. No official
   clarification of the clause's reach could be found.
2. **CC BY-SA is formally ODbL-incompatible.** The OSMF lists "All Creative
   Commons Share-alike licences (CC BY-SA)" under
   [specific incompatible licences](https://osmfoundation.org/wiki/Licence/Licence_Compatibility),
   and the import guidance states CC BY-SA "cannot be made ODbL compatible".

Mapillary does grant one narrow exception: imagery may be used "for editing and
deriving metadata **for the purpose of contributing content to OpenStreetMap**"
([mapillary.com/osm](https://www.mapillary.com/osm)). That authorises tracing
into OSM. It does not authorise a private commercial database.

KartaView has no locatable first-party terms page at all — every licence claim
traces to the OSM wiki rather than to KartaView — and no OSM exception. Treat as
unusable until first-party terms are found.

### The ODbL contamination risk, stated precisely

This is worse than an attribution obligation and it is the finding that matters
most.

Adding imagery-derived attributes to OSM geometries makes the routing graph a
**Derivative Database** under [ODbL](https://opendatacommons.org/licenses/odbl/1-0/)
§4.4. §4.6 then requires that if a Derivative Database **or a Produced Work from
one** is publicly used, a machine-readable copy of the Derivative Database, or of
all alterations, must be offered free of charge.

**Shipping only a routing website does not avoid this.** Hard-won accessibility
annotations would become a free download. §4.5(c) exempts internal use only.

And if those annotations came from a CC BY-SA source, the two licences deadlock:
CC BY-SA demands derivatives stay CC BY-SA, ODbL demands the derivative database
be ODbL, and neither yields.

**Four architectures avoid it**, in order of safety:

1. **CC0-only annotation sources** — nothing propagates.
2. **Panoramax**, which uniquely grants explicit permission to relicense
   non-photographic derivatives under ODbL 1.0. No North American instance
   exists; it is self-hostable.
3. **Contribute upstream, consume downstream** — push annotations into OSM under
   ODbL and read them back as ordinary OSM data. Loses exclusivity, gains
   complete licence hygiene, and serves the accessibility mission more durably.
4. **Sidecar database** joined at query time and never merged, relying on the
   [Collective Database Guideline](https://osmfoundation.org/wiki/License/Community_Guidelines/Collective_Database_Guideline_Guideline).
   This preserves the most commercial value and is the most likely to be
   litigated. **Not a decision for an engineer.**

### The route that may make computer vision unnecessary

[Project Sidewalk](https://sidewalk-sea.cs.washington.edu/api) publishes
crowdsourced sidewalk accessibility labels — kerb ramps, obstructions, surface
problems — **dedicated to the public domain under CC0 1.0**, with "no
restrictions on its use". No commercial bar, no share-alike, no attribution
obligation. It is the cleanest licence in the entire landscape.

It has **no Ontario deployment** — the only Canadian city is Burnaby, BC. The
code is MIT and the team actively solicits new cities. Standing up a Waterloo
deployment would produce labels that need no licensing review at all, and would
skip the imagery problem rather than solve it.

### Two traps specific to this project

- **Do not source imagery through the University of Waterloo.** The Geospatial
  Centre's SWOOP terms restrict use to "personal use for academic, research,
  and/or teaching purposes" under a signed release. Given the founder's
  `uwaterloo.ca` affiliation this is a live contamination risk for a commercial
  product, even though the underlying imagery is also available under OGL-Ontario
  through the public channel.
- **Canada has no sui generis database right**, and _CCH v. Law Society_ sets a
  skill-and-judgment originality bar, so a bare observation is weakly
  protectable here. But Mapillary's terms are governed by **Swedish law** with
  **Meta Platforms Ireland** as the contracting entity, which puts the **EU
  Database Directive** in play over the corpus as a whole, independent of
  copyright in any individual photograph.

### Canadian government imagery is aerial, not eye-level

Ontario GeoHub (SWOOP/SCOOP, LiDAR) and Region of Waterloo open data are both
commercially usable with no share-alike, and both are genuinely useful — LiDAR
can give cross-slope, ramp grade and kerb height. **Neither can see surface
condition or obstruction type.** There is no government street-level imagery in
Ontario.

### Nine questions for counsel, not for an engineer

1. Does extracting a factual annotation from a CC BY-SA photograph create
   "Adapted Material"? Creative Commons explicitly declines to answer this
   generically. If no, the deadlock dissolves.
2. Does Mapillary §5(1)'s "in connection with real-time navigation or route
   guidance" bar a pedestrian router built on Mapillary-derived attributes?
   **This single question decides whether Mapillary is usable at all.**
3. Is an accessibility-attribute table keyed to OSM way IDs a Collective
   Database under §4.5(a) or a Derivative Database under §4.4? Everything
   commercial rides on this.
4. Does the EU sui generis right reach systematic API extraction over Waterloo?
5. Is Project Sidewalk's CC0 dedication effective over labels derived from
   Google Street View, given GMP §3.2.3(c)?
6. Cyclomedia's standard terms vest all derivative works in Cyclomedia. Three
   must-haves before engaging: perpetual customer ownership of extracted
   annotations, the right to publish them, and either ODbL-compatible
   publication rights or written blessing of the sidecar architecture.
7. Does Google's ban on "test, validate" foreclose running an already-trained
   model over Street View? §18.13 makes §3.2 survive termination, so
   "extract now, license later" is unworkable.
8. Ontario's restricted imagery tier contradicts its own OGL tag; needs written
   clarification from the province.
9. Is a trained model itself a Derivative Database? The OSMF says predictions
   are not and training sets are; the weights are unsettled.

### Unverified — do not treat as settled

The City of Waterloo's open data licence body text is JavaScript-rendered and
could not be retrieved, though the OSMF Licensing Working Group cleared it in
February 2025. Mapillary, KartaView and Cyclomedia coverage density over
Waterloo is unverified — checking it requires only loading their viewers, and
that is step one of any follow-on. No kerb-ramp inventory exists in any
Waterloo-area portal, which is a ground-truth problem for training and
validation independent of licensing.

### Recommended sequence, if this is picked up

1. Survey Mapillary coverage density across the pilot corridors.
2. Ask the Region of Waterloo and City of Kitchener whether they already license
   Cyclomedia — extending a municipal contract is the cheapest clean route.
3. Contact Project Sidewalk about a Waterloo deployment. CC0 output, and it
   sidesteps computer vision entirely.
4. Get counsel on questions 1–3 before any pipeline is built.

---

## 7. User-contributed reports — Phase 2

Not implemented. When they are:

- Contributors must be told, in plain language, what happens to their report.
- The contribution licence must be settled before the first report is accepted —
  retroactive relicensing is not possible.
- Reports may be publishable as an ODbL-compatible derived database.
- Reports must be storable **without identifying the reporter**. Location
  observations tied to an identity are sensitive personal data.

---

## 8. Software licences

**PathAble itself has no licence yet** — it is private and unreleased, and all
rights are reserved by default. See [`../../LICENSING.md`](../../LICENSING.md).
Do not describe the project as open source.

The obligations below come from what PathAble _uses_ and apply regardless of what
licence PathAble eventually adopts. Key dependencies:

| Component                              | Licence                                                                   |
| -------------------------------------- | ------------------------------------------------------------------------- |
| MapLibre GL JS                         | BSD-3-Clause                                                              |
| Next.js, React                         | MIT                                                                       |
| FastAPI, Pydantic, SQLAlchemy, Alembic | MIT / BSD                                                                 |
| psycopg 3                              | LGPL-3.0 (used unmodified as a library)                                   |
| PostgreSQL                             | PostgreSQL Licence                                                        |
| PostGIS                                | GPL-2.0-or-later (used as a database extension, not linked into our code) |

PostGIS's GPL applies to PostGIS itself. Running queries against it does not make
PathAble a derivative work. Bundling or modifying PostGIS would be a different
question.

---

## 9. Checklist before any new data source

- [ ] Licence identified and recorded, with a link
- [ ] Compatible with ODbL if it will be combined with OSM-derived data
- [ ] Attribution requirements known and implemented
- [ ] Redistribution and share-alike implications understood
- [ ] For imagery: **model training explicitly permitted**
- [ ] Personal data implications assessed
- [ ] Terms allow the volume and frequency intended
- [ ] Founder approval obtained where cost, credentials or ambiguity are involved
