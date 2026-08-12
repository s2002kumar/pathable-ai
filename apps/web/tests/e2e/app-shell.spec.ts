import { expect, test } from '@playwright/test';
import { SCREENSHOT_DIR, hasHorizontalOverflow, stubHealthyApi } from './fixtures';

test.describe('application shell', () => {
  test('loads and shows the product identity', async ({ page }) => {
    await page.goto('/');

    await expect(page).toHaveTitle(/PathAble AI/);
    await expect(page.getByText('PathAble AI', { exact: true })).toBeVisible();
    await expect(page.getByTestId('pilot-region')).toContainText('Waterloo, Ontario');
  });

  test('states that missing data is never treated as a clear path', async ({ page }) => {
    // The product's central safety claim, asserted in the shipped page rather
    // than only in a unit test.
    await page.goto('/');

    const description = page.getByTestId('pilot-description');
    await expect(description).toBeVisible();
    await expect(description).toContainText(/missing information is never treated as a clear path/i);
    await expect(description).toContainText(/no route here is a guarantee/i);
  });

  test('describes what the page does in text as well as on the map', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByTestId('pilot-description')).toContainText(
      /compares the shortest walking route/i,
    );
  });

  test('shows visible map data attribution', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByTestId('attribution')).toContainText('OpenStreetMap');
  });

  test('renders attribution and navigation controls on the map itself', async ({ page }) => {
    // On a wide screen the panel's written attribution can sit below the fold, so
    // the on-map control is what actually guarantees attribution stays visible.
    await page.goto('/');
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready', {
      timeout: 20_000,
    });

    const attribution = page.locator('.maplibregl-ctrl-attrib');
    await expect(attribution).toBeVisible();
    await expect(attribution).toContainText('OpenStreetMap');

    await expect(page.getByRole('button', { name: /zoom in/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /zoom out/i })).toBeVisible();
    await expect(page.locator('.maplibregl-ctrl-scale')).toBeVisible();

    // Being in the DOM is not enough. If MapLibre's stylesheet failed to load,
    // the controls would still report visible while sitting unpositioned outside
    // the map. Assert they are actually laid out within the map frame.
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
    await page.goto('/');

    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready', {
      timeout: 20_000,
    });
    await expect(page.getByTestId('map-overlay')).toBeHidden();
  });

  test('exposes the map as a named region', async ({ page }) => {
    await page.goto('/');

    await expect(
      page.getByRole('region', { name: /interactive map of waterloo, ontario/i }),
    ).toBeVisible();
  });

  test('serves the MapLibre worker from our own origin', async ({ request }) => {
    // KI-1: MapLibre computes its worker URL from `import.meta.url` and yields an
    // empty string once bundled, so `new Worker("")` loads the HTML page as the
    // worker. The map then renders nothing, silently. The fix depends on this
    // asset existing, and the deterministic style has no sources — so nothing
    // else in this suite would notice if it went missing.
    const response = await request.get('/maplibre/maplibre-gl-worker.mjs');

    expect(response.status()).toBe(200);
    expect(await response.text()).toContain('maplibre-gl-shared.mjs');

    // The worker imports this sibling relatively; both must be served.
    expect((await request.get('/maplibre/maplibre-gl-shared.mjs')).status()).toBe(200);
  });

  test('the map container actually fills the map frame', async ({ page }) => {
    // Regression cover. MapLibre applies `.maplibregl-map { position: relative }`
    // to this element, which once overrode the absolute positioning and collapsed
    // it to zero height. Nothing caught it: the frame's own background still
    // showed, and a source-less style fires `load` at any size, so the lifecycle
    // reported `ready` over a map that had never rendered a tile.
    await page.goto('/');
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

  test('offers the mobility profiles as a labelled radio group', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByRole('radiogroup', { name: /mobility profile/i })).toBeVisible();
    await expect(page.getByRole('radio')).toHaveCount(5);
    await expect(page.getByRole('radio', { name: /Wheelchair/ })).toBeChecked();
  });

  test('explains how to start before any point is chosen', async ({ page }) => {
    await page.goto('/');

    const status = page.getByTestId('route-status');
    await expect(status).toHaveAttribute('data-route-state', 'idle');
    await expect(status).toContainText(/choose a start and an end/i);
  });

  test('gives keyboard focus a visible indicator', async ({ page }) => {
    await page.goto('/');
    await page.keyboard.press('Tab');

    const focused = page.locator(':focus-visible');
    await expect(focused).toBeVisible();

    // The first stop must be the skip link, and it must actually be drawn.
    await expect(focused).toContainText(/skip to main content/i);

    const outlineWidth = await focused.evaluate(
      (element) => getComputedStyle(element).outlineWidth,
    );
    expect(Number.parseFloat(outlineWidth)).toBeGreaterThan(0);
  });

  test('skip link moves focus to the main region', async ({ page }) => {
    await page.goto('/');
    await page.keyboard.press('Tab');
    await page.keyboard.press('Enter');

    await expect(page).toHaveURL(/#main-content$/);
    await expect(page.locator('#main-content')).toBeVisible();
  });

  test('does not overflow horizontally', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('map-frame')).toBeVisible();

    expect(await hasHorizontalOverflow(page)).toBe(false);
  });
});

test.describe('visual evidence', () => {
  test('captures the application', async ({ page }, testInfo) => {
    await stubHealthyApi(page);
    await page.goto('/');

    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready', {
      timeout: 20_000,
    });
    await expect(page.getByTestId('system-status')).toHaveAttribute('data-status', 'ready');

    const path = `${SCREENSHOT_DIR}/${testInfo.project.name}-application.png`;
    await page.screenshot({ path, fullPage: false });
    await testInfo.attach('application', { path, contentType: 'image/png' });
  });
});
