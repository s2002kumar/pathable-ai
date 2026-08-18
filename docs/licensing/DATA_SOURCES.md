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
  copyright page.
- In the repository: the README.

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

## 6. Street imagery — Phase 2, blocked pending review

**No imagery source has been selected. No imagery has been ingested. No imagery
may be ingested without an explicit licensing review and founder approval.**

This is the sharpest licensing risk in the project, because imagery licences
differ enormously in whether they permit:

- storing images,
- deriving a dataset from them,
- **training a model on them**,
- publishing anything derived.

| Candidate          | Licence                | Concern                                                                              |
| ------------------ | ---------------------- | ------------------------------------------------------------------------------------ |
| Mapillary          | CC BY-SA 4.0 (imagery) | Share-alike may extend to derived datasets; ownership by Meta means terms can change |
| KartaView          | CC BY-SA 4.0           | Smaller coverage                                                                     |
| Google Street View | Proprietary            | **Terms prohibit bulk download and ML training.** Not usable                         |
| Bing Streetside    | Proprietary            | Same class of restriction                                                            |
| Self-collected     | Ours                   | No licence issue; large effort; introduces privacy obligations (faces, plates)       |

Two questions must be answered **before** any ingestion code is written:

1. Does the licence permit training a model on the imagery?
2. Does it impose share-alike on the resulting model or dataset?

A wrong answer discovered after training means discarding the model.

Self-collected imagery is not licence-free either: it captures people and
vehicles, which brings PIPEDA obligations and a blurring requirement.

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
