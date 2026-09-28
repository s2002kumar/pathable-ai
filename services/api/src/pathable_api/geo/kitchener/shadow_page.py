"""A static page of representative shadow route changes, drawn as plain SVG.

Engineering evidence, not interface: no map tiles, no imagery, only the
routing graph's own OSM-derived geometry. Each drawing shows the baseline
route, the shadow route, the segments the City's surface assertions filled,
and the cause the costs give. Every figure is marked as a research
counterfactual.
"""

from __future__ import annotations

import html
import math
from collections.abc import Mapping, Sequence
from typing import Any

from pathable_api.geo.kitchener.shadow_overlay import Fill
from pathable_api.geo.kitchener.shadow_study import Category, Pair, Result, chosen_route
from pathable_api.routing.profiles import MobilityProfile

WATERMARK = "Research counterfactual — not production routing"
PAGE_LIMIT = 8
_SIZE = 520
_PAD = 24


def representatives(
    results: Sequence[Result], pairs: Mapping[tuple[str, str], Pair]
) -> list[Result]:
    """A deterministic handful: feasibility changes first, then the largest cost moves."""
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
        if len(chosen) >= PAGE_LIMIT:
            break
    return chosen


def _projector(points: Sequence[tuple[float, float]]) -> Any:
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


def _polyline(points: Sequence[tuple[float, float]], project: Any, style: str) -> str:
    coords = " ".join(f"{x},{y}" for x, y in (project(p) for p in points))
    return f'<polyline points="{coords}" {style} fill="none"/>'


def _figure(result: Result, pair: Pair, profile: MobilityProfile, fills: Mapping[str, Fill]) -> str:
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
    labels = []
    for route in routes:
        for segment in route.segments:
            fill = fills.get(segment.edge_identity)
            if fill is None:
                continue
            layers.append(
                _polyline(
                    segment.coordinates,
                    project,
                    'stroke="#ea580c" stroke-width="8" stroke-opacity="0.75"',
                )
            )
            x, y = project(segment.coordinates[0])
            labels.append(
                f'<text x="{x + 6}" y="{y - 6}" font-size="11" fill="#9a3412">City: '
                f"{html.escape(fill.surface)}</text>"
            )
    for route in routes:
        x, y = project(route.coordinates[0])
        layers.append(f'<circle cx="{x}" cy="{y}" r="5" fill="#111827"/>')
        x, y = project(route.coordinates[-1])
        layers.append(f'<circle cx="{x}" cy="{y}" r="5" fill="#111827"/>')
    cause = result.cause or {}
    svg = (
        f'<svg viewBox="0 0 {_SIZE} {_SIZE}" width="{_SIZE}" height="{_SIZE}" role="img" '
        f'aria-label="Baseline and shadow routes for journey {result.journey.journey_id}">'
        f'<rect width="{_SIZE}" height="{_SIZE}" fill="#f8fafc"/>'
        f'<text x="{_PAD}" y="18" font-size="12" font-weight="700" fill="#b91c1c">{WATERMARK}</text>'
        + "".join(layers)
        + "".join(dict.fromkeys(labels))
        + "</svg>"
    )
    records = ", ".join(str(r) for r in cause.get("records", [])) or "none"
    delta = cause.get("cost_delta_m")
    moved = "not comparable: route A is unusable" if delta is None else f"{delta:+.1f} effective m"
    return (
        "<figure>"
        f"<figcaption><strong>{html.escape(result.journey.journey_id)}</strong> "
        f"({html.escape(result.journey.corpus)} corpus) · profile "
        f"<code>{html.escape(result.profile_key)}</code> · {html.escape(str(result.category))}"
        f"<br>Distance {cause.get('distance_delta_m', 0):+.1f} m, cost {moved} against the "
        f"baseline. City records: "
        f"{html.escape(records)}.<br>{html.escape(str(cause.get('cause', '')))}</figcaption>"
        f"{svg}</figure>"
    )


def render_changes(
    results: Sequence[Result],
    pairs: Mapping[tuple[str, str], Pair],
    profiles: Mapping[str, MobilityProfile],
    fills: Mapping[str, Fill],
    attribution: Mapping[str, str],
) -> str:
    chosen = representatives(results, pairs)
    figures = "".join(
        _figure(r, pairs[(r.journey.journey_id, r.profile_key)], profiles[r.profile_key], fills)
        for r in chosen
    )
    if not figures:
        figures = "<p>No route changed, so there is nothing to draw.</p>"
    notes = "".join(f"<li>{html.escape(v)}</li>" for _k, v in sorted(attribution.items()))
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>PA-GEO-07 shadow route changes</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:16px;color:#111827;background:#fff}"
        "figure{margin:24px 0}figcaption{max-width:720px;margin-bottom:8px;line-height:1.4}"
        "svg{max-width:100%;height:auto;border:1px solid #cbd5e1}"
        ".banner{background:#fef2f2;border:2px solid #b91c1c;padding:8px 12px;font-weight:700}"
        "</style></head><body>"
        f"<p class='banner'>{WATERMARK}. City of Kitchener surface assertions are not "
        "routing evidence: licensing, validation and a routing policy are all outstanding.</p>"
        "<h1>PA-GEO-07: representative shadow route changes</h1>"
        "<p>Grey dashed: route A, the baseline (OSM only). Blue: route B, the shadow. Orange: "
        "segments where the City records a surface and OSM records none, filled only in the "
        "shadow. Dots: where the routes start and end.</p>"
        f"{figures}<ul>{notes}</ul></body></html>\n"
    )
