"""The blind review material for PA-GEO-08's held-out records.

PA-GEO-05's review material (:mod:`holdout_review`), with definitions version 2
and a text digest that shows two more things the new definitions turn on:

- **every OSM ``highway=steps`` way within the candidate radius**, however far,
  so that steps drawn a few metres from a City stair are never hidden;
- **how the listed candidates connect** — which of them share a node, and
  whether at an end or mid-way — because a corner or junction piece is judged
  by what meets where.

As before: no stratum, no matcher decision or score, no label, candidates in
OSM-id order.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pathable_api.geo.kitchener.correspondence import OsmIndex
from pathable_api.geo.kitchener.holdout_review import blind_document
from pathable_api.geo.kitchener.matcher_v2_labels import DEFINITIONS, LABELS_VERSION

PAGE_TITLE = "Kitchener and OpenStreetMap: PA-GEO-08 held-out correspondence review (blind)"
#: Candidates this near, or overlapping the record within 5 m, are listed; steps
#: and ways under construction are listed at any distance within the radius.
DIGEST_NEAR_M = 15.0
ALWAYS_LISTED = frozenset({"steps", "construction"})


def blind(study: Mapping[str, Any]) -> dict[str, Any]:
    """PA-GEO-05's blind document, with definitions version 2."""
    document = blind_document(study)
    document["definitions"] = {"version": LABELS_VERSION, **copy.deepcopy(DEFINITIONS)}
    return document


def retitle(page: str) -> str:
    return page.replace(
        "<title>Kitchener and OSM lineage review (blind)</title>", f"<title>{PAGE_TITLE}</title>"
    ).replace(
        "<h1>Kitchener and OpenStreetMap: geometry and lineage review</h1>",
        f"<h1>{PAGE_TITLE}</h1>",
    )


def _tags(tags: Mapping[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in sorted(tags.items()))


def _listed(candidate: Mapping[str, Any], element: Mapping[str, Any]) -> bool:
    metrics = candidate["metrics"]
    if element["tags"].get("highway") in ALWAYS_LISTED:
        return True
    return not (metrics["min_distance_m"] > DIGEST_NEAR_M and metrics["overlap_5m"] == 0)


def connections(listed: Sequence[tuple[int, int]], osm: OsmIndex) -> dict[int, list[str]]:
    """For each listed (number, way id): the other listed candidates it shares a node with."""
    found: dict[int, list[str]] = {}
    for number, way_id in listed:
        refs = osm.extract.ways[way_id].refs
        ends = {refs[0], refs[-1]}
        parts = []
        for other_number, other_id in listed:
            if other_id == way_id:
                continue
            other_refs = osm.extract.ways[other_id].refs
            shared = set(refs) & set(other_refs)
            if not shared:
                continue
            here = "end" if shared & ends else "mid-way"
            there = "end" if shared & {other_refs[0], other_refs[-1]} else "mid-way"
            parts.append(f"C{other_number} (at this way's {here}, that way's {there})")
        found[number] = parts
    return found


def digest(
    document: Mapping[str, Any],
    describe: Callable[[Sequence[int]], list[str]],
    osm: OsmIndex,
    ids: Sequence[int] | None = None,
) -> str:
    """The page as text, one block per record, candidates numbered as the page numbers them."""
    elements = document["osm_elements"]
    wanted = None if ids is None else set(ids)
    lines: list[str] = []
    for record in document["records"]:
        if wanted is not None and record["activetransportid"] not in wanted:
            continue
        k = record["kitchener"]
        lines.append(
            f"=== RECORD {record['activetransportid']} | {k['category']} / {k['subcategory']}"
        )
        lines.append(
            f"City: feature_type={k['feature_type']} curbcut={k['curbcut']} "
            f"surface={k['surface_material']} ({k['state_surface_material']}) "
            f"railing={k['railing']} street={k['street']} side={k['roadsegment_side']} "
            f"length={k['length_m']} m parts={k['part_count']} role={k['network_role']}"
        )
        road = record["road"]
        lines.append(
            f"Nearest OSM road: {road['osm']} '{road['name']}' ({road['highway']}), "
            f"{road['distance_m']} m, record side {road['record_side']}, record crosses it: "
            f"{road['record_crosses_road']}, road sidewalk tags {road['sidewalk_tags']}"
        )
        for end, touching in enumerate(record["kitchener_end_neighbours"], start=1):
            lines.append(
                f"City records touching end {end}: " + ("; ".join(describe(touching)) or "none")
            )
        shown = [
            (number, candidate)
            for number, candidate in enumerate(record["candidates"], start=1)
            if _listed(candidate, elements[candidate["osm"]])
        ]
        joined = connections([(number, int(c["osm"].split("/")[1])) for number, c in shown], osm)
        for number, candidate in shown:
            metrics = candidate["metrics"]
            element = elements[candidate["osm"]]
            if candidate["is_record_road"]:
                where = "the record's road"
            else:
                where = (
                    f"same road as record: {candidate['same_road_as_record']}, same side: "
                    f"{candidate['same_side_as_record']}, crosses the record's road: "
                    f"{candidate['crosses_record_road']}"
                )
            lines.append(
                f"  C{number} {candidate['osm']} class={candidate['osm_class']} | closest "
                f"{metrics['min_distance_m']} m, worst {metrics['max_offset_m']} m, median "
                f"{metrics['median_offset_m']} m, record within 2/5 m: {metrics['overlap_2m']}/"
                f"{metrics['overlap_5m']}, way within 5 m of record: "
                f"{metrics['osm_share_within_5m']}, angle {metrics['orientation_deg']} deg, "
                f"record ends to way {metrics['end_distances_m']} m, way length "
                f"{metrics['osm_length_m']} m | {where}"
            )
            lines.append(f"      tags: {_tags(element['tags'])}")
            lines.append(
                "      connects to: " + ("; ".join(joined[number]) or "no other listed candidate")
            )
            along = [
                r for r in candidate["kitchener_records_along"] if r != record["activetransportid"]
            ]
            if along and metrics["min_distance_m"] <= 5:
                lines.append(
                    "      other City records along this way: " + "; ".join(describe(along))
                )
        for node in record["nodes_near"]:
            lines.append(
                f"  {node['osm']} {node['distance_m']} m: {_tags(node['osm_tags'])} "
                f"(on {', '.join(node['on_ways']) or 'no way'})"
            )
        lines.append("")
    return "\n".join(lines)


def elements_by_record(document: Mapping[str, Any]) -> dict[int, list[str]]:
    """Every element a label may cite for each record: the listed ways and the nodes near it."""
    elements = document["osm_elements"]
    return {
        record["activetransportid"]: [
            c["osm"] for c in record["candidates"] if _listed(c, elements[c["osm"]])
        ]
        + [n["osm"] for n in record["nodes_near"]]
        for record in document["records"]
    }
