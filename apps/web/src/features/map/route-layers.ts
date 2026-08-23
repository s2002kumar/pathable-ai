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
 * answer; the standard route is the comparison.
 */
import type { Route } from '@pathable/contracts';

export const STANDARD_SOURCE_ID = 'pathable-standard-route';
export const ACCESSIBLE_SOURCE_ID = 'pathable-accessible-route';
export const STANDARD_LAYER_ID = 'pathable-standard-route-line';
export const ACCESSIBLE_LAYER_ID = 'pathable-accessible-route-line';
export const POINTS_SOURCE_ID = 'pathable-route-points';
export const POINTS_LAYER_ID = 'pathable-route-points-circle';
export const POINTS_LABEL_LAYER_ID = 'pathable-route-points-label';

/**
 * Route colours.
 *
 * Chosen to stay distinguishable without relying on hue alone: the two lines
 * also differ in dash pattern and width, so the comparison survives colour
 * vision deficiency and a greyscale print. Both meet 3:1 against the basemap's
 * light background.
 */
export const STANDARD_COLOUR = '#5b6470';
export const ACCESSIBLE_COLOUR = '#0b6bcb';
export const ORIGIN_COLOUR = '#0b6bcb';
export const DESTINATION_COLOUR = '#b3261e';

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

/** The standard route: a dashed grey reference line, drawn underneath. */
export function standardLineLayer(): Record<string, unknown> {
  return {
    id: STANDARD_LAYER_ID,
    type: 'line',
    source: STANDARD_SOURCE_ID,
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': STANDARD_COLOUR,
      'line-width': 5,
      'line-opacity': 0.85,
      'line-dasharray': [2, 1.6],
    },
  };
}

/** The accessible route: a solid line on top, because it is the answer. */
export function accessibleLineLayer(): Record<string, unknown> {
  return {
    id: ACCESSIBLE_LAYER_ID,
    type: 'line',
    source: ACCESSIBLE_SOURCE_ID,
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': ACCESSIBLE_COLOUR,
      'line-width': 6,
      'line-opacity': 0.95,
    },
  };
}

export function pointCircleLayer(): Record<string, unknown> {
  return {
    id: POINTS_LAYER_ID,
    type: 'circle',
    source: POINTS_SOURCE_ID,
    paint: {
      'circle-radius': 9,
      'circle-color': [
        'match',
        ['get', 'role'],
        'origin',
        ORIGIN_COLOUR,
        'destination',
        DESTINATION_COLOUR,
        ORIGIN_COLOUR,
      ],
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 2,
    },
  };
}

/**
 * A/B labels on the markers.
 *
 * The markers are also distinguished by colour, but colour alone is not a label
 * — the letters are what a colour-blind user reads.
 */
export function pointLabelLayer(): Record<string, unknown> {
  return {
    id: POINTS_LABEL_LAYER_ID,
    type: 'symbol',
    source: POINTS_SOURCE_ID,
    layout: {
      'text-field': ['get', 'label'],
      'text-size': 12,
      'text-allow-overlap': true,
    },
    paint: { 'text-color': '#ffffff' },
  };
}
