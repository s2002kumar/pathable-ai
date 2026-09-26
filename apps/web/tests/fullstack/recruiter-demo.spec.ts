/**
 * The sixty-second demo, driven end to end against the real containers.
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

/** Matches playwright.fullstack.config.ts, including its Compose override. */
const API_BASE_URL = process.env.FULLSTACK_API_URL ?? 'http://127.0.0.1:8100';

/** The journey the example loads, as the corpus records it. */
const CAMPUS = {
  region: 'waterloo',
  origin: { longitude: -80.5424, latitude: 43.4728 },
  destination: { longitude: -80.5449, latitude: 43.4715 },
  profile: 'wheelchair',
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

/** Press the example and return the request the browser actually made. */
async function runExample(page: Page): Promise<{ request: Request; body: unknown }> {
  const waitForCompare = page.waitForRequest(
    (request) => request.url().includes(COMPARE_PATH) && request.method() === 'POST',
  );
  const waitForAnswer = page.waitForResponse(
    (response) => response.url().includes(COMPARE_PATH) && response.status() === 200,
  );

  await page.getByTestId('run-verified-example').click();

  const request = await waitForCompare;
  const response = await waitForAnswer;
  return { request, body: await response.json() };
}

test.describe('the recruiter demo', () => {
  test('one press produces a live comparison, not a recording', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready');

    const { request, body } = await runExample(page);

    // The preset supplied inputs, and only inputs.
    const sent = request.postDataJSON() as Record<string, unknown>;
    expect(sent.profile).toBe('wheelchair');
    expect(sent.region).toBe('waterloo');
    expect(sent.origin).toEqual(CAMPUS.origin);
    expect(sent.destination).toEqual(CAMPUS.destination);

    // The engine answered, and the answer is a real comparison.
    const answer = body as {
      standard_route: { distance_m: number; stairway_count: number };
      accessible_route: { distance_m: number; stairway_count: number };
      ml_predictions_used: boolean;
    };
    expect(answer.standard_route.stairway_count).toBeGreaterThan(0);
    expect(answer.accessible_route.stairway_count).toBe(0);
    expect(answer.accessible_route.distance_m).toBeGreaterThan(answer.standard_route.distance_m);
    expect(answer.ml_predictions_used).toBe(false);

    // And the page is showing that answer, not a different one.
    const difference = page.getByTestId('route-difference');
    await expect(difference).toBeVisible();
    await expect(page.getByTestId('difference-shortest')).toContainText(
      `${Math.round(answer.standard_route.distance_m)} m`,
    );
    await expect(page.getByTestId('difference-accessible')).toContainText(
      `${Math.round(answer.accessible_route.distance_m)} m`,
    );
    // The detour is not credited to the stairs alone (D7): the extra-distance
    // line states the figure, and the reasons — every constraint the engine
    // found the routes differ on — are listed beneath it, stairs among them.
    await expect(page.getByTestId('difference-extra')).not.toContainText('to avoid');
    await expect(page.getByTestId('difference-reasons')).toContainText(
      `Avoids ${answer.standard_route.stairway_count} recorded stairways`,
    );
  });

  test('the difference is explained by kind of evidence, and unknowns stay unknown', async ({
    page,
  }) => {
    await page.goto('/');
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready');
    await runExample(page);

    const difference = page.getByTestId('route-difference');
    await expect(difference.getByText('Recorded in OpenStreetMap').first()).toBeVisible();
    // More than one "Not recorded" label is expected on real data: each reason
    // about missing records carries it, as well as the overall gap line.
    await expect(difference.getByText('Not recorded').first()).toBeVisible();
    // And a reason about missing records is never labelled as a recorded one (D6).
    const unrecordedReasons = page
      .getByTestId('difference-reasons')
      .locator('li[data-basis="not_recorded"]');
    for (const reason of await unrecordedReasons.all()) {
      await expect(reason).not.toContainText('Recorded in OpenStreetMap');
    }

    // The most dangerous possible bug: an absence of data reading as a clearance.
    const unknown = page.getByTestId('difference-unknown');
    await expect(unknown).toContainText(/missing information, not a clear path/i);
    await expect(unknown).not.toContainText(/\b(verified|safe|guaranteed|confident)\b/i);
  });

  test('the incompleteness of the data is visible without scrolling', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready');
    await runExample(page);

    const summary = page.getByTestId('uncertainty-summary');
    await expect(summary).toBeVisible();
    await expect(summary).toContainText('Accessibility data is incomplete');
    await expect(summary).not.toContainText(/\b(safe|verified|confident|guaranteed)\b/i);

    // Visible is not the same as in the viewport: the panel scrolls, and an
    // element below the fold still reports itself visible to Playwright.
    const inViewport = await summary.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return rect.top >= 0 && rect.bottom > 0 && rect.top < window.innerHeight;
    });
    expect(inViewport).toBe(true);

    // And the fuller explanation is still there, further down.
    await expect(page.getByTestId('difference-unknown')).toContainText(
      /missing information, not a clear path/i,
    );
  });

  test('both routes are drawn, and the key names them in words', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready');
    await runExample(page);

    // Colour is never the only cue: the legend is real text beside the map.
    const legend = page.getByTestId('map-legend');
    await expect(legend).toBeVisible();
    await expect(legend).toContainText('Route for your profile');
    await expect(legend).toContainText('Shortest walking route');

    await expect(page.getByTestId('difference-accessible')).toBeVisible();
    await expect(page.getByTestId('difference-shortest')).toBeVisible();
  });

  test('the deep link starts the same live request', async ({ page }) => {
    const waitForCompare = page.waitForRequest(
      (request) => request.url().includes(COMPARE_PATH) && request.method() === 'POST',
    );

    await page.goto('/?example=campus-library-to-student-life');

    const sent = (await waitForCompare).postDataJSON() as Record<string, unknown>;
    expect(sent.origin).toEqual(CAMPUS.origin);
    await expect(page.getByTestId('route-difference')).toBeVisible();
  });

  test('attribution travels with the result', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready');
    await runExample(page);

    // The map data licence, on the page and in the answer.
    await expect(page.getByTestId('attribution')).toContainText('OpenStreetMap');
    await expect(page.getByTestId('attribution')).toContainText('ODbL');
    await expect(page.getByTestId('elevation-attribution')).toContainText(
      /Open Government Licence/i,
    );
  });

  test('a person can still place their own points afterwards', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready');
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
    await page.goto('/');
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready');

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
    await page.goto('/');
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready');

    await expect(page.getByTestId('verified-example')).toBeVisible();
    await runExample(page);

    const difference = page.getByTestId('route-difference');
    await expect(difference).toBeVisible();

    // The uncertainty line has to survive the narrow viewport too.
    const summary = page.getByTestId('uncertainty-summary');
    await expect(summary).toContainText('Accessibility data is incomplete');
    const inViewport = await summary.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return rect.top >= 0 && rect.bottom > 0 && rect.top < window.innerHeight;
    });
    expect(inViewport).toBe(true);

    // Nothing may overflow the viewport sideways: a horizontal scrollbar on a
    // phone is how a comparison becomes unreadable.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
});
