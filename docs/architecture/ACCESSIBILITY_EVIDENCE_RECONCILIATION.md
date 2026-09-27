# Accessibility evidence reconciliation — OSM and Kitchener (PA-GEO-06)

Where PA-GEO-05 is sure enough that a City of Kitchener record and an
OpenStreetMap element are the same facility, how should PathAble hold what each
source claims about it? It must not overwrite either source, lose where a claim
came from, invent independence, or turn open questions into routing truth. This
card builds that model and runs it over the whole pilot.

**Reconciliation describes evidence; it does not choose truth.** Every
assertion is kept as published. How two assertions relate is classified, and so
is whether they may share an origin, but no value is picked and no source
outranks the other.

**Nothing here routes.** No Kitchener value reaches feasibility, hard
constraints, cost, uncertainty, explanations or the graph. The artifact stays in
the ignored data folder, no routing code can import it (a static test enforces
this, `test_kitchener_isolation.py`), and every row records why it may not be
routed on. The founder licensing gate stays closed (§10).

**Decision: LIMITED GO**, surfaces only (§12). The evidence is
[`kitchener-geo06-reconciliation.json`](../evidence/kitchener-geo06-reconciliation.json).
The decision is recorded in [ADR 0011](../adr/0011-accessibility-evidence-reconciliation.md).

**What the numbers are.** Counts over every correspondence this card accepts in
the full pilot. The correspondences are PA-GEO-05's frozen matcher's decisions;
that matcher was measured once, on a held-out sample against AI labels, and
nothing here re-measures it. Relationships are the output of a written
vocabulary (§4), and lineage is what OSM's edit metadata states (§6). None of it
is field-verified.

## 1. Inputs, bound to PA-GEO-05

| Input       | What                                                                                                                                                                                                                                           |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Kitchener   | PA-GEO-03's snapshot `513094727cc1…` (retrieved 2026-09-26), normalized GeoParquet `ffe042be…`                                                                                                                                                 |
| OSM         | PA-GEO-04's study extract `8391f097…`, cut from the PBF the active Waterloo dataset was built from (OSM data of 2026-08-16)                                                                                                                    |
| Matches     | PA-GEO-05's full-pilot artifact: `kitchener-geo05-matcher-v1`, 11,547 decisions (`352beaec…`), every file checked against its manifest. Its decisions are read, never re-made.                                                                 |
| OSM history | For the 3,500 OSM elements whose value is compared with the City's: ohsome API 1.10.4 (history to 2026-07-27), 71 requests, 14,828,105 bytes; changesets from the planet dump of 2026-09-21. 3,474 have history; 3,417 reach the frozen state. |

A run refuses a Kitchener file or an OSM extract other than those PA-GEO-05's
artifact records, a matcher other than v1, and history read for another
extract.

## 2. The model

Four tables, versioned apart: assertion schema, vocabulary, reconciliation
policy, accepted-input contract and artifact are each `kitchener-geo06-…-v1`.

- **Sources.** Provider, dataset, publications, frozen snapshot, when it was
  retrieved or published, licence and its URL, attribution.
- **Assertions** — one source's claim about one property of one record:
  - the raw attribute and raw value exactly as published, and a normalized
    value only where the mapping is defensible;
  - the **value state** — `non_default`, `template_default`, `unknown`,
    `null`… for the City, `asserted` for an OSM tag. A template default is
    kept, marked unusable, and never read as evidence;
  - the **evidence origin** — the City's per-field origin from PA-GEO-03
    (`administrative_assertion`, `observed_survey`…), or `osm_contributor_edit`;
  - the City record's capture source, typed dates (§7), and what OSM's history
    says about how the value entered OSM.
- **Correspondences** — every PA-GEO-05 decision:
  - its state, rule and relationship (1:1, 1:N, N:1, N:M);
  - its targets, each with element, OSM version, role, target type (node or
    local extent of a way) and metres;
  - which topics this card accepts from it, and why each other topic is
    excluded.
- **Reconciliations** — one property at one local target: a kerb node, or the
  metres of an OSM way one City record covers. Each lists:
  - the City's usable assertions, and any City value withheld as not evidence;
  - OSM's assertions;
  - the semantic relationship and its specificity, and the vocabulary rule
    that decided it;
  - the lineage relationship, and the target's own geometry lineage;
  - the evidence state and, for a conflict, `unresolved`;
  - routing eligibility (always `not_routing_eligible`) and every blocker.

A run refuses to finish if any row's classification disagrees with what it
holds, such as agreement without a usable assertion from each source, or a curb
ramp on a way. That check caught a real bug before any evidence was written:
PA-GEO-05's records carry no `FEATURE_TYPE` value state, so every City
structure assertion was being withheld while its row still said agreement.

## 3. Accepted inputs

A PA-GEO-05 `matched` decision is not enough. Each class passes its own gate,
the one PA-GEO-05's benchmark earned:

| Class               | Records | Eligible | Ambiguous | Excluded by class                                     | OSM representation absent                                           | No counterpart |
| ------------------- | ------- | -------- | --------- | ----------------------------------------------------- | ------------------------------------------------------------------- | -------------- |
| Non-default surface | 3,472   | 2,978    | 88        | 200: 100 on a curb cut's ways, 100 short pieces       | 11: 9 structures OSM does not tag, 2 crossings drawn as nodes       | 195            |
| Curb cut            | 3,192   | 1,678    | 341       | 1,152 matched only way-level: no OSM kerb node in 2 m | —                                                                   | 21             |
| Structure           | 129     | 63       | 5         | 13: 12 short stairs, 1 on a curb cut's ways           | 45: 25 underpasses, 12 stairs, 5 bridges, 2 overpasses, 1 boardwalk | 3              |

- **Surfaces** use the way-level correspondence, except for pieces of 5 m or
  less. Those are short pieces at junctions, where PA-GEO-05 found the matcher
  commits too readily.
- **Curb cuts** reconcile only at the kerb node the matcher named. The ways a
  curb-cut decision names are PA-GEO-05's unreliable way-level set, so nothing
  reconciles on them, and a curb cut never spreads along a sidewalk.
- **Structures** reconcile only where OSM tags the structure the City records.
  The 12 City stairs OSM draws as plain footways wait for matcher v2 (§11).

9,279 of the 11,547 decisions reach reconciliation for at least one topic.
Accepted surface targets that belong to no non-default surface record still
count, because OSM may assert a surface there: 4,858 of the 7,930 hold the
City's template-default `CONCRETE`, kept as withheld context.

**OSM's kerbs where the City records no curb cut** are found by location, not
by a match. A kerb node counts when it has no City curb cut within 3 m and a
City facility within 10 m (PA-GEO-04's distances). No correspondence to a City
record is claimed for these nodes. Of the OSM kerb nodes in the study area:

- 1,661 are named by accepted City curb cuts (17 by two);
- 804 have a City facility near and no City curb cut;
- 481 have a City curb cut within 3 m whose correspondence was not accepted,
  and are excluded;
- 1,954 lie outside the City's mapped network, and are excluded.

## 4. How assertions relate

The vocabulary (`reconciliation_vocabulary.py`) keeps equivalence narrow:

- **agreement** — the same claim: ASPHALT and `asphalt`;
- **compatible** — consistent without being the same claim. Its specificity
  says how: OSM less specific (ASPHALT and `paved`), OSM more specific (NATURAL
  and `dirt`), overlapping terms (BRICK and `paving_stones`), or different
  properties (a curb cut and `kerb=lowered`);
- **conflict** — comparable claims that cannot both hold: BRICK and `concrete`;
- **incomparable** — both assert something, but it cannot be compared: an
  unrecognised or multi-valued OSM value, `kerb=no` beside a curb cut;
- **source only**, one side or the other, and **unknown** when neither asserts.

`CURBCUT = Y` means what the City defines: "a curbcut down to street level" at
that feature. It is never read as `kerb=lowered` or `flush`. OSM's kerbs are
read exactly as PathAble's routing reads them: a bare `barrier=kerb` is a kerb
of unrecorded height. A City `FEATURE_TYPE` of one structure says nothing about
another, just as OSM's `highway=footway` does not say "no stairs". Every
observed pair and its classification is listed in the evidence
(`value_pairs`, 88 pairs).

## 5. Outcomes

| Topic                   | Agreement | Compatible | Conflict | City only | OSM only | Unknown |
| ----------------------- | --------- | ---------- | -------- | --------- | -------- | ------- |
| Surface                 | 1,671     | 198        | 257      | 943       | 3,136    | 1,725   |
| Curb ramp               | —         | 1,648      | 0        | 13        | 795      | 9       |
| Structure               | 46        | 17         | 0        | 0         | 26       | —       |
| Railing (not routed on) | —         | 3          | 0        | 27        | 9        | —       |

No row is incomparable.

- **Surface** agreement is mostly ASPHALT with `asphalt` (974), and painted
  asphalt with `asphalt` (627). Compatible pairs split as 100 overlapping (81
  STONEDUST with `compacted`), 59 where OSM is less specific (mostly `paved`
  and `unpaved`) and 39 where OSM is more specific (31 NATURAL with `dirt`).
  By local extent: 56.7 km agree, 12.2 km conflict, 26.7 km are City-only,
  312.7 km OSM-only and 197.6 km unknown.
- **Curb ramps**: all 1,648 two-sided rows are a City curb cut beside
  `kerb=lowered` (1,600) or `flush` (48): compatible, different properties,
  never agreement. The 13 City-only rows are kerb nodes with no recorded height
  (8 bare `barrier=kerb`, 5 `kerb=yes`). The 795 OSM-only rows are `lowered`
  691, `flush` 78, `no` 16 and `raised` 10.
- **Structures**: BRIDGE on `bridge=yes` 26, STAIRS on `highway=steps` 14,
  UNDERPASS on `tunnel=yes` 6. OVERPASS on `bridge=yes` is compatible (17): the
  City says what the bridge spans. No structure is City-only under this gate by
  construction. OSM alone records 17 bridges, 6 flights of steps and 3 tunnels
  where the City's `FEATURE_TYPE` is its template default.

## 6. Agreement is not independence

Where both sources assert something, OSM's edit history is read under PA-GEO-04's
rules, unchanged. The rules ask whether the edit that introduced OSM's value
names the City's data (known shared), names something the City's data may share
— the City's and the Region's photographs, which Esri World Imagery has served
over Kitchener since 2016 — (possible shared), or states an unrelated source
(apparently independent). `apparently_independent` is what the metadata states,
not proven independence.

| Topic and relationship | Apparently independent | Possible shared | Known shared | Unknown |
| ---------------------- | ---------------------- | --------------- | ------------ | ------- |
| Surface agreement      | 1,449                  | 155             | —            | 67      |
| Surface compatible     | 156                    | 30              | 5            | 7       |
| Surface conflict       | 221                    | 30              | 1            | 5       |
| Curb ramp compatible   | 1,513                  | 106             | —            | 29      |
| Structure agreement    | 20                     | 16              | —            | 10      |
| Structure compatible   | 5                      | 11              | —            | 1       |

Most OSM surface and kerb values here were entered by survey-app edits
(StreetComplete): 1,588 surface and 1,552 kerb values state a survey.

**Attribute and geometry lineage stay apart.** Of the 1,648 kerb nodes beside a
City curb cut, 1,485 have geometry that may share the City's photographs, while
their kerb value is apparently independent — for 1,472 of them, entered by an
edit that states a survey. Lineage and semantics are independent too. One
surface conflict sits on a way whose `surface=unpaved` came from an edit that
names Kitchener's data, beside the City's ASPHALT: known shared lineage, and
still a conflict.

## 7. Dates keep their meaning

| Date                  | Dates                                                                                          | City (4,747 usable)              | OSM (6,516)                    |
| --------------------- | ---------------------------------------------------------------------------------------------- | -------------------------------- | ------------------------------ |
| `source_capture_date` | City `SOURCE_DATE`: the record's capture; for orthoimagery, the photographs' date              | 4,702 (2012 on 1,992)            | —                              |
| `observation_date`    | An observation: OSM `check_date`, `survey:date`, or the survey-app edit that entered the value | 0: the City supplies none        | 2,891 (1,546 in 2021)          |
| `inspection_year`     | City `LAST_INSPECTION_YEAR`: an inspection, not what it found                                  | 4,592 (2021: 1,901; 2026: 1,834) | —                              |
| `record_created_at`   | City `CREATE_DATE`: database maintenance                                                       | 4,747                            | —                              |
| `record_modified_at`  | City `UPDATE_DATE`: database maintenance, mostly one bulk day                                  | 4,747, never read as freshness   | —                              |
| `osm_edit_timestamp`  | The element's last edit of any kind                                                            | —                                | 6,516                          |
| `osm_value_since`     | When OSM's current value entered OSM                                                           | —                                | 3,438 (where history was read) |

Every City date is read in UTC, the zone the City stores it in. An earlier
version formatted them in the laptop's time zone, which moved `SOURCE_DATE` —
kept at midnight UTC, mostly on the 1st of a month — to the previous day. That
is fixed here and in the PA-GEO-04 and PA-GEO-05 queries. Their matching and
metrics read no date.

Only an observation date is read as freshness. The City has none, so no City
assertion is fresh or stale by this model: its dates say when the record was
captured and when it was inspected. StreetComplete and Every Door record
answers on the spot, so their edit dates an observation. Of the 2,891 OSM
observation dates, 2,888 come from those edits and 3 from `check_date:surface`.
A `source=survey` a mapper typed does not say when the survey was, and dates
nothing. Observed OSM values here date from 2020 to 2026, and 1,546 of them
from 2021. None is a current fact.

## 8. Potential information gain — research view only

This is potential evidence coverage if eligible City assertions were included,
over this card's targets only. It is not validated, production or routing
coverage. A City-only assertion is an additional source assertion not
represented in the compared OSM field, not a correction.

| Class     | Unit                                                            | Targets | OSM asserts | City only | Union         | Unresolved conflicts | Unknown |
| --------- | --------------------------------------------------------------- | ------- | ----------- | --------- | ------------- | -------------------- | ------- |
| Surface   | a City record's extent on one OSM way                           | 7,930   | 5,262       | 943       | 6,205 (+18%)  | 257                  | 1,725   |
| Curb ramp | an OSM kerb node (accepted, or City-covered without a curb cut) | 2,465   | 2,443       | 13        | 2,456 (+0.5%) | 0                    | 9       |
| Structure | a City record's extent on one OSM way, per structure family     | 89      | 89          | 0         | 89            | 0                    | 0       |

The larger City-only signal is out of reach under this gate:

- 1,152 City curb cuts have no OSM kerb node within 2 m. They are the City
  curb cuts OSM may lack entirely, and they need way-level correspondence.
- 341 City curb cuts were matched ambiguously.
- 45 City structures are not tagged as structures in OSM, 12 of them stairs.

## 9. Conflicts

All 257 conflicts are surfaces; every one is in the evidence with both
assertions, their dates and provenance, the correspondence and the lineage
(`conflict_casebook`). The largest groups:

| City              | OSM             | Rows | Where the OSM value came from                              |
| ----------------- | --------------- | ---- | ---------------------------------------------------------- |
| ASPHALT           | `concrete`      | 74   | 67 apparently independent, 7 possible shared               |
| ASPHALT (PAINTED) | `paving_stones` | 35   | all apparently independent; 33 entered by survey-app edits |
| BRICK             | `concrete`      | 31   | 30 apparently independent, 1 possible shared               |
| ASPHALT           | `unpaved`       | 17   | 9 apparently independent, 4 possible, 1 known shared       |
| ASPHALT           | `compacted`     | 15   | all apparently independent                                 |
| ASPHALT (PAINTED) | `concrete`      | 13   | 6 apparently independent, 7 possible shared                |

In 211 of the 257 conflicts, the edit that entered OSM's value states a survey
(176 of them a survey app's), while the City's side is an administrative
assertion with no observation date. That says the two sources disagree. It does
not say which is wrong; either may be, and so may the correspondence. Painted
crosswalks recorded as paving stones could be decorative crosswalks, but that is
a hypothesis no one has checked. Nothing is resolved.

## 10. Routing isolation and licensing

- Every one of the 10,523 reconciliations is `not_routing_eligible`. All carry
  `blocked_by_routing_policy`. The 4,823 that hold a City assertion also carry
  `blocked_by_licensing` and `blocked_by_validation`. The 39 railing rows carry
  `not_a_routing_property`.
- The reconciliation modules import neither the database nor routing. Only the
  command line imports them, and nothing that serves routes names the artifacts
  or their folder. All of this is checked statically.
- The artifact — a combined table of City and OSM values — stays in
  `.kitchener-data/`. The committed evidence holds counts, value pairs and the
  conflicts, as earlier cards' evidence did.

The licensing gate is unchanged:

1. The City permits PathAble's research use.
2. The City separately permits its data in OSM.
3. OSMF LWG approval of its licence is not confirmed.

Before any routing integration, the licence status must be checked again, the
database and redistribution model written down, and the founder must approve
([`DATA_SOURCES.md`](../licensing/DATA_SOURCES.md) §11).

## 11. Matcher v2 — recorded, not built

The stair correspondence decision is locked in
[`KITCHENER_CONFLATION.md`](KITCHENER_CONFLATION.md) §11. A generic OSM
footway does not negate a City stair assertion: clear physical correspondence
and attribute agreement are separate questions. A clear match is a
correspondence, with the stair as a City-only assertion; the OSM way is never
retagged, and routing on the stair stays prohibited. Stairs stay ambiguous only
where physical identity is unclear.

Matcher v2 is a later card:

- stairs and other structures OSM draws as plain footways, under that rule;
- way-level curb-cut correspondence, which holds 1,152 City curb cuts with no
  OSM kerb node;
- an abstention rule for short pieces at junctions;
- better abstention generally;
- class compatibility redesigned, since it cost 8 curb cuts at crossings.

It needs a new policy version and a new, untouched held-out sample. PA-GEO-05's
holdout has been used and may not serve as v2's test.

## 12. Decision: LIMITED GO — surfaces only

To routing-evidence integration research, and not to integration. The founder
licensing decision is still required.

- **Surfaces: go.** The model keeps both sources honestly, and the accepted
  class is the one PA-GEO-05 measured best (33 of 33 exact). The City adds 943
  targets (26.7 km) OSM has no surface for. Conflicts are real but do not
  dominate: 257 of 2,126 two-sided rows. Provenance and dates survive end to
  end. The research must hold conflicts open, and weigh an undated
  administrative assertion against surveyed OSM values.
- **Curb ramps: not yet.** The model works — 1,648 compatible, no conflict —
  but under the kerb-node gate the City adds 13 nodes. Its useful signal, City
  curb cuts OSM has no kerb for, waits for matcher v2.
- **Structures: not yet.** Every accepted structure is one OSM already tags;
  the City adds only its own detail (OVERPASS). The City-only structures,
  including stairs on plain footways, wait for matcher v2.

This is not a GO, because licensing is not the only remaining gate: nothing is
validated by a person or in the field, and no routing policy exists for any of
it.

## 13. Limitations

- **The correspondences are unverified row by row.** They are PA-GEO-05's
  decisions, whose quality was measured once on 193 records against AI labels.
- **The vocabulary is engineering judgement.** It is written down, and every
  observed pair is listed, but no one outside this repository has reviewed it.
- **Lineage is what OSM metadata states.** History ends on 2026-07-27, before
  the extract. 26 elements have no history and 57 do not reach the frozen
  state; those are never called independent.
- **A survey-app observation date is the edit's date.** The observation was at
  or shortly before it.
- **OSM-only kerbs are found by location**, with no correspondence tested.
- **One City snapshot and one OSM extract.** Nothing is known about how these
  relationships age.
- **One laptop** for every timing (§14).

## 14. Determinism, performance, reproducing

Two runs from `fe55f20`, clean tree, same inputs: all four files
byte-identical, evidence content hash `6bb58d6f…`. They took 24.3 s and 22.7 s
end to end on one laptop (Windows 11, Python 3.13, 16 GB): about 10–11 s
loading the frozen inputs, 6 s reconciling with lineage, and 6 s writing. Peak
process memory was 513–518 MB.

| File            | Rows   | Bytes     |
| --------------- | ------ | --------- |
| sources         | 2      | 4,075     |
| assertions      | 15,921 | 223,037   |
| correspondences | 11,547 | 181,684   |
| reconciliations | 10,523 | 795,067   |
| **Total**       |        | 1,203,863 |

Every file's hash is in the evidence (`artifact`). From `services/api`, with
PA-GEO-03's normalized snapshot, PA-GEO-04's study extract, PA-GEO-05's artifact
and the planet changeset dump:

```
pathable kitchener reconcile-history --normalized <folder> --extract <…> --extract-manifest <…> \
    --geo05-artifact <folder> --evidence-dir ../../docs/evidence \
    --dump <changesets-*.osm.bz2> --out <history.json>
pathable kitchener reconcile <the same inputs> --history <history.json> \
    --artifact-dir <folder> --json <evidence.json> [--compare-to <an earlier run's folder>]
```

`reconcile-history` reads the ohsome API and the local dump, never the OSM
editing API. `reconcile` needs neither the network nor the database.
