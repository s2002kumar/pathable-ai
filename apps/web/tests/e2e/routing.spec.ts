import { expect, test } from '@playwright/test';
import {
  SCREENSHOT_DIR,
  hasHorizontalOverflow,
  stubHealthyApi,
  stubRouteComparison,
  waitForMapReady,
} from './fixtures';

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

    const map = page.getByTestId('map-frame');
    const box = await map.boundingBox();
    expect(box).not.toBeNull();
    if (box === null) return;

    await map.click({ position: { x: box.width * 0.35, y: box.height * 0.5 } });
    await expect(page.getByTestId('point-start')).not.toContainText(/click the map to set/i);

    await map.click({ position: { x: box.width * 0.65, y: box.height * 0.5 } });

    await expect(page.getByTestId('route-status')).toHaveAttribute(
      'data-route-state',
      'success',
    );
  });

  test('shows both routes with their own figures', async ({ page }) => {
    await page.goto('/');
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    await expect(page.getByTestId('route-card-accessible')).toContainText('709 m');
    await expect(page.getByTestId('route-card-standard')).toContainText('483 m');
  });

  test('states the trade-off the accessible route made', async ({ page }) => {
    await page.goto('/');
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    await expect(page.getByTestId('route-status')).toContainText(/226 m longer/);
    await expect(page.getByText(/Avoids 1 stairway/)).toBeVisible();
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

    await page.getByRole('radio', { name: /Crutches or cane/ }).check();

    await expect.poll(() => requests.length).toBeGreaterThanOrEqual(2);
    expect(requests.at(-1)).toContain('"crutches"');
  });

  test('clearing removes both points', async ({ page }) => {
    await page.goto('/');
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    await page.getByRole('button', { name: 'Clear' }).click();

    await expect(page.getByTestId('point-start')).toContainText(/click the map to set/i);
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
    // what this test arranges not to happen.
    await clickTwoPoints(page);

    // Scoped to the planner: Next.js renders its own empty route announcer with
    // role="alert", so an unscoped query matches two elements.
    const failure = page.getByTestId('route-status').getByRole('alert');
    await expect(failure).toContainText(/812 m from the nearest mapped path/);
    await expect(page.getByRole('button', { name: /try again/i })).toBeVisible();
  });

  test('the map key explains the two lines in text', async ({ page }) => {
    await page.goto('/');
    await waitForMapReady(page);

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
    await page.getByRole('searchbox').fill('Waterloo Public Square');
    await page.waitForTimeout(500);

    expect(searches).toHaveLength(0);

    await page.getByRole('button', { name: 'Search' }).click();
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

    await expect(page.getByTestId('route-card-accessible')).toBeVisible();
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
    await expect(page.getByTestId('route-card-accessible')).toBeVisible();

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

/** Click a start and an end on the map, without waiting for any outcome. */
async function clickTwoPoints(page: import('@playwright/test').Page): Promise<void> {
  const map = page.getByTestId('map-frame');
  const box = await map.boundingBox();
  if (box === null) throw new Error('map frame has no layout box');

  await map.click({ position: { x: box.width * 0.35, y: box.height * 0.5 } });
  await map.click({ position: { x: box.width * 0.65, y: box.height * 0.5 } });
}

/** Click two points and wait for the comparison to arrive. */
async function chooseTwoPoints(page: import('@playwright/test').Page): Promise<void> {
  await clickTwoPoints(page);
  await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
}
