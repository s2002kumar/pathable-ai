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

  test('the map fills the window behind the panel', async ({ page }) => {
    // PA-UX-02A. The previous layout gave the map a column beside the planner
    // and, below 64rem, a 34dvh strip above it. The map is the product: above
    // the document-flow fallback it takes the whole workspace and the planner
    // floats over it.
    await page.goto('/');
    await waitForMapReady(page);

    const map = await page.getByTestId('map-frame').boundingBox();
    const viewport = page.viewportSize();
    expect(map).not.toBeNull();
    expect(viewport).not.toBeNull();
    if (map === null || viewport === null) return;

    expect(map.width).toBe(viewport.width);
    // Everything but the header row.
    expect(map.height).toBeGreaterThan(viewport.height * 0.9);
  });

  test('what the panel covers is published to the map chrome', async ({ page }) => {
    // The panel floats over the map, so the map's own furniture — the scale
    // bar, the ODbL credit, the map key — and the camera's fit padding all
    // have to know how much of the map is behind it. That figure is measured
    // from the panel and written to a custom property; this is the wiring
    // between the measurement and everything that reads it.
    await page.goto('/');
    await waitForMapReady(page);

    const measured = await page.evaluate(() => {
      const workspace = document.querySelector('[data-testid="route-workspace"]');
      const panel = document.querySelector('[aria-label="Route planner"]');
      const map = document.querySelector('[data-testid="map-frame"]');
      if (!workspace || !panel || !map) return null;

      const panelBox = panel.getBoundingClientRect();
      const mapBox = map.getBoundingClientRect();
      const style = getComputedStyle(workspace);
      return {
        insetLeft: Number.parseFloat(style.getPropertyValue('--map-inset-left')),
        insetBottom: Number.parseFloat(style.getPropertyValue('--map-inset-bottom')),
        panelReachFromLeft: panelBox.right - mapBox.left,
        panelReachFromBottom: mapBox.bottom - panelBox.top,
      };
    });
    expect(measured).not.toBeNull();
    if (measured === null) return;

    // One of the two axes is the one the panel is anchored to, and that one
    // has to match what the panel actually covers. Rounded to whole pixels.
    const insetLeftMatches = Math.abs(measured.insetLeft - measured.panelReachFromLeft) <= 2;
    const insetBottomMatches = Math.abs(measured.insetBottom - measured.panelReachFromBottom) <= 2;
    expect(insetLeftMatches || insetBottomMatches).toBe(true);
    expect(measured.insetLeft + measured.insetBottom).toBeGreaterThan(0);
  });

  test('the map key and the ODbL credit stay out from under the panel', async ({ page }) => {
    // ODbL requires the credit to be visible. A full-bleed map with a panel
    // over one edge would cover it quietly, and in exactly the screenshot
    // somebody would publish.
    await page.goto('/');
    await waitForMapReady(page);
    // The map key appears with the routes it explains, so there has to be a
    // comparison on screen before there is a key to keep clear of the panel.
    await runExample(page);

    const panel = await page.getByRole('complementary', { name: /route planner/i }).boundingBox();
    const legend = await page.getByTestId('map-legend').boundingBox();
    const credit = await page.locator('.maplibregl-ctrl-attrib').boundingBox();
    expect(panel).not.toBeNull();
    expect(legend).not.toBeNull();
    expect(credit).not.toBeNull();
    if (panel === null || legend === null || credit === null) return;

    const overlapArea = (a: typeof panel, b: typeof panel) => {
      const x = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x));
      const y = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
      return x * y;
    };

    expect(overlapArea(panel, legend)).toBe(0);
    expect(overlapArea(panel, credit)).toBe(0);
    await expect(page.locator('.maplibregl-ctrl-attrib')).toBeVisible();
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
    await runExample(page);

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

  test('"Edit journey or profile" reaches the controls without touching the result', async ({
    page,
  }) => {
    // PA-UX-01F. The answer sits above the planning controls; this is the one
    // way back down. It moves focus and scrolls; it changes nothing else — no
    // new request, no map reset, the same comparison still on screen.
    const requests: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/routes/compare')) requests.push(request.url());
    });

    await page.goto('/');
    await waitForMapReady(page);
    await runExample(page);
    const requestsAfterExample = requests.length;
    await page.evaluate(() => {
      const frame = document.querySelector('[data-testid="map-frame"]');
      const states: string[] = [];
      (window as unknown as { __mapStates: string[] }).__mapStates = states;
      new MutationObserver(() => {
        states.push(frame?.getAttribute('data-map-state') ?? '');
      }).observe(frame!, { attributes: true, attributeFilter: ['data-map-state'] });
    });

    const edit = page.getByRole('button', { name: /edit journey or profile/i });
    await expect(edit).toBeVisible();
    await edit.focus();
    await page.keyboard.press('Enter');

    const plan = page.getByTestId('plan-journey');
    await expect(plan).toBeFocused();
    await expect(plan).toBeInViewport();
    // The next stop from the landing is a real control.
    await page.keyboard.press('Tab');
    await expect(page.getByRole('searchbox', { name: 'Start' })).toBeFocused();

    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
    await expect(page.getByTestId('route-difference')).toBeAttached();
    await expect(page.getByLabel(/how do you travel/i)).toHaveValue('wheelchair');
    expect(requests.length).toBe(requestsAfterExample);
    expect(
      await page.evaluate(() => (window as unknown as { __mapStates: string[] }).__mapStates),
    ).toEqual([]);
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
    await page.getByLabel(/how do you travel/i).selectOption('stroller');
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
    await page.getByTestId('swap-points').click();
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

  test('the planning controls come first for the keyboard, then the example', async ({ page }) => {
    // The panel is ordered Start → Destination → Profile → Compare → example,
    // so the example is no longer the first meaningful stop; the controls a
    // person came to use are. What still has to hold is that everything is
    // reachable by Tab alone, in that order, without hunting.
    await page.goto('/');
    await waitForMapReady(page);

    const stops: string[] = [];
    for (let i = 0; i < 24; i += 1) {
      await page.keyboard.press('Tab');
      const id = await page.evaluate(
        () => document.activeElement?.getAttribute('data-testid') ?? '',
      );
      stops.push(id);
      if (id === 'run-verified-example') break;
    }

    expect(stops).toContain('run-verified-example');
    // The order the panel reads in is the order the keyboard walks it.
    const at = (id: string) => stops.indexOf(id);
    expect(at('pick-origin')).toBeGreaterThanOrEqual(0);
    expect(at('pick-origin')).toBeLessThan(at('pick-destination'));
    expect(at('pick-destination')).toBeLessThan(at('run-verified-example'));

    // Compare is deliberately absent from that walk: with no journey drafted
    // it is disabled, and a disabled control is not a tab stop. It joins the
    // order as soon as there is something to compare.
    await expect(page.getByTestId('compare-routes')).toBeDisabled();
    await runExample(page);
    await expect(page.getByTestId('compare-routes')).toBeEnabled();
  });
});

test.describe('reflow', () => {
  test.beforeEach(async ({ page }) => {
    await stubHealthyApi(page);
    await stubRouteComparison(page);
  });

  test('an ordinary 1000 px laptop window gets the map-led layout', async ({ page }) => {
    // The bug the founder was looking at. The two-pane desktop layout was
    // gated at `min-width: 64rem` — 1024 px at a 16 px root — so a 1000 px
    // window missed it by 24 px and fell all the way back to the phone
    // composition: a 34dvh map strip above a long scrolling page. The map
    // area measured 1000 x 287.
    await page.setViewportSize({ width: 1000, height: 700 });
    await page.goto('/');
    await waitForMapReady(page);
    await runExample(page);

    const map = await page.getByTestId('map-frame').boundingBox();
    const panel = await page.getByRole('complementary', { name: /route planner/i }).boundingBox();
    expect(map).not.toBeNull();
    expect(panel).not.toBeNull();
    if (map === null || panel === null) return;

    expect(map.width).toBe(1000);
    expect(map.height).toBeGreaterThan(600);
    // Beside the map, not stacked above a page that scrolls.
    expect(panel.width).toBeLessThan(map.width / 2);

    // And the whole answer is on screen at that size, which is the point of
    // the panel being compact rather than a full-height rail.
    expect(await fullyInViewport(page, 'difference-accessible')).toBe(true);
    expect(await fullyInViewport(page, 'difference-shortest')).toBe(true);
    expect(await fullyInViewport(page, 'difference-extra')).toBe(true);
    expect(await fullyInViewport(page, 'uncertainty-summary')).toBe(true);
    expect(await hasHorizontalOverflow(page)).toBe(false);
  });

  test('a phone gets the same map, with the planner as a sheet it can shut', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    await waitForMapReady(page);
    await runExample(page);

    const viewport = page.viewportSize()!;
    const map = await page.getByTestId('map-frame').boundingBox();
    expect(map).not.toBeNull();
    if (map === null) return;
    expect(map.width).toBe(viewport.width);
    expect(map.height).toBeGreaterThan(viewport.height * 0.9);

    // The whole answer, inside the sheet, without scrolling it.
    expect(await fullyInViewport(page, 'difference-accessible')).toBe(true);
    expect(await fullyInViewport(page, 'difference-shortest')).toBe(true);
    expect(await fullyInViewport(page, 'difference-extra')).toBe(true);
    expect(await fullyInViewport(page, 'uncertainty-summary')).toBe(true);

    // The control says what it does and does it — the layout this replaced
    // drew a grip that looked draggable and was not.
    const toggle = page.getByTestId('sheet-toggle');
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');

    const open = await page.getByRole('complementary', { name: /route planner/i }).boundingBox();
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(toggle).toHaveText(/expand/i);
    const shut = await page.getByRole('complementary', { name: /route planner/i }).boundingBox();
    expect(open).not.toBeNull();
    expect(shut).not.toBeNull();
    if (open === null || shut === null) return;
    expect(shut.height).toBeLessThan(open.height);

    // And it opens again, with the same answer still in it.
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
    await expect(page.getByTestId('difference-accessible')).toBeVisible();
  });

  test('an answer arriving into a shut sheet still opens it', async ({ page }) => {
    // A shut sheet has its contents removed from the page, live region and
    // all. Planning a journey by map click with it pulled down would otherwise
    // compute a comparison that is announced to nobody and drawn with no
    // figures beside it.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    await waitForMapReady(page);

    const toggle = page.getByTestId('sheet-toggle');
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');

    const map = await page.getByTestId('map-frame').boundingBox();
    expect(map).not.toBeNull();
    if (map === null) return;

    // Well clear of the collapsed bar along the bottom.
    await page.mouse.click(map.x + map.width * 0.3, map.y + map.height * 0.25);
    await expect(page.getByTestId('endpoint-origin-value')).not.toContainText(/not set/i);
    // Setting only the start leaves it shut: somebody who pulled the sheet
    // down to see more map is still placing points on it.
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await page.mouse.click(map.x + map.width * 0.7, map.y + map.height * 0.35);

    // Completing the pair reopens it, because Compare lives inside the sheet:
    // a shut sheet would leave somebody with a finished journey and no way to
    // submit it.
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await page.getByTestId('compare-routes').click();
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
    await expect(page.getByTestId('difference-accessible')).toBeVisible();
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
    await page.getByTestId('run-verified-example').scrollIntoViewIfNeeded();
    await expect(page.getByTestId('run-verified-example')).toBeVisible();
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
