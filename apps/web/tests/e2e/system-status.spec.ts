import { expect, test } from '@playwright/test';
import { hasHorizontalOverflow, stubDegradedApi, stubHealthyApi } from './fixtures';

test.describe('backend status', () => {
  test('shows the API as online when readiness reports ready', async ({ page }) => {
    await stubHealthyApi(page);
    await page.goto('/');

    const badge = page.getByTestId('system-status');
    await expect(badge).toHaveAttribute('data-status', 'ready');
    await expect(badge).toContainText('API online');
    await expect(badge).toContainText('pathable-api v0.1.0');
  });

  test('shows the API as degraded when its database is down', async ({ page }) => {
    // "up but unusable" is a different problem from "not running", and the badge
    // has to say which, or the first thing a new contributor does is debug the
    // wrong layer.
    await stubDegradedApi(page);
    await page.goto('/');

    const badge = page.getByTestId('system-status');
    await expect(badge).toHaveAttribute('data-status', 'degraded');
    await expect(badge).toContainText('API degraded');
  });

  test('shows the API as offline when nothing is listening', async ({ page }) => {
    // No stub: the configured API base URL points at a closed port, so this is a
    // real connection failure rather than a simulated one.
    await page.goto('/');

    const badge = page.getByTestId('system-status');
    await expect(badge).toHaveAttribute('data-status', 'unreachable');
    await expect(badge).toContainText('API offline');
  });

  test('remains fully usable with the backend unavailable', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('system-status')).toHaveAttribute('data-status', 'unreachable');

    // Nothing on this page depends on the API in Phase 0, so an outage must
    // degrade the badge and nothing else.
    await expect(page.getByText('PathAble', { exact: true })).toBeVisible();
    await expect(page.getByTestId('pilot-description')).toBeVisible();
    await expect(page.getByTestId('route-status')).toBeVisible();
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready', {
      timeout: 20_000,
    });
    expect(await hasHorizontalOverflow(page)).toBe(false);
  });

  test('states the status in words, not colour alone', async ({ page }) => {
    await stubDegradedApi(page);
    await page.goto('/');

    await expect(page.getByText(/API degraded/)).toBeVisible();
  });
});
