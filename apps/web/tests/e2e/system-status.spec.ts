import { expect, test } from '@playwright/test';
import { PLANNER, hasHorizontalOverflow, stubDegradedApi, stubHealthyApi } from './fixtures';

/**
 * The routing service's state, probed once per page and shown twice: a word
 * in the bar's region pill whenever it is not ready, and the full sentence in
 * the strip under the planning form (17:3728).
 */
test.describe('backend status', () => {
  test('says the service is ready, with its version off the strip’s face', async ({ page }) => {
    await stubHealthyApi(page);
    await page.goto(PLANNER);

    const strip = page.getByTestId('system-status');
    await expect(strip).toHaveAttribute('data-status', 'ready');
    await expect(strip).toContainText('Ready to route');
    await expect(strip).toHaveAttribute('title', 'pathable-api v0.1.0');
    // Ready is the design's state: the bar keeps the word for assistive tech.
    await expect(page.getByTestId('header-status')).toHaveClass(/visually-hidden/);
  });

  test('says the service is degraded when its database is down', async ({ page }) => {
    // "Up but unusable" is a different problem from "not running", and the page
    // has to say which, or the first thing a contributor does is debug the
    // wrong layer.
    await stubDegradedApi(page);
    await page.goto(PLANNER);

    const strip = page.getByTestId('system-status');
    await expect(strip).toHaveAttribute('data-status', 'degraded');
    await expect(strip).toContainText('Routing service degraded');
    await expect(strip).toContainText('database and PostGIS unavailable');
  });

  test('says the service is offline when nothing is listening', async ({ page }) => {
    // No stub: the configured API base URL points at a closed port, so this is a
    // real connection failure rather than a simulated one.
    await page.goto(PLANNER);

    const strip = page.getByTestId('system-status');
    await expect(strip).toHaveAttribute('data-status', 'unreachable');
    await expect(strip).toContainText('Routing service offline');
  });

  test('states the status in words in the bar, not colour alone', async ({ page }) => {
    await stubDegradedApi(page);
    await page.goto(PLANNER);

    const word = page.getByTestId('header-status');
    await expect(word).toBeVisible();
    await expect(word).toHaveText('Routing service: Degraded');
  });

  test('remains usable with the backend unavailable', async ({ page }) => {
    await page.goto(PLANNER);
    await expect(page.getByTestId('system-status')).toHaveAttribute('data-status', 'unreachable');

    await expect(page.getByText('PathAble', { exact: true })).toBeVisible();
    await expect(page.getByTestId('pilot-description')).toBeAttached();
    await expect(page.getByLabel('Start location')).toBeVisible();
    await expect(page.getByTestId('header-status')).toHaveText('Routing service: Offline');
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready', {
      timeout: 20_000,
    });
    expect(await hasHorizontalOverflow(page)).toBe(false);
  });
});
