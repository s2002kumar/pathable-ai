# Labelling guide — PA-GEO-08 held-out correspondence labels (definitions version 2)

You are labelling City of Kitchener Active Transportation records against the
frozen OpenStreetMap (OSM) extract PathAble routes on. For each record you
decide which OSM elements are the same physical facility.

You label physical correspondence only. You do not judge whether either source
is right about the facility, and you do not judge attribute values. Physical
correspondence and attribute agreement are separate questions: OSM describing a
facility more generally than the City does (a plain footway where the City
records a stair) is an attribute difference, not by itself a reason to call the
correspondence ambiguous.

## What you have

- `records.txt` — one block per record: the City record's attributes; the
  nearest OSM road; the City records touching its ends; every OSM candidate way
  near it as `C<n> way/<id>` with distances, tags and which other listed
  candidates it connects to; and tagged OSM nodes within 8 m (`node/<id>`,
  distance, tags, the ways it is on).
- `maps/map-<id>.png` — the record drawn in the City's metres. The record is
  red; other City records orange; OSM roads grey; other OSM ways dark grey;
  numbered OSM candidates in colour (C1, C2 …); OSM kerb nodes as triangles,
  crossing nodes as circles, other tagged nodes as squares. A 10 m scale bar is
  at the bottom left; north is up.
- Candidates are numbered **in OSM-id order**. The number says nothing about how
  likely a candidate is. Nothing in this pack is a matcher's output.

Distances in `records.txt`: "closest" is the closest approach; "median" and
"worst" summarise the distance from each metre of the record to the way;
"record within 2/5 m" is the share of the record within 2 m and 5 m of the way;
"way within 5 m of record" is the share of the way near the record; "angle" is
the typical angle between them where they are near (0 = parallel, 90 =
perpendicular). `highway=steps` ways within 25 m are always listed.

## correspondence

- `obvious_correspondence` — OSM represents the same physical facility, and you
  can name exactly which OSM elements, with no reasonable alternative.
  Closeness alone never qualifies: the element must be the same facility in the
  same place — the same side of the road, the same crossing, the same flight of
  stairs.
- `ambiguous_correspondence` — OSM may represent it, but you cannot name the
  elements with confidence. Typical cases:
  - two OSM ways are equally plausible (parallel sidewalks; a sidewalk beside a
    cycle track at the same distance);
  - a short piece at a corner or junction that follows no single way — including
    a curb cut there with no kerb node;
  - two kerb nodes near a curb cut, and you cannot tell which marks this ramp;
  - OSM `highway=steps` nearby that may be the same stair drawn somewhere else;
  - an OSM way tagged `highway=construction`;
  - OSM records the facility only as a tag on a road (`sidewalk=both`,
    `cycleway=lane`): cite the road, representation `road_attribute`.
- `no_correspondence` — nothing in OSM represents this facility: no way or node
  of the same kind within about 5 m. A road alone is not a correspondence for a
  sidewalk unless it carries a tag for it, and a way that only touches one end
  of the record at an angle is not a correspondence.
- `not_comparable` — the record cannot be judged (for example, a broken
  geometry).

## osm — the exact correspondence set

For an obvious correspondence, list every element; for an ambiguous one, list
the plausible alternatives (they are kept for the record, not scored).

- **Ways.** Cite every OSM way that carries the same facility over any part of
  the record. If OSM splits the facility into several ways, cite each one that
  carries part of it. Cite a way even when it runs far beyond the record: OSM
  often draws one way where the City has several records. Do not cite ways that
  only touch its ends: about a junction's width (5 m) of the record running onto
  the next way is end slop, not a second way.
- **Crossings.** Cite the crossing way over the same road at the same place. If
  OSM has no crossing way there but has a crossing node (`highway=crossing`) on
  the road where the City's crossing is, cite the node.
- **Curb cuts** (records with `curbcut=Y`; usually a 1–3 m piece at a corner or
  at the end of a crossing). A curb cut is local: cite only the elements at the
  ramp.
  - Cite the OSM kerb node (`barrier=kerb` or `kerb=*`) that marks this ramp, if
    one lies within about 2 m of the piece — only the node that marks this ramp,
    not the kerb on the far side of the road.
  - With two kerb nodes near, cite the one where the crossing the piece runs
    onto begins. If the piece serves both crossings, or you cannot tell which,
    the correspondence is ambiguous.
  - Cite every OSM way the piece **follows**: most of it within about 2 m of the
    way and running in line with it, not across it. A crossing way counts
    exactly like a sidewalk: a piece running from the end of a sidewalk onto the
    first metres of a crossing follows both, so cite both. A way the piece only
    touches, or crosses at an angle, is not cited.
  - A piece too short or too diagonal to follow any way, beside a kerb node that
    marks it: cite the kerb node alone.
  - No kerb node, and no way the piece follows — it sits across a junction where
    several ways meet: ambiguous.
  - `curbcut=Y` says the City records a curb cut here. It does not say
    `kerb=lowered` or `kerb=flush`; do not judge the kerb value.
- **Stairs.** Cite the OSM ways that are the same flight of stairs.
  - If OSM tags it `highway=steps`, cite those ways.
  - If OSM draws the same stair as a plain footway or path — the same place, the
    same line, the same connections, and no `highway=steps` near — cite that way.
    It is an obvious correspondence with representation `generic_way`: the stair
    is then something only the City records.
  - If a `highway=steps` way lies nearby but not on the record, it may be the
    same stair drawn elsewhere: ambiguous. Also ambiguous: several plausible
    ways, connections that disagree, or an unclear split or merge.
- **Bridges, overpasses, underpasses, boardwalks.** Cite every OSM way that
  carries the same facility over any part of the record, including approach
  ways the City record runs along beyond the structure. If none of them is
  tagged as the structure (`bridge=*`, `tunnel=*`), the representation is
  `generic_way`.
- **Corner and junction pieces** (a few metres, not a curb cut, where ways
  meet): obvious only if the piece clearly follows one way. If it lies between
  two ways that meet at the corner, or across the junction at an angle,
  ambiguous.
- Kerb nodes belong in the set only for curb-cut records.

## representation

- `separate_way` — only ways are cited, and at least one is the City's kind of
  facility.
- `generic_way` — only ways are cited, and none carries the City's structure
  type: a City stair on a way not tagged `highway=steps`; a City bridge,
  overpass, underpass or boardwalk on ways with no `bridge=*` or `tunnel=*` tag.
- `node` — only nodes are cited.
- `multiple` — ways and nodes are cited.
- `road_attribute` — OSM records the facility only as a tag on a road.
- `none` — no correspondence.

For an ambiguous correspondence, give the representation you think OSM uses.

## relationship (obvious correspondences only; `null` otherwise)

- `one_to_one` — the record and one OSM way cover substantially the same extent,
  and that way carries no other physical City record of the same facility. A
  node-only correspondence is `one_to_one`.
- `one_to_many` — the record corresponds to several OSM ways (OSM splits it).
- `many_to_one` — the OSM way also carries other physical City records of the
  same facility (OSM merges what the City splits). `records.txt` lists the
  other City records along each way.
- `many_to_many` — several records and several ways, with no clean nesting.

City virtual links and connector stubs of a few metres at a junction are not
counted in a relationship. About a junction's width (5 m) of end slop is not a
difference in extent.

## note

One or two sentences: what OSM has, and why you chose the label. Name the
candidates you cite by C-number as well as id.

## Worked examples (from other records, labelled under these definitions)

1. A 2.6 m curb-cut piece straddling a `kerb=lowered` node 0.55 m away, lying
   about 1.2 m along the last metres of an OSM sidewalk and 1.4 m along the
   first metres of the crossing way that continues it, both at about 1°:
   `obvious_correspondence`, osm the kerb node, the sidewalk and the crossing,
   `multiple`, `many_to_many` (both ways carry other City records).
2. A 1.2 m curb-cut piece with a `kerb=lowered` node 0.1 m away, where a crossing
   leaves the corner; the sidewalks and the crossing meet the piece at 29–79°,
   so it follows none of them: `obvious_correspondence`, osm the kerb node only,
   `node`, `one_to_one`.
3. A 1.4 m curb-cut piece where two sidewalks and two crossings meet at one
   untagged junction, no kerb node within 8 m, the piece at 38–51° to every way:
   `ambiguous_correspondence`, osm lists the four ways, relationship `null`.
4. A 4.4 m curb-cut piece with kerb nodes at 0.8 m and 1.2 m; it runs along the
   end of a sidewalk onto one crossing, which begins at the 0.8 m node, while
   the 1.2 m node marks the other crossing: `obvious_correspondence`, osm the
   0.8 m kerb node, the sidewalk and that crossing.
5. A 1.8 m corner ramp touching both crosswalks, each marked by its own kerb node
   (1.45 m and 1.96 m away), running diagonally across the corner:
   `ambiguous_correspondence`, osm the two kerb nodes.
6. A 3.9 m corner piece joining two City sidewalks, where the two matching OSM
   sidewalks meet at an untagged corner node and the piece lies near both:
   `ambiguous_correspondence`, osm the two sidewalks.
7. A 4.8 m stair with an OSM `highway=footway` lying exactly on it along its
   whole length, no `highway=steps` within 25 m, the footway continuing over the
   City walkways at either end: `obvious_correspondence`, osm the footway,
   `generic_way`, `many_to_one`.
8. A 2 m stair with an OSM footway over it at 0.8 m, while OSM tags
   `highway=steps` 7.5–9.4 m further along the same path:
   `ambiguous_correspondence`, osm the footway and the steps.
9. Stairs with OSM `highway=steps` within 0.6 m and the same length:
   `obvious_correspondence`, `separate_way`, `one_to_one`.
10. A sidewalk over an overpass that runs 6–10 m past OSM's bridge way at each
    end, onto the OSM sidewalks either side: `obvious_correspondence`, osm all
    three ways, `separate_way`.
11. A sidewalk with an OSM sidewalk at a steady 0.7 m and an OSM cycleway 1.7 m
    away that is a different facility (the City's own cycle track):
    `obvious_correspondence`, osm the sidewalk only, `separate_way`.
12. A new sidewalk on the east side of a street; OSM has only the road (no
    sidewalk tags) and the west-side sidewalk 12 m away: `no_correspondence`,
    osm `[]`, `none`.
13. A 5.6 m dead-end trail spur that an OSM path touches at one end at a right
    angle, with nothing along the spur itself: `no_correspondence`.

## Output

Write a JSON file in exactly this shape (every record in your pack, in the
order of `records.txt`):

```json
{
  "kitchener_geo08_labels_version": 2,
  "pass": "<the pass name you were given>",
  "labeller": "<the labeller description you were given>",
  "records": [
    {
      "activetransportid": 123456,
      "correspondence": "obvious_correspondence",
      "osm": ["way/111", "node/222"],
      "representation": "multiple",
      "relationship": "one_to_one",
      "note": "…"
    }
  ]
}
```

Rules the file must follow (a validator checks them):

- an obvious correspondence lists at least one element, a relationship, and a
  representation that matches its elements (ways only → `separate_way` or
  `generic_way`, nodes only → `node`, both → `multiple`);
- anything else has `"relationship": null`;
- `no_correspondence` has `"osm": []` and `"representation": "none"`.

## Rules of the task

- Use only the files in your pack folder. Do not open any other file in the
  repository or on disk, do not look for other labels, and do not run the
  project's code except the validator command you were given.
- Label every record. When unsure between obvious and ambiguous, choose
  ambiguous and say why.
