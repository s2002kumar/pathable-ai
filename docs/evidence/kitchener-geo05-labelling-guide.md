# Labelling guide — PA-GEO-05 held-out correspondence labels (definitions version 1)

You are labelling City of Kitchener Active Transportation records against the
frozen OpenStreetMap (OSM) extract PathAble routes on. For each record you
decide which OSM elements represent the same physical facility.

You label correspondence only. You do not judge whether either source is right
about the facility, and you do not judge attribute values.

## What you have

- `records.txt` — one block per record: the City record's attributes; the
  nearest OSM road; the City records touching its ends; every OSM candidate way
  near it as `C<n> way/<id>` with distances and tags; and tagged OSM nodes
  within 8 m (`node/<id>`, distance, tags, the ways it is on).
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
perpendicular).

## correspondence

- `obvious_correspondence` — OSM represents the same physical facility, and you
  can name exactly which OSM elements, with no reasonable alternative.
  Closeness alone never qualifies: the element must be the same kind of
  facility in the same place — the same side of the road, the same crossing,
  the same stair.
- `ambiguous_correspondence` — OSM may represent it, but you cannot name the
  elements with confidence. Typical cases:
  - two OSM ways are equally plausible (parallel sidewalks; a sidewalk beside a
    cycle track at the same distance);
  - a City piece of a metre or two that OSM collapses into a junction of
    several ways, with no kerb node to say which;
  - OSM records the facility only as a tag on a road (`sidewalk=both`,
    `cycleway=lane`): cite the road, representation `road_attribute`.
- `no_correspondence` — nothing in OSM represents this facility: no way or node
  of the same kind within about 5 m. A road alone is not a correspondence for a
  sidewalk unless it carries a tag for it.
- `not_comparable` — the record cannot be judged (for example, a broken
  geometry).

## osm — the exact correspondence set

For an obvious correspondence, list every element; for an ambiguous one, list
the plausible alternatives (they are kept for the record, not scored).

- Cite every OSM way that carries the same facility over any part of the
  record. If OSM splits the facility into several ways, cite each one that
  carries part of it. Do not cite ways that only touch its ends.
- Cite a way even when it runs far beyond the record: OSM often draws one way
  where the City has several records.
- **Crossings:** cite the crossing way over the same road at the same place. If
  OSM has no crossing way there but has a crossing node (`highway=crossing`) on
  the road where the City's crossing is, cite the node.
- **Curb cuts** (records with `curbcut=Y`; usually a 1–3 m piece at a corner or
  at the end of a crossing):
  - cite the OSM kerb node (`barrier=kerb` or `kerb=*`) that marks this ramp's
    kerb, if one lies within about 2 m of the piece — only the node that marks
    this ramp, not the kerb on the far side of the road;
  - and cite every OSM way the piece lies along — most of the piece within
    about 2 m of the way and following it, such as the last metres of a
    sidewalk or the first metres of a crossing;
  - if OSM has neither — the piece sits where several ways meet at an untagged
    junction — the correspondence is ambiguous;
  - `curbcut=Y` says the City records a curb cut here. It does not say
    `kerb=lowered` or `kerb=flush`; do not judge the kerb value.
- **Stairs:** cite `highway=steps` ways. **Bridges, overpasses, underpasses,
  boardwalks:** cite the OSM ways that carry the same facility across the
  structure (usually tagged `bridge=*` or `tunnel=*`).
- Kerb nodes belong in the set only for curb-cut records.

## representation

- `separate_way` — only ways are cited.
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

1. A 3.3 m curb-cut piece lying along the last segment of an OSM sidewalk, from
   the corner to a `kerb=lowered` node where a marked crossing begins:
   `obvious_correspondence`, osm `["node/8905696991", "way/962754860"]`,
   `multiple`, `many_to_one` (the sidewalk also carries two City sidewalk
   records).
2. A 1.1 m curb-cut piece; OSM draws no stub but has a `kerb=lowered` node
   0.2 m away where the crossing leaves the corner (a second kerb node 1.8 m
   away marks the other crossing): `obvious_correspondence`, osm
   `["node/9160884963"]`, `node`, `one_to_one`.
3. A 1.1 m curb-cut piece where two OSM sidewalks and a marked crossing meet at
   one untagged junction, no kerb node: `ambiguous_correspondence`, osm lists
   the three ways, relationship `null`.
4. A sidewalk with an OSM sidewalk at a steady 0.7 m and an OSM cycleway 1.7 m
   away that is a different facility (the City's own cycle track):
   `obvious_correspondence`, osm the sidewalk only, `separate_way`,
   `many_to_one` (the sidewalk way carries other City records).
5. A trail whose east 70% lies on one OSM path and west end on another:
   `obvious_correspondence`, osm both ways, `separate_way`, `many_to_many`
   (one of them also continues over the City's next trail record).
6. A new sidewalk on the east side of a street; OSM has only the road (no
   sidewalk tags) and the west-side sidewalk 12 m away: `no_correspondence`,
   osm `[]`, `none`.
7. Stairs with OSM `highway=steps` within 0.6 m and the same length:
   `obvious_correspondence`, `separate_way`, `one_to_one`.
8. A crosswalk with an OSM crossing way of the same road within 1.4 m, while
   the neighbouring OSM crossings cross a different street:
   `obvious_correspondence`, osm the crossing way only, `one_to_one`.

## Output

Write a JSON file in exactly this shape (every record in your pack, in the
order of `records.txt`):

```json
{
  "kitchener_geo05_labels_version": 1,
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

- an obvious correspondence lists at least one element, a relationship, and the
  representation that matches its elements (ways only → `separate_way`, nodes
  only → `node`, both → `multiple`);
- anything else has `"relationship": null`;
- `no_correspondence` has `"osm": []` and `"representation": "none"`.

## Rules of the task

- Use only the files in your pack folder. Do not open any other file in the
  repository or on disk, do not look for other labels, and do not run the
  project's code except the validator command you were given.
- Label every record. When unsure between obvious and ambiguous, choose
  ambiguous and say why.
