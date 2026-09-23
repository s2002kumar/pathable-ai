/**
 * GeoJSON and paint definitions for the two route layers.
 *
 * Free of React and of MapLibre so the shapes can be unit-tested directly — the
 * question "did we draw the accessible route on top?" should not need a GPU to
 * answer.
 *
 * The two routes are drawn in a deliberate order and with deliberate styling:
 * the standard route sits underneath as a dashed reference line, and the
 * accessible route sits on top as a solid line. The accessible route is the
 * answer; the standard route is the comparison. Each line is cased in the
 * page's surface colour so it stays legible over any road the basemap draws.
 */
import type { Route } from '@pathable/contracts';

export const STANDARD_SOURCE_ID = 'pathable-standard-route';
export const ACCESSIBLE_SOURCE_ID = 'pathable-accessible-route';
export const STANDARD_CASING_LAYER_ID = 'pathable-standard-route-casing';
export const STANDARD_LAYER_ID = 'pathable-standard-route-line';
export const ACCESSIBLE_CASING_LAYER_ID = 'pathable-accessible-route-casing';
export const ACCESSIBLE_LAYER_ID = 'pathable-accessible-route-line';
export const POINTS_SOURCE_ID = 'pathable-route-points';
export const POINTS_HALO_LAYER_ID = 'pathable-route-points-halo';
export const POINTS_LAYER_ID = 'pathable-route-points-circle';
export const POINTS_LABEL_LAYER_ID = 'pathable-route-points-label';

/**
 * Route colours.
 *
 * Mirrored by `--color-route-*` in `styles/tokens.css`, which the legend uses:
 * MapLibre paints into WebGL and cannot read a CSS custom property, so the two
 * definitions are kept in step by hand and asserted by a unit test.
 *
 * Chosen to stay distinguishable without relying on hue alone: the two lines
 * also differ in dash pattern and width, so the comparison survives colour
 * vision deficiency and a greyscale print. Both meet 3:1 against the muted
 * basemap.
 */
export const STANDARD_COLOUR = '#4b463e';
export const ACCESSIBLE_COLOUR = '#1d4fc4';
export const ORIGIN_COLOUR = '#1d4fc4';
export const DESTINATION_COLOUR = '#b3261e';
/** The page surface, so a cased line reads as drawn on the map rather than glowing. */
export const CASING_COLOUR = '#ffffff';

/**
 * Camera movement is the one animation on the page longer than a transition,
 * and it is capped here. Reduced motion collapses it to an instant jump.
 */
export const CAMERA_DURATION_MS = 600;

/**
 * Room around a fitted route, before anything is floating over the map.
 *
 * Clears MapLibre's own chrome: navigation top-right, scale and attribution
 * along the bottom.
 */
export const FIT_PADDING = { top: 72, bottom: 72, left: 64, right: 72 } as const;

export type Padding = { top: number; bottom: number; left: number; right: number };

/** Just enough of an element to know where it is. */
export type Rect = {
  readonly left: number;
  readonly top: number;
  readonly right: number;
  readonly bottom: number;
  readonly width: number;
  readonly height: number;
};

export type PanelInset = {
  /** The edge of the map the panel is against. */
  readonly side: keyof Padding;
  /** How far it reaches in from that edge, in pixels. Zero when it does not. */
  readonly amount: number;
};

export const NO_PANEL_INSET: PanelInset = { side: 'left', amount: 0 };

/**
 * Which edge of the map the panel covers, and by how much.
 *
 * Decided by asking which inset leaves the most map behind, not by which one
 * is smallest. A bottom sheet spans the full width and is usually taller than
 * it is wide, so 'smallest reach' picks its width and insets the wrong axis —
 * a real bug, caught on a 390 x 844 phone where it pushed the camera sideways
 * off the route entirely.
 *
 * Deliberately unclamped. This is the geometric truth about the panel, and it
 * is what the map key and MapLibre's own credit are positioned against; the
 * camera's allowance is built from it separately, because a padding that has
 * been squeezed to fit is not a statement about where the panel is.
 */
export function panelInset(map: Rect | null, panel: Rect | null): PanelInset {
  if (map === null || panel === null || map.width <= 0 || map.height <= 0) return NO_PANEL_INSET;

  // No overlap, nothing to allow for.
  const overlapWidth = Math.min(map.right, panel.right) - Math.max(map.left, panel.left);
  const overlapHeight = Math.min(map.bottom, panel.bottom) - Math.max(map.top, panel.top);
  if (overlapWidth <= 0 || overlapHeight <= 0) return NO_PANEL_INSET;

  const reaches: ReadonlyArray<readonly [keyof Padding, number]> = [
    ['left', panel.right - map.left],
    ['right', map.right - panel.left],
    ['top', panel.bottom - map.top],
    ['bottom', map.bottom - panel.top],
  ];

  // How much map each inset would leave behind.
  const candidates = reaches.map(([side, amount]) => ({
    side,
    amount,
    free:
      side === 'left' || side === 'right'
        ? Math.max(0, map.width - amount) * map.height
        : Math.max(0, map.height - amount) * map.width,
  }));

  let best = candidates[0]!;
  for (const candidate of candidates) {
    if (candidate.amount <= 0) continue;
    // More map left over wins; a tie goes to the smaller inset.
    if (
      candidate.free > best.free ||
      (candidate.free === best.free && candidate.amount < best.amount)
    )
      best = candidate;
  }

  if (best.amount <= 0 || best.free <= 0) return NO_PANEL_INSET;
  return { side: best.side, amount: best.amount };
}

/**
 * Padding that keeps a fitted route out from under the floating panel.
 *
 * The map fills the viewport and the planning surface floats over one of its
 * edges — beside it on a laptop, across the bottom on a phone. Fitting to the
 * whole map would centre the route under that panel, which is the exact
 * failure the previous layout was built to avoid; the panel only moved, it did
 * not stop existing.
 *
 * A panel that does not overlap the map at all — the document-flow fallback on
 * a short window — gets the base padding untouched.
 *
 * The result is clamped to leave a real viewport behind: MapLibre given
 * padding wider than the map has nothing left to fit a route into. That clamp
 * is why this is a separate figure from `panelInset` above, and why the map's
 * own chrome is positioned from that one rather than from this.
 */
export function paddingForPanel(
  map: Rect | null,
  panel: Rect | null,
  base: Padding = { ...FIT_PADDING },
): Padding {
  const padding: Padding = { ...base };
  if (map === null) return padding;

  const inset = panelInset(map, panel);
  if (inset.amount > 0) padding[inset.side] = base[inset.side] + inset.amount;

  [padding.left, padding.right] = clampAxis(padding.left, padding.right, map.width);
  [padding.top, padding.bottom] = clampAxis(padding.top, padding.bottom, map.height);

  return padding;
}

/** The smallest strip of map a fitted route may be squeezed into. */
const MIN_FIT_PX = 64;

/**
 * Keep one axis's padding inside the map, shrinking both sides together.
 *
 * Proportional rather than clipping the larger side: the larger side is
 * normally the one the panel is against, and cutting that first would put the
 * route back underneath the panel, which is the whole thing this is for.
 */
function clampAxis(start: number, end: number, size: number): [number, number] {
  const available = size - MIN_FIT_PX;
  if (start + end <= available) return [start, end];
  if (available <= 0) return [0, 0];
  const scale = available / (start + end);
  return [start * scale, end * scale];
}

/** Which route, if any, the viewer has asked to see on its own. */
export type RouteFocus = 'standard' | 'accessible' | null;

/** How far the unfocused route fades. Never to nothing: the comparison stays. */
export const UNFOCUSED_OPACITY = 0.28;

export type LineFeatureCollection = {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    properties: Record<string, unknown>;
    geometry: { type: 'LineString'; coordinates: Array<[number, number]> };
  }>;
};

export type PointFeatureCollection = {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    properties: { role: 'origin' | 'destination'; label: string };
    geometry: { type: 'Point'; coordinates: [number, number] };
  }>;
};

export const EMPTY_LINES: LineFeatureCollection = { type: 'FeatureCollection', features: [] };
export const EMPTY_POINTS: PointFeatureCollection = { type: 'FeatureCollection', features: [] };

/** Wrap a route's polyline as a GeoJSON feature collection. */
export function routeToGeoJson(route: Route | null | undefined): LineFeatureCollection {
  if (!route || route.coordinates.length < 2) return EMPTY_LINES;

  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { profile: route.profile, distance_m: route.distance_m },
        geometry: {
          type: 'LineString',
          coordinates: route.coordinates.map(([longitude, latitude]) => [longitude, latitude]),
        },
      },
    ],
  };
}

export function pointsToGeoJson(
  origin: { longitude: number; latitude: number } | null,
  destination: { longitude: number; latitude: number } | null,
): PointFeatureCollection {
  const features: PointFeatureCollection['features'] = [];
  if (origin) {
    features.push({
      type: 'Feature',
      properties: { role: 'origin', label: 'A' },
      geometry: { type: 'Point', coordinates: [origin.longitude, origin.latitude] },
    });
  }
  if (destination) {
    features.push({
      type: 'Feature',
      properties: { role: 'destination', label: 'B' },
      geometry: { type: 'Point', coordinates: [destination.longitude, destination.latitude] },
    });
  }
  return { type: 'FeatureCollection', features };
}

/** Bounding box covering every coordinate, or null when there is nothing to fit. */
export function boundsOf(
  ...collections: Array<LineFeatureCollection | PointFeatureCollection>
): [[number, number], [number, number]] | null {
  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;

  for (const collection of collections) {
    for (const feature of collection.features) {
      const positions =
        feature.geometry.type === 'Point'
          ? [feature.geometry.coordinates]
          : feature.geometry.coordinates;
      for (const [longitude, latitude] of positions) {
        if (longitude < minLon) minLon = longitude;
        if (latitude < minLat) minLat = latitude;
        if (longitude > maxLon) maxLon = longitude;
        if (latitude > maxLat) maxLat = latitude;
      }
    }
  }

  if (!Number.isFinite(minLon) || !Number.isFinite(minLat)) return null;
  return [
    [minLon, minLat],
    [maxLon, maxLat],
  ];
}

/**
 * The opacity a route line should be drawn at, given what is focused.
 *
 * Focusing one route dims the other; it never removes it. A viewer who hides
 * the shortest route has not been shown a safer one, only a clearer one.
 */
export function lineOpacity(variant: 'standard' | 'accessible', focus: RouteFocus): number {
  if (focus === null || focus === variant) return 1;
  return UNFOCUSED_OPACITY;
}

/**
 * Whether the viewer has asked for less motion.
 *
 * MapLibre honours the same media query for non-essential camera moves, but the
 * duration is stated here as well so the behaviour is visible in one place and
 * testable without a renderer.
 */
export function prefersReducedMotion(
  matchMedia: ((query: string) => { matches: boolean }) | undefined = globalThis.window?.matchMedia,
): boolean {
  if (typeof matchMedia !== 'function') return false;
  try {
    return matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

/** How long the camera takes to frame a route: the cap, or nothing at all. */
export function cameraDuration(reducedMotion: boolean): number {
  return reducedMotion ? 0 : CAMERA_DURATION_MS;
}

const ROUND_LINE = { 'line-cap': 'round', 'line-join': 'round' } as const;

/** Casing under the standard route, so a grey dash stays visible on a grey road. */
export function standardCasingLayer(): Record<string, unknown> {
  return {
    id: STANDARD_CASING_LAYER_ID,
    type: 'line',
    source: STANDARD_SOURCE_ID,
    layout: ROUND_LINE,
    paint: {
      'line-color': CASING_COLOUR,
      'line-width': 8,
      'line-opacity': 0.9,
    },
  };
}

/** The standard route: a dashed ink-grey reference line, drawn underneath. */
export function standardLineLayer(): Record<string, unknown> {
  return {
    id: STANDARD_LAYER_ID,
    type: 'line',
    source: STANDARD_SOURCE_ID,
    layout: ROUND_LINE,
    paint: {
      'line-color': STANDARD_COLOUR,
      'line-width': 4,
      'line-opacity': 1,
      'line-dasharray': [1.8, 1.6],
    },
  };
}

/** Casing under the accessible route. */
export function accessibleCasingLayer(): Record<string, unknown> {
  return {
    id: ACCESSIBLE_CASING_LAYER_ID,
    type: 'line',
    source: ACCESSIBLE_SOURCE_ID,
    layout: ROUND_LINE,
    paint: {
      'line-color': CASING_COLOUR,
      'line-width': 10,
      'line-opacity': 0.9,
    },
  };
}

/** The accessible route: a solid line on top, because it is the answer. */
export function accessibleLineLayer(): Record<string, unknown> {
  return {
    id: ACCESSIBLE_LAYER_ID,
    type: 'line',
    source: ACCESSIBLE_SOURCE_ID,
    layout: ROUND_LINE,
    paint: {
      'line-color': ACCESSIBLE_COLOUR,
      'line-width': 5.5,
      'line-opacity': 1,
    },
  };
}

/** A pale halo behind each endpoint, so the marker stays readable over a label. */
export function pointHaloLayer(): Record<string, unknown> {
  return {
    id: POINTS_HALO_LAYER_ID,
    type: 'circle',
    source: POINTS_SOURCE_ID,
    paint: {
      'circle-radius': 14,
      'circle-color': CASING_COLOUR,
      'circle-opacity': 0.85,
    },
  };
}

export function pointCircleLayer(): Record<string, unknown> {
  return {
    id: POINTS_LAYER_ID,
    type: 'circle',
    source: POINTS_SOURCE_ID,
    paint: {
      'circle-radius': 10,
      'circle-color': [
        'match',
        ['get', 'role'],
        'origin',
        ORIGIN_COLOUR,
        'destination',
        DESTINATION_COLOUR,
        ORIGIN_COLOUR,
      ],
      'circle-stroke-color': CASING_COLOUR,
      'circle-stroke-width': 2.5,
    },
  };
}

/**
 * A/B labels on the markers.
 *
 * The markers are also distinguished by colour, but colour alone is not a label
 * — the letters are what a colour-blind user reads.
 *
 * The font is one the basemap actually serves. Left unset, MapLibre asks the
 * style's glyph endpoint for "Open Sans Regular", which OpenFreeMap does not
 * host, and every route draws with a 404 in the console.
 */
export function pointLabelLayer(): Record<string, unknown> {
  return {
    id: POINTS_LABEL_LAYER_ID,
    type: 'symbol',
    source: POINTS_SOURCE_ID,
    layout: {
      'text-field': ['get', 'label'],
      'text-font': ['Noto Sans Bold'],
      'text-size': 12,
      'text-allow-overlap': true,
      'text-ignore-placement': true,
    },
    paint: { 'text-color': '#ffffff' },
  };
}
