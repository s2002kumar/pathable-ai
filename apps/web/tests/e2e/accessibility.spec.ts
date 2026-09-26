import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { breakMapStyle, stubHealthyApi, stubRouteComparison } from './fixtures';

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

async function scan(page: import('@playwright/test').Page) {
  return (
    new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      // MapLibre's own control chrome is third-party markup this project does not
      // author. It is excluded so the suite reports on the application shell, which
      // is what the team can actually fix.
      .exclude('.maplibregl-control-container')
      .analyze()
  );
}

/**
 * Serious and critical violations, one entry per offending element.
 *
 * Reporting the element selector rather than just the rule name is the
 * difference between "fix the contrast somewhere" and a five-second fix.
 */
async function blockingViolations(page: import('@playwright/test').Page): Promise<string[]> {
  const results = await scan(page);
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

test.describe('accessibility', () => {
  test('application shell has no serious or critical violations', async ({ page }) => {
    await stubHealthyApi(page);
    await page.goto('/');
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready', {
      timeout: 20_000,
    });

    expect(await blockingViolations(page)).toEqual([]);
  });

  test('a comparison, with its evidence and the uphill field open, has none either', async ({
    page,
  }) => {
    // The result is where the new structure lives — the route radio group,
    // the evidence labels, the coverage bars, the labels pinned to the map —
    // so it gets the same scan as the empty shell.
    await stubHealthyApi(page);
    await stubRouteComparison(page);
    await page.goto('/');
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready', {
      timeout: 20_000,
    });
    await page.getByTestId('run-verified-example').click();
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
    await expect(page.getByTestId('map-marker-barrier-steps')).toBeVisible();
    await page.getByTestId('uphill-limit-toggle').check();
    await expect(page.getByTestId('uphill-limit-input')).toBeVisible();

    expect(await blockingViolations(page)).toEqual([]);
  });

  test('map failure state has no serious or critical violations', async ({ page }) => {
    // The fallback is exactly the state a screen-reader user is most likely to
    // meet, so it gets the same scrutiny as the happy path.
    await breakMapStyle(page);
    await page.goto('/');
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'error', {
      timeout: 20_000,
    });

    expect(await blockingViolations(page)).toEqual([]);
  });

  test('page declares a language', async ({ page }) => {
    await page.goto('/');

    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  });

  test('there is exactly one level-1 heading', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
  });

  test('zoom is not capped below 500%', async ({ page }) => {
    // Locking zoom shuts out low-vision users; the viewport meta must allow it.
    await page.goto('/');

    const content = await page.locator('meta[name="viewport"]').getAttribute('content');

    expect(content).not.toMatch(/user-scalable\s*=\s*no/);
    const maximum = /maximum-scale\s*=\s*([\d.]+)/.exec(content ?? '');
    if (maximum?.[1] !== undefined) {
      expect(Number.parseFloat(maximum[1])).toBeGreaterThanOrEqual(5);
    }
  });
});
