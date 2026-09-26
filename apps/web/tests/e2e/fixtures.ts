import type { Page } from '@playwright/test';

/**
 * Shared e2e helpers.
 *
 * Two invariants these exist to protect:
 *   - no test may reach the public internet (no tile servers, no CDNs)
 *   - no test may require a running backend or database
 *
 * The backend is therefore stubbed at the network layer when a test needs a
 * particular status, and left genuinely unreachable otherwise.
 */

export const READINESS_PATTERN = '**/api/v1/health/ready';
export const COMPARE_PATTERN = '**/api/v1/routes/compare';
export const MAP_STYLE_PATTERN = '**/map-styles/offline-test-style.json';

export const SCREENSHOT_DIR = 'artifacts/screenshots';

const READY_BODY = {
  status: 'ready',
  service: 'pathable-api',
  version: '0.1.0',
  checks: {
    database: { status: 'ok', detail: 'connected', latency_ms: 3.4 },
    postgis: { status: 'ok', detail: 'postgis 3.5.0', latency_ms: 1.2 },
  },
};

const NOT_READY_BODY = {
  status: 'not_ready',
  service: 'pathable-api',
  version: '0.1.0',
  checks: {
    database: { status: 'unavailable', detail: 'database unreachable', latency_ms: null },
    postgis: {
      status: 'unavailable',
      detail: 'not probed: database unreachable',
      latency_ms: null,
    },
  },
};

/** Serve the readiness payload a healthy full stack would return. */
export async function stubHealthyApi(page: Page): Promise<void> {
  await page.route(READINESS_PATTERN, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(READY_BODY),
    });
  });
}

/** Serve what a running API with a dead database returns. */
export async function stubDegradedApi(page: Page): Promise<void> {
  await page.route(READINESS_PATTERN, async (route) => {
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify(NOT_READY_BODY),
    });
  });
}

/** Make the map style 404, which drives MapLibre's initialisation-failure path. */
export async function breakMapStyle(page: Page): Promise<void> {
  await page.route(MAP_STYLE_PATTERN, async (route) => {
    await route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
  });
}

/**
 * Hold the map style until the caller releases it.
 *
 * A gate rather than a timed delay on purpose: with a fixed `setTimeout`, a
 * loaded machine can spend the whole delay just getting through `page.goto`, and
 * the loading state is gone before the assertion runs. Blocking until the test
 * says so makes the loading state observable regardless of how slow the host is.
 */
export async function holdMapStyle(page: Page): Promise<{ release: () => void }> {
  let release = (): void => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });

  await page.route(MAP_STYLE_PATTERN, async (route) => {
    await gate;
    await route.continue();
  });

  return { release: () => release() };
}

/** True when the page overflows sideways — always a layout bug, never a feature. */
export async function hasHorizontalOverflow(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const doc = document.documentElement;
    // 1px of tolerance for sub-pixel rounding on fractional device ratios.
    return doc.scrollWidth > doc.clientWidth + 1;
  });
}

/**
 * A fixed route comparison, so browser tests assert on what the page does with a
 * response rather than on whatever the routing engine happens to produce today.
 * The engine's own behaviour is covered by its unit and PostGIS tests.
 *
 * Shaped like a real response, segments and all: a short route across one
 * recorded stairway of 14 steps that the wheelchair profile rules out, and a
 * longer step-free route over one crossing. Every summary figure agrees with
 * the segments it summarises — a stub whose `stairway_count` says 1 while its
 * segments carry no stairway would test a response the API cannot send, and
 * the page would have to contradict itself to render it.
 */
type Position = [number, number];

type SegmentSpec = {
  readonly from: Position;
  readonly to: Position;
  readonly length: number;
  readonly id: string;
  readonly extra?: Record<string, unknown>;
};

function segmentOf({ from, to, length, id, extra = {} }: SegmentSpec) {
  return {
    edge_identity: id,
    coordinates: [from, to],
    length_m: length,
    effective_metres: length,
    cost_components: [],
    highway: 'footway',
    name: null,
    is_crossing: false,
    kerb: 'unknown',
    steps: 'no',
    step_count: null,
    surface: 'asphalt',
    surface_class: 'paved',
    smoothness_class: 'unknown',
    width_m: null,
    incline_percent: null,
    derived_grade_percent: 1.1,
    excluded_by_profile: null,
    unknown_attributes: ['smoothness'],
    ...extra,
  };
}

function lerp(a: Position, b: Position, t: number): Position {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

/** The two routes' segments, laid along the geometry the stub draws. */
function segmentsFor(straight: Position[], detour: Position[]) {
  const [a, b] = [straight[0]!, straight[1]!];
  const stairsFrom = lerp(a, b, 0.34);
  const stairsTo = lerp(a, b, 0.37);
  const standard = [
    segmentOf({ from: a, to: stairsFrom, length: 161, id: 'way/10:0-1' }),
    segmentOf({
      from: stairsFrom,
      to: stairsTo,
      length: 16,
      id: 'way/11:0-1',
      extra: {
        highway: 'steps',
        steps: 'yes',
        step_count: 14,
        surface: null,
        surface_class: 'unknown',
        excluded_by_profile: 'steps',
        derived_grade_percent: null,
        unknown_attributes: ['surface', 'smoothness', 'incline'],
      },
    }),
    segmentOf({ from: stairsTo, to: b, length: 306, id: 'way/12:0-1' }),
  ];
  const accessible = [
    // Surface condition is recorded everywhere but this first stretch.
    segmentOf({ from: detour[0]!, to: detour[1]!, length: 298, id: 'way/20:0-1' }),
    segmentOf({
      from: detour[1]!,
      to: detour[2]!,
      length: 81,
      id: 'way/21:0-1',
      extra: {
        is_crossing: true,
        kerb: 'lowered',
        incline_percent: 4,
        smoothness_class: 'good',
        unknown_attributes: [],
      },
    }),
    segmentOf({
      from: detour[2]!,
      to: detour[3]!,
      length: 330,
      id: 'way/22:0-1',
      extra: { smoothness_class: 'good', unknown_attributes: [] },
    }),
  ];
  return { standard, accessible };
}

const DATASET = {
  dataset_id: '0c9d1b3a-0000-4000-8000-000000000000',
  region: 'waterloo',
  checksum: 'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789',
  source_type: 'osm',
  source_name: 'openstreetmap:waterloo',
  acquired_at: '2026-08-12T00:00:00+00:00',
  attribution: '© OpenStreetMap contributors, ODbL 1.0',
};

function comparisonFor(origin: Point, destination: Point) {
  const straight: Position[] = [
    [origin.longitude, origin.latitude],
    [destination.longitude, destination.latitude],
  ];
  // A dogleg south then north, so the two routes are visibly different rather
  // than one line drawn on top of another.
  const offset = destination.latitude - origin.latitude || 0.0008;
  const detour: Position[] = [
    [origin.longitude, origin.latitude],
    [
      origin.longitude + (destination.longitude - origin.longitude) * 0.35,
      origin.latitude - Math.abs(offset) - 0.0008,
    ],
    [
      origin.longitude + (destination.longitude - origin.longitude) * 0.7,
      origin.latitude + Math.abs(offset) + 0.0006,
    ],
    [destination.longitude, destination.latitude],
  ];
  const segments = segmentsFor(straight, detour);
  const snapped = {
    origin: { ...origin, distance_m: 2 },
    destination: { ...destination, distance_m: 3 },
  };

  return {
    profile: 'wheelchair',
    profile_display_name: 'Wheelchair',
    profile_description:
      'Avoids steps entirely, prefers paved and smooth surfaces, and treats unrecorded kerbs and surfaces as risks rather than as clear paths.',
    standard_route: {
      profile: 'standard',
      profile_display_name: 'Standard walking',
      distance_m: 483,
      effective_distance_m: 483,
      estimated_duration_seconds: 508,
      // Both routes are timed at the traveller's pace, so the times compare.
      pace_profile: 'wheelchair',
      coordinates: straight,
      segments: segments.standard,
      ...snapped,
      stairway_count: 1,
      step_count: 14,
      crossing_count: 0,
      unknown_kerb_crossing_count: 0,
      steepest_incline_percent: null,
      gradient: {
        steepest_uphill: {
          percent: 1.1,
          direction: 'uphill',
          source: 'derived_elevation',
          segment_index: 0,
        },
        steepest_downhill: null,
        recorded_fraction: 0,
        estimated_fraction: 0.97,
        unknown_fraction: 0.03,
      },
      unknown_data_fraction: 1,
      evidence_coverage: { surface: 0.03, smoothness: 1, gradient: 0.03, width: 1, kerb: 0 },
      computation_ms: 4,
    },
    accessible_route: {
      profile: 'wheelchair',
      profile_display_name: 'Wheelchair',
      distance_m: 709,
      effective_distance_m: 980,
      estimated_duration_seconds: 746,
      pace_profile: 'wheelchair',
      coordinates: detour,
      segments: segments.accessible,
      ...snapped,
      stairway_count: 0,
      step_count: 0,
      crossing_count: 1,
      unknown_kerb_crossing_count: 0,
      steepest_incline_percent: 4,
      gradient: {
        steepest_uphill: {
          percent: 4,
          direction: 'uphill',
          source: 'osm_incline',
          segment_index: 1,
        },
        steepest_downhill: null,
        recorded_fraction: 0.11,
        estimated_fraction: 0.89,
        unknown_fraction: 0,
      },
      unknown_data_fraction: 0.42,
      evidence_coverage: { surface: 0, smoothness: 0.42, gradient: 0, width: 1, kerb: 0 },
      computation_ms: 6,
    },
    standard_failure: null,
    accessible_failure: null,
    extra_distance_m: 226,
    extra_distance_fraction: 0.468,
    explanations: [
      {
        code: 'avoids_stairs',
        summary:
          'Avoids 1 recorded stairway on the shortest route (14 steps in total), which this profile excludes.',
        basis: 'recorded',
        evidence: {
          hard_limit: true,
          stairway_count: 1,
          step_count: 14,
          stairways_without_step_count: 0,
          segments: ['way/11:0-1'],
        },
      },
      {
        code: 'avoids_unrecorded_surface',
        summary: 'Avoids 16 m where no surface has been recorded.',
        basis: 'not_recorded',
        evidence: { length_m: 16, cost_difference_effective_m: 8 },
      },
      {
        code: 'distance_difference',
        summary: '226 m longer than the shortest route.',
        basis: 'profile_rule',
        evidence: {},
      },
    ],
    cautions: [
      {
        code: 'missing_accessibility_data',
        summary:
          'On some of the wheelchair route (42% of its length) at least one accessibility ' +
          'attribute — surface, surface condition, gradient, steps or kerb — has no record in ' +
          'OpenStreetMap. Missing data is not evidence that a path is clear.',
        evidence: { unknown_data_fraction: 0.42 },
      },
    ],
    dataset: DATASET,
    routing_policy_version: 2,
    ml_predictions_used: false,
  };
}

/** What `/routes/profiles` returns, abridged to the fields the page reads. */
const PROFILES = {
  profiles: [
    {
      key: 'wheelchair',
      display_name: 'Wheelchair',
      description: 'Avoids steps entirely.',
      excludes_steps: true,
      max_incline_percent: null,
      min_width_m: null,
      prefers_gradient_under_percent: 8,
      prefers_width_over_m: 0.9,
      hard_requirements: ['cannot use steps'],
    },
    {
      key: 'walker',
      display_name: 'Walker or rollator',
      description: 'Avoids steps.',
      excludes_steps: true,
      max_incline_percent: null,
      min_width_m: null,
      prefers_gradient_under_percent: 10,
      prefers_width_over_m: 0.75,
      hard_requirements: ['cannot use steps'],
    },
    {
      key: 'crutches',
      display_name: 'Crutches or cane',
      description: 'Steps are possible but costly.',
      excludes_steps: false,
      max_incline_percent: null,
      min_width_m: null,
      prefers_gradient_under_percent: 15,
      prefers_width_over_m: null,
      hard_requirements: [],
    },
    {
      key: 'stroller',
      display_name: 'Stroller or pram',
      description: 'Avoids steps.',
      excludes_steps: true,
      max_incline_percent: null,
      min_width_m: null,
      prefers_gradient_under_percent: 12,
      prefers_width_over_m: 0.7,
      hard_requirements: ['cannot use steps'],
    },
    {
      key: 'reduced_mobility',
      display_name: 'Reduced mobility',
      description: 'Walks unaided but tires easily.',
      excludes_steps: false,
      max_incline_percent: null,
      min_width_m: null,
      prefers_gradient_under_percent: 15,
      prefers_width_over_m: null,
      hard_requirements: [],
    },
  ],
};

export const PROFILES_PATTERN = '**/api/v1/routes/profiles';

/**
 * Answer every route comparison with the payload above, re-anchored to the
 * points the caller actually asked about — and the profile list beside it.
 *
 * The distances and explanations stay fixed so assertions are stable, but the
 * geometry is rebuilt between the requested origin and destination. A stub with
 * hard-coded coordinates would send the camera somewhere else entirely and make
 * the screenshots evidence of nothing.
 */
export async function stubRouteComparison(page: Page): Promise<void> {
  await page.route(PROFILES_PATTERN, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(PROFILES),
    });
  });
  await page.route(COMPARE_PATTERN, async (route) => {
    const request = safeJson(route.request().postData());
    const origin = request?.origin ?? { longitude: -80.54, latitude: 43.47 };
    const destination = request?.destination ?? { longitude: -80.534, latitude: 43.47 };

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(comparisonFor(origin, destination)),
    });
  });
}

type Point = { longitude: number; latitude: number };

function safeJson(text: string | null): { origin?: Point; destination?: Point } | null {
  if (text === null) return null;
  try {
    return JSON.parse(text) as { origin?: Point; destination?: Point };
  } catch {
    return null;
  }
}

/**
 * Wait until MapLibre has finished loading.
 *
 * Every routing interaction needs a live map, and `[data-map-state]` is the
 * deterministic signal for that — far better than racing the canvas.
 */
export async function waitForMapReady(page: Page): Promise<void> {
  const frame = page.getByTestId('map-frame');
  await frame.waitFor({ state: 'visible' });
  await page.waitForFunction(
    () =>
      document.querySelector('[data-testid="map-frame"]')?.getAttribute('data-map-state') ===
      'ready',
    undefined,
    { timeout: 30_000 },
  );
}
