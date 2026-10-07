import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import {
  PLANNER,
  breakMapStyle,
  isPhone,
  openJourneyControls,
  runExample,
  stubHealthyApi,
  stubNoRoute,
  stubRouteComparison,
} from './fixtures';

/**
 * Automated accessibility checks.
 *
 * IMPORTANT: axe catches a minority of real accessibility problems — roughly the
 * machine-detectable ones. It cannot judge whether the pilot description is
 * genuinely useful without the map, whether focus order makes sense, or whether
 * the product's language is clear. Passing this suite is a floor, not a claim of
 * accessibility. See docs/development/TESTING.md.
 */

const SERIOUS = new Set(['serious', 'critical']);

/**
 * Serious and critical violations, one entry per offending element.
 *
 * MapLibre's own control chrome is third-party markup this project does not
 * author, so it is excluded; PathAble's own map controls and pins are not.
 */
async function blockingViolations(page: Page): Promise<string[]> {
  // Colour is judged as a reader sees it: after entrances have finished, not
  // halfway through a fade, when every colour on the surface is blended.
  await page.waitForFunction(() =>
    document.getAnimations().every((animation) => animation.playState !== 'running'),
  );
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .exclude('.maplibregl-control-container')
    .analyze();
  return results.violations
    .filter((violation) => SERIOUS.has(violation.impact ?? ''))
    .flatMap((violation) =>
      violation.nodes.map(
        (node) =>
          `${violation.id} (${violation.impact}) at ${node.target.join(' ')} :: ` +
          `${node.failureSummary?.replace(/\s+/g, ' ').trim() ?? violation.help}`,
      ),
    );
}

async function mapReady(page: Page): Promise<void> {
  await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready', {
    timeout: 20_000,
  });
}

test.describe('accessibility', () => {
  test('the landing page has no serious or critical violations', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');

    expect(await blockingViolations(page)).toEqual([]);
  });

  test('the planning form has none', async ({ page }) => {
    await stubHealthyApi(page);
    await page.goto(PLANNER);
    await mapReady(page);

    expect(await blockingViolations(page)).toEqual([]);
  });

  test('a comparison, with its controls open, has none either', async ({ page }) => {
    // The result is where the structure lives — the route radio group, the
    // evidence labels, the dock, the pins on the map — so it gets the same scan.
    await stubHealthyApi(page);
    await stubRouteComparison(page);
    await page.goto(PLANNER);
    await mapReady(page);
    await runExample(page);
    await openJourneyControls(page);
    await page.getByTestId('uphill-limit-toggle').click();
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');

    expect(await blockingViolations(page)).toEqual([]);
  });

  test('one route’s evidence and the full record have none', async ({ page }) => {
    await stubHealthyApi(page);
    await stubRouteComparison(page);
    await page.goto(PLANNER);
    await mapReady(page);
    await runExample(page);

    if (!isPhone(page)) {
      await page.getByTestId('view-evidence').click();
      await expect(page.getByTestId('gap-dock')).toBeVisible();
      expect(await blockingViolations(page)).toEqual([]);
    }

    await page.getByTestId('open-route-details').click();
    await expect(page.getByRole('dialog')).toBeVisible();
    expect(await blockingViolations(page)).toEqual([]);
  });

  test('"no route" has none', async ({ page }) => {
    await stubHealthyApi(page);
    await stubRouteComparison(page);
    await stubNoRoute(page);
    await page.goto(PLANNER);
    await mapReady(page);
    await runExample(page);
    await expect(page.getByTestId('no-accessible-route')).toBeVisible();

    expect(await blockingViolations(page)).toEqual([]);
  });

  test('the map failure state has none', async ({ page }) => {
    // The fallback is exactly the state a screen-reader user is most likely to
    // meet, so it gets the same scrutiny as the happy path.
    await breakMapStyle(page);
    await page.goto(PLANNER);
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'error', {
      timeout: 20_000,
    });

    expect(await blockingViolations(page)).toEqual([]);
  });

  test('both pages declare a language and have exactly one level-1 heading', async ({ page }) => {
    for (const path of ['/', PLANNER]) {
      await page.goto(path);
      await expect(page.locator('html')).toHaveAttribute('lang', 'en');
      await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
    }
  });

  test('zoom is not capped below 500%', async ({ page }) => {
    // Locking zoom shuts out low-vision users; the viewport meta must allow it.
    await page.goto(PLANNER);

    const content = await page.locator('meta[name="viewport"]').getAttribute('content');

    expect(content).not.toMatch(/user-scalable\s*=\s*no/);
    const maximum = /maximum-scale\s*=\s*([\d.]+)/.exec(content ?? '');
    if (maximum?.[1] !== undefined) {
      expect(Number.parseFloat(maximum[1])).toBeGreaterThanOrEqual(5);
    }
  });
});
