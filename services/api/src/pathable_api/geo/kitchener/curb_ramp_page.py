"""A static page of representative curb-ramp shadow route changes and rejected mappings, as plain SVG.

Engineering evidence, not interface: no map tiles, no imagery, only the routing
graph's own OSM-derived geometry. Every drawing carries the watermark. Each
route figure shows the baseline route, the shadow route and the crossing
segments the City's curb ramps replace an unknown kerb on. Each rejection
figure shows the named way extent and the routing segments around it, so a
reader can see why the mapping refused it.
"""

from __future__ import annotations

import html
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pathable_api.geo.kitchener.curb_ramp_shadow import Substitution
from pathable_api.geo.kitchener.curb_ramp_study import Result
from pathable_api.geo.kitchener.shadow_study import Category, Pair, chosen_route
from pathable_api.routing.profiles import MobilityProfile

WATERMARK = "RESEARCH COUNTERFACTUAL — NOT PRODUCTION ROUTING · UNVALIDATED MUNICIPAL ASSERTIONS"
PAGE_LIMIT = 8
_SIZE = 520
_PAD = 24
_SUBSTITUTED = "#0f766e"
_EXTENT = "#d97706"
_CROSSING = "#334155"
_CHAR_WIDTH = 6.2
_LINE_HEIGHT = 13.0

Coordinates = Sequence[tuple[float, float]]


@dataclass(frozen=True, slots=True)
class DrawnSegment:
    identity: str
    coordinates: tuple[tuple[float, float], ...]
    is_crossing: bool
    substituted: bool = False


@dataclass(frozen=True, slots=True)
class RejectedExample:
    """One candidate the mapping refused, with the geometry to show why."""

    record_id: int
    outcome: str
    rule: str
    record_length_m: float
    #: Each named extent, as lon/lat coordinates along its way.
    extents: tuple[tuple[str, tuple[tuple[float, float], ...]], ...]
    segments: tuple[DrawnSegment, ...] = field(default_factory=tuple)
    note: str = ""


def representatives(
    results: Sequence[Result], pairs: Mapping[tuple[str, str], Pair]
) -> list[Result]:
    """A deterministic handful: feasibility changes, the largest cost moves, then the smallest."""
    changed = [
        r for r in results if r.cause is not None and (r.journey.journey_id, r.profile_key) in pairs
    ]
    changed.sort(
        key=lambda r: (
            r.category is not Category.FEASIBILITY_CHANGED,
            -abs(float((r.cause or {}).get("cost_delta_m") or 0.0)),
            r.journey.journey_id,
            r.profile_key,
        )
    )
    chosen: list[Result] = []
    seen: set[str] = set()
    for r in changed:
        if r.journey.journey_id in seen:
            continue
        chosen.append(r)
        seen.add(r.journey.journey_id)
        if len(chosen) >= PAGE_LIMIT - 1:
            break
    # The smallest move, so the page shows both ends of the range.
    smallest = sorted(
        (r for r in changed if r.journey.journey_id not in seen),
        key=lambda r: (
            abs(float((r.cause or {}).get("cost_delta_m") or 0.0)),
            r.journey.journey_id,
        ),
    )
    if smallest:
        chosen.append(smallest[0])
    return chosen


def _projector(points: Coordinates) -> Any:
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    mid_lat = (min(lats) + max(lats)) / 2
    scale_x = math.cos(math.radians(mid_lat))
    width = max((max(lons) - min(lons)) * scale_x, 1e-9)
    height = max(max(lats) - min(lats), 1e-9)
    span = max(width, height)
    usable = _SIZE - 2 * _PAD

    def project(point: tuple[float, float]) -> tuple[float, float]:
        x = (point[0] - min(lons)) * scale_x / span * usable + _PAD
        y = _SIZE - ((point[1] - min(lats)) / span * usable + _PAD)
        return round(x, 1), round(y, 1)

    return project


def _polyline(points: Coordinates, project: Any, style: str) -> str:
    coords = " ".join(f"{x},{y}" for x, y in (project(p) for p in points))
    return f'<polyline points="{coords}" {style} fill="none"/>'


def _svg(layers: Sequence[str], label: str) -> str:
    return (
        f'<svg viewBox="0 0 {_SIZE} {_SIZE}" width="{_SIZE}" height="{_SIZE}" role="img" '
        f'aria-label="{html.escape(label)}">'
        f'<rect width="{_SIZE}" height="{_SIZE}" fill="#f8fafc"/>'
        f'<text x="{_PAD}" y="18" font-size="10" font-weight="700" fill="#b91c1c">'
        f"{html.escape(WATERMARK)}</text>" + "".join(layers) + "</svg>"
    )


def _label(
    x: float, y: float, text: str, colour: str, placed: list[tuple[float, float, float]]
) -> str:
    width = len(text) * _CHAR_WIDTH
    left = x + 6 if x + 6 + width <= _SIZE - 4 else max(4.0, x - 6 - width)
    top = y - 6
    if any(
        left < other_left + other_width
        and other_left < left + width
        and abs(top - other_top) < _LINE_HEIGHT
        for other_left, other_top, other_width in placed
    ):
        return ""
    placed.append((left, top, width))
    return (
        f'<text x="{left:.1f}" y="{top:.1f}" font-size="11" fill="{colour}" stroke="#f8fafc" '
        f'stroke-width="3" paint-order="stroke">{html.escape(text)}</text>'
    )


def _route_figure(
    result: Result,
    pair: Pair,
    profile: MobilityProfile,
    substitutions: Mapping[str, Substitution],
) -> str:
    base, _ = chosen_route(pair.base, profile)
    shadow, _ = chosen_route(pair.shadow, profile)
    routes = [r for r in (base, shadow) if r is not None]
    points = [p for route in routes for p in route.coordinates]
    project = _projector(points)
    layers = []
    if base is not None:
        layers.append(
            _polyline(
                base.coordinates,
                project,
                'stroke="#6b7280" stroke-width="4" stroke-dasharray="7 5"',
            )
        )
    if shadow is not None:
        layers.append(_polyline(shadow.coordinates, project, 'stroke="#1d4ed8" stroke-width="3"'))
    labels: list[str] = []
    placed: list[tuple[float, float, float]] = []
    drawn: set[str] = set()
    for route in routes:
        for segment in route.segments:
            item = substitutions.get(segment.edge_identity)
            if item is None or segment.edge_identity in drawn:
                continue
            drawn.add(segment.edge_identity)
            layers.append(
                _polyline(
                    segment.coordinates,
                    project,
                    f'stroke="{_SUBSTITUTED}" stroke-width="8" stroke-opacity="0.85"',
                )
            )
            (x1, y1), (x2, y2) = project(segment.coordinates[0]), project(segment.coordinates[-1])
            records = ", ".join(str(r) for r in item.records)
            labels.append(
                _label((x1 + x2) / 2, (y1 + y2) / 2, f"City curb ramp {records}", "#111827", placed)
            )
    for route in routes:
        for point in (route.coordinates[0], route.coordinates[-1]):
            x, y = project(point)
            layers.append(f'<circle cx="{x}" cy="{y}" r="5" fill="#111827"/>')
    cause = result.cause or {}
    delta = cause.get("cost_delta_m")
    moved = "not comparable" if delta is None else f"{delta:+.1f} effective m"
    records = ", ".join(str(r) for r in cause.get("records", [])) or "none"
    return (
        "<figure>"
        f"<figcaption><strong>{html.escape(result.journey.journey_id)}</strong> "
        f"({html.escape(result.journey.corpus)} corpus) · profile "
        f"<code>{html.escape(result.profile_key)}</code> · {html.escape(str(result.category))}"
        f"<br>Distance {cause.get('distance_delta_m', 0):+.1f} m, cost {moved}, kerb cost "
        f"{cause.get('kerb_cost_delta_m', 0):+.1f} effective m against the baseline. City "
        f"records on either route: {html.escape(records)}.<br>"
        f"{html.escape(str(cause.get('cause', '')))}</figcaption>"
        f"{_svg(layers + labels, f'Baseline and shadow routes for journey {result.journey.journey_id}')}"
        "</figure>"
    )


def _rejection_figure(example: RejectedExample) -> str:
    points = [p for _way, coords in example.extents for p in coords]
    points += [p for s in example.segments for p in s.coordinates]
    if not points:
        return ""
    project = _projector(points)
    layers = []
    for segment in example.segments:
        colour = (
            _SUBSTITUTED
            if segment.substituted
            else (_CROSSING if segment.is_crossing else "#9ca3af")
        )
        width = 5 if segment.is_crossing else 2
        layers.append(
            _polyline(segment.coordinates, project, f'stroke="{colour}" stroke-width="{width}"')
        )
    labels: list[str] = []
    placed: list[tuple[float, float, float]] = []
    for way, coords in example.extents:
        if len(coords) == 1:
            x, y = project(coords[0])
            layers.append(f'<circle cx="{x}" cy="{y}" r="6" fill="{_EXTENT}"/>')
        else:
            layers.append(
                _polyline(
                    coords, project, f'stroke="{_EXTENT}" stroke-width="9" stroke-opacity="0.9"'
                )
            )
        x, y = project(coords[len(coords) // 2])
        labels.append(_label(x, y, f"named extent on {way}", _EXTENT, placed))
    return (
        "<figure>"
        f"<figcaption><strong>City record {example.record_id}</strong> · matcher rule "
        f"<code>{html.escape(example.rule)}</code> · record {example.record_length_m:.1f} m · "
        f"<strong>{html.escape(example.outcome)}</strong><br>{html.escape(example.note)}"
        "</figcaption>"
        f"{_svg(layers + labels, f'Rejected mapping for City record {example.record_id}')}"
        "</figure>"
    )


def render_page(
    results: Sequence[Result],
    pairs: Mapping[tuple[str, str], Pair],
    profiles: Mapping[str, MobilityProfile],
    substitutions: Mapping[str, Substitution],
    rejected: Sequence[RejectedExample],
    attribution: Mapping[str, str],
) -> str:
    chosen = representatives(results, pairs)
    figures = "".join(
        _route_figure(
            r, pairs[(r.journey.journey_id, r.profile_key)], profiles[r.profile_key], substitutions
        )
        for r in chosen
    )
    if not figures:
        figures = "<p>No route changed, so there is nothing to draw.</p>"
    rejections = "".join(_rejection_figure(e) for e in rejected)
    if not rejections:
        rejections = "<p>No rejected mapping was selected for drawing.</p>"
    notes = "".join(f"<li>{html.escape(v)}</li>" for _k, v in sorted(attribution.items()))
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>PA-GEO-09 curb-ramp shadow route changes</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:16px;color:#111827;background:#fff}"
        "figure{margin:24px 0}figcaption{max-width:720px;margin-bottom:8px;line-height:1.4}"
        "svg{max-width:100%;height:auto;border:1px solid #cbd5e1}"
        ".banner{background:#fef2f2;border:2px solid #b91c1c;padding:8px 12px;font-weight:700}"
        "</style></head><body>"
        f"<p class='banner'>{html.escape(WATERMARK)}. City of Kitchener curb-ramp assertions "
        "are not routing evidence: licensing, validation and a routing policy are all "
        "outstanding, and nothing drawn here is a route anyone should follow.</p>"
        "<h1>PA-GEO-09: representative curb-ramp shadow route changes</h1>"
        "<p>Grey dashed: route A, the baseline (OSM only). Blue: route B, the shadow. Thick teal: "
        "crossing segments where a City curb ramp replaces an unknown kerb in the shadow only, "
        "labelled with the City record numbers. Dots: where the routes start and end.</p>"
        f"{figures}"
        "<h2>Candidates the mapping refused</h2>"
        "<p>Orange: the metres of the OSM way the matcher named for the City's curb cut. Dark "
        "slate: crossing segments of the routing graph nearby; light grey: other segments. The "
        "City's own geometry is not drawn.</p>"
        f"{rejections}<ul>{notes}</ul></body></html>\n"
    )
