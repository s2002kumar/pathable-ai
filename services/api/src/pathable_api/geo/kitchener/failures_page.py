"""A static page of every held-out record the matcher got wrong or abstained on.

One map per record, drawn like the review page's (no basemap, no imagery): the
City record in red, what the labeller named in green, what the matcher named
dashed in purple, everything else in grey. Beside it, the label with its note,
the decision with the rule and signals that made it, and the cause found on
inspection.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping
from typing import Any

import shapely

from pathable_api.geo.kitchener.correspondence import KitchenerIndex, OsmIndex, osm_class
from pathable_api.geo.kitchener.review import (
    _STYLE,
    SIZE_PX,
    _lines,
    _scale_bar,
    _table,
    window_for,
)

LABELLED = "#059669"
DECIDED = "#7c3aed"
RECORD = "#d62828"


def render_failures(
    report: Mapping[str, Any],
    kitchener: KitchenerIndex,
    osm: OsmIndex,
    attribution: Mapping[str, str],
) -> str:
    holdout = report["holdout"]
    analysis = holdout["failure_analysis"]
    failures = analysis["records"]
    level = holdout["matcher"]["records_level"]
    header = (
        "<header><h1>PA-GEO-05 held-out failures</h1>"
        f"<p>Every one of the {len(failures)} held-out records (of {holdout['records']}) where "
        "the frozen matcher's decision was not the labelled one: a wrong or partial set, a match "
        "where OSM has nothing or where the labeller could not name the elements, an abstention, "
        f"or a miss. The matcher made {level['exact_set_agreement']} exact matches. Labels are AI "
        "labels made blind before the evaluation, not human ground truth. Decisions "
        f"<span class=tag>{html.escape(holdout['decisions_sha256'][:16])}</span>, policy "
        f"<span class=tag>{html.escape(report['policy']['version'])}</span>.</p>"
        '<p class="legend">'
        f'<span><i class="swatch" style="background:{RECORD};opacity:.5"></i>City record</span>'
        f'<span><i class="swatch" style="background:{LABELLED}"></i>labelled OSM</span>'
        f'<span><i class="swatch" style="background:{DECIDED}"></i>matcher (dashed)</span>'
        '<span><i class="swatch" style="background:#f4a261"></i>other City records</span>'
        '<span><i class="swatch" style="background:#9ca3af"></i>other OSM</span>'
        "</p>"
        + _table(
            ["outcome", "records"],
            sorted(analysis["by_outcome"].items()),
        )
        + (
            _table(["cause", "records", "meaning"], _cause_rows(analysis))
            if analysis.get("categories")
            else ""
        )
        + "</header>"
    )
    body = "".join(_failure(f, kitchener, osm) for f in failures)
    footer = (
        '<footer class="muted"><p>'
        + "<br>".join(html.escape(text) for text in attribution.values())
        + "</p></footer>"
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>PA-GEO-05 held-out failures</title><style>{_STYLE}</style></head><body>"
        + header
        + f'<main id="records">{body}</main>'
        + footer
        + "</body></html>\n"
    )


def _cause_rows(analysis: Mapping[str, Any]) -> list[tuple[str, int, str]]:
    return [
        (name, analysis["by_cause"].get(name, 0), meaning)
        for name, meaning in analysis["categories"].items()
    ]


def _failure(failure: Mapping[str, Any], kitchener: KitchenerIndex, osm: OsmIndex) -> str:
    record_id = failure["activetransportid"]
    label = failure["label"]
    decision = failure["decision"]
    cause = failure.get("cause")
    labelled = set(label["osm"]) if label["correspondence"] == "obvious_correspondence" else set()
    shown = set(label["osm"]) - labelled
    decided = (
        {t["element"] for t in decision["targets"]} if decision["state"] == "matched" else set()
    )
    elements = sorted(set(label["osm"]) | decided)
    rows = [
        (
            e,
            "yes" if e in labelled else "named, ambiguous" if e in shown else "no",
            "yes" if e in decided else "no",
            _element_tags(e, osm),
        )
        for e in elements
    ]
    return (
        f'<section class="record" id="r{record_id}"><h2>{record_id} · '
        f"{html.escape(failure['outcome'])} · {html.escape(str(failure['stratum']))}</h2>"
        '<div class="grid"><div class="map">'
        + _svg(record_id, labelled | shown, decided, kitchener, osm)
        + '</div><div class="tables">'
        + _table(
            ["family", "classes", "length", "labelled by"],
            [
                (
                    failure["family"],
                    ", ".join(failure["classes"]),
                    f"{failure['length_m']} m",
                    failure["labelled_by"],
                )
            ],
        )
        + _table(
            ["label", "relationship", "representation", "note"],
            [
                (
                    label["correspondence"],
                    label["relationship"],
                    label["representation"],
                    label["note"],
                )
            ],
        )
        + _table(
            ["matcher", "rule", "relationship", "representation"],
            [
                (
                    decision["state"],
                    decision["rule"],
                    decision["relationship"],
                    decision["representation"],
                )
            ],
        )
        + _table(["OSM element", "labelled", "matched", "tags"], rows)
        + '<p class="tag">'
        + html.escape(json.dumps(decision["signals"], sort_keys=True))
        + "</p>"
        + (
            f'<p><span class="label">Cause: {html.escape(cause["cause"])}.</span> '
            f"{html.escape(cause['explanation'])}</p>"
            if cause
            else '<p class="muted">Cause not yet recorded.</p>'
        )
        + "</div></div></section>"
    )


def _element_tags(element: str, osm: OsmIndex) -> str:
    kind, _, number = element.partition("/")
    item = (
        osm.extract.ways.get(int(number)) if kind == "way" else osm.extract.nodes.get(int(number))
    )
    if item is None:
        return "not in the frozen extract"
    keep = (
        "highway",
        "footway",
        "crossing",
        "kerb",
        "barrier",
        "bridge",
        "tunnel",
        "surface",
        "name",
    )
    return "; ".join(f"{k}={v}" for k, v in sorted(item.tags.items()) if k in keep)


def _svg(
    record_id: int,
    labelled: set[str],
    decided: set[str],
    kitchener: KitchenerIndex,
    osm: OsmIndex,
) -> str:
    geometry = kitchener.features[record_id].geometry
    window = window_for(geometry)
    box = shapely.box(*window)
    scale = SIZE_PX / (window[2] - window[0])

    def xy(x: float, y: float) -> str:
        return f"{(x - window[0]) * scale:.1f},{(window[3] - y) * scale:.1f}"

    def path(line: Any) -> str:
        return " ".join("M" + " L".join(xy(x, y) for x, y in part.coords) for part in _lines(line))

    def stroke(line: Any, colour: str, width: float, extra: str = "") -> str:
        clipped = line.intersection(box)
        if clipped.is_empty or not _lines(clipped):
            return ""
        return (
            f'<path d="{path(clipped)}" stroke="{colour}" stroke-width="{width}" fill="none" '
            f'stroke-linecap="round"{extra}/>'
        )

    layers = [f'<rect width="{SIZE_PX}" height="{SIZE_PX}" fill="#fbfbf9"/>']
    ways = sorted(osm.way_ids[int(i)] for i in osm.tree.query(box, predicate="intersects"))
    for way_id in ways:
        klass = osm_class(osm.extract.ways[way_id].tags)
        colour, width = {"road": ("#d1d5db", 7.0), "service": ("#e5e7eb", 4.0)}.get(
            klass, ("#9ca3af", 1.4)
        )
        layers.append(stroke(osm.lines[way_id], colour, width))
    for other in kitchener.near(box, 0.0):
        if other != record_id:
            layers.append(stroke(kitchener.features[other].geometry, "#f4a261", 2.0))
    layers.append(stroke(geometry, RECORD, 8.0, ' stroke-opacity=".45"'))
    for element in sorted(labelled):
        if element.startswith("way/") and int(element[4:]) in osm.lines:
            layers.append(stroke(osm.lines[int(element[4:])], LABELLED, 4.0))
    for element in sorted(decided):
        if element.startswith("way/") and int(element[4:]) in osm.lines:
            layers.append(
                stroke(osm.lines[int(element[4:])], DECIDED, 2.4, ' stroke-dasharray="6 4"')
            )
    for node_id in sorted(osm.fact_ids[int(i)] for i in osm.fact_tree.query(box)):
        point = osm.fact_points[node_id]
        if not box.contains(point):
            continue
        cx, cy = xy(point.x, point.y).split(",")
        element = f"node/{node_id}"
        tags = osm.extract.nodes[node_id].tags
        fill = (
            "#f59e0b"
            if "kerb" in tags
            else "#2563eb"
            if "crossing" in tags or tags.get("highway") == "crossing"
            else "#6b7280"
        )
        layers.append(f'<circle cx="{cx}" cy="{cy}" r="3.5" fill="{fill}"/>')
        if element in labelled:
            layers.append(
                f'<circle cx="{cx}" cy="{cy}" r="8" fill="none" stroke="{LABELLED}" stroke-width="2.5"/>'
            )
        if element in decided:
            layers.append(
                f'<circle cx="{cx}" cy="{cy}" r="11" fill="none" stroke="{DECIDED}" '
                'stroke-width="2" stroke-dasharray="3 2"/>'
            )
    layers.append(_scale_bar(scale))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE_PX}" height="{SIZE_PX}" '
        f'viewBox="0 0 {SIZE_PX} {SIZE_PX}" role="img" aria-label="record {record_id}">'
        + "".join(layers)
        + "</svg>"
    )
