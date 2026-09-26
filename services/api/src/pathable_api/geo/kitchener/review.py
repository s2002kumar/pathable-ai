"""A static review page for the lineage study: one map and one set of tables per record.

The maps are inline SVG drawn from the two datasets themselves — the Kitchener
record, its Kitchener neighbours, the frozen OSM ways and tagged nodes — in the
source's metres. There is no basemap and no imagery, so nothing copyrighted is
embedded and the page renders offline. Candidates are numbered in the study's
display order, which is not a ranking of likelihood.

A blind page leaves out every label and every lineage finding, for the
repeat review.
"""

from __future__ import annotations

import html
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import shapely
from shapely.geometry import LineString, MultiLineString
from shapely.geometry.base import BaseGeometry

from pathable_api.geo.kitchener.correspondence import (
    KitchenerIndex,
    OsmIndex,
    ends,
    osm_class,
    parts,
)

SIZE_PX = 520
MIN_WINDOW_M = 70.0
MARGIN_M = 20.0
PALETTE = ("#1d4ed8", "#059669", "#7c3aed", "#b45309", "#0e7490", "#be185d", "#4d7c0f", "#9333ea")

_STYLE = """
body{font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;margin:0;color:#1f2933;background:#fff}
header,main,footer{max-width:1180px;margin:0 auto;padding:16px}
h1{font-size:22px;margin:8px 0}h2{font-size:17px;margin:0 0 8px}
table{border-collapse:collapse;font-size:12px;margin:6px 0 12px;width:100%}
th,td{border:1px solid #d9dee3;padding:3px 5px;text-align:left;vertical-align:top}
th{background:#f3f5f7;font-weight:600}
.record{border-top:3px solid #1f2933;padding:14px 0 18px;margin-top:10px}
.grid{display:flex;flex-wrap:wrap;gap:16px}
.map{flex:0 0 auto;align-self:flex-start}.tables{flex:1 1 520px;min-width:0;overflow-x:auto}
.tag{font-family:ui-monospace,Consolas,monospace;font-size:11px}
.muted{color:#66727f}.label{font-weight:600}
.legend span{display:inline-block;margin-right:14px}
.swatch{display:inline-block;width:18px;height:4px;vertical-align:middle;margin-right:4px}
details{margin:6px 0}summary{cursor:pointer;font-weight:600}
"""


def render_review(
    document: Mapping[str, Any],
    kitchener: KitchenerIndex,
    osm: OsmIndex,
    *,
    blind: bool = False,
    only: Iterable[int] | None = None,
) -> str:
    wanted = set(only) if only is not None else None
    records = [r for r in document["records"] if wanted is None or r["activetransportid"] in wanted]
    body = [
        _header(document, blind=blind, count=len(records)),
        '<main id="records">',
        *(_record(r, document, kitchener, osm, blind=blind) for r in records),
        "</main>",
        _footer(document),
    ]
    title = "Kitchener and OSM lineage review" + (" (blind)" if blind else "")
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head><body>"
        + "\n".join(body)
        + "</body></html>\n"
    )


def _header(document: Mapping[str, Any], *, blind: bool, count: int) -> str:
    inputs = document["inputs"]
    sample = inputs["kitchener"]["sample"]
    dataset = inputs["osm_frozen"]["dataset"]
    definitions = document["definitions"]
    rows = [
        ("Kitchener snapshot", inputs["kitchener"]["snapshot_id"]),
        ("Normalized GeoParquet SHA-256", inputs["kitchener"]["normalized_sha256"]),
        ("Sample file SHA-256", sample["sha256"]),
        ("PathAble dataset", f"{dataset.get('dataset_id')} ({dataset.get('source_timestamp')})"),
        ("Source extract SHA-256", dataset.get("source_file_sha256")),
        ("Frozen study extract SHA-256", inputs["osm_frozen"]["extract_sha256"]),
    ]
    history = inputs.get("osm_history")
    if history and not blind:
        rows.append(("OSM history", _history_line(history)))
    legend = (
        '<p class="legend">'
        '<span><i class="swatch" style="background:#d62828;opacity:.55"></i>Kitchener record</span>'
        '<span><i class="swatch" style="background:#f4a261"></i>other Kitchener records</span>'
        '<span><i class="swatch" style="background:#c8ccd0;height:6px"></i>OSM road</span>'
        '<span><i class="swatch" style="background:#6b7280;height:2px"></i>other OSM way</span>'
        '<span><i class="swatch" style="background:#1d4ed8"></i>numbered OSM candidate</span>'
        "<span>▲ OSM kerb node · ● OSM crossing node · ■ other tagged node</span></p>"
    )
    definition_html = "".join(
        f"<details><summary>{html.escape(group)}</summary>{_definition_table(items)}</details>"
        for group, items in definitions.items()
    )
    note = (
        "<p><strong>Blind page:</strong> no labels, no lineage and no history are shown.</p>"
        if blind
        else ""
    )
    return (
        "<header><h1>Kitchener and OpenStreetMap: geometry and lineage review</h1>"
        f"<p>{count} records from the PA-GEO-03 sample, drawn in the City's own NAD83 / UTM 17N "
        "metres against the frozen OSM extract PathAble's routing dataset was built from. No "
        "basemap, no imagery. Candidate numbers are the study's display order, not a ranking. "
        "Nothing here is a match decision or a routing input.</p>"
        f"{note}{_table(['Input', 'Identity'], rows)}{legend}{definition_html}</header>"
    )


def _history_line(history: Mapping[str, Any]) -> str:
    ohsome = history.get("ohsome", {})
    dump = history.get("changeset_dump", {})
    return (
        f"ohsome API {ohsome.get('api_version')} to {ohsome.get('temporal_extent', {}).get('to')}; "
        f"changesets from {dump.get('file')} ({dump.get('header', {}).get('timestamp')})"
    )


def _definition_table(items: Mapping[str, str]) -> str:
    return _table(["Label", "Definition"], list(items.items()))


def _footer(document: Mapping[str, Any]) -> str:
    attribution = document["attribution"]
    return (
        "<footer><p class=muted>"
        + "<br>".join(html.escape(text) for text in attribution.values())
        + "</p></footer>"
    )


# ---------------------------------------------------------------------------
# One record
# ---------------------------------------------------------------------------


def _record(
    record: Mapping[str, Any],
    document: Mapping[str, Any],
    kitchener: KitchenerIndex,
    osm: OsmIndex,
    *,
    blind: bool,
) -> str:
    record_id = record["activetransportid"]
    k = record["kitchener"]
    title = (
        f"{record_id} · {k['subcategory']} · {record['family']} · stratum {record['stratum']} "
        f"#{record['rank_in_stratum']}"
    )
    sections = [
        _kitchener_table(record),
        _road_table(record),
        _candidate_table(record, document["osm_elements"]),
        _nodes_table(record),
    ]
    if not blind:
        sections.append(_labels_block(record))
        sections.append(_attributes_block(record))
        sections.append(_lineage_block(record))
    return (
        f'<section class="record" id="r-{record_id}"><h2>{html.escape(title)}</h2>'
        f'<div class="grid"><div class="map" id="map-{record_id}">'
        f"{record_svg(record, kitchener, osm)}</div>"
        f'<div class="tables">{"".join(sections)}</div></div></section>'
    )


def _kitchener_table(record: Mapping[str, Any]) -> str:
    k = record["kitchener"]
    rows = [
        ("category / subcategory", f"{k['category']} / {k['subcategory']}"),
        ("physical class / role", f"{k['physical_class']} / {k['network_role']}"),
        ("feature type", k["feature_type"]),
        ("surface material", f"{k['surface_material']} ({k['state_surface_material']})"),
        ("width m", f"{k['width_m']} ({k['state_width_m']})"),
        ("curb cut", f"{k['curbcut']} ({k['state_curbcut']})"),
        ("railing", f"{k['railing']} ({k['state_railing']})"),
        ("surface condition", f"{k['surface_condition']} ({k['state_surface_condition']})"),
        ("street / side", f"{k['street']} / {k['roadsegment_side']}"),
        ("source class / year", f"{k['source_class']} / {k['source_year']}"),
        ("created / source date", f"{k['create_date']} / {k['source_date']}"),
        ("length m / parts", f"{k['length_m']} / {k['part_count']}"),
        ("touching Kitchener records at each end", json.dumps(record["kitchener_end_neighbours"])),
    ]
    if k.get("restricted_lineage"):
        rows.append(("lineage", k["restricted_lineage"]))
    return "<h3>Kitchener</h3>" + _table(["Field", "Value"], rows)


def _road_table(record: Mapping[str, Any]) -> str:
    road = record["road"]
    rows = [
        ("nearest OSM road", f"{road['osm']} {road['name']} ({road['highway']})"),
        ("distance m / record side", f"{road['distance_m']} / {road['record_side']}"),
        ("sidewalk tags on road", json.dumps(road["sidewalk_tags"])),
        ("street name matches Kitchener STREET", road["street_matches_kitchener_street"]),
        ("record crosses that road", road["record_crosses_road"]),
    ]
    return "<h3>Road context</h3>" + _table(["", ""], rows)


def _candidate_table(record: Mapping[str, Any], elements: Mapping[str, Any]) -> str:
    rows = []
    for number, candidate in enumerate(record["candidates"], start=1):
        m = candidate["metrics"]
        element = elements[candidate["osm"]]
        rows.append(
            (
                f"C{number}",
                candidate["osm"],
                f"{candidate['osm_class']} ({candidate['class_compatibility']})",
                m["min_distance_m"],
                m["max_offset_m"],
                m["median_offset_m"],
                f"{m['overlap_2m']:.2f} / {m['overlap_5m']:.2f}",
                f"{m['osm_share_within_5m']:.2f}",
                m["orientation_deg"],
                m["nearest_endpoint_pair_m"],
                _side(candidate),
                len(candidate["kitchener_records_along"]),
                _tags(element["tags"]),
            )
        )
    headers = [
        "#",
        "OSM",
        "class (fit)",
        "min m",
        "worst m",
        "median m",
        "overlap 2/5 m",
        "OSM within 5 m",
        "angle °",
        "end pair m",
        "road/side",
        "K along",
        "tags",
    ]
    return f"<h3>Candidates within 25 m ({record['candidate_count']})</h3>" + _table(headers, rows)


def _side(candidate: Mapping[str, Any]) -> str:
    if candidate["is_record_road"]:
        return "is the road"
    road = {True: "same road", False: "other road", None: "?"}[candidate["same_road_as_record"]]
    side = {True: "same side", False: "other side", None: "side ?"}[
        candidate["same_side_as_record"]
    ]
    crosses = " · crosses it" if candidate["crosses_record_road"] else ""
    return f"{road}, {side}{crosses}"


def _nodes_table(record: Mapping[str, Any]) -> str:
    if not record["nodes_near"]:
        return "<h3>Tagged OSM nodes within 8 m</h3><p class=muted>none</p>"
    rows = [
        (n["osm"], n["distance_m"], _tags(n["osm_tags"]), ", ".join(n["on_ways"]))
        for n in record["nodes_near"]
    ]
    return "<h3>Tagged OSM nodes within 8 m</h3>" + _table(["OSM", "m", "tags", "on ways"], rows)


def _labels_block(record: Mapping[str, Any]) -> str:
    labels = record.get("labels")
    if not labels:
        return "<h3>Labels</h3><p class=muted>not labelled</p>"
    rows = [(k, v) for k, v in labels.items() if k != "activetransportid"]
    repeat = record.get("repeat_labels")
    out = "<h3>Labels</h3>" + _table(["", "primary"], rows)
    if repeat:
        out += "<h4>Repeat review</h4>" + _table(
            ["", "repeat"], [(k, v) for k, v in repeat.items() if k != "activetransportid"]
        )
    facts = record.get("topology_facts")
    if facts:
        out += (
            "<h4>Topology facts</h4><pre class=tag>"
            + html.escape(json.dumps(facts, indent=1))
            + "</pre>"
        )
    return out


def _attributes_block(record: Mapping[str, Any]) -> str:
    attributes = record.get("attributes")
    if not attributes:
        return ""
    return (
        "<h3>Attribute comparison</h3><pre class=tag>"
        + html.escape(json.dumps(attributes, indent=1, ensure_ascii=False))
        + "</pre>"
    )


def _lineage_block(record: Mapping[str, Any]) -> str:
    lineage = record.get("lineage")
    if not lineage or not lineage.get("ways"):
        return ""
    parts_html = [f"<h3>Geometry lineage: {html.escape(str(lineage.get('geometry')))}</h3>"]
    for way, finding in lineage["ways"].items():
        steps = finding.get("steps") or []
        rows = [
            (
                s["timestamp"][:10],
                s["changeset"],
                s["kind"],
                "; ".join(f"{e['signal']} ({e['where']}: {e['value']})" for e in s["evidence"])
                or "no source stated",
            )
            for s in steps
        ]
        parts_html.append(
            f"<p><span class=label>{html.escape(way)}</span>: {html.escape(finding['label'])} — "
            f"{html.escape('; '.join(finding.get('reasons', [])))}"
            + (
                f" <span class=muted>({html.escape('; '.join(finding.get('notes', [])))})</span>"
                if finding.get("notes")
                else ""
            )
            + "</p>"
        )
        if rows:
            parts_html.append(_table(["date", "changeset", "kind", "stated source"], rows))
    return "".join(parts_html)


def _tags(tags: Mapping[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in sorted(tags.items()))


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    head = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(_cell(value))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


# ---------------------------------------------------------------------------
# The map
# ---------------------------------------------------------------------------


def window_for(geometry: BaseGeometry) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = geometry.bounds
    side = max(maxx - minx, maxy - miny) + 2 * MARGIN_M
    side = max(side, MIN_WINDOW_M)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    return cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2


def record_svg(record: Mapping[str, Any], kitchener: KitchenerIndex, osm: OsmIndex) -> str:
    record_id = record["activetransportid"]
    geometry = kitchener.features[record_id].geometry
    window = window_for(geometry)
    box = shapely.box(*window)
    scale = SIZE_PX / (window[2] - window[0])

    def px(x: float, y: float) -> tuple[float, float]:
        return (x - window[0]) * scale, (window[3] - y) * scale

    def xy(x: float, y: float) -> str:
        a, b = px(x, y)
        return f"{a:.1f},{b:.1f}"

    def path(line: BaseGeometry) -> str:
        return " ".join("M" + " L".join(xy(x, y) for x, y in part.coords) for part in _lines(line))

    layers: list[str] = [f'<rect width="{SIZE_PX}" height="{SIZE_PX}" fill="#fbfbf9"/>']
    numbers = {c["osm"]: n for n, c in enumerate(record["candidates"], start=1)}
    ways = sorted(osm.way_ids[int(i)] for i in osm.tree.query(box, predicate="intersects"))
    for way_id in ways:
        if f"way/{way_id}" in numbers:
            continue
        klass = osm_class(osm.extract.ways[way_id].tags)
        clipped = osm.lines[way_id].intersection(box)
        if clipped.is_empty:
            continue
        stroke, width = {
            "road": ("#c8ccd0", 7.0),
            "service": ("#dde0e3", 4.0),
        }.get(klass, ("#6b7280", 1.4))
        layers.append(
            f'<path d="{path(clipped)}" stroke="{stroke}" stroke-width="{width}" fill="none" '
            'stroke-linecap="round"/>'
        )
    for other in kitchener.near(box, 0.0):
        if other == record_id:
            continue
        feature = kitchener.features[other]
        clipped = feature.geometry.intersection(box)
        if clipped.is_empty:
            continue
        dash = ' stroke-dasharray="4 3"' if feature.physical_class == "virtual_link" else ""
        layers.append(
            f'<path d="{path(clipped)}" stroke="#f4a261" stroke-width="2.2" fill="none"{dash}/>'
        )
    layers.append(
        f'<path d="{path(geometry.intersection(box))}" stroke="#d62828" stroke-width="8" '
        'stroke-opacity=".45" fill="none" stroke-linecap="round"/>'
    )
    for end in ends(geometry):
        if box.contains(end):
            ex, ey = px(end.x, end.y)
            layers.append(
                f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4" fill="none" stroke="#d62828" '
                'stroke-width="1.5"/>'
            )
    labels: list[str] = []
    # Nearest candidates last, so they draw on top.
    for candidate in reversed(record["candidates"]):
        number = numbers[candidate["osm"]]
        way_id = int(candidate["osm"].split("/")[1])
        clipped = osm.lines[way_id].intersection(box)
        if clipped.is_empty:
            continue
        colour = PALETTE[(number - 1) % len(PALETTE)]
        width = 4.5 if osm_class(osm.extract.ways[way_id].tags) == "road" else 2.6
        layers.append(
            f'<path d="{path(clipped)}" stroke="{colour}" stroke-width="{width}" fill="none" '
            'stroke-opacity=".9"/>'
        )
        # Spread labels along their lines rather than piling them up at the record.
        longest = max(_lines(clipped), key=lambda line: line.length)
        anchor = longest.interpolate(0.15 + 0.7 * ((number * 0.618) % 1.0), normalized=True)
        lx, ly = px(anchor.x, anchor.y)
        labels.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" dx="4" dy="-4" font-size="12" font-weight="700" '
            f'fill="{colour}" stroke="#fff" stroke-width="3" paint-order="stroke">C{number}</text>'
        )
    named: set[str] = set()
    for way_id in ways:
        tags = osm.extract.ways[way_id].tags
        name = tags.get("name")
        if osm_class(tags) != "road" or not name or name in named:
            continue
        clipped = osm.lines[way_id].intersection(box)
        if clipped.is_empty:
            continue
        named.add(name)
        anchor = max(_lines(clipped), key=lambda line: line.length).interpolate(
            0.5, normalized=True
        )
        nx, ny = px(anchor.x, anchor.y)
        labels.append(
            f'<text x="{nx:.1f}" y="{ny:.1f}" dy="14" font-size="11" font-style="italic" '
            f'fill="#4b5563" stroke="#fff" stroke-width="3" paint-order="stroke">'
            f"{html.escape(name)}</text>"
        )
    for node_id in sorted(osm.fact_ids[int(i)] for i in osm.fact_tree.query(box)):
        point = osm.fact_points[node_id]
        if not box.contains(point):
            continue
        tags = osm.extract.nodes[node_id].tags
        x, y = px(point.x, point.y)
        if "kerb" in tags:
            layers.append(
                f'<path d="M{x:.1f},{y - 6:.1f} L{x + 5:.1f},{y + 4:.1f} L{x - 5:.1f},{y + 4:.1f} Z" '
                'fill="#f59e0b" stroke="#78350f" stroke-width="1"/>'
                f'<text x="{x + 6:.1f}" y="{y + 12:.1f}" font-size="10" fill="#78350f">'
                f"{html.escape(tags['kerb'])}</text>"
            )
        elif tags.get("highway") == "crossing" or "crossing" in tags:
            layers.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#2563eb" stroke="#fff" stroke-width="1"/>'
            )
        else:
            layers.append(
                f'<rect x="{x - 3:.1f}" y="{y - 3:.1f}" width="6" height="6" fill="#6b7280"/>'
            )
    layers.extend(labels)
    layers.append(_scale_bar(scale))
    layers.append(
        f'<text x="{SIZE_PX - 18}" y="20" font-size="13" font-weight="700" fill="#1f2933">N</text>'
        f'<path d="M{SIZE_PX - 14},24 L{SIZE_PX - 14},40" stroke="#1f2933" stroke-width="2"/>'
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE_PX}" height="{SIZE_PX}" '
        f'viewBox="0 0 {SIZE_PX} {SIZE_PX}" role="img" aria-label="record {record_id}">'
        + "".join(layers)
        + "</svg>"
    )


def _scale_bar(scale: float) -> str:
    metres = 10.0 if SIZE_PX / scale < 150 else 25.0 if SIZE_PX / scale < 400 else 100.0
    length = metres * scale
    y = SIZE_PX - 16
    return (
        f'<path d="M12,{y} L{12 + length:.1f},{y}" stroke="#1f2933" stroke-width="3"/>'
        f'<text x="12" y="{y - 6}" font-size="11" fill="#1f2933">{metres:g} m</text>'
    )


def _lines(geometry: BaseGeometry) -> list[LineString]:
    if isinstance(geometry, LineString | MultiLineString):
        return parts(geometry)
    if hasattr(geometry, "geoms"):
        return [g for g in geometry.geoms if isinstance(g, LineString) and not g.is_empty]
    return []
