/**
 * The demo, driven end to end against the real containers.
 *
 * Nothing is stubbed here and nothing may be: the point of the exercise is that
 * a viewer presses one button and the live engine answers. These tests watch the
 * network to prove the request actually happened, then assert that the answer on
 * screen is the answer the API sent — so a preset that quietly hardcoded a route
 * would fail rather than look impressive.
 *
 * Run against a running Compose stack:
 *
 *   FULLSTACK_TARGET=compose FULLSTACK_WEB_URL=http://localhost:3001 \
 *   FULLSTACK_API_URL=http://localhost:8001 \
 *     pnpm --filter @pathable/web exec playwright test --config=playwright.fullstack.config.ts
 */
import { expect, test, type Page, type Request } from '@playwright/test';

const COMPARE_PATH = '/api/v1/routes/compare';
const PLANNER = '/planner';

/** Matches playwright.fullstack.config.ts, including its Compose override. */
const API_BASE_URL = process.env.FULLSTACK_API_URL ?? 'http://127.0.0.1:8100';

/** The journey the example loads, as the corpus records it. */
const CAMPUS = {
  region: 'waterloo',
  origin: { longitude: -80.5424, latitude: 43.4728 },
  destination: { longitude: -80.5449, latitude: 43.4715 },
  profile: 'wheelchair',
};

type Answer = {
  standard_route: { distance_m: number; stairway_count: number };
  accessible_route: { distance_m: number; stairway_count: number };
  extra_distance_m: number;
  ml_predictions_used: boolean;
};

/**
 * This suite needs the real Waterloo network, which is a 970 MB extract and
 * hours of ingestion. CI loads the nine-node synthetic fixture instead, so
 * these tests skip there rather than failing — and say so, because a silent
 * skip would let the demo rot unnoticed.
 *
 * Where they do run: locally, against the production-smoke stack, which is the
 * environment the demo is actually given in. See docs/evidence/DEMO_SCRIPT.md.
 */
let waterlooLoaded = false;

test.beforeAll(async ({ request }) => {
  const response = await request.post(`${API_BASE_URL}${COMPARE_PATH}`, {
    data: CAMPUS,
    failOnStatusCode: false,
  });
  waterlooLoaded = response.status() === 200;
  if (!waterlooLoaded) {
    console.warn(
      `[recruiter-demo] skipping: ${API_BASE_URL} has no routable Waterloo dataset ` +
        `(POST ${COMPARE_PATH} returned ${response.status()}). Run the production-smoke ` +
        `stack to exercise these.`,
    );
  }
});

test.beforeEach(() => {
  test.skip(
    !waterlooLoaded,
    'needs the real Waterloo dataset; run against the production-smoke stack',
  );
});

async function openPlanner(page: Page): Promise<void> {
  await page.goto(PLANNER);
  await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready');
}

/** Press the example and return the request the browser actually made. */
async function runExample(page: Page): Promise<{ request: Request; answer: Answer }> {
  const waitForCompare = page.waitForRequest(
    (request) => request.url().includes(COMPARE_PATH) && request.method() === 'POST',
  );
  const waitForAnswer = page.waitForResponse(
    (response) => response.url().includes(COMPARE_PATH) && response.status() === 200,
  );

  await page.getByTestId('run-verified-example').click();

  const request = await waitForCompare;
  const response = await waitForAnswer;
  await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
  return { request, answer: (await response.json()) as Answer };
}

test.describe('the recruiter demo', () => {
  test('one press produces a live comparison, not a recording', async ({ page }) => {
    await openPlanner(page);

    const { request, answer } = await runExample(page);

    // The preset supplied inputs, and only inputs.
    const sent = request.postDataJSON() as Record<string, unknown>;
    expect(sent.profile).toBe('wheelchair');
    expect(sent.region).toBe('waterloo');
    expect(sent.origin).toEqual(CAMPUS.origin);
    expect(sent.destination).toEqual(CAMPUS.destination);

    // The engine answered, and the answer is a real comparison.
    const stairways = answer.standard_route.stairway_count;
    expect(stairways).toBeGreaterThan(0);
    expect(answer.accessible_route.stairway_count).toBe(0);
    expect(answer.accessible_route.distance_m).toBeGreaterThan(answer.standard_route.distance_m);
    expect(answer.ml_predictions_used).toBe(false);

    // And the page is showing that answer, not a different one.
    await expect(page.getByTestId('difference-shortest')).toContainText(
      `${Math.round(answer.standard_route.distance_m)} m`,
    );
    await expect(page.getByTestId('difference-accessible')).toContainText(
      `${Math.round(answer.accessible_route.distance_m)} m`,
    );
    await expect(page.getByTestId('difference-extra')).toHaveText(
      `+${Math.round(answer.extra_distance_m)} m detour`,
    );
    await expect(page.getByTestId('main-difference')).toContainText(
      `Avoids ${stairways} recorded stairways`,
    );

    // The shortest route crosses stairs a wheelchair cannot use, so it gets no
    // travel time — read from the segments the live API marks, not the count.
    await expect(page.getByTestId('difference-shortest-time')).toHaveText(
      'Time unavailable for this profile',
    );
    await expect(page.getByTestId('route-blocked')).toContainText(
      `${stairways} recorded stairways`,
    );
    await expect(page.getByTestId('map-marker-barrier-steps')).toContainText(
      `${stairways} recorded stairways`,
    );
  });

  test('every category is labelled by its evidence, and unknowns stay unknown', async ({
    page,
  }) => {
    await openPlanner(page);
    await runExample(page);

    // The four categories against the shortest route, each with its label.
    await expect(page.getByTestId('dock-stairs')).toContainText('Recorded · OSM');
    await expect(page.getByTestId('dock-stairs')).toContainText('Your profile rule');
    await expect(page.getByTestId('dock-grade')).toContainText(/Recorded · OSM|Derived · HRDEM/);
    const dock = page.getByTestId('evidence-dock');
    await expect(dock).not.toContainText(/\b(verified|safe|guaranteed|confident|score)\b/i);

    // The full record: every statement's label comes from its basis. A reason
    // about missing records is never labelled as a recorded one (D6).
    await page.getByTestId('open-route-details').click();
    const sheet = page.getByRole('dialog', { name: 'Route details' });
    const reasons = sheet.getByTestId('difference-reasons');
    for (const reason of await reasons.locator('li[data-basis="recorded"]').all()) {
      await expect(reason.locator('span').first()).toHaveText('Recorded');
    }
    for (const reason of await reasons.locator('li[data-basis="not_recorded"]').all()) {
      await expect(reason.locator('span').first()).toHaveText('Not recorded');
    }
    const coverage = sheet.getByTestId('evidence-coverage');
    await expect(coverage).toContainText(/not recorded is not the same as clear/i);
    await expect(coverage).not.toContainText(/\b(verified|safe|guaranteed|confident)\b/i);
  });

  test('the gaps in the record are on screen without scrolling', async ({ page }) => {
    await openPlanner(page);
    await runExample(page);

    // Per category, never as one figure: the surface record says how much of
    // the route has no surface on record.
    const surface = page.getByTestId('dock-surface');
    await expect(surface).toContainText(/not recorded/);
    await expect(surface).toBeInViewport({ ratio: 1 });

    // And the route's own record is one press away, with its gaps drawn.
    await page.getByTestId('view-evidence').click();
    await expect(page.getByTestId('gap-banner')).toContainText(
      'Route found with accessibility data gaps',
    );
    await expect(page.getByTestId('gap-banner')).toContainText('not an accessibility guarantee');
  });

  test('both routes are drawn, and named in words beside the map', async ({ page }) => {
    await openPlanner(page);
    await runExample(page);

    // Colour is never the only cue: each line's card names its route.
    await expect(page.getByTestId('difference-accessible')).toContainText('Wheelchair route');
    await expect(page.getByTestId('difference-shortest')).toContainText(
      'Shortest pedestrian route',
    );
  });

  test('the deep link, at either address, starts the same live request', async ({ page }) => {
    for (const address of [
      '/planner?example=campus-library-to-student-life',
      '/?example=campus-library-to-student-life',
    ]) {
      const waitForCompare = page.waitForRequest(
        (request) => request.url().includes(COMPARE_PATH) && request.method() === 'POST',
      );
      await page.goto(address);

      const sent = (await waitForCompare).postDataJSON() as Record<string, unknown>;
      expect(sent.origin).toEqual(CAMPUS.origin);
      await expect(page).toHaveURL(/\/planner\?example=/);
      await expect(page.getByTestId('route-difference')).toBeVisible();
    }
  });

  test('attribution travels with the result', async ({ page }) => {
    await openPlanner(page);
    await runExample(page);

    // The map data licence and the elevation licence, on the page and in the answer.
    const credit = page.getByTestId('attribution');
    await expect(credit).toContainText('OpenStreetMap');
    await expect(credit).toContainText('ODbL');
    await expect(credit).toContainText('Open Government Licence – Canada');
    await page.getByTestId('open-route-details').click();
    await expect(page.getByTestId('elevation-attribution')).toContainText(
      /Open Government Licence/i,
    );
  });

  test('a person can still place their own points afterwards', async ({ page }) => {
    await openPlanner(page);
    await runExample(page);

    await page.getByTestId('clear-journey').click();
    await expect(page.getByTestId('endpoint-origin-value')).toContainText(/not set/i);

    const map = page.getByTestId('map-frame');
    const box = await map.boundingBox();
    if (box === null) throw new Error('the map has no box to click');
    await map.click({ position: { x: box.width * 0.6, y: box.height * 0.4 } });
    await expect(page.getByTestId('endpoint-origin-value')).not.toContainText(/not set/i);
  });

  test('the example is reachable and operable from the keyboard', async ({ page }) => {
    await openPlanner(page);

    const button = page.getByTestId('run-verified-example');
    await button.focus();
    await expect(button).toBeFocused();

    // A visible focus indicator, not just a focusable element.
    const outlineWidth = await button.evaluate(
      (element) => getComputedStyle(element).outlineWidth ?? '',
    );
    expect(outlineWidth).not.toBe('0px');

    const waitForCompare = page.waitForRequest(
      (request) => request.url().includes(COMPARE_PATH) && request.method() === 'POST',
    );
    await page.keyboard.press('Enter');
    await waitForCompare;
    await expect(page.getByTestId('route-difference')).toBeVisible();
  });
});

test.describe('the demo on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('the example and the difference are usable at 390 px', async ({ page }) => {
    await openPlanner(page);

    await expect(page.getByTestId('verified-example')).toBeVisible();
    const { answer } = await runExample(page);

    // The answer opens at the map, with the sheet beneath it.
    await expect(page.getByTestId('map-frame')).toBeInViewport({ ratio: 0.9 });
    await expect(page.getByTestId('difference-shortest')).toContainText(
      `${Math.round(answer.standard_route.distance_m)} m`,
    );
    await expect(page.getByTestId('route-blocked')).toContainText(
      `${answer.standard_route.stairway_count} recorded stairways`,
    );
    // The surface gap survives the narrow viewport too.
    await expect(page.getByTestId('mobile-surface')).toContainText(/unknown/);

    // Nothing may overflow the viewport sideways.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
});
