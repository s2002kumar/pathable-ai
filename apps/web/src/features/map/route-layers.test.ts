import { describe, expect, it } from 'vitest';
import type { Route } from '@pathable/contracts';
import {
  ACCESSIBLE_LAYER_ID,
  EMPTY_LINES,
  FIT_PADDING,
  NO_RECORDED_STAIRS,
  STANDARD_LAYER_ID,
  accessibleLineLayer,
  boundsOf,
  paddingForPanel,
  pointsToGeoJson,
  recordedStairs,
  stairsToGeoJson,
  routeToGeoJson,
  standardLineLayer,
} from './route-layers';

/** A DOMRect-shaped box, from the two corners. */
function box(left: number, top: number, width: number, height: number) {
  return { left, top, right: left + width, bottom: top + height, width, height };
}

function route(coordinates: Array<[number, number]>): Route {
  return {
    profile: 'wheelchair',
    profile_display_name: 'Wheelchair',
    distance_m: 500,
    effective_distance_m: 720,
    estimated_duration_seconds: 600,
    pace_profile: 'wheelchair',
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
    gradient: {
      steepest_uphill: null,
      steepest_downhill: null,
      recorded_fraction: 0,
      estimated_fraction: 0,
      unknown_fraction: 1,
    },
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

/**
 * Framing a route around the panel that floats over the map.
 *
 * The map fills the viewport now, so "fit the route to the map" and "fit the
 * route to the part of the map a person can see" are different instructions.
 * Getting this wrong puts the answer under the panel — the exact failure the
 * previous layout was built to avoid — and it is invisible to every test that
 * only asks whether a route was drawn.
 */
describe('fitting a route around the panel', () => {
  // A 1000 x 700 laptop window: header gone, panel floating against the left.
  const MAP = box(0, 48, 1000, 652);
  const SIDE_PANEL = box(12, 60, 320, 628);
  // A 390 x 844 phone: the same map, the panel across the bottom.
  const PHONE_MAP = box(0, 48, 390, 796);
  const SHEET = box(12, 480, 366, 364);

  it('leaves room on the side the panel is against', () => {
    const padding = paddingForPanel(MAP, SIDE_PANEL);

    // The panel's right edge is 332 px into the map.
    expect(padding.left).toBe(FIT_PADDING.left + 332);
    expect(padding.right).toBe(FIT_PADDING.right);
    expect(padding.top).toBe(FIT_PADDING.top);
    expect(padding.bottom).toBe(FIT_PADDING.bottom);
  });

  it('leaves room underneath when the panel is a bottom sheet', () => {
    // Regression: the anchored edge used to be whichever one the panel
    // reached into least. For a bottom sheet on a 390 x 844 phone that is its
    // width (366 px), not its height (517 px), so the camera was told to
    // inset the *left* edge by almost the whole map and framed the route
    // off-screen. The edge is now the one whose inset leaves the most map.
    const padding = paddingForPanel(PHONE_MAP, SHEET);

    expect(padding.bottom).toBe(FIT_PADDING.bottom + 364);
    expect(padding.left).toBe(FIT_PADDING.left);
    expect(padding.right).toBe(FIT_PADDING.right);
  });

  it('insets the bottom for a sheet taller than it is wide', () => {
    // The shape that produced the bug: the sheet covers 517 px of a 796 px
    // map and spans all 390 px of it. Insetting the width would leave a
    // 12 px strip; insetting the height leaves 279 px of usable map.
    const tallSheet = box(12, 327, 366, 517);
    const padding = paddingForPanel(PHONE_MAP, tallSheet);

    expect(padding.bottom).toBeGreaterThan(FIT_PADDING.bottom);
    expect(padding.left).toBe(FIT_PADDING.left);
    expect(padding.right).toBe(FIT_PADDING.right);
    expect(PHONE_MAP.height - padding.top - padding.bottom).toBeGreaterThan(100);
  });

  it('adds nothing when the panel sits below the map instead of over it', () => {
    // The document-flow fallback: a short window, map above, planner beneath.
    const flowMap = box(0, 48, 720, 208);
    const flowPanel = box(0, 256, 720, 900);

    expect(paddingForPanel(flowMap, flowPanel)).toEqual({ ...FIT_PADDING });
  });

  it('never demands more room than the map has', () => {
    // A panel wider than the viewport it floats in. Padding that exceeds the
    // map leaves MapLibre nothing to fit into, and a route that cannot be
    // framed is a route nobody sees.
    const padding = paddingForPanel(MAP, box(0, 48, 1200, 652));

    expect(padding.left).toBeLessThan(MAP.width);
    expect(padding.left + padding.right).toBeLessThan(MAP.width);
    expect(padding.top + padding.bottom).toBeLessThan(MAP.height);
  });

  it('falls back to the base padding before anything has been measured', () => {
    expect(paddingForPanel(null, null)).toEqual({ ...FIT_PADDING });
    expect(paddingForPanel(MAP, null)).toEqual({ ...FIT_PADDING });
    expect(paddingForPanel(box(0, 0, 0, 0), SIDE_PANEL)).toEqual({ ...FIT_PADDING });
  });
});

/**
 * Reading the stairway evidence off a response.
 *
 * The whole product turns on one distinction here: a segment nobody has
 * surveyed is not a segment without stairs. `steps` is a three-valued enum for
 * that reason, and every case below exists because collapsing it to a boolean
 * would produce a confident, wrong answer.
 */
describe('recorded stairways', () => {
  const segment = (overrides: Record<string, unknown> = {}) =>
    ({
      edge_identity: '1->2#0',
      name: null,
      length_m: 4,
      effective_metres: 4,
      coordinates: [
        [-80.54, 43.47],
        [-80.5401, 43.4701],
      ],
      highway: 'footway',
      surface: null,
      surface_class: 'unknown',
      smoothness_class: 'unknown',
      steps: 'no',
      step_count: null,
      incline_percent: null,
      kerb: 'unknown',
      is_crossing: false,
      width_m: null,
      unknown_attributes: [],
      cost_components: [],
      ...overrides,
    }) as unknown as Route['segments'][number];

  const routeWith = (segments: Array<Route['segments'][number]>) =>
    ({ ...route([[-80.54, 43.47]]), segments }) as Route;

  it('counts only what the map records as a stairway', () => {
    const result = recordedStairs(
      routeWith([
        segment({ steps: 'yes', step_count: 5 }),
        segment({ steps: 'no' }),
        segment({ steps: 'yes', step_count: 11 }),
      ]),
    );

    expect(result.stairways).toBe(2);
    expect(result.recordedSteps).toBe(16);
  });

  it('never treats an unrecorded step state as "no stairs"', () => {
    // The failure this guards against is silent: an `unknown` segment counted
    // as `no` would make a route look confirmed step-free when nobody has
    // looked at it. It is neither a stairway nor evidence of the absence of
    // one, and it is reported separately so the UI can say so.
    const result = recordedStairs(
      routeWith([segment({ steps: 'unknown' }), segment({ steps: 'unknown', step_count: 9 })]),
    );

    expect(result.stairways).toBe(0);
    expect(result.segments).toHaveLength(0);
    expect(result.unknownSegments).toBe(2);
    // Even a step count on an unknown segment does not promote it to a stairway.
    expect(result.recordedSteps).toBe(0);
  });

  it('reports the recorded step total as a floor, not a total', () => {
    // Two counted stairways and two uncounted ones: "16 steps" would be a
    // statement about the whole route that the data does not support.
    const result = recordedStairs(
      routeWith([
        segment({ steps: 'yes', step_count: 5 }),
        segment({ steps: 'yes', step_count: null }),
        segment({ steps: 'yes', step_count: 11 }),
        segment({ steps: 'yes', step_count: null }),
      ]),
    );

    expect(result.stairways).toBe(4);
    expect(result.recordedSteps).toBe(16);
    expect(result.unknownStepCount).toBe(2);
  });

  it('ignores a stairway with no geometry to draw', () => {
    const result = recordedStairs(routeWith([segment({ steps: 'yes', coordinates: [] })]));

    expect(result.stairways).toBe(0);
  });

  it('is empty for a missing route rather than throwing', () => {
    expect(recordedStairs(null)).toEqual(NO_RECORDED_STAIRS);
    expect(recordedStairs(undefined)).toEqual(NO_RECORDED_STAIRS);
  });

  it('draws each stairway as its own line, keyed by position not identity', () => {
    // `edge_identity` is undirected and repeats on an out-and-back route, so
    // it cannot be the feature id.
    const shared = { steps: 'yes', edge_identity: 'same->same#0' };
    const collection = stairsToGeoJson(
      recordedStairs(routeWith([segment(shared), segment(shared)])),
    );

    expect(collection.features).toHaveLength(2);
    expect(collection.features.map((f) => f.properties.index)).toEqual([0, 1]);
    expect(collection.features[0]?.geometry.type).toBe('LineString');
  });

  it('draws nothing when nothing is recorded', () => {
    expect(stairsToGeoJson(NO_RECORDED_STAIRS).features).toHaveLength(0);
  });
});
