import { expect, test, type Page } from '@playwright/test';
import {
  hasHorizontalOverflow,
  stubHealthyApi,
  stubRouteComparison,
  waitForMapReady,
} from './fixtures';

/**
 * The map-first layout, in a real browser.
 *
 * Unit tests can say what the panel contains; only a layout engine can say
 * where it is. These assert the two things the layout exists for — the planner
 * never covers the map, and the answer is on screen without scrolling — plus
 * the behaviours that are easy to lose in a restyle: a single map instance,
 * keyboard reach, reduced motion, and reflow at 320 px and 200% zoom.
 */

async function runExample(page: Page): Promise<void> {
  await page.getByTestId('run-verified-example').click();
  await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
}

/** Whole element inside the viewport, not merely attached and unhidden. */
async function fullyInViewport(page: Page, testId: string): Promise<boolean> {
  return page.evaluate((id) => {
    const element = document.querySelector(`[data-testid="${id}"]`);
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    return rect.top >= 0 && rect.bottom <= window.innerHeight && rect.height > 0;
  }, testId);
}

test.describe('layout', () => {
  test.beforeEach(async ({ page }) => {
    await stubHealthyApi(page);
    await stubRouteComparison(page);
  });

  test('the planner never covers the map', async ({ page }) => {
    await page.goto('/');
    await waitForMapReady(page);

    const map = await page.getByTestId('map-frame').boundingBox();
    const planner = await page.getByRole('complementary', { name: /route planner/i }).boundingBox();
    expect(map).not.toBeNull();
    expect(planner).not.toBeNull();
    if (map === null || planner === null) return;

    const overlapX = Math.max(
      0,
      Math.min(map.x + map.width, planner.x + planner.width) - Math.max(map.x, planner.x),
    );
    const overlapY = Math.max(
      0,
      Math.min(map.y + map.height, planner.y + planner.height) - Math.max(map.y, planner.y),
    );
    // On a phone the sheet's rounded top tucks under the map by design; the
    // budget below allows that lip and nothing more.
    expect(overlapX * overlapY).toBeLessThanOrEqual(planner.width * 20);
  });

  test('the answer is on screen without scrolling or opening anything', async ({ page }) => {
    await page.goto('/');
    await waitForMapReady(page);
    await runExample(page);

    // Both figures, the extra distance and the uncertainty line, together.
    expect(await fullyInViewport(page, 'difference-accessible')).toBe(true);
    expect(await fullyInViewport(page, 'difference-shortest')).toBe(true);
    expect(await fullyInViewport(page, 'difference-extra')).toBe(true);
    expect(await fullyInViewport(page, 'uncertainty-summary')).toBe(true);

    // And nothing had to be opened to see them.
    await expect(page.getByTestId('route-detail')).not.toHaveAttribute('open');
    await expect(page.getByTestId('route-provenance')).not.toHaveAttribute('open');
  });

  test('map attribution and controls stay uncovered by the legend', async ({ page }) => {
    await page.goto('/');
    await waitForMapReady(page);

    const legend = await page.getByTestId('map-legend').boundingBox();
    const attribution = await page.locator('.maplibregl-ctrl-attrib').boundingBox();
    const zoomIn = await page.getByRole('button', { name: /zoom in/i }).boundingBox();
    expect(legend).not.toBeNull();
    expect(attribution).not.toBeNull();
    expect(zoomIn).not.toBeNull();
    if (legend === null || attribution === null || zoomIn === null) return;

    const disjoint = (a: typeof legend, b: typeof legend) =>
      a.x + a.width <= b.x ||
      b.x + b.width <= a.x ||
      a.y + a.height <= b.y ||
      b.y + b.height <= a.y;
    expect(disjoint(legend, attribution)).toBe(true);
    expect(disjoint(legend, zoomIn)).toBe(true);
  });

  test('highlighting a route is keyboard-operable and never erases the comparison', async ({
    page,
  }) => {
    await page.goto('/');
    await waitForMapReady(page);
    await runExample(page);

    const highlight = page.getByTestId('focus-accessible');
    await highlight.focus();
    await expect(highlight).toBeFocused();
    await page.keyboard.press('Enter');

    await expect(highlight).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('legend-accessible')).toContainText(/highlighted/);
    await expect(page.getByTestId('legend-standard')).toBeVisible();
    await expect(page.getByTestId('difference-shortest')).toBeVisible();
    await expect(page.getByTestId('focus-note')).toContainText(/neither is certified/i);

    await page.keyboard.press('Enter');
    await expect(highlight).toHaveAttribute('aria-pressed', 'false');
  });

  test('ordinary updates never recreate the map', async ({ page }) => {
    await page.goto('/');
    await waitForMapReady(page);

    // Record every lifecycle transition from here on. A remount would pass
    // back through `initialising`.
    await page.evaluate(() => {
      const frame = document.querySelector('[data-testid="map-frame"]');
      const states: string[] = [];
      (window as unknown as { __mapStates: string[] }).__mapStates = states;
      new MutationObserver(() => {
        states.push(frame?.getAttribute('data-map-state') ?? '');
      }).observe(frame!, { attributes: true, attributeFilter: ['data-map-state'] });
    });

    await runExample(page);
    await page.getByRole('radio', { name: /Stroller or pram/ }).check();
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
    await page.getByRole('button', { name: 'Swap' }).click();
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');

    const states = await page.evaluate(
      () => (window as unknown as { __mapStates: string[] }).__mapStates,
    );
    expect(states).toEqual([]);
  });

  test('reduced motion removes the transitions', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');
    await waitForMapReady(page);
    await runExample(page);

    const durations = await page.evaluate(() => {
      const result = document.querySelector('[data-testid="route-difference"]')?.parentElement;
      const figure = document.querySelector('[data-testid="difference-accessible"]');
      return {
        animation: result ? getComputedStyle(result).animationDuration : null,
        transition: figure ? getComputedStyle(figure).transitionDuration : null,
      };
    });
    // 0.01ms is what the global reduced-motion rule collapses everything to;
    // Chromium reports it as "1e-05s". Anything under a frame counts as none.
    const seconds = (value: string) => Number.parseFloat(value);
    expect(seconds(durations.animation ?? '1s')).toBeLessThan(0.016);
    for (const part of (durations.transition ?? '1s').split(',')) {
      expect(seconds(part)).toBeLessThan(0.016);
    }
  });

  test('the example is the first meaningful stop for the keyboard', async ({ page }) => {
    await page.goto('/');
    await waitForMapReady(page);

    // Skip link, then whatever the header exposes, then the example. Count the
    // stops rather than assert an exact path so a harmless header change does
    // not break this; the point is that the offer is reached quickly.
    const stops: string[] = [];
    for (let i = 0; i < 8; i += 1) {
      await page.keyboard.press('Tab');
      const id = await page.evaluate(
        () => document.activeElement?.getAttribute('data-testid') ?? '',
      );
      stops.push(id);
      if (id === 'run-verified-example') break;
    }
    expect(stops).toContain('run-verified-example');
    expect(stops.indexOf('run-verified-example')).toBeLessThanOrEqual(6);
  });
});

test.describe('reflow', () => {
  test.beforeEach(async ({ page }) => {
    await stubHealthyApi(page);
    await stubRouteComparison(page);
  });

  test('320 px wide, nothing overflows and everything is reachable', async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 568 });
    await page.goto('/');
    await waitForMapReady(page);
    await runExample(page);

    expect(await hasHorizontalOverflow(page)).toBe(false);

    // The map's own attribution has to sit inside the map, not under the
    // sheet. Regression cover: the frame's minimum height was once taller
    // than the phone-height map area, so the frame overflowed beneath the
    // sheet and the credit was covered on a 320 px screen.
    await page.evaluate(() => window.scrollTo(0, 0));
    const frame = await page.getByTestId('map-frame').boundingBox();
    const credit = await page.locator('.maplibregl-ctrl-attrib').boundingBox();
    const sheet = await page.getByRole('complementary', { name: /route planner/i }).boundingBox();
    expect(frame).not.toBeNull();
    expect(credit).not.toBeNull();
    expect(sheet).not.toBeNull();
    if (frame === null || credit === null || sheet === null) return;
    expect(credit.y + credit.height).toBeLessThanOrEqual(frame.y + frame.height + 1);
    expect(credit.y + credit.height).toBeLessThanOrEqual(sheet.y + 1);

    await page.getByTestId('route-provenance').scrollIntoViewIfNeeded();
    await expect(page.getByTestId('attribution')).toBeVisible();
    await expect(page.locator('.maplibregl-ctrl-attrib')).toBeVisible();
  });

  test('at the width 200% zoom leaves, the page falls back to document flow', async ({ page }) => {
    // 1440 × 900 at 200% is 720 × 450 CSS pixels: too narrow for a second
    // column and too short for a fixed two-pane grid. The page must scroll as
    // a page, with no inner region trapping the wheel.
    await page.setViewportSize({ width: 720, height: 450 });
    await page.goto('/');
    await waitForMapReady(page);
    await runExample(page);

    expect(await hasHorizontalOverflow(page)).toBe(false);
    const scrollable = await page.evaluate(
      () => document.documentElement.scrollHeight > document.documentElement.clientHeight,
    );
    expect(scrollable).toBe(true);
    await page.getByRole('radio', { name: /Reduced mobility/ }).scrollIntoViewIfNeeded();
    await expect(page.getByRole('radio', { name: /Reduced mobility/ })).toBeVisible();
  });

  test('landscape phone keeps the map and reaches the planner by scrolling', async ({ page }) => {
    await page.setViewportSize({ width: 844, height: 390 });
    await page.goto('/');
    await waitForMapReady(page);

    const map = await page.getByTestId('map-frame').boundingBox();
    expect(map).not.toBeNull();
    if (map === null) return;
    expect(map.height).toBeGreaterThanOrEqual(200);

    await runExample(page);
    expect(await hasHorizontalOverflow(page)).toBe(false);
    await page.getByTestId('uncertainty-summary').scrollIntoViewIfNeeded();
    await expect(page.getByTestId('uncertainty-summary')).toBeVisible();
  });
});
