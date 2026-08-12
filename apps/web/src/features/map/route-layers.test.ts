import { describe, expect, it } from 'vitest';
import type { Route } from '@pathable/contracts';
import {
  ACCESSIBLE_LAYER_ID,
  EMPTY_LINES,
  STANDARD_LAYER_ID,
  accessibleLineLayer,
  boundsOf,
  pointsToGeoJson,
  routeToGeoJson,
  standardLineLayer,
} from './route-layers';

function route(coordinates: Array<[number, number]>): Route {
  return {
    profile: 'wheelchair',
    profile_display_name: 'Wheelchair',
    distance_m: 500,
    effective_distance_m: 720,
    estimated_duration_seconds: 600,
    coordinates,
    segments: [],
    origin: {
      longitude: coordinates[0]?.[0] ?? 0,
      latitude: coordinates[0]?.[1] ?? 0,
      distance_m: 3,
    },
    destination: {
      longitude: coordinates.at(-1)?.[0] ?? 0,
      latitude: coordinates.at(-1)?.[1] ?? 0,
      distance_m: 4,
    },
    stairway_count: 0,
    step_count: 0,
    crossing_count: 1,
    unknown_kerb_crossing_count: 0,
    steepest_incline_percent: null,
    unknown_data_fraction: 0.2,
    computation_ms: 12,
  };
}

describe('routeToGeoJson', () => {
  it('wraps a route polyline as one linestring feature', () => {
    const collection = routeToGeoJson(
      route([
        [-80.54, 43.47],
        [-80.538, 43.47],
      ]),
    );

    expect(collection.features).toHaveLength(1);
    expect(collection.features[0]?.geometry.coordinates).toEqual([
      [-80.54, 43.47],
      [-80.538, 43.47],
    ]);
  });

  it('produces an empty collection for a missing route', () => {
    expect(routeToGeoJson(null)).toEqual(EMPTY_LINES);
    expect(routeToGeoJson(undefined)).toEqual(EMPTY_LINES);
  });

  it('produces an empty collection for a degenerate polyline', () => {
    // A single position is not a line, and MapLibre throws on one.
    expect(routeToGeoJson(route([[-80.54, 43.47]]))).toEqual(EMPTY_LINES);
  });
});

describe('pointsToGeoJson', () => {
  it('labels the endpoints A and B', () => {
    const collection = pointsToGeoJson(
      { longitude: -80.54, latitude: 43.47 },
      { longitude: -80.53, latitude: 43.48 },
    );

    expect(collection.features.map((feature) => feature.properties.label)).toEqual(['A', 'B']);
    expect(collection.features.map((feature) => feature.properties.role)).toEqual([
      'origin',
      'destination',
    ]);
  });

  it('renders the origin alone while the destination is still unset', () => {
    const collection = pointsToGeoJson({ longitude: -80.54, latitude: 43.47 }, null);
    expect(collection.features).toHaveLength(1);
  });

  it('renders nothing when neither point is set', () => {
    expect(pointsToGeoJson(null, null).features).toHaveLength(0);
  });
});

describe('boundsOf', () => {
  it('covers every position across every collection', () => {
    const lines = routeToGeoJson(
      route([
        [-80.54, 43.47],
        [-80.53, 43.48],
      ]),
    );
    const points = pointsToGeoJson({ longitude: -80.55, latitude: 43.46 }, null);

    expect(boundsOf(lines, points)).toEqual([
      [-80.55, 43.46],
      [-80.53, 43.48],
    ]);
  });

  it('returns null when there is nothing to fit', () => {
    // The map must keep its configured view rather than jumping to [0, 0].
    expect(boundsOf(EMPTY_LINES)).toBeNull();
  });
});

describe('layer definitions', () => {
  it('distinguishes the routes by dash pattern, not only by colour', () => {
    // Colour alone would not survive colour vision deficiency or a greyscale
    // print, and the comparison is the whole product.
    const standard = standardLineLayer().paint as Record<string, unknown>;
    const accessible = accessibleLineLayer().paint as Record<string, unknown>;

    expect(standard['line-dasharray']).toBeDefined();
    expect(accessible['line-dasharray']).toBeUndefined();
    expect(standard['line-color']).not.toBe(accessible['line-color']);
  });

  it('gives each layer a stable id so it can be updated rather than re-added', () => {
    expect(standardLineLayer().id).toBe(STANDARD_LAYER_ID);
    expect(accessibleLineLayer().id).toBe(ACCESSIBLE_LAYER_ID);
  });

  it('draws the accessible route wider than the reference line', () => {
    // It is the answer; the shortest route is the comparison.
    const standard = standardLineLayer().paint as Record<string, number>;
    const accessible = accessibleLineLayer().paint as Record<string, number>;

    expect(accessible['line-width']).toBeGreaterThan(standard['line-width'] ?? 0);
  });
});
