# Kitchener and OpenStreetMap — matcher v2 and a new held-out benchmark (PA-GEO-08)

PA-GEO-05 measured matcher v1 once and found its central weakness: it committed
where a careful reviewer would not. It also left three classes of City
evidence out of reach:

- curb cuts with no OSM kerb node;
- stairs OSM draws as plain footways;
- short pieces at junctions.

This card built matcher v2 against those failures and measured it once, on a
new held-out sample that neither matcher's design had seen.

**Nothing here routes.** No kerb, stair or surface value from Kitchener reaches
feasibility, cost, uncertainty, explanations or the graph, and the founder
licensing gate stays closed. Matcher v2 writes only the evidence below; a
static check keeps routing from importing it (`test_kitchener_isolation.py`).
PA-GEO-07's 40-record surface validation queue is untouched, and no external
validation is claimed.

**Decision: LIMITED GO**, to reconciliation research for **curb ramps only**
(§11). The evidence is
[`kitchener-geo08-matcher-v2.json`](../evidence/kitchener-geo08-matcher-v2.json);
every failure is drawn in
[`kitchener-geo08-errors.html`](../evidence/kitchener-geo08-errors.html).

**What the numbers are.** Counts over a stratified sample of 186 records, scored
against labels made blind by AI model instances (Claude), not people. No figure
is a proportion of the City's inventory, a field-verified accuracy, or a claim
about any other place. Intervals are sampling uncertainty over these records,
conditional on these labels.

## 1. What was spent, and what is new

PA-GEO-05's 193 held-out records and PA-GEO-04's 80 are **development data**.
v2 was designed and tuned on them, and on PA-GEO-05's failure analysis. The
final evaluation uses a **new sample** drawn from the 11,296 eligible records in
neither. Inputs are as before:

- the Kitchener snapshot `513094727cc1…`;
- the OSM study extract `8391f097…`;
- 11,547 eligible physical pedestrian records.

**Order of work**, all in the branch history:

1. `e0b9337` — the new held-out sample, drawn before any v2 rule existed.
2. `e5a099d` — label definitions version 2, the guide, the blind review
   material and the development labels re-read under the new definitions.
3. `74778a4` — matcher v2 frozen, tuned on development data only.
4. `48a422a` — the held-out labels frozen, collected after the freeze.
5. `2d4d5f0` — the benchmark command; the single held-out evaluation ran from
   this commit with a clean tree (decisions `5c64cc03…`).
6. `3728dba` — the failure analysis; the committed evidence is a second run
   that the code refuses unless it reproduces those decisions.

The benchmark pipeline was rehearsed on development records before step 5.
After step 5, nothing in the matcher, its policy or a label changed. **This
held-out sample is now spent** for matcher v2. Any change to v2 is a new
policy version and needs another untouched sample.

## 2. The new benchmark

**Sample.** 186 records in 18 strata, drawn by `pathable kitchener
matcher-v2-holdout`, first matching rule wins, in the order of
`sha256(seed:id)`. The seed binds the sample version, the snapshot and the
extract. Two draws were byte-identical (`999a1b21…`):

| Stratum                                                  | Records | Population |
| -------------------------------------------------------- | ------- | ---------- |
| Curb cut, no OSM kerb node, two or more pedestrian ways  | 36      | 1,140      |
| Curb cut, no OSM kerb node, one way / no way within 3 m  | 12 / 6  | 100 / 24   |
| Curb cut shorter than a metre                            | 16      | 367        |
| Curb cut with a kerb node, onto a crossing / otherwise   | 16 / 4  | 1,483 / 12 |
| Corner or junction piece under 5 m, not a curb cut       | 26      | 324        |
| Stairs: OSM steps beside it / steps displaced nearby     | 9 / 1   | 9 / 1      |
| Stairs: on a plain footway / anything else               | 6 / 1   | 6 / 1      |
| Structure across two or more OSM ways / other structures | 7 / 12  | 7 / 59     |
| Crossing OSM draws as a node                             | 2       | 2          |
| Parallel facilities / hard negatives                     | 10 / 10 | 984 / 40   |
| Other short pieces / straightforward                     | 4 / 8   | 14 / 6,723 |

Every eligible stair not already used is in it: only 17 remain after PA-GEO-05
took 20, so **stair results rest on 17 records and six plain-footway stairs**.
The size and weighting are argued in the sample file; no statistical certainty
is claimed.

**Labels.** Five AI model instances each labelled about a fifth of the sample
blind, under
[definitions version 2](../evidence/kitchener-geo08-labelling-guide.md). Each
worked from a text digest and a map per record, with no access to either
matcher, its output, the development labels or another pack. Two more
instances labelled a 60-record subset again. Each was told to open only its
pack folder and run only the validator, and each reported back only its record
count and the validator's verdict.

The labels are **not** human ground truth, and not expert or externally
validated. The labellers, the guide's author and the matcher's designer are the
same model family, and the guide's definitions ("about 2 m", "follows") are
also values in the matcher.

**Definitions version 2** change PA-GEO-05's only where its failures left the
answer open:

- **Stairs.** A stair OSM draws as a plain footway in the same place and line
  corresponds to it (representation `generic_way`); OSM steps displaced
  nearby keep it ambiguous.
- **Curb cuts.** A way is cited only if the piece follows it, and a crossing
  counts like a sidewalk. With two kerb nodes, the one where the crossing the
  piece runs onto begins.
- **Corner pieces** are obvious only when they clearly follow one way.
- **Construction.** A way under construction is not a facility.

The 251 development labels were re-read under these definitions with 15
recorded changes: six stairs on plain footways became correspondences, and nine
representations became `generic_way`
([`kitchener-geo08-development-labels.json`](../evidence/kitchener-geo08-development-labels.json)).

The held-out labels: 125 obvious, 41 ambiguous, 20 with no counterpart.

## 3. Candidate generation

v1's contract, unchanged in reach: every `highway` way within 25 m and every
kerb or crossing node within 10 m. Curb cuts and pieces under 5 m are now sampled
every 0.25 m instead of every metre.

- **Recall: 172 of 172** labelled elements were among the candidates.
- **Per record:** a median of 10 ways (95th percentile 21, maximum 53) and 1
  node (95th percentile 5).

Recall is measured against obvious labels only: an element no labeller named
cannot be missed.

## 4. Matcher v2

`kitchener-geo08-matcher-v2`: deterministic, interpretable rules, every
threshold named with its provenance (`POLICY_PROVENANCE`). There is no score and
no confidence; each decision records the rule that made it and the values it
read.

| Change from v1                       | Rule                                                                                                                                          |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Crossings carry curb cuts            | Any footway, path or steps way may carry a record; a crossing carries curb cuts and crossings. Kind only breaks ties, never removes a carrier |
| Pieces follow ways                   | A curb cut or piece under 5 m, sampled every 0.25 m within 2 m, is carried only by a way it follows: within 15° where near                    |
| A short piece follows one way        | One way carries at least 60% of it, and no rival lies within 30° and 2 m along all of it; else ambiguous                                      |
| Curb cuts are local                  | Kerb node within 2 m; with two, the one on a way the piece follows, else ambiguous. No kerb node and no way followed at a junction: ambiguous |
| Stairs                               | On a plain footway: a correspondence (`generic_way`), unless OSM steps lie within 25 m: ambiguous                                             |
| Structures                           | Every carrier kept; pieces tagged as the structure carry from 1 m                                                                             |
| Chained ways never compete           | Ways sharing a node are one line for the contest; corners are caught by the rival rule                                                        |
| Partial counterparts must be aligned | A path touching a spur at a right angle is not one                                                                                            |

**Tuning.** A declared 36-point grid over follow angle, rival allowance, carry
distance and coverage. The selection rule was declared before the grid ran: a
false attachment costs twice an abstention on an obvious correspondence, then
the most exact sets, then the most conservative values.

- **Identified by the development data:** the follow angle (15°) and the carry
  distance (3 m).
- **Not identified:** the rival allowance (10° and 15° tie) and the coverage
  (0.6 and 0.75 tie). The rule took the more conservative value of each.
- **Every benchmark run** re-runs the grid and refuses to continue unless it
  still selects the frozen policy.

On the development set, where it was designed and tuned, v2 made 201 exact sets
to v1's 195, with 12 false attachments to v1's 19 and 2 matches where the
labeller abstained to v1's 16. **That is not a result.**

## 5. Held-out results

The single evaluation, over 186 records:

| Outcome                                                  | v1 (frozen, unchanged) | v2      |
| -------------------------------------------------------- | ---------------------- | ------- |
| Exact correspondence set                                 | 89                     | **105** |
| Partial / wrong set                                      | 33 / 2                 | 13 / 2  |
| Abstained on an obvious correspondence                   | 1                      | 5       |
| Correctly unmatched / abstained where OSM has nothing    | 12 / 8                 | 11 / 9  |
| Correctly abstained where the labeller could not name it | 15                     | **33**  |
| **Matched where the labeller could not name it**         | 25                     | **7**   |
| Unmatched where the labeller could not name it           | 1                      | 1       |
| Correct decisions                                        | 116                    | **149** |

- **Pairs:** v2 found 153 true pairs, with 3 false positives and 19 false
  negatives.
  - Precision **0.981** (bootstrap over records 0.956–1.000); v1 0.940.
  - Recall **0.890** (0.845–0.932); v1 0.820.
  - F1 **0.933** (0.901–0.960); v1 0.876.
- **False attachments** (a partial or wrong set, or a match where OSM has
  nothing): v2 15, v1 35.
- **Exact-set precision among matches**, where the labeller named the elements:
  v2 0.875 (Wilson 0.804–0.923), v1 0.718.
- **Abstention:** v2 abstains on 25.3% of records (automatic decisions 74.7%,
  0.680–0.804), against v1's 12.9%. The labellers called 22% ambiguous. Almost
  all the difference is on records the labellers could not name either: v2
  abstains on 33 of them, v1 on 15.
- **Baselines** never abstain, so each matched all 41 records the labellers
  called ambiguous:
  - nearest geometry: 31 exact sets, 114 false attachments, pair precision
    0.324;
  - median offset and overlap: 75 exact sets, 70 false attachments, pair
    precision 0.745 each.

## 6. v1 against v2, class by class

A record may be in more than one class. Records in the class are in brackets.

| Class (records)                        | Exact v1 → v2 | False attachments | Matched where labeller abstained | Abstained on obvious | Pair P / R v2 |
| -------------------------------------- | ------------- | ----------------- | -------------------------------- | -------------------- | ------------- |
| Curb cuts (91)                         | 24 → **39**   | 30 → **12**       | 13 → **3**                       | 0 → 3                | 0.987 / 0.839 |
| — without an OSM kerb node (54)        | 15 → 17       | 13 → 8            | 7 → **1**                        | 0 → 3                | 0.967 / 0.725 |
| Short and junction pieces (36)         | 24 → 23       | 1 → 0             | 7 → **1**                        | 0 → 2                | 1.000 / 0.920 |
| Stairs (17)                            | 14 → 13       | 0 → 0             | 2 → 1                            | 0 → 1                | 1.000 / 0.929 |
| — OSM steps beside it (9)              | 8 → 8         | 0 → 0             | 1 → 1                            | 0 → 0                | 1.000 / 1.000 |
| — plain footway or displaced steps (8) | 6 → 5         | 0 → 0             | 1 → **0**                        | 0 → 1                | 1.000 / 0.833 |
| Other structures (19)                  | 15 → 18       | 3 → 1             | 0 → 0                            | 1 → 0                | 0.964 / 1.000 |
| None of these (30)                     | 19 → 18       | 1 → 2             | 3 → 2                            | 0 → 0                | 0.950 / 0.905 |

- **Curb cuts improve most.** 28 records are fixed and 4 broken. The crossing a
  piece runs onto is now named, and pieces at junctions abstain.
- **Short pieces stop over-committing** (7 matches where the labeller abstained
  fall to 1), at the price of 2 abstentions on obvious pieces.
- **Stairs are the same count either way**, on too few records to say more. The
  one displaced stair is now abstained on, and one bent-footway stair is
  newly abstained on (§7).
- **Regressions exist and are named.** The "none of these" class gains one
  false attachment: an alley crossing OSM marks with a node on the sidewalk
  line. v2 lets a sidewalk carry a crossing record, and v1's class rule did
  not (§7). v2 also abstains on 9 records where OSM has nothing, against v1's 8.

**Ablations**, each switching one change off on the held-out sample:

| Switched off                    | Exact | False attachments | Matched where labeller abstained | Correct |
| ------------------------------- | ----- | ----------------- | -------------------------------- | ------- |
| (frozen v2)                     | 105   | 15                | 7                                | 149     |
| Crossings never carry curb cuts | 95    | 24                | 6                                | 140     |
| Follow rule (45° as in v1)      | 103   | 21                | 23                               | 131     |
| Piece rules                     | 82    | 41                | 26                               | 109     |
| Kerb topology                   | 105   | 15                | 9                                | 147     |
| Stair rule                      | 105   | 15                | 8                                | 148     |
| Structure pieces                | 104   | 15                | 6                                | 149     |

The piece and follow rules carry most of the gain. Switching the
structure-piece rule off loses one exact set, adds one abstention and removes
one over-commitment: no net change on this sample.

**Repeat labels.** On the 60-record subset, a second pass gave the same
correspondence class 60 times of 60, and the same OSM set on 35 of the 39
records both passes called obvious. This is the consistency of one procedure,
not inter-rater reliability. Scored against the second pass, v2's exact sets on
the subset rise from 34 to 36.

## 7. Failure analysis

Every one of the 37 failures, with its cause
([`kitchener-geo08-failure-analysis.json`](../evidence/kitchener-geo08-failure-analysis.json)):

| Cause                                         | Records | What happened                                                                                                                                                                                                                                          |
| --------------------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Curb cut's crossing claims under a quarter    | 11      | The piece runs from a sidewalk's end in line with the crossing it leads onto; the crossing is within 2 m but nearest to under a quarter of it and is dropped. The kerb node and sidewalk named are right: an **incomplete set, never a wrong element** |
| Abstained where OSM has nothing               | 9       | A sidewalk touches the curb cut or connector at about 90°; the junction rule counts any near way, aligned or not. **Safe direction**                                                                                                                   |
| Follow-angle boundary                         | 5       | Four pieces follow their way at 22–31° and abstain; one names the crossing at 13.4° where the label names the sidewalk at 15.3°                                                                                                                        |
| Kerb node at 2.02 m or 2.26 m                 | 2       | Just past the 2 m definition                                                                                                                                                                                                                           |
| Trail on highway=service ways                 | 2       | Matched; the labeller could not tell a trail from a service track                                                                                                                                                                                      |
| Crossing drawn as a node on the sidewalk line | 2       | OSM runs the sidewalk across an alley and marks the crossing with a node on it; v2 names the sidewalk                                                                                                                                                  |
| Six single records                            | 6       | A stair split between steps and footway; an apex ramp serving two crossings; a piece past a crossing's end; a non-curb piece onto a crossing; a bridge 5.5 m onto its approach (5 m end slop); an offset crossride                                     |

**Of the 7 matches where the labeller abstained, every one is a named
boundary:** a second kerb just beyond 2 m, an apex ramp, a piece past a
crossing's end, a stair split, a non-curb piece onto a crossing, and two trails
on service ways. Representative cases are drawn in the error page.

## 8. Full-pilot dry run

Matcher v2 over all 11,547 eligible records, with v1 beside it. **Nothing here
says the decisions are right** — the benchmark is the measure.

| Records                               | v2 matched | v2 ambiguous | v2 unmatched |
| ------------------------------------- | ---------- | ------------ | ------------ |
| All eligible (v1: 10,808 / 474 / 265) | 10,257     | 1,029        | 261          |
| Curb cuts (3,192)                     | 2,406      | 775          | 11           |
| The 1,152 v1 matched to ways only     | 803        | 349          | —            |
| Stairs (40)                           | 35         | 3            | 2            |
| Short non-curb pieces (372)           | 229        | 140          | 3            |

- **Curb cuts.** 959 are matched to a kerb node and the ways followed, 631 to
  a kerb node alone, and 816 to ways alone. 581 are at junctions with no kerb
  node, and 194 have two kerb nodes it cannot choose between.
- **The 1,152 PA-GEO-06 could not accept.** v2 matches 803 of them to the
  metres of the ways they follow, and abstains on 349 at junctions. The pilot
  finds 1,152 curb cuts that v1 matched to ways only, the count PA-GEO-06
  reported, a check that it reproduces that accounting.
- **Stairs.** 15 of the 35 matched stairs lie on plain OSM footways
  (`generic_way`), 2 are ambiguous because OSM steps are displaced nearby, and
  2 have no counterpart.
- **Short pieces.** 119 abstain at junctions, and 20 lie between two ways.
- **Relationships:** 4,884 one-to-one, 4,715 many-to-one, 561 many-to-many,
  97 one-to-many.
- **Local scope.** Matched curb cuts name a median 2 m of way (95th percentile
  6 m). On the held-out sample the largest is 6 m.
- **Runtime on one laptop** (Windows 11, Python 3.13, 16 GB): 183 s end to end,
  of which 157 s ran both matchers over every record and 16 s the development
  check. Peak process memory was 435 MB.

## 9. Potential evidence unlocked — research only

If a later, licensed reconciliation accepted these correspondences:

- **816 City curb ramps** would sit at a local way extent where OSM records no
  kerb node and no kerb tag.
  - Three of them come from City records over 20 m long carrying
    `CURBCUT = Y`. The City does not say where along them the ramp is, so those
    locate no ramp and would have to be excluded.
  - On the held-out sample, v2's way-only curb-cut matches without a kerb node
    named only labelled elements in 24 of 26 cases; 7 of those 24 were
    incomplete.
- **15 City stairs** would be assertions only the City makes, on OSM ways that
  record no steps.

**Neither is routed, neither is verified**, and both rest on correspondences
measured on a sample.

## 10. Licensing

Unchanged, and the founder gate stays closed:

1. The City permits PathAble's research use.
2. The City separately permits use of its data in OSM.
3. OSMF LWG approval is not confirmed.

No Kitchener assertion is production-routable, and no combined production
database exists. The committed evidence holds City and OSM geometry in the
review page, the error page and the label files, credited as
[`DATA_SOURCES.md` §11](../licensing/DATA_SOURCES.md) requires.

## 11. Decision: LIMITED GO — curb ramps only

To reconciliation research for **curb ramps without an OSM kerb node**, behind
the licensing gate and still without routing.

**Curb ramps pass, with conditions.**

What the held-out sample shows for curb cuts without an OSM kerb node (54
records):

- v2 is precise at the level of elements: pair precision 0.967.
- It rarely commits where the labeller could not: 1 of 15, against v1's 7.
- Of its 26 matches, 24 name only labelled elements.
- The pilot turns 803 of the 1,152 blocked curb cuts into local
  correspondences.

A reconciliation may say "the City records a curb ramp at this local place" on
these conditions:

- attach it only to the named kerb node or way extent;
- treat the set as possibly incomplete: 11 held-out sets missed the crossing
  the piece runs onto, and nothing may be inferred from the gap;
- exclude records longer than 20 m;
- leave the 349 junction abstentions out.

**Stairs are not established.** They are neither passed nor failed:

- On six held-out stairs on plain footways, v2 made five exact correspondences,
  abstained on one, and attached nothing falsely.
- It abstained on the one displaced stair.

Six records cannot establish a class. The pilot has 15 such stairs, few enough
to review one by one. That review, or more data, should come before any stair
reconciliation. A City stair where OSM records none remains the most
safety-relevant fact this data holds, which is why it should not ride on six
records.

**Not NO-GO.** Ambiguity is where it belongs: v2 abstains on 33 of 41 records
the labellers could not name, against v1's 15, and most of its remaining
over-commitments are named boundaries.

**Short pieces** stop over-committing on this sample (1 match where the
labeller abstained, against 7). PA-GEO-06 excluded pieces of 5 m or less from
surface reconciliation for exactly that reason. A later card may revisit that
exclusion on this evidence; this one does not.

Any change to v2 is a new policy version and needs another untouched held-out
sample. **This one is spent.** The follow-angle boundary, the perpendicular
touch rule and the quarter-share rule for a crossing continuation are all
visible now, and fixing them against this sample would be tuning on the test.

## 12. Limitations

- **AI labels throughout, one model family.** The labellers, the guide's author
  and the matcher's designer are the same model. Errors the model makes
  consistently would not show as disagreement.
- **Definitions and rules share values.** "About 2 m", "follows" and the 5 m
  end slop are in both the guide and the matcher.
- **Stratified sample.** It is weighted to the unresolved classes, so no figure
  is a population estimate. Strata of 1 to 16 records say little alone. Stairs
  rest on 17 records.
- **The development set** includes the records whose failures designed v2. Its
  figures are fitted, not results.
- **No field check, no imagery.** Correspondence is judged from both datasets'
  geometry and tags.
- **One OSM extract and one City snapshot, one laptop.**

## 13. Reproducing

From `services/api`, with PA-GEO-03's normalized snapshot and PA-GEO-04's study
extract. None of these commands needs the database or the network.

```
pathable kitchener matcher-v2-holdout --normalized <folder> --extract <…> --extract-manifest <…> \
    --development-sample ../../docs/evidence/kitchener-geo04-sample.geojson \
    --development-sample ../../docs/evidence/kitchener-geo05-holdout.geojson --out <holdout.geojson>
pathable kitchener matcher-v2-review <the same inputs> --sample <holdout.geojson> \
    --html <review.html> --digest <digest.txt> --packs-dir <packs>
pathable kitchener matcher-v2-development-labels <the same inputs> --evidence-dir ../../docs/evidence --out <…>
pathable kitchener matcher-v2-benchmark <the same inputs> --evidence-dir ../../docs/evidence \
    --failure-analysis ../../docs/evidence/kitchener-geo08-failure-analysis.json \
    --json <matcher-v2.json> --errors-html <errors.html> --pilot
```
