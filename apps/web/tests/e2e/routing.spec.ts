import { expect, test, type Page } from '@playwright/test';
import {
  PLANNER,
  SCREENSHOT_DIR,
  hasHorizontalOverflow,
  isPhone,
  openJourneyControls,
  runExample,
  stubHealthyApi,
  stubNoRoute,
  stubRouteComparison,
  waitForMapReady,
} from './fixtures';

/**
 * The routing journey in a real browser.
 *
 * The comparison payload is stubbed at the network layer, so what is under test
 * is everything the browser does with it: clicking the map, drawing two lines,
 * stating the comparison in text, and re-requesting when the profile changes.
 * The backend's own behaviour is covered by its integration tests against real
 * PostGIS. Every test runs on the desktop composition (9:1905) and the phone's
 * (17:2865); where they differ, each says what its own layout shows.
 */
test.describe('route comparison', () => {
  test.beforeEach(async ({ page }) => {
    await stubHealthyApi(page);
    await stubRouteComparison(page);
  });

  test('clicking the map twice drafts a journey; Compare asks for it', async ({ page }) => {
    await page.goto(PLANNER);
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
    await expect(page.getByTestId('route-workspace')).toHaveAttribute('data-layout', 'compare');
  });

  test('shows both routes with their own figures', async ({ page }) => {
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    await expect(page.getByTestId('difference-accessible')).toContainText('709 m');
    await expect(page.getByTestId('difference-shortest')).toContainText('483 m');
  });

  test('states the trade-off and the reason that decided it', async ({ page }) => {
    // At the frame's own height the dock draws all four categories; shorter
    // windows slim it to a bar (see layout.spec.ts).
    if (!isPhone(page)) await page.setViewportSize({ width: 1280, height: 1152 });
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    if (isPhone(page)) {
      await expect(page.getByTestId('difference-extra')).toContainText('+226.0 m');
      await expect(page.getByTestId('mobile-stairs')).toContainText('0 recorded stairways');
      await expect(page.getByTestId('mobile-stairs')).toContainText('1 on shortest');
      return;
    }
    await expect(page.getByTestId('difference-extra')).toHaveText('+226 m detour');
    // The engine's own statement, word for word.
    await expect(page.getByTestId('main-difference')).toContainText(
      'Avoids 1 recorded stairway on the shortest route (14 steps in total)',
    );
    // And the four categories against the shortest route, each labelled.
    await expect(page.getByTestId('dock-stairs')).toContainText('Your profile rule');
    await expect(page.getByTestId('dock-grade')).toContainText('Recorded · OSM');
  });

  test('gives no travel time for a route the profile cannot use', async ({ page }) => {
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    const shortest = page.getByTestId('difference-shortest');
    await expect(page.getByTestId('route-blocked')).toContainText('1 recorded stairway');
    await expect(shortest).not.toContainText(/Est\. \d+ min/);
    if (!isPhone(page)) {
      await expect(page.getByTestId('difference-shortest-time')).toHaveText(
        'Time unavailable for this profile',
      );
      await expect(page.getByTestId('difference-accessible-time')).toHaveText(/^Est\. \d+ min$/);
    } else {
      await expect(page.getByTestId('route-blocked')).toContainText('14 recorded steps');
      await expect(shortest).toContainText('Incompatible with Wheelchair profile');
    }
  });

  test('pins what the profile rules out to the map, as text', async ({ page }) => {
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    if (isPhone(page)) {
      await expect(page.getByTestId('map-marker-badge-steps')).toHaveText('1 stairway');
    } else {
      const barrier = page.getByTestId('map-marker-barrier-steps');
      await expect(barrier).toBeVisible();
      await expect(barrier).toContainText('1 recorded stairway');
      await expect(barrier).toContainText('Recorded · OSM');
    }
    // A repeat of the panel, so assistive technology hears it once.
    await expect(page.getByTestId('map-evidence')).toHaveAttribute('aria-hidden', 'true');
  });

  test('re-frames the routes on request without asking for them again', async ({ page }) => {
    const requests: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/routes/compare')) requests.push(request.url());
    });
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    await page.getByTestId('fit-routes').click();
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
    expect(requests).toHaveLength(1);
  });

  test('a typed uphill limit is sent exactly as typed', async ({ page }) => {
    const bodies: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/routes/compare')) bodies.push(String(request.postData()));
    });
    await page.goto(PLANNER);
    await waitForMapReady(page);

    await page.getByTestId('uphill-limit-toggle').check();
    await page.getByTestId('uphill-limit-input').fill('5.5');
    await clickTwoPoints(page);
    await page.getByTestId('compare-routes').click();

    await expect.poll(() => bodies.length).toBe(1);
    const sent = JSON.parse(bodies[0]!);
    expect(sent.profile).toBe('custom');
    expect(sent.custom).toEqual({ base: 'wheelchair', max_incline_percent: 5.5 });
  });

  test('beside an answer, the uphill slider re-runs once it is set', async ({ page }) => {
    const bodies: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/routes/compare')) bodies.push(String(request.postData()));
    });
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await chooseTwoPoints(page);
    expect(JSON.parse(bodies[0]!)).not.toHaveProperty('custom');

    await openJourneyControls(page);
    await page.getByTestId('uphill-limit-toggle').click();
    await expect.poll(() => bodies.length).toBe(2);
    expect(JSON.parse(bodies[1]!).custom).toEqual({ base: 'wheelchair', max_incline_percent: 5 });
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');

    // The keyboard moves the slider half a percent and sets it on release.
    await openJourneyControls(page);
    await page.getByTestId('uphill-limit-range').focus();
    await page.keyboard.press('ArrowRight');
    await expect.poll(() => bodies.length).toBe(3);
    expect(JSON.parse(bodies[2]!).custom).toEqual({
      base: 'wheelchair',
      max_incline_percent: 5.5,
    });
  });

  test('says when no route meets the profile, and loosens nothing', async ({ page }) => {
    await stubNoRoute(page);
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    await expect(page.getByTestId('route-workspace')).toHaveAttribute('data-layout', 'no-route');
    const status = page.getByTestId('no-accessible-route');
    await expect(status).toContainText('No route satisfies your profile requirements');
    await expect(status).toContainText('It will not silently relax them.');
    await expect(status).toContainText('No route satisfies the wheelchair profile');
    // A fact about the shortest route the engine returned, labelled.
    const stairs = page.getByTestId('requirement-steps');
    await expect(stairs).toContainText('uses 1 recorded stairway');
    await expect(stairs).toContainText('Recorded · OSM');
    await expect(page.getByTestId('route-status').getByRole('alert')).toHaveCount(0);
  });

  test('the full record says no model was involved, and that missing is not clear', async ({
    page,
  }) => {
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    const opener = page.getByTestId('open-route-details');
    await opener.click();
    const sheet = page.getByRole('dialog', { name: 'Route details' });
    await expect(sheet).toBeVisible();
    await expect(page.getByTestId('close-route-details')).toBeFocused();
    await expect(sheet).toContainText(/no predictions, no scoring, no machine learning/i);
    await expect(sheet).toContainText(/Missing data is not evidence that a path is clear/);
    await expect(sheet).toContainText('© OpenStreetMap contributors, ODbL 1.0');

    await page.keyboard.press('Escape');
    await expect(sheet).toBeHidden();
    await expect(opener).toBeFocused();
  });

  test('one route’s evidence, with its gaps, and back again', async ({ page }) => {
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    await page.getByTestId('view-evidence').click();
    if (isPhone(page)) {
      // The phone opens the full record at its evidence section.
      await expect(page.getByRole('dialog', { name: 'Route evidence' })).toBeVisible();
      await expect(page.getByTestId('evidence-coverage')).toBeVisible();
      return;
    }
    await expect(page.getByTestId('route-workspace')).toHaveAttribute('data-layout', 'evidence');
    await expect(page.getByTestId('gap-banner')).toContainText('not an accessibility guarantee');
    await expect(page.getByTestId('gap-dock')).toContainText('no aggregate confidence score');
    await page.getByRole('button', { name: 'Back to the route comparison' }).click();
    await expect(page.getByTestId('route-workspace')).toHaveAttribute('data-layout', 'compare');
  });

  test('changing the mobility profile requests a new comparison', async ({ page }) => {
    const requests: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/routes/compare')) {
        requests.push(String(request.postData()));
      }
    });

    await page.goto(PLANNER);
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    await openJourneyControls(page);
    await page.getByRole('radio', { name: /^Crutches or cane/ }).check();

    await expect.poll(() => requests.length).toBeGreaterThanOrEqual(2);
    expect(requests.at(-1)).toContain('"crutches"');
  });

  test('clearing removes both points and the answer', async ({ page }) => {
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await chooseTwoPoints(page);

    await openJourneyControls(page);
    await page.getByTestId('clear-journey').click();

    await expect(page.getByTestId('endpoint-origin-value')).toContainText(/not set/i);
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'idle');
    await expect(page.getByTestId('route-workspace')).toHaveAttribute('data-layout', 'plan');
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

    await page.goto(PLANNER);
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

    await page.goto(PLANNER);
    await page.getByLabel('Start location').fill('Waterloo Public Square');
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

    await page.goto(PLANNER);
    await waitForMapReady(page);
    await runExample(page);

    await expect(page.getByTestId('difference-accessible')).toBeVisible();
    expect(await hasHorizontalOverflow(page)).toBe(false);
  });

  test('captures the comparison for visual review', async ({ page }, testInfo) => {
    // The project name is in the filename because both viewport projects run
    // this file: a shared path would let one silently overwrite the other.
    await stubHealthyApi(page);
    await stubRouteComparison(page);

    await page.goto(PLANNER);
    await waitForMapReady(page);
    await runExample(page);
    await expect(page.getByTestId('difference-accessible')).toBeVisible();

    // Let the camera finish flying to the route before capturing: `fitBounds`
    // runs a timed animation, and this test exists to produce a picture.
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
 * The panel floats over the map's left edge on a laptop and starts under it on
 * a phone, so a fixed fraction of the map element can land on the panel and
 * stop being a map-click test at all.
 */
async function usableMapPoints(page: Page): Promise<Array<{ x: number; y: number }>> {
  const box = await page.getByTestId('map-frame').boundingBox();
  const panel = await page.getByRole('complementary', { name: /route planner/i }).boundingBox();
  if (box === null) throw new Error('map frame has no layout box');

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

  // Clear of the map's own controls, which sit along its right edge.
  return [0.25, 0.6].map((fraction) => ({ x: x + width * fraction, y: y + height * 0.55 }));
}

/** Click a start and an end on the map, without waiting for any outcome. */
async function clickTwoPoints(page: Page): Promise<void> {
  // On a phone the form scrolls the map away; points are clicked on the map.
  await page.evaluate(() => window.scrollTo(0, 0));
  for (const point of await usableMapPoints(page)) {
    await page.mouse.click(point.x, point.y);
  }
}

/** Click two points, ask for the comparison, and wait for it. */
async function chooseTwoPoints(page: Page): Promise<void> {
  await clickTwoPoints(page);
  await page.getByTestId('compare-routes').click();
  await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
}
