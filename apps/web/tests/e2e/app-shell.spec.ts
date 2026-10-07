import { expect, test } from '@playwright/test';
import {
  PLANNER,
  SCREENSHOT_DIR,
  hasHorizontalOverflow,
  isPhone,
  stubHealthyApi,
} from './fixtures';

test.describe('planner shell', () => {
  test('loads and shows the product identity', async ({ page }) => {
    await page.goto(PLANNER);

    await expect(page).toHaveTitle('Route Planner — PathAble');
    await expect(page.getByText('PathAble', { exact: true })).toBeVisible();
    await expect(page.getByTestId('pilot-region')).toContainText('Waterloo');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Route Planner');
    // The brand goes home, to the landing page.
    await expect(page.getByRole('link', { name: 'PathAble home' })).toHaveAttribute('href', '/');
  });

  test('states that missing data is never treated as a clear path', async ({ page }) => {
    // The product's central safety claim, asserted in the shipped page rather
    // than only in a unit test.
    await page.goto(PLANNER);

    const description = page.getByTestId('pilot-description');
    await expect(description).toContainText(
      /missing information is never treated as a clear path/i,
    );
    await expect(description).toContainText(/no route here is a guarantee/i);
    await expect(description).toContainText(/compares the shortest walking route/i);
  });

  test('credits the map data, the elevation licence and the tile host', async ({ page }) => {
    await page.goto(PLANNER);

    const credit = page.getByTestId('attribution');
    await credit.scrollIntoViewIfNeeded();
    await expect(credit).toBeVisible();
    await expect(credit).toContainText('OpenStreetMap');
    await expect(credit).toContainText('Open Government Licence – Canada');
    await expect(credit).toContainText(/OpenFreeMap, which has not been approved for production/);
  });

  test('draws the credit and its own controls on the map itself', async ({ page }) => {
    await page.goto(PLANNER);
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready', {
      timeout: 20_000,
    });

    const attribution = page.locator('.maplibregl-ctrl-attrib');
    await expect(attribution).toBeVisible();
    await expect(attribution).toContainText('OpenStreetMap');

    // PathAble's own controls, each one doing something real. MapLibre's
    // built-in zoom and scale are not added.
    const ids = isPhone(page)
      ? ['map-layers', 'toggle-evidence-labels', 'fit-routes']
      : ['zoom-in', 'zoom-out', 'fit-routes', 'reset-north', 'map-layers'];
    for (const id of ids) await expect(page.getByTestId(id)).toBeVisible();
    await expect(page.locator('.maplibregl-ctrl-zoom-in')).toHaveCount(0);
    await expect(page.locator('.maplibregl-ctrl-scale')).toHaveCount(0);

    // Being in the DOM is not enough: assert the credit is laid out inside
    // the map frame, where MapLibre's stylesheet puts it.
    const frame = await page.getByTestId('map-frame').boundingBox();
    const attributionBox = await attribution.boundingBox();
    expect(frame).not.toBeNull();
    expect(attributionBox).not.toBeNull();
    if (frame === null || attributionBox === null) return;

    expect(attributionBox.x).toBeGreaterThanOrEqual(frame.x);
    expect(attributionBox.x + attributionBox.width).toBeLessThanOrEqual(frame.x + frame.width + 1);
    expect(attributionBox.y + attributionBox.height).toBeLessThanOrEqual(
      frame.y + frame.height + 1,
    );
  });

  test('initialises the map against the deterministic offline style', async ({ page }) => {
    // The style has no sources, so reaching `ready` proves the whole MapLibre
    // lifecycle ran without a single network request to a tile server.
    await page.goto(PLANNER);

    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready', {
      timeout: 20_000,
    });
    await expect(page.getByTestId('map-overlay')).toBeHidden();
  });

  test('exposes the map as a named region', async ({ page }) => {
    await page.goto(PLANNER);

    await expect(
      page.getByRole('region', { name: /interactive map of waterloo, ontario/i }),
    ).toBeVisible();
  });

  test('serves the MapLibre worker from our own origin', async ({ request }) => {
    // KI-1: MapLibre computes its worker URL from `import.meta.url` and yields an
    // empty string once bundled, so `new Worker("")` loads the HTML page as the
    // worker. The fix depends on this asset existing.
    const response = await request.get('/maplibre/maplibre-gl-worker.mjs');

    expect(response.status()).toBe(200);
    expect(await response.text()).toContain('maplibre-gl-shared.mjs');
    expect((await request.get('/maplibre/maplibre-gl-shared.mjs')).status()).toBe(200);
  });

  test('the map container actually fills the map frame', async ({ page }) => {
    // Regression cover: `.maplibregl-map { position: relative }` once collapsed
    // this element to zero height while the lifecycle still reported `ready`.
    await page.goto(PLANNER);
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready', {
      timeout: 30_000,
    });

    const frame = await page.getByTestId('map-frame').boundingBox();
    const container = await page.getByRole('region', { name: /interactive map/i }).boundingBox();

    expect(frame).not.toBeNull();
    expect(container).not.toBeNull();
    if (frame === null || container === null) return;

    expect(container.height).toBeGreaterThan(100);
    expect(container.height).toBeGreaterThanOrEqual(frame.height - 4);
    expect(container.width).toBeGreaterThanOrEqual(frame.width - 4);
  });

  test('offers every mobility profile as one group of radio buttons', async ({ page }) => {
    await page.goto(PLANNER);

    // Native radio buttons drawn as cards: all five on show, one tab stop,
    // and the arrow keys move the choice — the platform's own behaviour.
    const group = page.getByRole('group', { name: /mobility profile/i });
    await expect(group).toBeVisible();
    await expect(group.getByRole('radio')).toHaveCount(5);
    const wheelchair = group.getByRole('radio', { name: /^Wheelchair/ });
    await expect(wheelchair).toBeChecked();

    await wheelchair.focus();
    await page.keyboard.press('ArrowDown');
    const walker = group.getByRole('radio', { name: /^Walker or rollator/ });
    await expect(walker).toBeChecked();
    await expect(walker).toBeFocused();
  });

  test('explains how to start before any point is chosen', async ({ page }) => {
    await page.goto(PLANNER);

    const status = page.getByTestId('route-status');
    await expect(status).toHaveAttribute('data-route-state', 'idle');
    await expect(status).toContainText(/name both ends to begin/i);
    await expect(page.getByTestId('compare-routes')).toBeDisabled();
  });

  test('gives keyboard focus a visible indicator', async ({ page }) => {
    await page.goto(PLANNER);
    await page.keyboard.press('Tab');

    const focused = page.locator(':focus-visible');
    await expect(focused).toBeVisible();
    // The first stop is the skip link, and it is actually drawn.
    await expect(focused).toContainText(/skip to main content/i);

    const outlineWidth = await focused.evaluate(
      (element) => getComputedStyle(element).outlineWidth,
    );
    expect(Number.parseFloat(outlineWidth)).toBeGreaterThan(0);
  });

  test('skip link moves focus to the main region', async ({ page }) => {
    await page.goto(PLANNER);
    await page.keyboard.press('Tab');
    await page.keyboard.press('Enter');

    await expect(page).toHaveURL(/#main-content$/);
    await expect(page.locator('#main-content')).toBeVisible();
  });

  test('the header search goes to the start field', async ({ page }) => {
    await page.goto(PLANNER);

    await page.getByTestId('header-search').click();
    await expect(page.getByLabel('Start location')).toBeFocused();
  });

  test('does not overflow horizontally', async ({ page }) => {
    await page.goto(PLANNER);
    await expect(page.getByTestId('map-frame')).toBeVisible();

    expect(await hasHorizontalOverflow(page)).toBe(false);
  });
});

test.describe('visual evidence', () => {
  test('captures the planner before a journey', async ({ page }, testInfo) => {
    await stubHealthyApi(page);
    await page.goto(PLANNER);

    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready', {
      timeout: 20_000,
    });
    await expect(page.getByTestId('system-status')).toHaveAttribute('data-status', 'ready');

    const path = `${SCREENSHOT_DIR}/${testInfo.project.name}-application.png`;
    await page.screenshot({ path, fullPage: false });
    await testInfo.attach('application', { path, contentType: 'image/png' });
  });
});
