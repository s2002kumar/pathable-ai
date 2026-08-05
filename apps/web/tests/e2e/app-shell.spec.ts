import { expect, test } from '@playwright/test';
import { SCREENSHOT_DIR, hasHorizontalOverflow, stubHealthyApi } from './fixtures';

test.describe('application shell', () => {
  test('loads and shows the product identity', async ({ page }) => {
    await page.goto('/');

    await expect(page).toHaveTitle(/PathAble AI/);
    await expect(page.getByText('PathAble AI', { exact: true })).toBeVisible();
    await expect(page.getByTestId('pilot-region')).toContainText('Waterloo, Ontario');
  });

  test('discloses that this is a Phase 0 build with no routing or ML', async ({ page }) => {
    await page.goto('/');

    const notice = page.getByTestId('development-notice');
    await expect(notice).toBeVisible();
    await expect(notice).toContainText(/Phase 0/i);
    await expect(notice).toContainText(/no routing/i);
    await expect(notice).toContainText(/no machine learning/i);
  });

  test('describes the pilot area in text as well as on the map', async ({ page }) => {
    await page.goto('/');

    const description = page.getByTestId('pilot-description');
    await expect(description).toBeVisible();
    await expect(description).toContainText(/uptown core/i);
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

  test('presents no routing controls', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByRole('textbox')).toHaveCount(0);
    await expect(page.getByRole('searchbox')).toHaveCount(0);
    await expect(page.getByRole('combobox')).toHaveCount(0);
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
