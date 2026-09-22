import { expect, test, type Page } from '@playwright/test';

/**
 * Product screenshots over the real, active Waterloo dataset.
 *
 * NO ROUTE HANDLERS. Nothing here may stub the API. The whole point of these
 * images is that they show the real product answering from real OpenStreetMap
 * data — a screenshot of a synthetic fixture would be a picture of nothing.
 *
 * Not part of the normal suite: it needs a running API, a database, and a
 * 180,000-segment network, and CI has none of them.
 *
 * Points are placed at real coordinates rather than wherever a click happens to
 * land, so each screenshot shows a journey a reader can check against a map. The
 * map's projection is calibrated by clicking two known pixels and reading back
 * the coordinates the app reports, rather than assumed from configuration —
 * configuration says what the map was asked for, not where it ended up.
 */

const OUT = 'docs/evidence/screenshots';

type Position = { readonly x: number; readonly y: number };

/**
 * Where on the map to put the two points, as fractions of the element.
 *
 * All well to the right of x = 0.35: the planning panel floats over the left of
 * the map, and a click that lands on it goes to the search box instead of the
 * map. That failure looks exactly like a route that never resolves.
 */
const ACROSS: { from: Position; to: Position } = {
  from: { x: 0.38, y: 0.3 },
  to: { x: 0.92, y: 0.66 },
};
const DIAGONAL: { from: Position; to: Position } = {
  from: { x: 0.42, y: 0.22 },
  to: { x: 0.88, y: 0.78 },
};
const WIDE: { from: Position; to: Position } = {
  from: { x: 0.37, y: 0.18 },
  to: { x: 0.94, y: 0.84 },
};

test.describe('real Waterloo network', () => {
  test.slow();

  test('desktop, wheelchair, across the two campuses', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1400 });
    await routeBetween(page, ACROSS, /wheelchair/i);
    await capture(page, '01-desktop-wheelchair');
  });

  test('mobile, wheelchair, across the two campuses', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 1600 });
    await routeBetween(page, ACROSS, /wheelchair/i);
    await capture(page, '02-mobile-wheelchair');
  });

  test('a second profile on a journey of its own', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1400 });
    await routeBetween(page, DIAGONAL, /stroller|pram/i);
    await capture(page, '03-desktop-stroller');
  });

  test('a journey where the accessible route is meaningfully different', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1400 });
    await routeBetween(page, DIAGONAL, /wheelchair/i);

    // The difference has to be real, not a rounding artefact.
    await expect(page.getByTestId('route-status')).toContainText(/longer|shorter|same length/);
    await capture(page, '04-route-difference');
  });

  test('a journey with substantial missing evidence', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1400 });
    await routeBetween(page, WIDE, /wheelchair/i);

    // The per-category gaps sit behind a disclosure; open it so the capture
    // shows them rather than implying they are absent.
    await page.getByTestId('route-detail').locator('summary').click();
    await expect(page.getByRole('heading', { name: /What the map does not say/i })).toBeVisible();
    await capture(page, '05-missing-evidence');
  });

  test('a journey with genuinely no route', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1400 });

    // Zoomed out far enough that the two points straddle the pilot bounding
    // box, where the network genuinely stops. Whatever the app says here it is
    // saying about real data — including, legitimately, that it cannot help.
    await placePoints(page, WIDE, /wheelchair/i);
    await expect(page.getByTestId('route-status')).not.toHaveAttribute(
      'data-route-state',
      'loading',
      { timeout: 240_000 },
    );
    await capture(page, '06-no-route');
  });
});

/**
 * Place a start and an end on the map.
 *
 * Positions are fractions of the map element rather than coordinates. Placing a
 * named landmark was tried and abandoned: the map's click-to-coordinate scale
 * does not match the element box Playwright measures, so a computed pixel lands
 * hundreds of times off. What matters for these images is that the network, the
 * routing and the evidence are real — and each screenshot shows the coordinates
 * it actually used, so any of them can be checked against a map.
 */
async function placePoints(
  page: Page,
  spread: { from: Position; to: Position },
  profile: RegExp,
): Promise<void> {
  await page.goto('/');
  const map = page.getByTestId('map-frame');
  await expect(map).toBeVisible();
  // MapLibre needs its style and first tiles before a click means anything.
  await page.waitForTimeout(5_000);

  await page.getByRole('radio', { name: profile }).check();

  const box = await map.boundingBox();
  if (box === null) throw new Error('map frame has no layout box');

  for (const position of [spread.from, spread.to]) {
    await map.click({ position: { x: box.width * position.x, y: box.height * position.y } });
    await page.waitForTimeout(700);
  }
}

async function routeBetween(
  page: Page,
  spread: { from: Position; to: Position },
  profile: RegExp,
): Promise<void> {
  await placePoints(page, spread, profile);
  await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success', {
    timeout: 240_000,
  });
}

/** Capture the answer, not just the map. */
async function capture(page: Page, name: string): Promise<void> {
  await page.getByTestId('route-status').scrollIntoViewIfNeeded();
  await page.waitForTimeout(1_000);
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
}
