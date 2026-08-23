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
 * The geometry is the synthetic fixture's: a short route across a stairway
 * versus a longer step-free one.
 */
const COMPARISON = {
  profile: 'wheelchair',
  profile_display_name: 'Wheelchair',
  profile_description: 'Avoids steps entirely.',
  standard_route: {
    profile: 'standard',
    profile_display_name: 'Standard walking',
    distance_m: 483,
    effective_distance_m: 483,
    estimated_duration_seconds: 380,
    coordinates: [
      [-80.54, 43.47],
      [-80.538, 43.47],
      [-80.536, 43.47],
      [-80.534, 43.47],
    ],
    segments: [],
    origin: { longitude: -80.54, latitude: 43.47, distance_m: 2 },
    destination: { longitude: -80.534, latitude: 43.47, distance_m: 3 },
    stairway_count: 1,
    step_count: 14,
    crossing_count: 1,
    unknown_kerb_crossing_count: 1,
    steepest_incline_percent: null,
    unknown_data_fraction: 0.22,
    computation_ms: 4,
  },
  accessible_route: {
    profile: 'wheelchair',
    profile_display_name: 'Wheelchair',
    distance_m: 709,
    effective_distance_m: 980,
    estimated_duration_seconds: 746,
    coordinates: [
      [-80.54, 43.47],
      [-80.538, 43.47],
      [-80.537, 43.469],
      [-80.536, 43.47],
      [-80.535, 43.471],
      [-80.534, 43.47],
    ],
    segments: [],
    origin: { longitude: -80.54, latitude: 43.47, distance_m: 2 },
    destination: { longitude: -80.534, latitude: 43.47, distance_m: 3 },
    stairway_count: 0,
    step_count: 0,
    crossing_count: 1,
    unknown_kerb_crossing_count: 0,
    steepest_incline_percent: 4,
    unknown_data_fraction: 0.31,
    computation_ms: 6,
  },
  standard_failure: null,
  accessible_failure: null,
  extra_distance_m: 226,
  extra_distance_fraction: 0.468,
  explanations: [
    {
      code: 'avoids_stairs',
      summary: 'Avoids 1 stairway (14 steps in total).',
      evidence: { stairway_count: 1, step_count: 14 },
    },
    {
      code: 'avoids_unrecorded_kerbs',
      summary:
        'Avoids 1 crossing where no kerb has been recorded, so nobody has confirmed it is dropped.',
      evidence: { crossing_count: 1 },
    },
  ],
  cautions: [
    {
      code: 'missing_accessibility_data',
      summary:
        'OpenStreetMap has no accessibility details for some of this route (31% of its length). ' +
        'Missing data is not evidence that a path is clear.',
      evidence: { unknown_data_fraction: 0.31 },
    },
  ],
  dataset: {
    dataset_id: '0c9d1b3a-0000-4000-8000-000000000000',
    region: 'waterloo',
    checksum: 'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789',
    source_type: 'osm',
    source_name: 'openstreetmap:waterloo',
    acquired_at: '2026-08-12T00:00:00+00:00',
    attribution: '© OpenStreetMap contributors, ODbL 1.0',
  },
  ml_predictions_used: false,
};

/**
 * Answer every route comparison with the payload above, re-anchored to the
 * points the caller actually asked about.
 *
 * The distances and explanations stay fixed so assertions are stable, but the
 * geometry is rebuilt between the requested origin and destination. A stub with
 * hard-coded coordinates would send the camera somewhere else entirely and make
 * the screenshots evidence of nothing.
 */
export async function stubRouteComparison(page: Page): Promise<void> {
  await page.route(COMPARE_PATTERN, async (route) => {
    const request = safeJson(route.request().postData());
    const origin = request?.origin ?? { longitude: -80.54, latitude: 43.47 };
    const destination = request?.destination ?? { longitude: -80.534, latitude: 43.47 };

    const straight: Array<[number, number]> = [
      [origin.longitude, origin.latitude],
      [destination.longitude, destination.latitude],
    ];
    // A dogleg south then north, so the two routes are visibly different rather
    // than one line drawn on top of another.
    const offset = destination.latitude - origin.latitude || 0.0008;
    const detour: Array<[number, number]> = [
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

    const body = {
      ...COMPARISON,
      standard_route: {
        ...COMPARISON.standard_route,
        coordinates: straight,
        origin: { ...origin, distance_m: 2 },
        destination: { ...destination, distance_m: 3 },
      },
      accessible_route: {
        ...COMPARISON.accessible_route,
        coordinates: detour,
        origin: { ...origin, distance_m: 2 },
        destination: { ...destination, distance_m: 3 },
      },
    };

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
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
