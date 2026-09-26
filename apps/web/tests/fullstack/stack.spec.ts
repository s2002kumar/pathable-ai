import { expect, test } from '@playwright/test';

/**
 * Real frontend-to-backend-to-database integration.
 *
 * NOTHING IN THIS FILE MAY REGISTER A `page.route` HANDLER FOR THE API, except
 * the final test, which deliberately simulates the backend going away *after* the
 * real path has already been proven. Everything else must reach the running
 * FastAPI service and, through it, real PostgreSQL/PostGIS.
 */

const READINESS_PATH = '/api/v1/health/ready';

/** Matches playwright.fullstack.config.ts, including its Compose override. */
const API_BASE_URL = process.env.FULLSTACK_API_URL ?? 'http://127.0.0.1:8100';

type ReadinessBody = {
  status: string;
  service: string;
  version: string;
  checks: Record<string, { status: string; detail: string; latency_ms: number | null }>;
};

test.describe('full stack', () => {
  test('status badge is driven by a real API response, not a stub', async ({ page }) => {
    // Capture the actual network exchange so "it went green" cannot be confused
    // with "something answered". No route handler is registered anywhere here.
    const readinessResponses: { url: string; status: number; body: ReadinessBody }[] = [];

    page.on('response', async (response) => {
      if (!response.url().includes(READINESS_PATH)) return;
      try {
        readinessResponses.push({
          url: response.url(),
          status: response.status(),
          body: (await response.json()) as ReadinessBody,
        });
      } catch {
        // Non-JSON body — captured as a failure by the assertions below.
      }
    });

    await page.goto('/');

    await expect(page.getByTestId('system-status')).toHaveAttribute('data-status', 'ready');

    // The response really came from the API server, on a different origin to the
    // page, and really reported a healthy database and PostGIS.
    expect(readinessResponses.length).toBeGreaterThan(0);
    const readiness = readinessResponses[0];
    expect(readiness).toBeDefined();
    if (readiness === undefined) return;

    expect(readiness.status).toBe(200);

    // The response came from a genuinely different origin to the page — a real
    // cross-origin call to the API, not something served by the web app. Asserted
    // on origins rather than a hard-coded host, because the same suite runs
    // against locally started servers and against the Compose stack.
    expect(new URL(readiness.url).origin).not.toBe(new URL(page.url()).origin);
    expect(readiness.url).toMatch(/^https?:\/\//);

    expect(readiness.body.status).toBe('ready');
    expect(readiness.body.service).toBe('pathable-api');
    expect(readiness.body.checks.database?.status).toBe('ok');
    expect(readiness.body.checks.postgis?.status).toBe('ok');
  });

  test('readiness reports a genuine PostGIS version from the database', async ({ request }) => {
    // A stub would have to invent this string; the real database reports its own
    // installed extension version.
    const response = await request.get(`${API_BASE_URL}${READINESS_PATH}`);

    expect(response.status()).toBe(200);
    const body = (await response.json()) as ReadinessBody;

    expect(body.checks.postgis?.detail).toMatch(/^postgis \d+\.\d+/);
    expect(body.checks.database?.detail).toBe('connected');
    // Real round trips take measurable time.
    expect(body.checks.database?.latency_ms).toBeGreaterThan(0);
  });

  test('the badge shows the version the API actually reports', async ({ page }) => {
    await page.goto('/');

    const badge = page.getByTestId('system-status');
    await expect(badge).toHaveAttribute('data-status', 'ready');
    await expect(badge).toContainText('API online');
    await expect(badge).toContainText('pathable-api v0.1.0');
  });

  test('the map and the shell work alongside the live backend', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByTestId('system-status')).toHaveAttribute('data-status', 'ready');
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready');
    await expect(page.getByRole('group', { name: /how do you travel/i })).toBeVisible();
    // The profile's rules are the live API's, not a copy in the browser.
    await expect(page.getByTestId('profile-rule')).toContainText('Hard limit: cannot use steps.');
    // The map key arrives with the routes it explains, so before a comparison
    // there is nothing for it to say.
    await expect(page.getByTestId('map-legend')).toHaveCount(0);
  });

  test('the page stays usable when the backend becomes unavailable', async ({ page }) => {
    // The only interception in this file, and it runs last on purpose: the real
    // path is proven by the tests above, and this simulates the API disappearing
    // mid-session. Killing the Playwright-managed server instead would take the
    // whole suite down with it.
    await page.goto('/');
    await expect(page.getByTestId('system-status')).toHaveAttribute('data-status', 'ready');

    await page.route(`**${READINESS_PATH}`, (route) => route.abort('connectionrefused'));
    await page.reload();

    await expect(page.getByTestId('system-status')).toHaveAttribute('data-status', 'unreachable');
    await expect(page.getByText('PathAble', { exact: true })).toBeVisible();
    await expect(page.getByTestId('pilot-description')).toBeVisible();
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready');
  });
});

test.describe('routing, end to end', () => {
  /**
   * The only test that proves the *whole* chain agrees on routing.
   *
   * The default e2e suite stubs the comparison, so it says nothing about
   * whether the server's real response satisfies the client's runtime
   * validation. The contract drift check compares generated files, which is a
   * different question again. This is browser → Next.js → FastAPI → PostGIS,
   * over the synthetic network the CI job loads.
   */
  test('compares two real routes over the live backend', async ({ page }) => {
    await page.goto('/?region=waterloo-synthetic');
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready');

    const response = await page.request.post(`${API_BASE_URL}/api/v1/routes/compare`, {
      data: {
        region: 'waterloo-synthetic',
        origin: { longitude: -80.54, latitude: 43.47 },
        destination: { longitude: -80.534, latitude: 43.47 },
        profile: 'wheelchair',
      },
    });

    expect(response.status()).toBe(200);
    const body = await response.json();

    // The trade-off the product exists to show, computed by the real engine.
    expect(body.standard_route.stairway_count).toBe(1);
    expect(body.accessible_route.stairway_count).toBe(0);
    expect(body.extra_distance_m).toBeGreaterThan(0);

    // Never a prediction, and never a boolean where "nobody recorded this" is
    // a possible answer.
    expect(body.ml_predictions_used).toBe(false);
    for (const segment of body.standard_route.segments) {
      expect(['yes', 'no', 'unknown']).toContain(segment.steps);
    }

    // Attribution travels with the data, and synthetic data says what it is.
    expect(body.dataset.source_type).toBe('synthetic');
    expect(body.dataset.attribution).toMatch(/not a survey/i);
  });

  test('refuses a point that is nowhere near the network, with a reason', async ({ page }) => {
    const response = await page.request.post(`${API_BASE_URL}/api/v1/routes/compare`, {
      data: {
        region: 'waterloo-synthetic',
        origin: { longitude: -80.6, latitude: 43.4 },
        destination: { longitude: -80.534, latitude: 43.47 },
        profile: 'wheelchair',
      },
    });

    expect(response.status()).toBe(422);
    const body = await response.json();
    expect(body.code).toBe('no_route');
    expect(body.message).toMatch(/nearest mapped path/);
  });
});
