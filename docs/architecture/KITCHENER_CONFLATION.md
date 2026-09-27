# Kitchener and OpenStreetMap — conflation benchmark (PA-GEO-05)

Can PathAble automatically say which OpenStreetMap elements a City of Kitchener
record describes, for the classes PA-GEO-04 found worth it, and abstain where it
cannot tell? This card built a deterministic matcher and measured it once
against a held-out sample labelled blind before the matcher ever saw it.

**Nothing here routes.** No Kitchener value reaches feasibility, cost,
uncertainty or explanations, and no graph changes. The matcher writes a research
artifact that no routing code imports; a static check enforces it
(`test_kitchener_isolation.py`). Attribute reconciliation — deciding between the
City's value and OSM's — is not done: both are kept side by side.

**Decision: LIMITED GO** to PA-GEO-06 (§11). The evidence is
[`kitchener-geo05-benchmark.json`](../evidence/kitchener-geo05-benchmark.json);
every failure is drawn in
[`kitchener-geo05-errors.html`](../evidence/kitchener-geo05-errors.html).

**What the numbers are.** Counts over a stratified sample of 193 records, scored
against labels made by AI model instances (Claude), not people. No figure here is
a proportion of the City's inventory, a field-verified accuracy, or a claim about
any other place. Intervals are sampling uncertainty over these records,
conditional on these labels.

## 1. Inputs, frozen

| Side      | What                                                                                                                                                    |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Kitchener | PA-GEO-03's snapshot `513094727cc1…`, normalized GeoParquet `ffe042be…`, native NAD83 / UTM 17N metres                                                  |
| OSM       | PA-GEO-04's study extract `8391f097…`, cut from the PBF the active Waterloo dataset (`51585450…`, checksum `51e75f78…`) was built from                  |
| Eligible  | Physical pedestrian ways and crossings, not sourced from street-level imagery, wholly inside the study box shrunk by 50 m: **11,547** of 34,052 records |

Virtual links are excluded as physical facilities. Default width, default
CONCRETE, default GOOD, grade, derived slope and `UPDATE_DATE` are never read as
evidence.

## 2. Benchmark design

**Development set.** PA-GEO-04's 80-record sample; the 58 eligible records carry
PA-GEO-04's adjudicated labels, re-read under this card's definitions with four
recorded conversions
([`kitchener-geo05-development-labels.json`](../evidence/kitchener-geo05-development-labels.json)).
Every threshold was tuned on these alone.

**Held-out set.** 193 records drawn by `pathable kitchener holdout` from the
eligible records minus the development set: 14 strata by first matching rule,
each a fixed number of records (or all of a smaller one), in the order of
`sha256(seed:id)`. The seed binds the sample version, the Kitchener snapshot and
the OSM extract. The sizes are argued in the file, and no statistical certainty
is claimed for them
([`kitchener-geo05-holdout.geojson`](../evidence/kitchener-geo05-holdout.geojson)).

| Stratum                                                      | Records |
| ------------------------------------------------------------ | ------- |
| Curb cuts with an OSM kerb node within 3 m / without         | 28 / 28 |
| Stairs / bridges, overpasses, underpasses and boardwalks     | 20 / 20 |
| Non-default surfaces                                         | 28      |
| Parallel ways, offset geometry, OSM split or long            | 10 each |
| Dense intersection, short piece                              | 8 each  |
| No OSM pedestrian way near, candidate-heavy, straightforward | 7, 6, 6 |
| Crossings                                                    | 4       |

**Order of work**, all in the branch history:

1. `e9c22d9` — the held-out sample, drawn before any tuning.
2. `9ec4d37` — the labelling guide and the blind review material.
3. `fa28972` — matcher policy v1 frozen, tuned on the development set only.
4. `8e27133` — the held-out labels frozen and pushed.
5. `08e2dd6` — the benchmark command; the single held-out evaluation ran from
   this commit, with a clean tree.

The matcher was never run on a held-out record before step 5. After it, nothing
in the matcher, its policy or a label changed. The failure analysis (§7) was
attached by a second run that the code refuses unless it reproduces the same
decisions (hash `0145279b…`).

**Labels.** Five AI model instances each labelled one fifth of the holdout blind:
from a text digest and maps of the record and every OSM candidate, under the
frozen guide
([`kitchener-geo05-labelling-guide.md`](../evidence/kitchener-geo05-labelling-guide.md)),
with no access to the matcher, its output, the development labels or another
pack. Two more instances labelled a 60-record subset again. One labeller reported
listing its own pack folder and counting its lines before labelling. Nothing
outside the pack was opened, and the file records this.

**What the labels are not.** They are not human ground truth, not expert labels
and not externally validated. The labellers, the guide's author and the matcher's
designer are all instances of the same model. The guide's definitions — about
5 m of end slop at a junction, a kerb node within about 2 m — are also fixed
values in the matcher. Errors the model makes consistently would not show up as
disagreement.

## 3. Candidate generation

Every `highway` way within 25 m of a record, and every kerb or crossing node
within 10 m, sampled every metre along the record: distance, position along the
way, and angle at each sample (`kitchener-geo05-candidates-v1`).

**Candidate recall: 189 of 189** labelled elements were among the candidates.
Ways per record: median 12, 95th percentile 30, maximum 52. Recall is measured
against obvious labels only; an element no labeller named cannot be missed.

## 4. Baselines

Four one-signal baselines take the single best way whenever any exists, and never
abstain.

| Baseline                | Exact sets | False matches | Pair precision (95%) | Pair recall (95%)   |
| ----------------------- | ---------- | ------------- | -------------------- | ------------------- |
| A — nearest geometry    | 47         | 120           | 0.389 (0.317–0.461)  | 0.344 (0.283–0.408) |
| B — median offset       | 118        | 49            | 0.880 (0.826–0.922)  | 0.778 (0.725–0.834) |
| C — worst point         | 118        | 49            | 0.868 (0.820–0.916)  | 0.767 (0.711–0.827) |
| D — share within 2 m    | 119        | 48            | 0.886 (0.838–0.928)  | 0.783 (0.731–0.839) |
| **Matcher v1** (frozen) | **135**    | **18**        | 0.955 (0.925–0.983)  | 0.905 (0.858–0.951) |

"False matches" counts a matched record whose set is partial or wrong, or a
match where OSM has nothing. Matches where the labeller abstained are counted
separately (§6).

## 5. The matcher

`kitchener-geo05-matcher-v1`: interpretable rules, every threshold named with its
provenance in the policy (`MatcherPolicy`, `POLICY_PROVENANCE`).

- **Claims.** Each sample is claimed by the nearest aligned (≤ 45°) compatible
  way within `carry_m` = 3 m. A way that claims less than `end_slop_m` = 5 m
  (or half a short record) is junction end slop, not a carrier. Coverage is the
  share of samples claimed.
- **Class.** A way's class must be compatible with the record's (a cycleway is a
  plausible trail, a road never a sidewalk), and a same-class way outranks a
  plausible one.
- **Ambiguity.** A sample is contested when another aligned compatible way, not
  joined to the nearest and at least as good a class match, is within 1.5 m of
  it. Above 20% contested, the matcher abstains.
- **Curb cuts.** A kerb node within 2 m marks the ramp; two within 0.5 m of the
  same distance cannot be told apart, so the matcher abstains. The target is the
  kerb node plus the metres of sidewalk the piece covers — never the whole way.
- **Structures.** Where a carrier is tagged as the City's structure (steps,
  bridge, tunnel), the approaches it runs onto are dropped.
- **Nodes and road tags.** A crossing OSM draws only as a node matches that node.
  A sidewalk OSM records only as a road's `sidewalk=*` tag is ambiguous, never a
  match to the road.
- **States.** `matched`, `ambiguous`, `unmatched`. There is no confidence score:
  each decision records the rule that made it and the values it read.
- **Relationships.** 1:1, 1:N, N:1 or N:M, from the carriers and the other
  physical City records lying along them.

**Tuning.** A 108-point grid over carry distance, coverage, contest margin and
contested share, with the selection rule declared before it ran (fewest false
matches, then most exact sets, then most decisions, then the most conservative
values). Every point gave 2 development false matches. The contest thresholds
are not identified by the development set at all. Each benchmark run re-runs the
grid and refuses to continue unless it still selects the frozen policy.

On the development set the frozen policy made 54 exact sets of 55 obvious labels,
pair precision 0.952 and recall 1.0. That is where it was tuned; it is not a
result.

## 6. Held-out results

The single evaluation, over 193 records: 154 labelled obvious, 26 ambiguous and
13 with no counterpart.

| Outcome                                                            | Records |
| ------------------------------------------------------------------ | ------- |
| Exact correspondence set                                           | 135     |
| Partial set / wrong set                                            | 17 / 1  |
| Abstained on an obvious correspondence                             | 1       |
| Correctly unmatched / abstained where OSM has none                 | 11 / 2  |
| Correctly abstained where the labeller could not name the elements | 4       |
| **Matched where the labeller could not name the elements**         | **21**  |
| Unmatched where the labeller could not name them                   | 1       |

- **Pairs:** 171 true, 8 false positives, 18 false negatives. Precision 0.955
  (bootstrap over records, 0.925–0.983), recall 0.905 (0.858–0.951).
- **Records:** 150 of 193 decisions correct. Exact-set precision among matches
  where the labeller named the elements is 0.882 (Wilson 0.822–0.924). Counting
  matches where the labeller abstained, it is 0.776.
- **Abstention:** the matcher abstained on 7 records (3.6%); the labellers could
  not name the elements on 26 (13.5%). This is the main weakness: **the matcher
  commits where a careful reviewer would not.**
- **Kerb nodes:** 23 of 24 labelled kerb nodes matched, no false kerb node.
- **Relationship** agreed on 121 of 135 exact matches; in 14 the labeller saw
  1:1 where the matcher counted another City record along the way (N:1).

**Per class** (a record can be in more than one):

| Class                 | Records | Exact / obvious | Partial or wrong | Matched where labeller abstained | Way pairs P / R |
| --------------------- | ------- | --------------- | ---------------- | -------------------------------- | --------------- |
| Non-default surface   | 38      | 33 / 33         | 0                | 1 of 1                           | 1.00 / 1.00     |
| Stairs and structures | 40      | 27 / 31         | 4                | 7 of 8                           | 1.00 / 0.84     |
| Curb cuts             | 56      | 30 / 44         | 13               | 8 of 12                          | 0.83 / 0.76     |
| None of these         | 69      | 55 / 56         | 1                | 5 of 5                           | 0.98 / 1.00     |

Per stratum, every figure is in the evidence file (`matcher_by_stratum`). The
stairs stratum made 10 exact sets of 20; the stratum of curb cuts with a kerb
node near made 14 of 28.

**Repeat labels.** On the 60-record subset, a second pass gave the same
correspondence class 60 times of 60, and the same OSM set on 49 of the 51 records
both passes called obvious. This is the consistency of one procedure repeated,
not inter-rater reliability. Scored against the second pass, the matcher's exact
sets on the subset fall from 43 to 41.

**Labeller effect.** Primary packs called between 1 and 9 of their ~39 records
ambiguous. Packs were interleaved by record id, so each saw every stratum; part
of the abstention gap is how readily a labeller says "ambiguous".

## 7. Ablations and failure analysis

Each ablation switches one kind of signal off, as declared with the frozen
policy.

| Ablation               | Exact sets | False matches | Matched where labeller abstained | Abstention | Pair P / R    |
| ---------------------- | ---------- | ------------- | -------------------------------- | ---------- | ------------- |
| Frozen policy          | 135        | 18            | 21                               | 3.6%       | 0.955 / 0.905 |
| Geometry only          | 122        | 25            | 23                               | 5.7%       | 0.962 / 0.799 |
| No class compatibility | **139**    | **14**        | 22                               | 3.1%       | 0.957 / 0.942 |
| No local alignment     | 130        | 21            | 23                               | 3.6%       | 0.933 / 0.889 |
| No ambiguity margin    | 135        | 18            | 21                               | 3.6%       | 0.955 / 0.905 |
| No topology            | 129        | 15            | 16                               | 10.9%      | 0.964 / 0.852 |
| No node representation | 121        | 31            | 20                               | 4.7%       | 0.949 / 0.788 |

Two ablations contradict the design:

- **Class compatibility did net harm on the holdout.** It was added for a
  development case (a cycleway beside a sidewalk), but it also stops a crossing
  way from carrying a sidewalk-family curb cut — the most common curb-cut
  failure below.
- **The ambiguity margin changed one held-out decision and no outcome.** It was
  unidentified on the development set and almost inert here, so the matcher's
  abstention comes from other rules.

Turning topology off abstains more and matches wrongly less. That is the
direction a cautious pipeline might prefer, at the cost of 6 exact sets.

**Every failure, with its cause** — 43 records, each inspected against its
label, the rule and signals, the OSM tags and its decision under every ablation
([`kitchener-geo05-failure-analysis.json`](../evidence/kitchener-geo05-failure-analysis.json)):

| Cause                                         | Records | What happened                                                                                                                                     |
| --------------------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Curb cut runs onto the crossing               | 8       | Class compatibility never lets a crossing way carry a sidewalk-family curb cut, so the crossing half of the piece is lost; the kerb node is right |
| Stair on an untagged footway                  | 7       | OSM draws the walkway as a plain footway; labellers said ambiguous, the matcher matched and reports the stair as the City's alone                 |
| Curb-cut carrier for a piece of about a metre | 6       | Two or three samples and the 45° limit decide whether a sidewalk belongs; labellers cited only the kerb node, or another stub                     |
| Diagonal piece at an untagged junction        | 6       | A short piece at 37–45° across a junction with no kerb node; one sidewalk passes the angle limit and nothing competes                             |
| Corner piece between chained ways             | 5       | Two ways share the corner node, so they do not compete; the matcher names the majority way where the labeller could not choose                    |
| Structure longer than OSM's structure         | 4       | The structure rule drops approaches the City record runs along, and end slop drops structure pieces under 5 m                                     |
| Kerb node choice                              | 3       | Two kerb nodes near one corner; distance with a 0.5 m margin against which crossing the ramp serves                                               |
| Perpendicular neighbour                       | 2       | Abstained on a spur with nothing along it, because a path touching one end is within 5 m. Safe direction                                          |
| End slop boundary                             | 1       | 6.5 m onto the next way, just over the 5 m end slop                                                                                               |
| OSM under construction                        | 1       | Only a `highway=construction` way; the matcher says no counterpart, the labeller ambiguous                                                        |

Of the 21 matches where the labeller abstained, 13 are corner or junction pieces
of 5 m or less (three of them beside kerb nodes the labeller could not choose
between); the other 8 are the seven stairs on untagged footways and one trail
connector. The matcher has no rule that says "a short piece where ways meet is
ambiguous unless a kerb node settles it", and it needs one.

## 8. Attributes after matching

The City's non-default assertion beside OSM's on the same elements, kept apart
and never resolved. Counted through the labelled correspondence, to leave out
matching error:

| Attribute                    | Same or consistent | OSM coarser | Conflict | City only | OSM only |
| ---------------------------- | ------------------ | ----------- | -------- | --------- | -------- |
| Curb cut (kerb node)         | 24                 | —           | 0        | 20        | —        |
| Structure                    | 22                 | —           | —        | 9         | —        |
| Surface material             | 18                 | 2           | 2        | 11        | 80       |
| Railing (OSM `handrail`)     | 1                  | —           | —        | 7         | —        |
| Condition (2015, historical) | —                  | —           | —        | 7         | —        |

"Consistent" for a curb cut means OSM's `kerb=lowered` or `flush` agrees with
the City's "a curbcut down to street level". It never means the City stated a
kerb height. "OSM only" for surface is a record whose City surface is the
template default, which is not evidence. Through the matcher's own decisions the
counts are similar: curb cut 26 consistent and 25 City-only, structure 22 same
and 16 City-only. The difference is mostly the stairs on untagged footways.

What PA-GEO-04's lineage study said still holds: agreement is not independent
confirmation, and the City-only facts are where any value is. On these records,
that means 20 curb cuts OSM marks with no kerb node, and stairs OSM draws as
plain footways.

## 9. Full-pilot dry run

The frozen matcher over all 11,547 eligible records, written as the research
artifact. **Nothing here says the decisions are right** — the benchmark is the
measure.

- **Decisions:** 10,808 matched, 474 ambiguous, 265 unmatched. The pilot agreed
  with the benchmark on all 193 held-out records.
- **Artifact:** four files, 1.02 MB.
  - `source_features` — GeoParquet 1.1, native CRS.
  - `matches` — each target's element, OSM version, role and extent in metres.
  - `assertions` — 7,271 rows.
  - `comparisons` — 11,413 rows, every one `unresolved`.
  - A manifest records every hash.
- **Local scope:** the median curb-cut way target spans 2 m (95th percentile
  5 m). Three curb-cut records claim nearly a whole way over 20 m, and each is a
  long City record (85–327 m) carrying `CURBCUT = Y`. The City does not say
  where along it the ramp is, so the extent is the record's own.
- **Runtime on one laptop** (Windows 11, Python 3.13, 16 GB): 95–101 s end to
  end over two runs.
  - 76–79 s is candidates and matching for 11,547 records.
  - About 10 s is the development grid.
  - The artifact write takes about 2 s.
  - Peak process memory is 458 MB.
- **Determinism:** a second run reproduced every decision, every metric and all
  four artifact files byte for byte.

## 10. Licensing

Unchanged, and the founder gate stays closed. Three facts stay separate:

1. The City permits PathAble's research use.
2. The City separately permits use of its data in OSM.
3. OSMF LWG approval is not confirmed, and the public documentation is not
   consistent.

The artifact stays in the ignored data folder. The committed evidence holds
City and OSM geometry in the failure maps and label files, credited as §11 of
[`DATA_SOURCES.md`](../licensing/DATA_SOURCES.md) requires. Nothing from
Kitchener enters a dataset PathAble serves.

## 11. Decision: LIMITED GO to PA-GEO-06

PA-GEO-06 is reconciliation research: a provenance and conflict model, and a
coverage benchmark. The benchmark supports starting it for some classes only,
still behind the licensing gate, and still without routing.

**Go, for reconciliation research:**

- **Non-default surfaces.** 33 of 33 exact, no false match, 4 correct "no
  counterpart". The comparison is ready: 18 same, 2 coarser, 2 conflicts,
  11 City-only.
- **Curb cuts through the kerb node only.** 23 of 24 labelled kerb nodes matched
  and none falsely. The way-level set is not reliable enough (below), so a curb
  cut's evidence may attach to its kerb node, not to a length of sidewalk.
- **Structures OSM tags as the structure.** No false way pair among
  structures (records labelled ambiguous are not scored as pairs; the seven
  matched where the labeller abstained are the stairs below). Incomplete sets,
  where the City record runs past the structure, attach less than they could,
  but never to a wrong element.

**No go until fixed and re-measured on a new holdout:**

- **Way-level curb-cut sets.** The crossing defect costs 8 records.
- **Short pieces at junctions.** 13 of the 21 matches where the labeller
  abstained are corner or junction pieces of 5 m or less. They need an explicit
  abstention rule.
- **Stairs on untagged footways.** Decide first what the correspondence is
  (decided below, for matcher v2). The City recording a stair where OSM records
  none may be the most safety-relevant thing this data holds. Matching it
  silently, or dropping it, would both be wrong.

Any change to the matcher is a new policy version, and it needs a new held-out
sample: this holdout has been used. Without that, the next figures would be
tuned on the test set.

### Decided after the evaluation: correspondence and attributes are separate

Recorded on 2026-09-27, after the single held-out run, for matcher v2. It
changes no v1 rule, label or figure above: the seven stair failures in §7 stay
failures under the frozen guide.

A City record with `FEATURE_TYPE = STAIRS` may correspond to an OSM way tagged
only `highway=footway`, when geometry and topology make it clear that both
describe the same physical facility. Two questions are answered separately:

1. **Physical correspondence** — is it the same facility? Geometry and topology
   decide. The absence of `highway=steps` does not by itself make the
   correspondence ambiguous.
2. **Attribute assertions** — what does each source say about it? The City says
   stairs. OSM's `highway=footway` says a footway and asserts nothing about
   steps: it does not say "there are no stairs".

A clear case is therefore a correspondence, with the stair recorded as an
assertion only the City makes. The OSM way is never retagged `highway=steps`,
and the City's assertion does not become routing truth; routing on it stays
prohibited.

A stair stays ambiguous where physical identity itself is unclear: several
plausible footways, topology that disagrees, material geometric displacement, a
nearby OSM `highway=steps` that may be the actual stair somewhere else, or an
unclear split or merge.

Matcher v2 needs this rule written into its labelling guide and a new, untouched
holdout. PA-GEO-06 does not reconcile these stairs; they wait for that
benchmark.

## 12. Limitations

- **AI labels throughout, and one model family.** The labellers, the guide's
  author and the matcher's designer are the same model.
- **Stratified sample.** Nothing weights it to the inventory, so no figure is a
  population estimate. Strata of 4 to 10 records say little alone.
- **Development set.** Only 58 records, with 2 ambiguous labels and 1 with no
  counterpart. Abstention was barely tunable, and the contest thresholds were
  not identified at all.
- **No field check, no imagery.** Correspondence is judged from both datasets'
  geometry and tags.
- **One OSM extract and one City snapshot.** Nothing is known about how matches
  age.
- **Lineage is not assessed per match.** The artifact marks every assertion
  `not_assessed`. PA-GEO-04's finding still applies: most OSM geometry here may
  share the City's photographic source.
- **One laptop.** The runtime and memory figures describe this machine only.

## 13. Reproducing

From `services/api`, with PA-GEO-03's normalized snapshot and PA-GEO-04's study
extract:

```
pathable kitchener holdout --normalized <folder> --extract <study-extract.jsonl.gz> \
    --extract-manifest <manifest.json> \
    --development-sample ../../docs/evidence/kitchener-geo04-sample.geojson \
    --out <holdout.geojson>
pathable kitchener holdout-review <the same inputs> --sample <holdout.geojson> \
    --html <review.html> --digest <digest.txt>
pathable kitchener benchmark --normalized <folder> --extract <…> --extract-manifest <…> \
    --evidence-dir ../../docs/evidence \
    --failure-analysis ../../docs/evidence/kitchener-geo05-failure-analysis.json \
    --json <benchmark.json> --errors-html <errors.html> --artifact-dir <folder>
```

None of them needs the database or the network.
