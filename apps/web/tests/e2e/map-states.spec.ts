import { expect, test } from '@playwright/test';
import { PLANNER, SCREENSHOT_DIR, breakMapStyle, holdMapStyle } from './fixtures';

test.describe('map lifecycle', () => {
  test('shows a loading state before the map is ready', async ({ page }, testInfo) => {
    const { release } = await holdMapStyle(page);
    await page.goto(PLANNER);

    const frame = page.getByTestId('map-frame');
    await expect(frame).toHaveAttribute('data-map-state', 'initialising');
    await expect(page.getByTestId('map-overlay')).toContainText(/loading the map/i);

    const path = `${SCREENSHOT_DIR}/${testInfo.project.name}-map-loading.png`;
    await page.screenshot({ path });
    await testInfo.attach('map-loading', { path, contentType: 'image/png' });

    // And it does resolve once the style arrives, rather than hanging forever.
    release();
    await expect(frame).toHaveAttribute('data-map-state', 'ready', { timeout: 20_000 });
  });

  test('falls back readably when the map style cannot be loaded', async ({ page }, testInfo) => {
    await breakMapStyle(page);
    await page.goto(PLANNER);

    const frame = page.getByTestId('map-frame');
    await expect(frame).toHaveAttribute('data-map-state', 'error', { timeout: 20_000 });

    const overlay = page.getByTestId('map-overlay');
    await expect(overlay).toContainText(/map is unavailable/i);
    await expect(overlay).toContainText(
      /name both ends in the planner; every answer is given in text/i,
    );

    // The planning form is what makes this a fallback rather than a dead end.
    await expect(page.getByLabel('Start location')).toBeVisible();

    const path = `${SCREENSHOT_DIR}/${testInfo.project.name}-map-failure.png`;
    await page.screenshot({ path });
    await testInfo.attach('map-failure', { path, contentType: 'image/png' });
  });

  test('announces a map failure assertively', async ({ page }) => {
    await breakMapStyle(page);
    await page.goto(PLANNER);

    const overlay = page.getByTestId('map-overlay');
    await expect(overlay).toHaveAttribute('role', 'alert', { timeout: 20_000 });
  });

  test('keeps the page usable when the map fails', async ({ page }) => {
    await breakMapStyle(page);
    await page.goto(PLANNER);

    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'error', {
      timeout: 20_000,
    });
    await expect(page.getByText('PathAble', { exact: true })).toBeVisible();
    // The planning form still works without the map: name both ends instead.
    await expect(page.getByLabel('Start location')).toBeVisible();
    await expect(page.getByTestId('route-status')).toBeAttached();
    await page.getByTestId('attribution').scrollIntoViewIfNeeded();
    await expect(page.getByTestId('attribution')).toBeVisible();
  });
});
