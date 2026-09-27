# Kitchener and OpenStreetMap — geometry and lineage study (PA-GEO-04)

For the 80 sampled records of the City of Kitchener's Active Transportation
inventory ([PA-GEO-03](KITCHENER_ACTIVE_TRANSPORT.md)), PA-GEO-04 asks three
questions:

- Does OpenStreetMap carry the same facility?
- Where did OSM's shape and its accessibility values come from?
- What would the City add that OSM lacks?

It changes nothing PathAble routes on. No Kitchener value reaches feasibility,
cost, uncertainty or an explanation. Nothing is matched automatically, and no
weight or threshold exists.

**Decision: LIMITED GO** (§14). PA-GEO-05 should benchmark only three classes:
curb cuts against OSM kerb nodes, stairs and structures, and non-default
surfaces. The City's geometry goes forward only as a matching input, never as
evidence.

Headline findings:

1. **Most records have an obvious OSM counterpart.** 69 of 80 do. 7 are
   ambiguous, because OSM collapses a curb-cut stub into a junction or records a
   bicycle lane as a tag on the road. 4 have none. OSM often merges what the
   City splits: 30 of the 69 are many-to-one.
2. **OSM's shapes probably share the City's photographs.** Since 2016, Esri World
   Imagery's finest layer over Kitchener has been the City's own orthophotos,
   then the Region of Waterloo's. The City's records were traced from photographs
   of the same years. 63 of the 69 obvious counterparts were shaped in OSM edits
   that recorded Esri imagery since then, and one road was reshaped from the
   City's own open data. OSM's geometry there is therefore not independent
   confirmation of the City's, and the City's geometry adds nothing independent.
3. **OSM's accessibility values mostly come from people on the ground.** All 5
   OSM kerb values found at sampled curb cuts, and 9 of the 13 traceable OSM
   surface values, were set in StreetComplete survey edits. Where OSM already
   has a value, agreement with the City is independent of the City's inventory.
   Where OSM lacks one, the City's value is additional but unconfirmed.
4. **The City adds most where OSM is silent.**
   - 6 of 10 sampled curb cuts have no OSM kerb value. Across the study area, by
     proximity, 1,419 of 3,296 curb-cut records have no OSM kerb node within
     3 m.
   - 9 of 22 comparable non-default surfaces are the City's alone.
   - OSM carries all 6 sampled stairs and structures, yet 20 of the 40 in-area
     stairs have no OSM steps within 3 m.
   - The gap runs both ways. OSM has a lowered or flush kerb at 769 places in
     the City's network where the City records no curb cut within 3 m.

**Every proportion describes a stratified sample.** Strata are deliberately over-
and under-drawn. None of these figures is an estimate for the City's 34,052
records.

| File                                                                                                   | What it holds                                                                                                                               |
| ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| [`kitchener-geo04-lineage.json`](../evidence/kitchener-geo04-lineage.json)                             | Inputs on both sides, every candidate with its signals, the labels, topology, attributes, lineage, repeat review, matcher signals and scope |
| [`kitchener-geo04-review.html`](../evidence/kitchener-geo04-review.html)                               | The static review page: a map and tables per record, drawn from the two datasets                                                            |
| [`kitchener-geo04-labels.json`](../evidence/kitchener-geo04-labels.json)                               | The labels the results use (definitions version 2), each revision with its reason                                                           |
| [`kitchener-geo04-first-pass-labels.json`](../evidence/kitchener-geo04-first-pass-labels.json)         | The first pass, as labelled                                                                                                                 |
| [`kitchener-geo04-repeat-labels.json`](../evidence/kitchener-geo04-repeat-labels.json)                 | The blind second pass over 40 records, as labelled                                                                                          |
| [`kitchener-geo04-repeat-refined-labels.json`](../evidence/kitchener-geo04-repeat-refined-labels.json) | The second pass re-reviewed under definitions version 2                                                                                     |
| [`kitchener-geo04-esri-imagery.json`](../evidence/kitchener-geo04-esri-imagery.json)                   | Esri World Imagery's metadata over Kitchener, current and archived: which photographs its finest layer showed                               |

Code: `services/api/src/pathable_api/geo/kitchener/`. The commands are
`pathable kitchener lineage-extract`, `lineage-study`, `lineage-history` and
`imagery-metadata`. How to reproduce the run is in the
[evidence README](../evidence/README.md).

---

## 1. Both sides, frozen

**Kitchener.** The study uses PA-GEO-03's artifacts as they are. It never
re-draws the sample.

| Input                 | Identity                                                                                               |
| --------------------- | ------------------------------------------------------------------------------------------------------ |
| Snapshot              | `513094727cc1…`, retrieved 2026-09-26T12:55:26Z                                                        |
| Normalized GeoParquet | `ffe042be875e…`, 34,052 records: every record's native geometry, for neighbours and merges             |
| Sample                | `kitchener-geo04-sample.geojson`, SHA-256 `5c8f5e3548a4…`, 80 records in 18 strata; refused if changed |

**OpenStreetMap geometry, frozen.** Every comparison is made against the map
PathAble routes on, never against today's OSM. `pathable kitchener
lineage-extract` reads the active dataset's own record in a `READ ONLY`
transaction and takes the source extract's SHA-256 from it. It then reads that
exact file and refuses any other.

| Input            | Identity                                                                                                                                           |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| PathAble dataset | `51585450-8ff5-409d-a02e-66d5a3c5e260` (active), content checksum `51e75f78…`                                                                      |
| Source extract   | Geofabrik `ontario-latest.osm.pbf`, 969,572,077 bytes, SHA-256 `cee90e37…`, timestamp 2026-08-16T23:08:23Z (PA-GEO-02 provenance)                  |
| Study extract    | SHA-256 `8391f097…`: 38,370 `highway` ways with a node in the pilot box, kept whole; 164,986 nodes; 21,388 tagged kerb, crossing and barrier nodes |

Two extractions from the source extract gave byte-identical files.

**OpenStreetMap history.** The history is metadata about how the frozen geometry
came to be. It is never the geometry compared. The OSMF reserves the editing API
for editing, so the history comes from two read-only routes
([`DATA_SOURCES.md` §12](../licensing/DATA_SOURCES.md)):

- **The ohsome API** (1.10.4, `contributions/geometry`), history from 2007-10-08
  to 2026-07-27. It was asked for the ways within 10 m of each record and the
  tagged nodes within 8 m: 738 elements, in 16 requests.
- **The planet changeset dump** of 2026-09-21. It supplied every changeset's
  source, imagery record, editor and comment. All 1,824 changesets were found.

Of the 738 elements:

- 731 have history, with 5,201 contributions.
- 7 have none in ohsome's extent. All seven are kerb nodes tagged
  `kerb=lowered`, `tactile_paving=no` between 2026-08-11 and 2026-08-15, after
  ohsome's history ends.
- For 31 of the 731, the frozen extract holds a later state than the history
  reaches. For 30 of them it is a newer version; for one way it is a changed
  geometry.

An element whose history stops short of the frozen state is never called
independent.

**Esri's imagery metadata** (§7) comes from Esri's own public metadata services.
They were read at three points across the City, for the current map, the
Clarity layer and the first and last archived release of each year since 2014.
Only metadata was read, never imagery.

## 2. Candidates, and the signals beside them

Every `highway` way within 25 m of a record is a candidate, roads included. That
gives 1,094 candidates for the 80 records, a median of 13 per record (from 3 to
35). Each candidate carries the reasons it was generated and descriptive signals:

- closest approach;
- worst point: the record is sampled every metre, a directed Hausdorff
  distance;
- median offset;
- the record's share within 2 m and 5 m of the way, and the way's share within
  5 m of the record;
- median orientation where the two are near;
- the nearest pair of ends;
- class compatibility;
- the road each is beside, which side, and whether it crosses that road;
- the City records lying along the way;
- whether the way's vertices sit on the City's under one common shift.

Display order is not a ranking, and nothing here is a matching threshold. §11
reports which signals actually separated the reviewed answer from the other ways
nearby. The committed evidence keeps full signals for the 567 candidates within
10 m, and identity and distance for the rest.

## 3. The review page

[`kitchener-geo04-review.html`](../evidence/kitchener-geo04-review.html) has one
section per record. Each section has:

- an inline SVG map in the City's own metres, drawn from the two datasets:
  - the record and its City neighbours, with virtual links dashed;
  - OSM roads, paths and numbered candidates;
  - kerb and crossing nodes;
- the City's attributes with their value states;
- the road context;
- the candidate table and nearby tagged nodes;
- every label version, side by side;
- topology facts, attribute comparisons and the lineage steps.

The page fetches nothing: there is no basemap and no imagery. A blind variant
leaves out labels, lineage and history, and the repeat review used it. The page
carries the same scope statement as the evidence file: what it shows and what it
does not.

## 4. Labels, and how they were made

The definitions are in the evidence file (`definitions`, version 2) and on the
review page:

- **Correspondence**:
  - `obvious_correspondence`: OSM carries the same facility (for a virtual link,
    the same connection), and a reviewer would not reasonably choose another way.
    Closeness alone never qualifies.
  - `ambiguous_correspondence`: OSM may carry it, but not clearly, or only as a
    node or a tag on the road.
  - `no_correspondence`.
  - `not_comparable`.
- **Relationship**, for obvious correspondences only: `one_to_one`,
  `one_to_many`, `many_to_one`, `many_to_many`.
- **Geometry**: `closely_aligned`, `offset`, `partial_overlap`,
  `differently_split`, `differently_merged`, `materially_different`.
- **Topology**: `topology_agreement`, `topology_disagreement`,
  `ambiguous_topology`, `not_assessed`.
- **Representation**: how OSM carries the facility: separate way, node, road
  attribute or none.

A label may cite OSM ways or tagged nodes. That lets a curb cut that OSM holds
only as a kerb node be recorded as exactly that.

**Who labelled.** The primary labels are the implementing AI agent's (Claude
Opus 5.5). They were made from the review page and the candidate signals, with no
field visit, no imagery, and no OSM history while judging correspondence. The
repeat pass (§10) was made by a second instance of the same model, blind to the
first. Neither is ground truth.

**Definitions changed twice during the first pass** (logged in the label file):

- An unofficial connection along a road became a possible obvious
  correspondence.
- A tagged node became citable.

**They changed once more after the repeat review, as version 2** (§10). Version
2 was then applied to every record. That changed six of the first pass's labels:
five under the new definitions, and one error the repeat review found. Each
revision is recorded with its reason, its before and its after.

## 5. What the 80 records show

Labels are the adjudicated labels, under definitions version 2.

| Correspondence | All 80 | Physical or unresolved (71) | Virtual link or connection (9) |
| -------------- | -----: | --------------------------: | -----------------------------: |
| Obvious        |     69 |                          63 |                              6 |
| Ambiguous      |      7 |                           7 |                              0 |
| None           |      4 |                           1 |                              3 |
| Not comparable |      0 |                           0 |                              0 |

| Relationship (69 obvious) |     | Geometry (69 obvious) |     |
| ------------------------- | --: | --------------------- | --: |
| One to one                |  37 | Closely aligned       |  32 |
| One to many               |   0 | Differently merged    |  30 |
| Many to one               |  30 | Partial overlap       |   3 |
| Many to many              |   2 | Differently split     |   2 |
|                           |     | Offset                |   1 |
|                           |     | Materially different  |   1 |

Representation: 69 as a separate way, 4 as a node, 3 as a road attribute, and 4
not at all.

**The ambiguous seven are two kinds of representation difference.**

- **Four City corner pieces of 1–2 m** (393902, 388243, 321409, 321269) that
  OSM collapses into a junction. Two of those junctions have a `kerb=lowered`
  node 0.2–0.3 m away; the other two are untagged.
- **Three bicycle lanes** (388300, 388260, 412442) that OSM records only as
  `cycleway=*` tags on the road.

**The four without a counterpart.**

- **One genuinely new facility**: 19413, a sidewalk the City records as installed
  in 2024, along the east side of Lawrence Avenue. OSM has only the road and the
  west-side sidewalk, 12 m away.
- **Three virtual links whose crossing OSM does not map** (§6).

**Merging is common.** In 30 of the 69, one OSM way carries several City
records. The City splits sidewalks at curb cuts, driveways and junctions, while
OSM often runs one sidewalk way along a whole block or crescent: 446 m at 299388. A City value therefore applies to part of an OSM way, not all of it
(§12).

**Examples of geometry that disagrees.**

| Record | Label                | What differs                                                                                                                              |
| ------ | -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 419454 | materially different | The same named mountain-bike single track, surveyed with GPS in OSM. Along the winding trail the lines differ by up to 14 m (median 4 m). |
| 388381 | offset               | A City connection drawn about 4 m to the side of the Lennox Lewis Way centreline that carries it.                                         |
| 392049 | partial overlap      | OSM's bridge sidewalk covers 93% of the City's overpass record, which runs 6 m and 12 m further onto the approaches.                      |
| 24574  | partial overlap      | OSM's sidewalk runs 21 m on past the City's dead end, to meet a road.                                                                     |
| 88229  | differently split    | OSM carries the Lakeside Park trail on two paths, one of which continues over the City's next trail record.                               |

**PA-GEO-03's "not along OSM" stratum was an artifact of how PathAble's graph was
read.** All three sampled records have an obvious OSM counterpart:

- 397142 and 16079 run past the edge of the study box, where PathAble's graph
  stops.
- 6009, the Iron Horse Trail, is an OSM `highway=cycleway` with
  `foot=designated`, and PA-GEO-03's filter left cycleways out.

That audit measured distance to PathAble's clipped pedestrian graph, not to OSM.
A note now says so in [its document](KITCHENER_ACTIVE_TRANSPORT.md) (§8).

## 6. Topology and virtual links

Under the version 2 definitions, topology compares only facilities both sources
have, at the record's ends:

- **72 agreements, 0 disagreements, 4 ambiguous, 4 not assessed.**
- A facility only one source models is a coverage difference, named in the
  label's note. The adjudicated notes name three, where a label changed:
  - the City's virtual link across Spadina Road East, at two records;
  - OSM joining a sidewalk to a road centreline the City does not map.
- The repeat pass under version 2 named more. Examples are the City's virtual
  links across Rolling Meadows Drive at 16079, and an informal dirt path only
  OSM has at 6009.
- Coverage differences were not counted systematically. A benchmark that needs
  them should record them as a field, not in notes.

Agreement therefore means the shared network connects the same way. It does not
mean the two networks are the same.

**Virtual links are topology, never a physical facility.** The sample has six:

| OSM                             | Records                | What                                                                                                                                                     |
| ------------------------------- | ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Has the connection              | 308464                 | An unmarked crossing of Stoke Drive, within 2.6 m                                                                                                        |
| Has it, inside a continuous way | 310638, 391249         | The City splits a sidewalk where it crosses rails. OSM keeps the sidewalk whole and marks the rails with a `railway=crossing` node                       |
| Lacks it                        | 337366, 307871, 305259 | Street crossings the City's network makes and OSM does not: Wexford Crescent, Onward Avenue at Crescent Street, and Dekay Street north of Delisle Avenue |

For two of the three missing crossings, an OSM crossing of another leg of the
same junction lies within 5 m. An earlier version of the study counted those as
OSM having the crossing (§13). The outcome is now the reviewer's label.

## 7. Where OSM's shapes and values came from

### Imagery the City's records were traced from

88.3% of the City's 34,052 records name an orthophoto as their source (`ORTHO
2012` alone on 7,769). OSM mappers trace from imagery too, and the editors
record which layers were on screen. What Esri World Imagery showed over
Kitchener is recorded in Esri's own archived metadata. The same sources appear at
all three points queried
([`kitchener-geo04-esri-imagery.json`](../evidence/kitchener-geo04-esri-imagery.json)):

| Esri releases (first and last of each year) | Finest layer over Kitchener                  | Credited to            |
| ------------------------------------------- | -------------------------------------------- | ---------------------- |
| 2014_r01                                    | Aerials Express, 2007, 0.5 m                 | commercial             |
| 2014_r21 – 2016_r02                         | DigitalGlobe QuickBird, 2008, 0.6 m          | commercial             |
| 2016_r22 – 2017_r01                         | "City of Kitchener 2012", 0.12 m             | **City of Kitchener**  |
| 2017_r21 – 2020_r01                         | "Kit2016", 0.12 m                            | **City of Kitchener**  |
| 2020_r16 – 2023_r00                         | "Kit2019", 0.1 m                             | **City of Kitchener**  |
| 2023_r11 – 2025_r01                         | "2037WTRL-2020", 0.1 m                       | **Region of Waterloo** |
| 2025_r12 – 2026_r07, and today              | "Waterloo Imagery2022", 0.1 m, at zoom 20–21 | **Region of Waterloo** |

Today, below zoom 20, Esri serves Vantor WorldView-2 imagery from 2025, and its
Clarity layer serves the City's 2016 photographs. The photograph years match the
City's own sources: ORTHO 2012, 2016, 2019, 2020 and 2022.

**A shape traced on Esri since 2016 may therefore come from the City's own
photographs.** The lineage rules count an edit that recorded or declared Esri
imagery on or after 2016-02-23 as public orthoimagery, so its lineage is possibly
shared. 2016-02-23 is the earliest date Esri gives any municipal source over the
City, a conservative bound. It cannot be known at what zoom a mapper traced, so
the lineage is "possible", never "known". `pathable kitchener imagery-metadata`
re-reads the metadata. It stops for review if the date it measures no longer
matches the rules.

Bing's provider over Kitchener is published only through a keyed API, which this
study did not use. Edits that record Bing alone remain editor-recorded unrelated
imagery, the weakest basis there is.

### Geometry lineage

The lineage labels are conservative by construction:

- `apparently_independent` needs positive evidence: every shaping edit states an
  unrelated source, or the shape is older than the City's record.
- The absence of a municipal source tag is never evidence of independence.
- There is no numeric confidence.

| Record-level geometry lineage (69 obvious) | Records | By the City record's own source                       |
| ------------------------------------------ | ------: | ----------------------------------------------------- |
| Known Kitchener-derived                    |       1 | ORTHO                                                 |
| Possible shared lineage                    |      64 | 57 ORTHO; 4 the 2015 trail inventory; 2 none; 1 staff |
| Apparently independent                     |       3 | 2 ORTHO; 1 none                                       |
| Unknown                                    |       1 | ORTHO                                                 |

11 records are not assessed: the 4 without a counterpart and the 7 ambiguous
ones. With no OSM shape agreed to be the facility, there is nothing to trace.

- **The 1 known Kitchener-derived record is 50569**, an on-road connection. The
  OSM road that carries it was reshaped in 2017 by an edit whose source names
  "local data: data.kitchenergis.opendata.arcgis.com…Basemap", the City's
  open-data portal. It is the City's road data, not its Active Transportation
  inventory.
- **63 of the 64 possible-shared records** had a shaping edit since 2016 that
  recorded or declared Esri imagery. Some have a further reason:
  - 10 also name the Region's or the City's imagery directly;
  - 3 also have OSM vertices sitting on the City's under one common shift (spread
    0.26 m at 299388);
  - 1 also had a GeoJSON data file loaded in the editor.

  The shaping edits that recorded Esri date from 2019 to 2025, most of them from
  2020 to 2022.

- **The 64th, 47012**, rests only on data of unnamed origin: a 2026 edit whose
  source is "tt_proprietary".
- **For the 8 records whose City source is not an orthophoto**, sharing is only
  possible if the City aligned them to its own photographs. They are still
  counted as possible. Calling shared lineage independent is the worse error.
- **The 3 apparently independent records:**
  - **419454** (dates): a mountain-bike trail mapped from a GPS trace, declared
    "Site survey (2022-Aug)", before the City's 2025 record.
  - **388381** (editor-recorded): a 2017 edit declaring survey, then a 2022
    edit with only Bing aerial and street-level layers on screen.
  - **392049** (editor-recorded): Bing aerial and street-level layers only.

  All three rest on Bing or GPS, never on Esri.

- **The 1 unknown record, 301013**: it was created in 2019 by an edit that states
  no source.
- **No OSM edit in the sample names the City's Active Transportation
  inventory.** Nothing here says OSM imported it. What it says is that both
  were most likely drawn on the same photographs.

**Reading Esri's metadata changed the answer.** Before it, the same rules
counted Esri as unrelated imagery. The run before the change (content hash
`cad5f708…`) called 47 records apparently independent, 14 possible shared and 8
unknown. The run after it (`cfa4cc42…`) gave 4, 64 and 1. The difference is one
dated fact about one imagery layer. It is recorded here because the earlier
answer looked well supported.

A last review of every distinct source value in the history found two more
misreadings (§13). Fixing them gives the final figures above: 50569 became known
Kitchener-derived, and 47012 moved from apparently independent to possible
shared. The committed evidence (`2b093d52…`) also carries the OSM-only kerb
count of §8, which changed no lineage.

### Attribute lineage

Attribute lineage is traced separately from geometry, for the value in the frozen
extract and only on an obvious correspondence. A value the history cannot trace
is reported as unknown, never dropped.

| OSM value | Apparently independent                                                                  | Possible shared                                               | Unknown                               |
| --------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------- | ------------------------------------- |
| Kerb      | **5 of 5**, all StreetComplete survey edits, 2021–2023                                  | 0                                                             | 0                                     |
| Surface   | 10 of 14: 9 StreetComplete survey edits; 1 older than the City's record (6009, 2012)    | 3: set in edits that recorded Esri imagery                    | 1: 306773, set after the history ends |
| Structure | 3 of 6: 392049 (Bing and street-level); bridges 7863 and 6363, created in 2010 and 2009 | 3: stairs whose steps tag was set with Esri imagery on screen | 0                                     |

**Geometry and attribute lineage differ, as the card expected.** 7863 is a
wooden path bridge:

- its OSM way was created in 2010, before the City's record, so the `bridge=yes`
  that came with it is older than the City's;
- its `surface=wood` was added by a StreetComplete survey in 2020;
- its shape was later edited with Esri imagery on screen.

So the structure is apparently independent, the surface is surveyed, and the
geometry is possibly shared.

**The date rule sees only the record's own dates.** 7863 and 6363 count as
independent because their OSM ways are older than the City's record. That record
was created on 2014-06-30, the City's commonest creation date (1,638 records), so
most likely a bulk load. City data older than the load is invisible to the rule,
and the lineage definition says so.

**Records the City sourced from Street View.** PA-GEO-03 found three. None of
them is in the sample. The study marks any such record
`restricted_or_unresolved_lineage` and compares nothing of it. The in-area
proximity context (§8) also excludes such records. No Street View imagery was
read.

## 8. Attributes

Only the fields PA-GEO-03 approved are compared, and only on what the City
actually asserts. A template default is never evidence.

| Attribute (sample records) | Correspondence          | Outcome                                                  | OSM value lineage                         |
| -------------------------- | ----------------------- | -------------------------------------------------------- | ----------------------------------------- |
| Curb cut, CURBCUT = Y (10) | 7 obvious, 3 ambiguous  | 4 consistent, 6 City only, 0 conflict, 0 other semantics | 5 kerb values, all apparently independent |
| Stairs and structures (6)  | 6 obvious               | 6 same                                                   | 3 independent, 3 possible shared          |
| Railing (1)                | 1 obvious               | 1 consistent (`handrail=yes`)                            | —                                         |
| Non-default surface (24)   | 22 obvious, 2 ambiguous | 12 same, 9 City only, 1 conflict, 2 not comparable       | 10 independent, 3 possible, 1 unknown     |
| Dated condition, 2015 (3)  | 3 obvious               | 2 City only, 1 both present                              | —                                         |
| Virtual link (6)           | 3 obvious, 3 none       | 3 OSM has the connection, 3 OSM lacks it                 | —                                         |

**Curb cuts: the narrowest fact.** The City defines CURBCUT = Y as "a curbcut
down to street level". That fits OSM's `kerb=lowered` and `kerb=flush` but
implies neither of them. So a lowered or flush kerb is **consistent** with the
City's value, never "the same". Only `kerb=raised` would conflict, and none
occurred.

- **The 4 consistent records** have `kerb=lowered` nodes 0.2–0.9 m away (a
  second one at 1.8 m for 321409). All five nodes were set by StreetComplete
  survey edits.
- **The 6 City-only records** have no OSM kerb node within 3 m, nor within 8 m
  on the ways they correspond to. An OSM crossing lies near 5 of them.
- **Across the study area** (proximity, not correspondence), 1,871 of 3,296
  in-area curb-cut records have a lowered or flush OSM kerb node within 3 m. 1,419
  have no kerb node, 5 have other or mixed values, and 1 has a raised kerb. A
  nearby node may belong to a different corner.
- **OSM only.** At record level the question does not arise, because the City
  draws each curb cut as its own short segment. Across the study area it does.
  - Of the 2,896 lowered or flush OSM kerb nodes that lie where the City maps its
    network (some City record within 10 m), 2,127 have a City curb cut within
    3 m and 769 do not.
  - Another 1,827 lie more than 10 m from any City record, outside the City's
    network. That network excludes the parts of the box in the City of Waterloo.

**Stairs and structures.** OSM carries all six sampled: the three stairs as
`highway=steps`, the overpass and two bridges as `bridge=yes`.

- The one City railing, on stair 418763, is consistent with OSM's
  `handrail=yes`.
- OSM also records handrails on two stairs where the City records no railing
  (400043, 403230).
- Across the study area, 20 of 40 in-area stairs have OSM steps within 3 m, and
  20 do not.

**Surfaces.**

- **Same (12):** mostly asphalt; wood on the two bridges; the City's stonedust as
  OSM's `compacted` on one trail.
- **City only (9):** the corresponding OSM ways have no surface tag.
- **The one conflict (388284):** the City says BRICK. OSM says `concrete`, set by
  a StreetComplete survey in 2021.
- **Not comparable (2):** the two ambiguous bicycle lanes are never compared with
  their road's surface.
- **OSM only (30):** the City's value is its template CONCRETE, which is not an
  assertion, so there OSM's `surface=*` is the only information there is.

**Dated condition.** The City's FAIR values are documented as found by its 2015
trail inventory: historical, not current.

- 6363 and 6009 are the City's alone.
- For 45654, OSM has `smoothness=intermediate`, which is undated too.

Neither is a current condition, and neither would be presented as one.

## 9. What only one side has

- **City only, and physical:**
  - one new sidewalk (19413);
  - 6 curb cuts and 9 surfaces OSM does not record;
  - 2 dated trail conditions.
- **City only, topology:** three street crossings its network makes and OSM
  does not map.
- **OSM only:**
  - surfaces on 30 records where the City has only its default;
  - handrails on 2 stairs;
  - by proximity, lowered or flush kerbs at 769 places in the City's network with
    no City curb cut within 3 m;
  - the kerb and crossing detail at junctions where the City has only a short
    segment.

## 10. Repeat-label consistency

**Method.** A deterministic 40-record subset was chosen: one record per stratum,
then filled by hash, seed `pathable-pa-geo-04-repeat-v1`. A second instance of
the same model labelled it from a blind page and a text digest, under the same
written definitions, without seeing the first pass. The two passes were compared
**as labelled**.

This is repeat-label consistency, not inter-rater reliability. The rater is one
model twice, so no chance-corrected statistic is reported.

| As labelled (definitions version 1)   | Agree   |
| ------------------------------------- | ------- |
| Correspondence                        | 40 / 40 |
| Relationship, where both obvious      | 35 / 37 |
| The same OSM ways, where both obvious | 34 / 37 |
| Geometry                              | 34 / 37 |
| Topology                              | 30 / 40 |

**The disagreements were mostly the definitions' fault.**

- **Topology:** 10 disagreements.
  - Seven turned on something only one source models, or a facility joining
    along the record rather than at its ends. Examples are a City virtual link,
    an informal path, and a road centreline the City does not map.
  - Two turned on corner pieces OSM collapses into a junction.
  - One turned on a winding trail whose end OSM places 14 m from the City's
    junction.
- **Relationship and geometry:** 88440, 392049 and 307104 split on whether a
  junction stub or a few metres of end slop count.
- **Citation:** the two corner pieces, 321269 and 321409, cited different
  elements.

**Version 2 settles the three questions and records why** (`DEFINITION_REFINEMENTS`):

- Topology compares only facilities both sources have.
- About a junction's width (5 m) of end slop is not a difference in extent.
  Virtual links and junction stubs are not counted in a relationship.
- A corner piece cites the kerb node there, or else every way meeting at the
  junction.

Both passes were then re-reviewed under version 2. The first pass's six changed
labels are listed in the label file. The repeat pass's own reviewer changed 14
of its 40, still blind.

| After refinement (not independent) | Agree   |
| ---------------------------------- | ------- |
| Correspondence                     | 40 / 40 |
| Relationship                       | 36 / 37 |
| The same OSM ways                  | 35 / 37 |
| Geometry                           | 36 / 37 |
| Topology                           | 40 / 40 |

The second table is agreement after a refinement that the disagreements
themselves prompted, so it is not a second measurement. The figure that measures
consistency is the first table.

**The repeat review found one real error.** 403539 is a 3 m curb-cut stub. The
first pass cited OSM's crossing. The stub actually lies along the last segment of
OSM's sidewalk, up to the kerb node the two ways share. The adjudicated label
corrects it.

## 11. What a future matcher would need

This section uses the 69 obvious correspondences: 72 labelled record–way pairs
against the other 872 candidates. For each signal alone, it counts how often the
labelled way ranks first. No weights, no thresholds and no accuracy target.

| Signal                                    | Labelled way first | Labelled median | Other candidates' median |
| ----------------------------------------- | -----------------: | --------------: | -----------------------: |
| Median offset                             |            68 / 69 |          0.70 m |                  25.46 m |
| Worst point (directed Hausdorff)          |            66 / 69 |          1.18 m |                  43.80 m |
| Share of the record within 2 m            |            65 / 69 |            1.00 |                     0.00 |
| Share of the record within 5 m            |            56 / 69 |            1.00 |                     0.00 |
| Share of the way within 5 m of the record |            49 / 69 |            0.97 |                     0.00 |
| Orientation                               |            39 / 69 |            0.9° |                    64.1° |
| Nearest pair of ends                      |            26 / 69 |          1.20 m |                  13.80 m |
| Closest approach                          |            24 / 69 |          0.38 m |                  10.43 m |

**What helped.**

- Shape-based distance separates the right way from the rest: median offset,
  worst point, and share within 2 m.
- The labelled way's worst point is under 1.84 m for three quarters of the
  labelled pairs. For the other candidates it is over 16.5 m for three quarters.

**What failed.**

- **Closest approach ranks the right way first only 24 times in 69.** The nearest
  OSM way is usually a crossing touching the record's end, the road, or a
  parallel facility.
- **End distances fail because OSM merges and splits differently.**
- **Share within 5 m is too permissive.** A parallel sidewalk, the road and a
  crossing all fit within 5 m.
- **The way's share within the record is low whenever OSM merges.** It is the
  many-to-one signal, not a ranking signal.
- **The worst point fails on curb-cut stubs**, where OSM models its own 1–2 m
  stub (335487, 335421), and on the many-to-many trail 47012.

**Categorical signals are for ties, not for ranking.**

- **Class** is compatible for 59 of 72 labelled pairs and plausible for 10. The
  3 different ones are virtual links carried inside sidewalks, and a trail
  carried partly by a crossing.
- **The road side** agrees for 52 of the 55 labelled pairs with a side. The
  other 3 are all crossings, where a side means nothing.
- **The nearest road** differs from the record's for 16 labelled pairs.

**Combinations that appear necessary.**

- Rank on shape, meaning median or worst-point offset with share within 2 m.
  Then break ties with class compatibility: 14357's parallel cycleway at 1.7 m
  would otherwise pass.
- Find many-to-one by the City records lying along an OSM way, not by pairwise
  scores.
- Carry the representations explicitly. A curb cut can correspond to a kerb node
  or to nothing, and a lane to a road tag. A matcher that only pairs lines cannot
  express 7 of these 80 records.
- Treat a City virtual link as a connection to find across the road, never as a
  line to match.

## 12. What the canonical evidence model needs

These requirements are refined against the real examples above. PA-GEO-05 should
freeze the actual representation; nothing here is a schema.

| Requirement                  | What the study showed                                                                                     | Refinement                                                                                                                                          |
| ---------------------------- | --------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Source assertion             | The City asserts per record (CURBCUT = Y); OSM per element (a kerb node)                                  | An assertion is source, record or element, attribute, raw value, value state, and the date it was observed if known                                 |
| Raw and normalized assertion | CURBCUT = Y fits `kerb=lowered` and `kerb=flush` without meaning either                                   | Normalize per attribute with explicit relations — consistent, conflicting, different semantics — never equality alone                               |
| Source record identity       | The City's permanent id; OSM type, id and version                                                         | OSM identity includes the frozen version: for 31 elements the history ends before it                                                                |
| Publication and snapshot     | Both sides frozen by content hash; OSM is the routing dataset's own extract                               | Kept from PA-GEO-03                                                                                                                                 |
| Geometry correspondence      | Separate way, node, road attribute or nothing                                                             | Add representation; a correspondence need not be line to line                                                                                       |
| 1:N, N:1, N:M                | Many-to-one in 30 of 69                                                                                   | A relation between sets, with the part of the OSM way each record covers (linear referencing), so a value can apply to part of a way                |
| Lineage                      | Geometry possibly shared while the value on it was surveyed (7863); imagery meaning changes with the date | Separate geometry and attribute lineage; a label with its basis (declared, dates, editor-recorded) and its evidence steps; imagery provenance dated |
| Conflict                     | BRICK against a surveyed `concrete` (388284)                                                              | Both values kept, each with lineage and date; no automatic winner                                                                                   |
| Evidence freshness           | The 2015 condition; StreetComplete edits date their surveys; the City's dates are record-level            | An observation date per value where a source gives one; a record date never stands in for it                                                        |
| Virtual topology             | Three street crossings only the City models                                                               | A virtual link is a relation between facilities, never a routable line                                                                              |
| Match state                  | Obvious, ambiguous, none, not comparable, plus coverage differences and restricted records                | Keep all of them; "unmatched" is a result, not a failure                                                                                            |

## 13. What building the study caught

Each of these was found by running the study on real data. Each code defect is
fixed with a regression test that names it. The label error is corrected in the
adjudicated labels.

- **The frozen extract dropped 22 of PathAble's own ways.** Ways running far
  beyond the box were lost at the read margin. The extract now keeps every way
  with a node in the box whole, using a location index.
- **The changeset dump's streams split multi-byte characters, and one index
  lookup could return the wrong stream.** Now it parses bytes and reads on
  through streams that start no element.
- **`Geobase_Import_2009` did not read as an import.** Word boundaries missed
  underscores.
- **Words iD writes into `source` by itself were read as the mapper's own
  declarations.** Editor records and declarations are now kept apart.
- **One first-pass label cited the wrong way (403539)**, found by the repeat
  review.
- **Lineage and attributes were traced through ambiguous correspondences.** A
  bicycle lane was compared with its road's surface.
- **Virtual links "had" a crossing whenever any OSM crossing lay within 5 m.**
  That included crossings of another leg of the junction.
- **A value the history could not trace was silently dropped.** A value changed
  after the history ends was traced as if it were the frozen one.
- **A declared survey was reported as resting on dates**, the weaker basis.
- **Esri World Imagery was read as unrelated imagery** (§7).
- **The City's open-data portal (`kitchenergis`) did not read as Kitchener
  data.** In addition, a value naming several sources was read whole, so
  "Esri World Imagery" in one part turned "Kitchener Open Data" in another into
  imagery. Both were found by listing every distinct source and imagery value in
  the 1,824 changesets with its reading.
- **That same listing found five smaller misreadings:**
  - the Region's road-closure page read as its imagery;
  - Rapid's own source words read as the mapper's;
  - iD's own layer ids read as declarations;
  - GPS-trace layers read as unnamed imagery;
  - loaded data files, "local data" and proprietary sources not read as data
    of unnamed origin.

## 14. Decision: LIMITED GO

- **Enough unambiguous correspondence?** For line facilities, yes. The
  exceptions are all representation differences a benchmark can name: 4 corner
  pieces as nodes, 3 lanes as road tags.
- **Useful new evidence?** Only in particular attributes:
  - curb cuts (6 of 10 sampled without an OSM kerb value, and a wide gap by
    proximity);
  - non-default surfaces (9 of 22);
  - stairs, where OSM has the sampled ones but lacks half the area's by
    proximity.
- **Meaningful matching signals?** Yes, and they are known: shape offset, share
  within 2 m, class to break ties, and many-to-one by aggregation. Nearest
  distance is not one of them.
- **Stable labels?** Correspondence was fully consistent. Relationship and
  geometry mostly were. Topology was not, until its definition was fixed.
- **Genuinely new geometry?** No. Shared photographs make the City's geometry
  confirm nothing, and OSM already has almost every line.

**Continue to PA-GEO-05 for:**

1. **Curb cuts.** Benchmark CURBCUT = Y, as "a curb cut to street level exists
   here", against OSM kerb nodes and their absence.
2. **Stairs and structures**, with railings as context.
3. **Non-default surfaces.**

The benchmark must represent nodes and road attributes, and parts of merged ways.

**Nothing else goes forward.**

- The City's geometry is a matching input only, never evidence.
- Virtual links stay topology context.
- The 2015 condition stays dated context.
- Width, CONCRETE, grade and the derived fields stay rejected.

**Licensing is unchanged.** Three facts stay distinct:

- The City's licence permits this research.
- The City has separately permitted its data in OSM.
- OSMF LWG approval of the licence is not confirmed.

PA-GEO-05 is a benchmark and stays research. Before any Kitchener-derived value
is written where routing can read it, or redistributed with the OSM-derived
database, compatibility is reviewed again as a founder licensing decision
([`DATA_SOURCES.md` §11](../licensing/DATA_SOURCES.md)).

## 15. Performance

Measured on one Windows laptop under memory pressure: shapes, not service levels.

| Step                                               | Measured                                            |
| -------------------------------------------------- | --------------------------------------------------- |
| Frozen study extract from the 970 MB PBF           | 210 s and 114.66 s; peak 2,946 MB; identical output |
| Changeset dump stream index (once per dump)        | 877 s                                               |
| History, ohsome answers cached, dump lookups       | 41–42 s                                             |
| Candidates and signals, 80 records                 | 25–27 s                                             |
| Study with labels and history, and the review page | 27–28 s; two runs, identical content hash and page  |
| Esri imagery metadata, 85 requests                 | 334 s                                               |

## 16. Limitations and unresolved questions

- **The labels are one AI model's, twice.** No person has reviewed them, and
  nothing was checked in the field.
- **Proportions describe a stratified sample**, not the City's 34,052 records.
  The proximity figures in §8 cover every in-area record, but they measure
  distance, not correspondence.
- **Esri imagery.** Esri's metadata says what its finest layer showed, not what
  zoom a mapper used. Hence "possible", never "known".
- **Bing.** Bing's provider over Kitchener is not checked.
- **Dates.** The date rule cannot see City data older than a record, such as a
  bulk load's source.
- **History coverage.** The history ends 2026-07-27. The 7 kerb nodes tagged in
  August 2026 have none, and 31 elements changed after it.
- **Unresolved:**
  - Whether CURBCUT = Y means lowered or flush remains open; the study only needed
    it to be consistent with both.
  - Why the City models some rail crossings as virtual links.
  - Whether the City's non-orthophoto records were aligned to its photographs.
