"""The blind review pack for PA-GEO-05's held-out records.

The same principles as PA-GEO-04's review page, and two more, because this
time a matcher's quality will be measured against what the reviewer decides:

- **nothing that hints at the answer** — no stratum (its names say "parallel
  ways" or "no OSM pedestrian way"), no matcher decision or score, no label;
- **a neutral order** — candidates are numbered in OSM-id order, not by any
  distance a matcher might also rank by, so "C1" means nothing.

The page and the text digest carry the same numbering. Both are built from
PA-GEO-04's study analysis of the held-out sample: the frozen OSM extract, every
way within 25 m, tagged nodes within 8 m, the City's own attributes.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pathable_api.geo.kitchener.benchmark_labels import DEFINITIONS, LABELS_VERSION

#: What the reviewer is told the page is.
PAGE_TITLE = "Kitchener and OpenStreetMap: PA-GEO-05 held-out correspondence review (blind)"
_DIGEST_NEAR_M = 15.0


def _element_order(element: str) -> tuple[str, int]:
    kind, _, number = element.partition("/")
    return kind, int(number)


def blind_document(study: Mapping[str, Any]) -> dict[str, Any]:
    """The study analysis with strata masked, candidates in OSM-id order, these definitions."""
    document = copy.deepcopy(dict(study))
    records = sorted(document["records"], key=lambda r: r["activetransportid"])
    for number, record in enumerate(records, start=1):
        record["stratum"] = "held-out"
        record["rank_in_stratum"] = number
        record["candidates"] = sorted(record["candidates"], key=lambda c: _element_order(c["osm"]))
    document["records"] = records
    document["definitions"] = {"version": LABELS_VERSION, **DEFINITIONS}
    document["scope"] = {
        "what_this_shows": [
            "Each held-out City record drawn against the frozen OSM extract PathAble routes on, "
            "with every OSM way within 25 m numbered in OSM-id order, for a blind reviewer to "
            "label which OSM elements represent the same facility.",
        ],
        "what_this_does_not_show": [
            "Any matcher's decision or score, any label, or the stratum a record was drawn from.",
            "Anything PathAble routes on: no City value reaches routing.",
        ],
    }
    return document


def retitle(page: str) -> str:
    """PA-GEO-04's renderer, titled for this review."""
    return page.replace(
        "<title>Kitchener and OSM lineage review (blind)</title>", f"<title>{PAGE_TITLE}</title>"
    ).replace(
        "<h1>Kitchener and OpenStreetMap: geometry and lineage review</h1>",
        f"<h1>{PAGE_TITLE}</h1>",
    )


def _tags(tags: Mapping[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in sorted(tags.items()))


def digest(
    document: Mapping[str, Any],
    describe: Callable[[Sequence[int]], list[str]],
) -> str:
    """The page as text, one block per record, candidates as the page numbers them.

    ``describe`` turns City record ids into one-line descriptions of them.
    """
    elements = document["osm_elements"]
    lines: list[str] = []
    for record in document["records"]:
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
        for number, candidate in enumerate(record["candidates"], start=1):
            metrics = candidate["metrics"]
            if metrics["min_distance_m"] > _DIGEST_NEAR_M and metrics["overlap_5m"] == 0:
                continue
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
