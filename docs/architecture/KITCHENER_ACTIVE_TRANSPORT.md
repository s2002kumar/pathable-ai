# City of Kitchener Active Transportation — source audit (PA-GEO-03)

Can the City of Kitchener's published Active Transportation inventory supply
pedestrian accessibility evidence that is **useful, non-default, legally usable
and independent of OpenStreetMap**? PA-GEO-03 froze one snapshot of it and
measured. It changes nothing PathAble routes on: no Kitchener field affects
feasibility, cost, uncertainty or any explanation, and no record is matched to an
OSM way.

**Decision: LIMITED GO** (§13). A few attributes carry real, located, non-default
evidence; the most attractive ones are dominated by template defaults; and the
geometry runs so close to OpenStreetMap's that lineage must be settled first.

Every figure below comes from the committed evidence:

| File                                                                                                   | What it holds                                                                                                     |
| ------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| [`kitchener-active-transport-snapshot.json`](../evidence/kitchener-active-transport-snapshot.json)     | The snapshot manifest: items, layers, schema, edit dates, licence check, archived documents, every request's hash |
| [`kitchener-active-transport-normalized.json`](../evidence/kitchener-active-transport-normalized.json) | The GeoParquet artifact's manifest: inputs, output hash, GeoParquet metadata, CRS pipeline, joins                 |
| [`kitchener-active-transport-profile.json`](../evidence/kitchener-active-transport-profile.json)       | The profile, study geography, adoption matrix and exit-gate figures                                               |
| [`kitchener-geo04-sample.geojson`](../evidence/kitchener-geo04-sample.geojson)                         | The 80-record PA-GEO-04 inspection sample                                                                         |

Code: `services/api/src/pathable_api/geo/kitchener/`; commands `pathable kitchener
snapshot | normalize | audit`.

---

## 1. The source, exactly

The City maintains one internal layer, `GIS_DATA.ACTIVE_TRANSPORTATION`
(TIS – GeoSpatial Data and Analytics), and publishes it through ArcGIS Online
(organisation `qAo1OsXi67t7XgmS`) as several hosted feature services. **Neither
of the two that matter is complete on its own**, so both were frozen together and
joined on the City's permanent id, `ACTIVETRANSPORTID`:

|                  | Active_Transportation                               | Walkability                                                                                                 |
| ---------------- | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Item             | `9fcaa379310643d1a72094972ee55833`                  | `64710818a7e044f4aad99b5d6dff4a3f`                                                                          |
| Layer            | `…/Active_Transportation/FeatureServer/0`           | `…/Walkability/FeatureServer/0`                                                                             |
| Fields           | 63                                                  | 12                                                                                                          |
| Features         | 28,750                                              | 31,801                                                                                                      |
| Carries          | every published attribute                           | the network links                                                                                           |
| Withholds        | anything not `ACTIVE`; the `NETWORK LINKS` category | `STATUS`, `CURBCUT`, condition, inspection, slope, every date but `SOURCE_DATE`; field defaults and domains |
| Data last edited | 2026-09-23T08:16:45.878Z                            | 2026-09-25T07:44:44.505Z                                                                                    |

- Geometry: polylines, NAD83 / UTM zone 17N (EPSG:26917); the City states ±0.5 m
  feature accuracy.
- Retrieved 2026-09-26T12:55:26Z. Snapshot id
  `513094727cc139dd29980e2c281570f9d5183c1d0ca8171754ece0cbd7281b38`.
- 26,499 ids are in both publications, with identical values in every shared
  field and identical geometry. 2,251 are only in Active_Transportation (cycling,
  maintenance access, crossrides, trail crossings, continuous sidewalks) and 5,302
  only in Walkability (every network link).
- The City's metadata report of 2026-05-27 gives 42,056 features for the internal
  layer; the two publications hold 34,052 distinct ids. Neither publishes a record
  that is not active. The City's older `Sidewalks` service (data last edited
  2024-11-21) was also checked on 2026-09-26 with a statistics query, not part of
  the committed evidence: it holds only ACTIVE records too. Planned, potential and
  closed infrastructure therefore cannot be studied from open data, and what the
  remaining internal records are cannot be established from outside.
- The item says "Update Frequency: Daily"; the City's metadata report says
  "ANNUAL". Both are recorded; the service is republished more often than the
  inventory is maintained.

## 2. Licence and independence

**Licence.** Open Government Licence – The Corporation of the City of Kitchener,
**version 1.0**. The text served with the data (the item's `licenseInfo`, SHA-256
`5343e584…`) contains every sentence the earlier research relied on: commercial
use; copy, modify, publish, adapt and distribute; attribution optional, with a
stated credit line; personal information excluded; version 1.0. The snapshot
command checks those sentences on every run and stops normalization if any is
missing.

Three licensing facts are kept apart:

- The City's licence permits PathAble's present read-only research use.
- The City has separately given explicit permission for its data to be
  incorporated into OpenStreetMap.
- Formal OSMF Licensing Working Group approval of the Kitchener licence has
  **not been confirmed**. The OSMF's list of approved Canadian OGL variants
  names the Region of Waterloo, the City of Waterloo and the City of Cambridge,
  not Kitchener, and a review request of 2026-08-18 reported on the OSM forum
  had not been acknowledged.

This does not block this research. But licence compatibility must be reviewed
again, as a founder licensing decision, before any Kitchener-derived assertion
is incorporated into or redistributed with the production OSM-derived routing
database. This is an engineering reading, not legal advice. Details and the
gate: [`DATA_SOURCES.md` §11](../licensing/DATA_SOURCES.md).

**Independence.** The City has given explicit permission for its data to be used
in OpenStreetMap: the OSM wiki page _Waterloo region/Kitchener authorization_,
revision 2726386 (2024-07-03), quotes it, and the OSM _Contributors_ page lists
Kitchener. The snapshot archives that page. **Agreement between Kitchener and OSM
is therefore not independent confirmation**, and §8 shows why this is not a
formality.

## 3. How the snapshot is taken

- **By object id, never by offset.** The count and the full id list must agree;
  features are requested by id in chunks of 1,000 (half the service's
  `maxRecordCount`); every response must return exactly the ids asked for; a page
  flagged `exceededTransferLimit` is refused.
- **Consistency.** The layer's edit dates and count are read again after the read.
  If either moved — a republish mid-read — the read starts over, up to three times.
- **Retries.** Connection errors, HTTP 429/5xx and ArcGIS's own 5xx errors inside
  HTTP 200 bodies are retried with backoff; anything else stops with the reason.
- **Immutable output.** A timestamped folder named by content hash, written under
  a temporary name, renamed only when complete, then made read-only. It holds
  every raw page, one canonical line per feature, the item, service and layer
  descriptions, and five documents: the City's two metadata reports, its licence
  page, and the OSM wiki revision and page.
- **Two content hashes.** `features_sha256` covers features as served, in
  `OBJECTID` order. `municipal_content_sha256` orders by `ACTIVETRANSPORTID` and
  drops `OBJECTID`, which the City documents as changing on export and import;
  in this snapshot the two publications agree on it for every shared record.
- **The Hub export was evaluated and not used.** On 2026-09-26 its GeoJSON export
  of Active_Transportation (the service's replica file cache) was complete, and
  all 28,750 geometries were identical to this read, in the native CRS. But it is
  generated asynchronously on request, rewrites date fields as HTTP-date text,
  covers one publication per file, and can be checked only as a whole file. The
  by-id read can be checked request by request.

**Reproducibility.** Two retrievals 40 s apart produced identical feature files for
both publications, all 61 raw pages byte for byte, and all five documents; each
received 70,137,658 bytes in 80 requests. An earlier development retrieval, about
70 minutes before and not committed, had produced the same snapshot id. The source did not change
between these runs, so this shows the read is deterministic; it cannot show how
the read behaves across a real republish.

## 4. The analytical GeoParquet file

`kitchener-active-transport.parquet` holds one row per municipal record (34,052),
following **GeoParquet 1.1.0**. That is the current stable release; 2.0.0 was at
release candidate on 2026-09-26. The `geo` metadata is written by the code, not
inferred by the writer. The file contains:

- identity (`activetransportid`, publication membership, both `OBJECTID`s) and any
  field on which the publications disagree (none here);
- every raw attribute under its own name, except `CREATE_BY` and `UPDATE_BY`,
  which hold staff user names — only whether an update came from a named system
  account is kept;
- `geometry` in OGC:CRS84 (the primary column, with a bbox covering) and
  `geometry_native` in EPSG:26917 with PROJJSON, untouched;
- per-field **value states** — not published, null, blank, unknown, not
  applicable, template default, non-default, out of domain — and **evidence
  origins**, network role, lifecycle, physical class and SOURCE vocabulary class.

Defaults and domains come from the layer description archived in the snapshot,
not from code. Walkability serves none, so its records are classified by the
internal layer's schema, which only Active_Transportation publishes. That was a
bug before it was caught: a Walkability-only `CONCRETE` was being called
"non-default".

**CRS.** PROJ's default path from NAD83 to WGS 84 is a null datum shift, with a
stated accuracy of 4 m (PROJ 9.5.1). It is recorded in the manifest; every
distance in this audit is computed in native metres.

**Reproducibility.** Three normalizations of the one frozen snapshot produced
byte-identical files (SHA-256 `ffe042be…`, 6,799,591 bytes).

## 5. What the inventory contains

| Physical class                  |             Records | Of which in the pilot study area |
| ------------------------------- | ------------------: | -------------------------------: |
| Physical, active                |              28,727 |                           12,897 |
| — pedestrian ways and crossings | 26,594 (1,638.0 km) |                11,835 (686.0 km) |
| Virtual street crossing (link)  |               5,030 |                            2,019 |
| Unofficial connection           |                 276 |                              116 |
| Unresolved                      |                  19 |                               10 |

- Every geometry is valid, single-part and of non-zero length. Their lengths agree
  with the service's own `Shape__Length` to 0.05 m.
- `ACTIVETRANSPORTID` is present and unique on every record of both publications.
- Largest subcategories: sidewalk 16,126; crosswalk 4,453; pedestrian link 4,411;
  multi-use trail 2,254; boulevard multi-use trail 1,576; major trail 1,055.

## 6. The default-value problem

Every attractive field has an ArcGIS template default. A value equal to its
default cannot be told apart from a record nobody edited, so it is **never
counted as evidence**; null, blank, unknown and default are kept apart throughout.

| Field (default)               | What the snapshot shows                                                                                                                                                                                                                                                                                         |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `WIDTH_M` (1.5)               | 1.5 on 18,543 records and on **15,489 of 16,126 sidewalks (96.1%)**. The City documents "default width 1.8m"; **no record has 1.8**, which is not in the coded domain. 0 on 8,751 records, mostly crossings and links. 6,684 non-default, non-zero widths, mostly 3 and 3.5 m on trails, all from a coded list. |
| `SURFACE_MATERIAL` (CONCRETE) | CONCRETE on 18,317 records and **15,888 of 16,126 sidewalks (98.5%)**. 10,448 non-default values: asphalt 6,988, painted asphalt 2,049, stonedust 918, natural 178, gravel 113, brick 112, wood 50, and others.                                                                                                 |
| `SURFACE_CONDITION` (GOOD)    | **Explicit UNKNOWN on 21,776 of 28,750.** GOOD on 5,518; 871 of those come from records whose source is the 2015 trail inventory. FAIR, POOR or UNUSABLE on 1,224 — 1,089 of them active pedestrian ways and crossings.                                                                                         |
| `CURBCUT` (N)                 | N on 21,786; **Y on 6,888**; U on none; null on 76. Y marks short segments — median 2.22 m, against 58.6 m for N — matching the City's definition: "the facility is a curbcut down to street level". 5,322 of the Y records are sidewalk segments.                                                              |
| `RAILING` (N)                 | Y on 133, including 57 of the 77 stairs.                                                                                                                                                                                                                                                                        |
| `FEATURE_TYPE` (SURFACE)      | STAIRS 77, BRIDGE 94, UNDERPASS 74, OVERPASS 49, BOARDWALK 17.                                                                                                                                                                                                                                                  |

553 Active_Transportation records have all six of these fields at their default,
and 12,016 have five. Among the 26,594 active pedestrian records, 15,732 carry at
least one non-default value from the list above. Much of that count is crosswalks
coded as asphalt and trails with design widths, which are true but of little
accessibility value.

## 7. Provenance, freshness and evidence origin

- **SOURCE** is populated on 32,259 records. 30,061 cite orthoimagery
  (`ORTHO 2012` and similar, 1997–2026), and on 29,641 of them `SOURCE_DATE` falls
  in the imagery's year. **SOURCE_DATE dates when a record was captured, not when
  any attribute was observed.** Other classes:
  - the 2015 trail inventory, 1,674;
  - plans, 254;
  - projects, 129;
  - staff, 115 (49 of them "to be verified");
  - personal observation, 20;
  - Google Street View, 3 — a licensing flag to carry forward;
  - placeholder, 2.

  Personal observations and one unclassified value are counted but not published.
  The City documents that SOURCE may name a staff member.

- **UPDATE_DATE is not freshness.** 28,209 of 28,750 values (98.1%) fall on one
  day, 2026-08-24, written by the `GIS_DATA` account.
- **LAST_INSPECTION_YEAR** is populated on 25,911 records, with 2026 on 17,071. It
  is documented as the year of an inspection by the City's programmes. It dates an
  inspection, not what the inspection found.
- **INSTALLATION_YEAR** is 1997 on 9,514 of 23,026 populated values (41.3%). That
  looks like a bulk load; it is unresolved.
- **Derived fields.**
  - `GRADE`, documented as "calculated through a script", is UNKNOWN on 33,284 of
    34,052 records.
  - The `SLOPE_GRADIENT_*` fields name an FME workspace (`CalculateTrailGradient`)
    as their source, and 16 exceed 100%.
  - `GRADE_CATEGORY_MAX` agrees with the City's own `SLOPE_GRADIENT_MAX` on only
    12,438 of 24,525 records.
  - `CONDITION_SCORE` takes only the values 0 and 1. 990 of its 992 values have no
    `CONDITION_DATE`, and 391 dates have no score.

Evidence origin is classified per value, only where the City's documentation
supports a class. There are five classes, plus unresolved:

- observed survey: condition "as found in the 2015 Trail inventory project";
- observed event: the inspection year;
- administrative assertion: a deliberate non-default value whose per-record
  origin is undocumented;
- derived: script- or Cityworks-calculated values;
- template default, and unknown.

Anything the documentation does not explain is `unresolved`, for example
`GRADE_CATEGORY_MAX`.

## 8. Study geography and overlap

**Study area.** PathAble's own pilot region, exactly as defined in
`pathable_api.geo.regions` (ADR 0006): the rectangle −80.59, 43.42 to −80.46,
43.52 (EPSG:4326). The stored region boundary is identical. Dataset `51585450…`
(checksum `51e75f78…`) has recorded bounds within 4×10⁻⁶° of it, and its edges do
not extend beyond it.

**Overlap is meaningful.**

- 15,042 of 34,052 records (44.2%; 825.1 of 1,948.1 km) intersect the area,
  including 11,835 active pedestrian ways and crossings (686.0 km).
- 55,530 of PathAble's 180,554 edges (30.8%) lie within 20 m of one of those
  records.
- An intersection is overlap feasibility, not a match.

**The geometry runs along OpenStreetMap's.** Each in-area pedestrian record was
sampled every metre, and its worst point measured against the nearest OSM
footway, path, pedestrian way or steps edge. This is a directed Hausdorff distance;
a closest-approach distance would call a line that merely touches OSM at one corner
coincident.

- **10,375 of 11,835 (87.7%) lie entirely within 2 m.**
- For sidewalks: 7,190 of 7,654 (93.9%), median worst point 0.91 m.
- For CURBCUT=Y segments: 2,986 of 3,296.

That is consistent with OSM's pedestrian network sharing lineage with the City's
inventory, through import or through tracing the same imagery. It is not proof,
and it is measured across a datum shift of stated 4 m accuracy. **This does not
establish independent geometry.** The high agreement, together with the City's
documented permission for OSM use, means PathAble must treat the geometry as
potentially shared-lineage until record-level history is inspected. Likewise,
where OSM already carries an attribute, agreement may be the same fact twice.

**OSM baseline on the same ground.** On the 55,530 edges near the inventory:

- 2,937 of 5,357 crossing edges (54.8%) already carry a kerb value;
- 19,193 of 33,131 separate pedestrian edges (57.9%) carry a surface;
- 189 (0.6%) carry a width.

## 9. Field adoption matrix

No field is approved for routing. "Eligible for normalized evidence" means only
that a later card may translate the value into PathAble's vocabulary as a source
claim, kept apart from OpenStreetMap facts.

| Field                               | Disposition                      | Scope                                          | Rests on                                                           |
| ----------------------------------- | -------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------ |
| `ACTIVETRANSPORTID`                 | identity/provenance              | all                                            | 0 null, 0 duplicated, joins both publications with no disagreement |
| `OBJECTID`                          | rejected as identity             | —                                              | documented to change on export/import                              |
| `SOURCE`, `SOURCE_DATE`             | identity/provenance              | by vocabulary class                            | 30,061 orthoimagery; date = imagery year on 29,641                 |
| `CREATE_DATE`, `STATUS_DATE`        | identity/provenance              | all                                            | database-maintained timestamps                                     |
| `UPDATE_DATE`                       | rejected as freshness            | —                                              | 98.1% on one bulk day                                              |
| `STATUS`                            | identity/provenance              | publication filter                             | 100% ACTIVE, which is also the default                             |
| `CATEGORY`, `SUBCATEGORY`           | matching/conflation input only   | all                                            | separates sidewalks, crossings, trails, links                      |
| `FEATURE_TYPE`                      | eligible for normalized evidence | STAIRS, BRIDGE, OVERPASS, UNDERPASS, BOARDWALK | 311 deliberate departures from SURFACE                             |
| geometry                            | matching/conflation input only   | all                                            | 87.7% within 2 m of OSM along the whole line                       |
| `WIDTH_M`                           | comparison only                  | non-default, non-zero; 1.5 and 0 never         | 96.1% of sidewalks at the default; 1.8 never occurs                |
| `SURFACE_MATERIAL`                  | eligible for normalized evidence | non-default only; CONCRETE never               | 10,448 non-default; 98.5% of sidewalks CONCRETE                    |
| `SURFACE_CONDITION`                 | eligible as raw evidence         | FAIR/POOR/UNUSABLE, dated 2015                 | 1,224 non-default; UNKNOWN on 21,776                               |
| `CURBCUT`                           | eligible for normalized evidence | Y only; N never means "no curb cut"            | 6,888 short ramp segments                                          |
| `RAILING`                           | eligible as raw evidence         | Y only                                         | 133; no railing input in the cost model                            |
| `GRADE`                             | rejected                         | —                                              | UNKNOWN on 33,284 of 34,052                                        |
| `SLOPE_GRADIENT_*`                  | comparison only                  | against PathAble's derived grade               | FME-derived; 16 over 100%                                          |
| `GRADE_CATEGORY_MAX`                | rejected                         | —                                              | undocumented; 50.7% agreement with SLOPE_GRADIENT_MAX              |
| `CONDITION_SCORE`, `CONDITION_DATE` | rejected                         | —                                              | 0/1 only; score and date almost never together                     |
| `LAST_INSPECTION_YEAR`              | eligible as raw evidence         | the year a record was inspected                | 25,911 populated; 2026 on 17,071                                   |
| `INSTALLATION_YEAR`                 | unresolved                       | —                                              | 1997 on 41.3%                                                      |
| virtual links                       | matching/conflation input only   | topology, crossing location                    | 5,030; never a routable segment                                    |
| unofficial connections              | comparison only                  | connectivity context                           | 276                                                                |
| `ROADSEGMENTID`, `ROADSEGMENT_SIDE` | matching/conflation input only   | LEFT/RIGHT                                     | 53 `UNDEFINED`, outside the City's domain                          |
| `NOTES`                             | rejected                         | —                                              | only CHECK and DONE, undocumented                                  |

## 10. Canonical-model requirements, checked against Kitchener

The research proposed requirements for a source-independent model. What this
real source supports, and what it changes:

| Requirement                               | Kitchener shows                                                                                           | Change                                                                                                                                      |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Source provider                           | One municipality                                                                                          | Kept                                                                                                                                        |
| Source dataset                            | One internal layer, served as several filtered views                                                      | **Add the publication**: which view a record was read from, and what that view withholds, so a missing record is not read as a missing path |
| Snapshot/version                          | No upstream version exists; only edit timestamps                                                          | **Snapshot = our content hash**; upstream timestamps recorded, never treated as versions                                                    |
| Source record id                          | `ACTIVETRANSPORTID` is stable; `OBJECTID` is documented not to be                                         | **The documented permanent id only**; service row numbers are never identity                                                                |
| Feature type                              | Links and connections sit beside physical records; 19 are ambiguous                                       | **Add network role and physical class**; nothing with a virtual signal is routable                                                          |
| Geometry                                  | Native NAD83/UTM, ±0.5 m; the conversion is a null shift of stated 4 m accuracy                           | **Keep the native geometry** beside the converted one, with the transformation recorded                                                     |
| Raw value and normalized value            | Defaults dominate; unknown codes vary by field (`UNKNOWN`, `U`, `NA (VIRTUAL LINK)`)                      | **Add the value state** as a first-class field; normalize non-default values only                                                           |
| Evidence origin                           | Supported for documented fields only                                                                      | Kept; `unresolved` is a legitimate value                                                                                                    |
| Source dates                              | SOURCE_DATE dates the record's capture; the inspection year dates an event; UPDATE_DATE dates maintenance | **Type every date** by what it dates. Per-attribute observation dates are not supplied by this source                                       |
| Record dates                              | Maintenance timestamps, one bulk day                                                                      | Kept as lineage, never as freshness                                                                                                         |
| Lineage                                   | The City permits its data in OSM, and the geometry runs along OSM's                                       | **Add lineage relative to OSM** (derived / independent / unknown), per source and ideally per record                                        |
| Match state, relationship, conflict state | Not exercised: no matching in this card                                                                   | Deferred to PA-GEO-04/05, unchanged                                                                                                         |

## 11. PA-GEO-04 sample

80 records, drawn from the 15,042 that intersect the study area. Each record falls
into one stratum, the first whose rule it meets. Every non-empty stratum gets at
least three records, and the rest are shared by stratum size (largest remainder).
Within a stratum, records are ordered by `sha256("pathable-pa-geo-04-sample-v1:" +
snapshot_id + ":" + ACTIVETRANSPORTID)`. The draw is reproducible from the snapshot
and the seed, and nothing was chosen by eye.

| Stratum                                | Population | Sampled |
| -------------------------------------- | ---------: | ------: |
| Virtual link                           |      2,019 |       6 |
| Unofficial connection                  |        116 |       3 |
| Unresolved semantics                   |         10 |       3 |
| Stairs                                 |         40 |       3 |
| Other structure                        |        116 |       3 |
| CURBCUT = Y                            |      3,294 |       9 |
| Not along OSM (a point ≥ 20 m away)    |        341 |       3 |
| Offset from OSM (worst point 3–20 m)   |        514 |       3 |
| Crossing                               |      2,172 |       7 |
| Trail                                  |        809 |       4 |
| Walkway                                |        185 |       3 |
| Merged-looking (multi-part or ≥ 400 m) |         59 |       3 |
| Split-looking (< 5 m)                  |        209 |       3 |
| Dense-core sidewalk                    |        370 |       3 |
| Parallel sidewalk pair                 |      3,752 |      14 |
| Residential sidewalk                   |        168 |       3 |
| Ordinary sidewalk                      |         82 |       3 |
| Other physical                         |        786 |       4 |

The sample's rules that mention OSM describe where records sit; they match nothing.

## 12. Performance

Measured on one Windows laptop (16 GB, about 1.7 GB free when checked), every run
recorded. Two runs of identical work took about six times longer than their
twins, with byte-identical output. The cause was not established, so ranges are
given rather than a single number.

| Operation                                         | Measured                                                                                                        |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Snapshot, both publications and documents         | 31.0 s and 28.0 s; 80 requests; 70,137,658 bytes received; 137,961,539 bytes stored; peak process memory 541 MB |
| Canonical features                                | 52,580,774 bytes (Active_Transportation), 15,722,721 bytes (Walkability)                                        |
| Normalization                                     | 21.6 s, 140.2 s and 20.5 s (writing 5.5–6.5 s of each); 6,799,591-byte GeoParquet; peak 973 MB                  |
| Profile (DuckDB)                                  | 1.5–2.4 s over four audit runs                                                                                  |
| Geography, including the per-metre offset measure | 20.6–139.8 s over four audit runs; peak 645 MB                                                                  |

## 13. Exit gate

1. **Meaningful overlap with the pilot?** Yes. 11,835 active pedestrian records
   (686.0 km) intersect it, and 30.8% of PathAble's edges lie within 20 m of them.
2. **Active physical pedestrian records?** 26,594 (1,638.0 km) in total; 11,835 in
   the study area.
3. **Useful fields beyond template defaults?** Only in particular classes:
   - curb-cut segments: 6,888, of which 3,296 are in the study area;
   - stairs: 77 (40); other structures: 234;
   - railings: 133;
   - non-default surfaces: mostly trails, crossings and lanes;
   - trail condition: 1,224 values, dated 2015.

   Sidewalk width and surface are defaults (96.1% and 98.5%); sidewalk condition is
   mostly explicit UNKNOWN. Grade is empty, and condition scores are unusable.

4. **Provenance and freshness?** Record-level only. A source date (the capture
   imagery's date) is on 31,993 records (94.0%), and the inspection year on 25,911
   (2026 on 17,071). No attribute carries its own observation date, except
   condition's documented 2015. The update date is a maintenance run.
5. **Stairs, crossings, curb-related facilities?** 77 stairs (40 in the study area),
   4,513 pedestrian crossings (2,222), and 6,888 CURBCUT=Y segments (3,296).
6. **Virtual or non-physical?** 5,325: 5,030 virtual links, 276 unofficial
   connections and 19 unresolved (2,145 in the study area). None of them is direct
   graph evidence.
7. **Enough to justify another card?** For particular attributes, yes — see below.

### Decision: LIMITED GO

Continue to PA-GEO-04 for **curb-cut segments, stairs and structures with their
railings, non-default surface material, dated trail condition, and the network
links (for topology only)**, with the inspection year as record-level freshness.
Nothing else goes forward:

- width, CONCRETE, GOOD, grade, the derived slope and condition fields, and the
  update date are not carried;
- no sidewalk attribute is carried on the strength of a default.

PA-GEO-04's first question is **lineage**, before any attribute work. The
geometry's closeness to OSM, and the City's permission to use its data there,
mean a Kitchener value may already be in OSM. That is plausible where 54.8% of
nearby crossing edges already carry kerb values. Where a value in OSM came from
the City, agreement with it adds nothing independent. Kitchener's contribution is
what OSM lacks, and that can only be counted once lineage is known. The 80-record
sample exists for that inspection.

Before any later card writes a Kitchener-derived value where routing can read it,
the licensing gate in §2 applies.

## 14. Unresolved

- What `GRADE_CATEGORY_MAX`, `CONDITION_SCORE` (0/1) and the `NOTES` values CHECK
  and DONE mean.
- Why 1997 is 41.3% of installation years.
- Whether CURBCUT=Y means a lowered or a flush kerb.
- Whether combined and mixed crossrides are for pedestrians.
- Which NAD83 realization the City's coordinates use.
- What the roughly 8,000 internal records missing from both publications are.
- Whether OSM's kerb values in Kitchener came from CURBCUT.
