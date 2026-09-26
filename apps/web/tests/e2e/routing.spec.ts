import { expect, test } from '@playwright/test';
import {
  SCREENSHOT_DIR,
  hasHorizontalOverflow,
  stubHealthyApi,
  stubRouteComparison,
  waitForMapReady,
} from './fixtures';

/**
 * No route meets the profile: the API still returns the shortest route, with
 * the stairway it cannot use marked, and says why the profile's route failed.
 */
const NO_ACCESSIBLE_ROUTE = {
  profile: 'wheelchair',
  profile_display_name: 'Wheelchair',
  profile_description: 'Avoids steps entirely.',
  standard_route: {
    profile: 'standard',
    profile_display_name: 'Standard walking',
    distance_m: 120,
    effective_distance_m: 120,
    estimated_duration_seconds: 126,
    pace_profile: 'wheelchair',
    coordinates: [
      [-80.54, 43.47],
      [-80.5385, 43.47],
    ],
    segments: [
      {
        edge_identity: 'way/30:0-1',
        coordinates: [
          [-80.54, 43.47],
          [-80.5385, 43.47],
        ],
        length_m: 120,
        effective_metres: 120,
        cost_components: [],
        is_crossing: false,
        kerb: 'unknown',
        steps: 'yes',
        step_count: 22,
        surface_class: 'unknown',
        smoothness_class: 'unknown',
        excluded_by_profile: 'steps',
        unknown_attributes: ['surface', 'smoothness'],
      },
    ],
    origin: { longitude: -80.54, latitude: 43.47, distance_m: 2 },
    destination: { longitude: -80.5385, latitude: 43.47, distance_m: 2 },
    stairway_count: 1,
    step_count: 22,
    crossing_count: 0,
    unknown_kerb_crossing_count: 0,
    steepest_incline_percent: null,
    gradient: {
      steepest_uphill: null,
      steepest_downhill: null,
      recorded_fraction: 0,
      estimated_fraction: 0,
      unknown_fraction: 1,
    },
    unknown_data_fraction: 1,
    evidence_coverage: { surface: 1, smoothness: 1, gradient: 1, width: 1, kerb: 0 },
    computation_ms: 3,
  },
  accessible_route: null,
  standard_failure: null,
  accessible_failure: 'No route satisfies the wheelchair profile between these points.',
  extra_distance_m: null,
  extra_distance_fraction: null,
  explanations: [],
  cautions: [],
  dataset: {
    dataset_id: '0c9d1b3a-0000-4000-8000-000000000000',
    region: 'waterloo',
    checksum: 'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789',
    source_type: 'osm',
    source_name: 'openstreetmap:waterloo',
    acquired_at: '2026-08-12T00:00:00+00:00',
    attribution: '© OpenStreetMap contributors, ODbL 1.0',
  },
  routing_policy_version: 2,
  ml_predictions_used: false,
};

/**
 * The routing journey in a real browser.
 *
 * The comparison payload is stubbed at the network layer, so what is under test
 * is everything the browser does with it: clicking the map, drawing two lines,
 * rendering the written comparison, and re-requesting when the profile changes.
 * The backend's own behaviour is covered by its integration tests against real
 * PostGIS.
 */
test.describe('route comparison', () => {
  test.beforeEach(async ({ page }) => {
    await stubHealthyApi(page);
    await stubRouteComparison(page);
  });

  test('clicking the map twice produces a comparison', async ({ page }) => {
    await page.goto('/');
    await waitForMapReady(page);

    const [start, end] = await usableMapPoints(page);
    expect(start).toBeDefined();
    expect(end).toBeDefined();
    if (start === undefined || end === undefined) return;

    await page.mouse.click(start.x, start.y);
    await expect(page.getByTestId('endpoint-origin-value')).not.toContainText(/not set/i);

    await page.mouse.click(end.x, end.y);
    // Two points is a draft; the press is the request.
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'idle');

    await page.getByTestId('compare-routes').click();
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
  });

  test('shows both routes with their own figures', async ({ page }) => {
    await page.goto('/');
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    await expect(page.getByTestId('difference-accessible')).toContainText('709 m');
    await expect(page.getByTestId('difference-shortest')).toContainText('483 m');
  });

  test('states the trade-off the accessible route made', async ({ page }) => {
    await page.goto('/');
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    await expect(page.getByTestId('route-status')).toContainText(/226 m longer/);
    // The reason that decided it, above the fold, labelled with its evidence.
    const main = page.getByTestId('main-difference');
    await expect(main).toBeVisible();
    await expect(main).toContainText('Stairs');
    await expect(main).toContainText('Recorded');
    await expect(main).toContainText(/Avoids 1 recorded stairway/);
  });

  test('gives no travel time for a route the profile cannot use', async ({ page }) => {
    await page.goto('/');
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    const time = page.getByTestId('difference-shortest-time');
    await expect(time).toHaveText('Time unavailable for this profile');
    await expect(page.getByTestId('route-blocked')).toHaveText(
      'Ruled out: 1 stairway · 14 recorded steps',
    );
    await expect(page.getByTestId('difference-accessible-time')).toHaveText(/^Est\. \d+ min$/);
  });

  test('pins what the profile rules out to the map, where the response puts it', async ({
    page,
  }) => {
    await page.goto('/');
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    const barrier = page.getByTestId('map-marker-barrier-steps');
    await expect(barrier).toBeVisible();
    await expect(barrier).toHaveText('Ruled out: 1 stairway');
    // A repeat of the panel, so assistive technology hears it once.
    await expect(page.getByTestId('map-evidence')).toHaveAttribute('aria-hidden', 'true');
    await expect(page.getByTestId('legend-stairs')).toBeVisible();
  });

  test('re-frames the routes on request without asking for them again', async ({ page }) => {
    const requests: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/routes/compare')) requests.push(request.url());
    });
    await page.goto('/');
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    await page.mouse.move(700, 400);
    await page.mouse.wheel(0, 1200);
    await page.getByTestId('fit-routes').click();
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
    expect(requests).toHaveLength(1);
  });

  test('sends the traveller’s own uphill limit exactly, on the chosen preset', async ({ page }) => {
    const bodies: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/routes/compare')) {
        bodies.push(String(request.postData()));
      }
    });
    await page.goto('/');
    await waitForMapReady(page);
    await chooseTwoPoints(page);
    expect(JSON.parse(bodies[0]!)).not.toHaveProperty('custom');

    await page.getByTestId('uphill-limit-toggle').check();
    await page.getByTestId('uphill-limit-input').fill('5.5');
    await page.getByTestId('uphill-limit-input').press('Enter');

    await expect.poll(() => bodies.length).toBe(2);
    const sent = JSON.parse(bodies[1]!);
    expect(sent.profile).toBe('custom');
    expect(sent.custom).toEqual({ base: 'wheelchair', max_incline_percent: 5.5 });
  });

  test('says calmly when no route meets the profile, and loosens nothing', async ({ page }) => {
    await page.unroute('**/api/v1/routes/compare');
    await page.route('**/api/v1/routes/compare', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(NO_ACCESSIBLE_ROUTE),
      });
    });
    await page.goto('/');
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    const status = page.getByTestId('no-accessible-route');
    await expect(status).toContainText('No route meets the wheelchair profile');
    await expect(status).toContainText('does not loosen your profile’s limits');
    await expect(page.getByTestId('route-status').getByRole('alert')).toHaveCount(0);
    await expect(page.getByTestId('route-card-standard-time')).toHaveText(
      'Time unavailable for this profile',
    );
  });

  test('never implies a route is guaranteed or model-driven', async ({ page }) => {
    await page.goto('/');
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    await expect(page.getByText(/no predictions, no scoring, no machine learning/i)).toBeVisible();
    await expect(page.getByText(/Missing data is not evidence that a path is clear/)).toBeVisible();
  });

  test('changing the mobility profile requests a new comparison', async ({ page }) => {
    const requests: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/routes/compare')) {
        requests.push(String(request.postData()));
      }
    });

    await page.goto('/');
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    await page.getByRole('radio', { name: 'Crutches or cane' }).check();

    await expect.poll(() => requests.length).toBeGreaterThanOrEqual(2);
    expect(requests.at(-1)).toContain('"crutches"');
  });

  test('clearing removes both points', async ({ page }) => {
    await page.goto('/');
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    await page.getByTestId('clear-journey').click();

    await expect(page.getByTestId('endpoint-origin-value')).toContainText(/not set/i);
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'idle');
  });

  test('explains a failure instead of showing an empty panel', async ({ page }) => {
    await page.route('**/api/v1/routes/compare', async (route) => {
      await route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 'no_route',
          message: 'The origin is 812 m from the nearest mapped path.',
        }),
      });
    });

    await page.goto('/');
    await waitForMapReady(page);
    // Not `chooseTwoPoints`: that helper waits for success, which is exactly
    // what this test arranges not to happen. The press is still the request.
    await clickTwoPoints(page);
    await page.getByTestId('compare-routes').click();

    // Scoped to the planner: Next.js renders its own empty route announcer with
    // role="alert", so an unscoped query matches two elements.
    const failure = page.getByTestId('route-status').getByRole('alert');
    await expect(failure).toContainText(/812 m from the nearest mapped path/);
    await expect(page.getByRole('button', { name: /try again/i })).toBeVisible();
  });

  test('the map key explains the two lines in text, once there are two', async ({ page }) => {
    await page.goto('/');
    await waitForMapReady(page);

    // A key to two lines that do not exist yet is furniture sitting on the map.
    await expect(page.getByTestId('map-legend')).toHaveCount(0);

    await chooseTwoPoints(page);

    const legend = page.getByTestId('map-legend');
    await expect(legend).toBeVisible();
    await expect(legend).toContainText(/Route for your profile/i);
    await expect(legend).toContainText(/Shortest walking route/i);
  });

  test('place search is submit-only', async ({ page }) => {
    // Per-keystroke geocoding is forbidden by the provider's usage policy.
    const searches: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/geocode/search')) searches.push(request.url());
    });
    await page.route('**/api/v1/geocode/search', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ provider: 'disabled', enabled: false, matches: [] }),
      });
    });

    await page.goto('/');
    await page.getByRole('searchbox', { name: 'Start' }).fill('Waterloo Public Square');
    await page.waitForTimeout(500);

    expect(searches).toHaveLength(0);

    await page.getByRole('button', { name: 'Search for a start' }).click();
    await expect(page.getByText(/not enabled on this deployment/i)).toBeVisible();
  });
});

test.describe('visual evidence of a comparison', () => {
  test('the comparison is readable without sideways scrolling', async ({ page }) => {
    await stubHealthyApi(page);
    await stubRouteComparison(page);

    await page.goto('/');
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    await expect(page.getByTestId('difference-accessible')).toBeVisible();
    expect(await hasHorizontalOverflow(page)).toBe(false);
  });

  test('captures the comparison for visual review', async ({ page }, testInfo) => {
    // The project name is in the filename because both viewport projects run
    // this file: a shared path would mean whichever finished last silently
    // overwrote the other, and the "desktop" evidence would be a phone.
    await stubHealthyApi(page);
    await stubRouteComparison(page);

    await page.goto('/');
    await waitForMapReady(page);
    await chooseTwoPoints(page);
    await expect(page.getByTestId('difference-accessible')).toBeVisible();

    // Let the camera finish flying to the route before capturing. This is the
    // one place a fixed wait is right: `fitBounds` runs a timed animation, and
    // this test exists to produce a picture a person will look at, not to assert
    // a behaviour. Without it the capture can catch a half-flown camera with the
    // route outside the frame.
    await page.waitForTimeout(1_200);

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/${testInfo.project.name}-route-comparison.png`,
      fullPage: true,
    });
  });
});

/**
 * Two points to click, inside the part of the map the planner does not cover.
 *
 * That is the only part a person can click. The panel floats over one edge of
 * a full-bleed map — beside it on a laptop, across the bottom on a phone — so
 * a fixed fraction of the map *element* lands on the panel on one of the two
 * and stops being a map-click test at all.
 */
async function usableMapPoints(
  page: import('@playwright/test').Page,
): Promise<Array<{ x: number; y: number }>> {
  const box = await page.getByTestId('map-frame').boundingBox();
  const panel = await page.getByRole('complementary', { name: /route planner/i }).boundingBox();
  if (box === null) throw new Error('map frame has no layout box');

  // Shrink the map box away from whichever edge the panel is against.
  const { y } = box;
  let { x, width, height } = box;
  if (panel !== null) {
    const fromLeft = panel.x + panel.width - x;
    const fromBottom = y + height - panel.y;
    if (fromLeft > 0 && fromLeft < width / 2) {
      x += fromLeft;
      width -= fromLeft;
    } else if (fromBottom > 0 && fromBottom < height) {
      height -= fromBottom;
    }
  }

  if (width < 40 || height < 40) throw new Error('no usable map area outside the planner');

  return [0.3, 0.7].map((fraction) => ({ x: x + width * fraction, y: y + height * 0.5 }));
}

/** Click a start and an end on the map, without waiting for any outcome. */
async function clickTwoPoints(page: import('@playwright/test').Page): Promise<void> {
  for (const point of await usableMapPoints(page)) {
    await page.mouse.click(point.x, point.y);
  }
}

/**
 * Click two points, ask for the comparison, and wait for it.
 *
 * The press is the request now. Placing points is drafting a journey; it used
 * to fire the moment two coordinates existed, which is wrong once an endpoint
 * is a named place somebody may still be typing.
 */
async function chooseTwoPoints(page: import('@playwright/test').Page): Promise<void> {
  await clickTwoPoints(page);
  await page.getByTestId('compare-routes').click();
  await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
}
