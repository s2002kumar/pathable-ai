import { expect, test, type Page } from '@playwright/test';
import {
  PLANNER,
  hasHorizontalOverflow,
  isPhone,
  openJourneyControls,
  runExample,
  stubHealthyApi,
  stubNoRoute,
  stubRouteComparison,
  waitForMapReady,
} from './fixtures';

/**
 * The map-first layout, in a real browser.
 *
 * Unit tests can say what the panel contains; only a layout engine can say
 * where it is. These assert what the Golden Master's layout exists for — the
 * map is the product and the panel never hides what it must not, the answer
 * is on screen without scrolling on a laptop — plus what is easy to lose in a
 * restyle: one map instance, keyboard reach, reduced motion, and reflow.
 */

type Box = { x: number; y: number; width: number; height: number };

function overlapArea(a: Box, b: Box): number {
  const x = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x));
  const y = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
  return x * y;
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

/**
 * Which of these sit wholly on screen and inside the panel's visible box —
 * not merely in the window, where an element scrolled out of the panel still
 * counts. Elements outside the panel are judged against the window alone.
 */
async function visibleIn(page: Page, ids: readonly string[]): Promise<Record<string, boolean>> {
  return page.evaluate((list) => {
    const panel = document.querySelector('[aria-label="Route planner"]');
    const box = panel?.getBoundingClientRect();
    const result: Record<string, boolean> = {};
    for (const id of list) {
      const element = document.querySelector(`[data-testid="${id}"]`);
      const rect = element?.getBoundingClientRect();
      if (!element || !rect || rect.height === 0) {
        result[id] = false;
        continue;
      }
      const inPanel = panel !== null && panel !== undefined && panel.contains(element);
      const top = inPanel && box ? Math.max(0, box.top) : 0;
      const bottom = inPanel && box ? Math.min(window.innerHeight, box.bottom) : window.innerHeight;
      result[id] = rect.top >= top - 1 && rect.bottom <= bottom + 1;
    }
    return result;
  }, ids);
}

/** Record every map lifecycle transition from now on; a remount passes `initialising`. */
async function watchMapLifecycle(page: Page): Promise<() => Promise<string[]>> {
  await page.evaluate(() => {
    const frame = document.querySelector('[data-testid="map-frame"]');
    const states: string[] = [];
    (window as unknown as { __mapStates: string[] }).__mapStates = states;
    new MutationObserver(() => {
      states.push(frame?.getAttribute('data-map-state') ?? '');
    }).observe(frame!, { attributes: true, attributeFilter: ['data-map-state'] });
  });
  return () => page.evaluate(() => (window as unknown as { __mapStates: string[] }).__mapStates);
}

/** Everything drawn over the map's canvas, hidden for `routeUnderSurfaces`'s shot. */
const OVER_THE_MAP = `
  [data-testid="map-frame"] > :not([role="region"]),
  .maplibregl-control-container,
  aside[aria-label="Route planner"],
  [data-testid="evidence-dock"],
  [data-testid="gap-dock"] { visibility: hidden !important; opacity: 0 !important; }
`;

/**
 * Whether the map drew anything, and how many of its pixels lie under the
 * panel or a dock.
 *
 * The routes are WebGL, so no DOM box says where they are; the pixels do. The
 * test style paints only a flat background, so with every surface over the
 * map hidden for the shot, any pixel unlike the map's corner is a route, a
 * stairway or an endpoint. Hidden by `visibility` and `opacity`, which move
 * nothing; `visibility` alone left text inside them drawn.
 */
async function routeUnderSurfaces(page: Page): Promise<{ drawn: boolean; covered: number }> {
  const frame = await page.getByTestId('map-frame').boundingBox();
  if (frame === null) return { drawn: false, covered: -1 };
  const surfaces = await page.evaluate(() =>
    [
      'aside[aria-label="Route planner"]',
      '[data-testid="evidence-dock"]',
      '[data-testid="gap-dock"]',
    ]
      .map((selector) => document.querySelector(selector)?.getBoundingClientRect())
      .filter((rect): rect is DOMRect => rect !== undefined && rect.width > 0)
      .map(({ left, top, right, bottom }) => ({ left, top, right, bottom })),
  );
  const shot = await page.screenshot({ clip: frame, style: OVER_THE_MAP });
  return page.evaluate(
    async ({ png, frame, surfaces }) => {
      const image = new Image();
      image.src = `data:image/png;base64,${png}`;
      await image.decode();
      const canvas = document.createElement('canvas');
      canvas.width = image.width;
      canvas.height = image.height;
      const context = canvas.getContext('2d')!;
      context.drawImage(image, 0, 0);
      const { data } = context.getImageData(0, 0, image.width, image.height);
      const scale = image.width / frame.width;
      const [r, g, b] = [data[0]!, data[1]!, data[2]!];
      let drawn = 0;
      let covered = 0;
      for (let y = 0; y < image.height; y += 1) {
        for (let x = 0; x < image.width; x += 1) {
          const i = (y * image.width + x) * 4;
          if (
            Math.abs(data[i]! - r) + Math.abs(data[i + 1]! - g) + Math.abs(data[i + 2]! - b) <
            48
          ) {
            continue;
          }
          drawn += 1;
          const px = frame.x + x / scale;
          const py = frame.y + y / scale;
          if (surfaces.some((s) => px >= s.left && px < s.right && py >= s.top && py < s.bottom)) {
            covered += 1;
          }
        }
      }
      // A route at least a few hundred pixels long, or this proves nothing.
      return { drawn: drawn > 400 * scale * scale, covered };
    },
    { png: shot.toString('base64'), frame, surfaces },
  );
}

/** Every visible label on the map whose box crosses one of the map's controls. */
async function labelsUnderControls(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    // Found as a viewer would name them, not by the attribute the fix added.
    const controls = [
      ...document.querySelectorAll(
        '[data-testid="map-controls"], [data-testid="map-frame"] [role="group"][aria-label="Map view"]',
      ),
    ].map((element) => element.getBoundingClientRect());
    return [...document.querySelectorAll<HTMLElement>('[data-testid="map-evidence"] [data-pin]')]
      .filter(
        (label) => label.closest<HTMLElement>('[data-variant]')?.style.visibility === 'visible',
      )
      .filter((label) => {
        const a = label.getBoundingClientRect();
        return controls.some(
          (b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom,
        );
      })
      .map((label) => label.dataset.testid ?? '?');
  });
}

test.describe('layout', () => {
  test.beforeEach(async ({ page }) => {
    await stubHealthyApi(page);
    await stubRouteComparison(page);
  });

  test('the map runs the full width, from the bar to the credit line', async ({ page }) => {
    await page.goto(PLANNER);
    await waitForMapReady(page);

    const map = await page.getByTestId('map-frame').boundingBox();
    const viewport = page.viewportSize();
    expect(map).not.toBeNull();
    expect(viewport).not.toBeNull();
    if (map === null || viewport === null) return;

    expect(map.width).toBe(viewport.width);
    // Directly under the 64 px bar.
    expect(Math.round(map.y)).toBe(64);
    if (isPhone(page)) {
      // 17:2865: a map band above the sheet, not a sliver.
      expect(map.height).toBeGreaterThanOrEqual(300);
    } else {
      // 9:1905: everything between the bar and the credit line.
      const footer = await page.getByTestId('attribution').boundingBox();
      expect(footer).not.toBeNull();
      if (footer === null) return;
      expect(Math.abs(map.y + map.height - footer.y)).toBeLessThanOrEqual(1);
    }
  });

  test('what the panel covers is published to the map chrome', async ({ page }) => {
    // The panel floats over the map, so the map's own furniture — the ODbL
    // credit — and the camera's fit padding have to know how much of the map
    // is behind it. That figure is measured from the panel and written to a
    // custom property; this is the wiring between the two.
    test.skip(isPhone(page), 'the phone sheet starts under the map rather than over it');
    await page.goto(PLANNER);
    await waitForMapReady(page);

    const measured = await page.evaluate(() => {
      const workspace = document.querySelector('[data-testid="route-workspace"]');
      const panel = document.querySelector('[aria-label="Route planner"]');
      const map = document.querySelector('[data-testid="map-frame"]');
      if (!workspace || !panel || !map) return null;
      const panelBox = panel.getBoundingClientRect();
      const mapBox = map.getBoundingClientRect();
      return {
        insetLeft: Number.parseFloat(
          getComputedStyle(workspace).getPropertyValue('--map-inset-left'),
        ),
        panelReachFromLeft: panelBox.right - mapBox.left,
      };
    });
    expect(measured).not.toBeNull();
    if (measured === null) return;
    expect(Math.abs(measured.insetLeft - measured.panelReachFromLeft)).toBeLessThanOrEqual(2);
  });

  test('the ODbL credit stays out from under the panel, the dock and the pills', async ({
    page,
  }) => {
    // ODbL requires the credit to be visible. A full-bleed map with surfaces
    // floating over it would cover it quietly, in exactly the screenshot
    // somebody would publish.
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await runExample(page);
    await page.evaluate(() => window.scrollTo(0, 0));

    const credit = await page.locator('.maplibregl-ctrl-attrib').boundingBox();
    expect(credit).not.toBeNull();
    if (credit === null) return;
    await expect(page.locator('.maplibregl-ctrl-attrib')).toBeVisible();

    const covers = isPhone(page)
      ? [page.getByRole('complementary', { name: /route planner/i })]
      : [
          page.getByRole('complementary', { name: /route planner/i }),
          page.getByTestId('evidence-dock'),
        ];
    for (const surface of covers) {
      const box = await surface.boundingBox();
      expect(box).not.toBeNull();
      if (box !== null) expect(overlapArea(box, credit)).toBe(0);
    }
  });

  test('at the frame’s own size the whole comparison is on screen as drawn', async ({ page }) => {
    // 9:1905 is 1280 × 1152: both routes in the panel, all four categories in
    // the dock beneath, nothing scrolled.
    test.skip(isPhone(page), 'the phone answer is a sheet under the map; see reflow');
    await page.setViewportSize({ width: 1280, height: 1152 });
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await runExample(page);

    const ids = [
      'difference-accessible',
      'difference-shortest',
      'difference-extra',
      'main-difference',
      'evidence-dock',
      'dock-stairs',
      'dock-grade',
      'dock-crossings',
      'dock-surface',
    ] as const;
    expect(await visibleIn(page, ids)).toEqual(Object.fromEntries(ids.map((id) => [id, true])));
    expect(await page.evaluate(() => document.documentElement.scrollTop)).toBe(0);
  });

  test('choosing a route is keyboard-operable and never erases the comparison', async ({
    page,
  }) => {
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await runExample(page);

    // The profile's own route is chosen first; the group is one tab stop.
    const accessible = page.getByTestId('difference-accessible');
    const shortest = page.getByTestId('difference-shortest');
    await expect(accessible).toHaveAttribute('aria-checked', 'true');
    await expect(shortest).toHaveAttribute('tabindex', '-1');
    await accessible.focus();

    await page.keyboard.press('ArrowDown');
    await expect(shortest).toHaveAttribute('aria-checked', 'true');
    await expect(shortest).toBeFocused();
    // The other route stays on screen, and nothing calls either one cleared.
    await expect(accessible).toBeVisible();
    await expect(page.getByTestId('plan-journey')).not.toContainText(/\bcleared\b|\bcertified\b/i);

    await page.keyboard.press('ArrowUp');
    await expect(accessible).toHaveAttribute('aria-checked', 'true');
    await expect(accessible).toBeFocused();
  });

  test('from "no route", Edit Profile reaches the profile without asking again', async ({
    page,
  }) => {
    await stubNoRoute(page);
    const requests: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/routes/compare')) requests.push(request.url());
    });

    await page.goto(PLANNER);
    await waitForMapReady(page);
    await runExample(page);
    await expect(page.getByTestId('route-workspace')).toHaveAttribute('data-layout', 'no-route');
    const lifecycle = await watchMapLifecycle(page);
    const asked = requests.length;

    await page.getByTestId('edit-profile').click();

    await expect(page.getByTestId('route-workspace')).toHaveAttribute('data-layout', 'compare');
    await expect(page.getByRole('radio', { name: /^Wheelchair/ })).toBeFocused();
    await expect(page.getByRole('radio', { name: /^Wheelchair/ })).toBeInViewport();
    // The answer is still the one asked for; nothing was asked again.
    await expect(page.getByTestId('no-accessible-route')).toBeVisible();
    expect(requests.length).toBe(asked);
    expect(await lifecycle()).toEqual([]);
  });

  test('Change Destination goes to the destination field', async ({ page }) => {
    await stubNoRoute(page);
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await runExample(page);

    await page.getByTestId('change-destination').click();
    await expect(page.getByLabel('Destination')).toBeFocused();
  });

  test('ordinary updates never recreate the map', async ({ page }) => {
    await page.goto(PLANNER);
    await waitForMapReady(page);
    const lifecycle = await watchMapLifecycle(page);

    await runExample(page);
    await openJourneyControls(page);
    await page.getByRole('radio', { name: /^Stroller or pram/ }).check();
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
    await openJourneyControls(page);
    await page.getByTestId('swap-points').click();

    expect(await lifecycle()).toEqual([]);
  });

  test('reduced motion removes the transitions', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await runExample(page);

    const durations = await page.evaluate(() => {
      const dock = document.querySelector('[data-testid="evidence-dock"]');
      const card = document.querySelector('[data-testid="difference-accessible"]');
      return {
        animation: dock ? getComputedStyle(dock).animationDuration : '0s',
        transition: card ? getComputedStyle(card).transitionDuration : '0s',
      };
    });
    // The global reduced-motion rule collapses everything to 0.01ms; Chromium
    // reports it as "1e-05s". Anything under a frame counts as none.
    for (const part of `${durations.animation},${durations.transition}`.split(',')) {
      expect(Number.parseFloat(part)).toBeLessThan(0.016);
    }
  });

  test('the planning form is walked by the keyboard in reading order', async ({ page }) => {
    await page.goto(PLANNER);
    await waitForMapReady(page);

    const stops: string[] = [];
    for (let i = 0; i < 40; i += 1) {
      await page.keyboard.press('Tab');
      const id = await page.evaluate(
        () => document.activeElement?.getAttribute('data-testid') ?? '',
      );
      stops.push(id);
      if (id === 'run-verified-example') break;
    }

    const at = (id: string) => stops.indexOf(id);
    expect(at('pick-origin')).toBeGreaterThanOrEqual(0);
    expect(at('pick-origin')).toBeLessThan(at('pick-destination'));
    expect(at('pick-destination')).toBeLessThan(at('uphill-limit-toggle'));
    expect(at('uphill-limit-toggle')).toBeLessThan(at('run-verified-example'));

    // Compare is not a stop until there is a journey: a disabled control is
    // not focusable, and it says so rather than sending half a journey.
    await expect(page.getByTestId('compare-routes')).toBeDisabled();
  });
});

test.describe('reflow', () => {
  test.beforeEach(async ({ page }) => {
    await stubHealthyApi(page);
    await stubRouteComparison(page);
  });

  test('an ordinary 1000 px laptop window keeps the map-led layout', async ({ page }) => {
    await page.setViewportSize({ width: 1000, height: 700 });
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await runExample(page);

    const map = await page.getByTestId('map-frame').boundingBox();
    const panel = await page.getByRole('complementary', { name: /route planner/i }).boundingBox();
    expect(map).not.toBeNull();
    expect(panel).not.toBeNull();
    if (map === null || panel === null) return;

    expect(map.width).toBe(1000);
    // Beside the map, not stacked above a page that scrolls.
    expect(panel.width).toBeLessThan(map.width / 2);
    expect(await fullyInViewport(page, 'difference-accessible')).toBe(true);
    expect(await hasHorizontalOverflow(page)).toBe(false);
  });

  for (const size of [
    { width: 1280, height: 800 },
    { width: 1366, height: 768 },
  ]) {
    test(`a ${size.width} × ${size.height} laptop shows both routes without scrolling the panel`, async ({
      page,
    }) => {
      // The comparison opened still scrolled to the form's foot, and the frame's
      // composition left the panel too short to show the shortest route. A
      // shorter window puts the answer first and slims the dock to one bar.
      await page.setViewportSize(size);
      await page.goto(PLANNER);
      await waitForMapReady(page);
      await runExample(page);

      const ids = [
        'difference-accessible',
        'difference-shortest',
        'difference-extra',
        'main-difference',
        'evidence-dock',
      ] as const;
      expect(await visibleIn(page, ids)).toEqual(Object.fromEntries(ids.map((id) => [id, true])));
      expect(
        await page
          .getByRole('complementary', { name: /route planner/i })
          .evaluate((panel) => panel.scrollTop),
      ).toBe(0);

      const panel = await page.getByRole('complementary', { name: /route planner/i }).boundingBox();
      const dock = await page.getByTestId('evidence-dock').boundingBox();
      expect(panel).not.toBeNull();
      expect(dock).not.toBeNull();
      if (panel !== null && dock !== null) expect(overlapArea(panel, dock)).toBe(0);
      expect(await fullyInViewport(page, 'evidence-dock')).toBe(true);
    });
  }

  test('on a 1280 × 800 laptop, one route’s evidence keeps its panel whole beside its gaps', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await runExample(page);
    await page.getByTestId('view-evidence').click();
    await expect(page.getByTestId('gap-dock')).toBeVisible();

    const ids = ['gap-banner', 'open-route-details', 'toggle-evidence', 'gap-dock'] as const;
    expect(await visibleIn(page, ids)).toEqual(Object.fromEntries(ids.map((id) => [id, true])));
    const panel = await page.getByRole('complementary', { name: /route planner/i }).boundingBox();
    const dock = await page.getByTestId('gap-dock').boundingBox();
    expect(panel).not.toBeNull();
    expect(dock).not.toBeNull();
    if (panel !== null && dock !== null) expect(overlapArea(panel, dock)).toBe(0);
    expect(await hasHorizontalOverflow(page)).toBe(false);
  });

  test('on a 1280 × 800 laptop, neither the panel nor a dock covers the route', async ({
    page,
  }) => {
    // Regression, PA-UX-04: one route's evidence was framed for the
    // comparison's slim dock, and the far taller gap dock beside the panel
    // covered most of the route. The camera is immediate under reduced motion.
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await runExample(page);
    await expect(page.getByTestId('evidence-dock')).toBeVisible();
    await expect.poll(() => routeUnderSurfaces(page)).toEqual({ drawn: true, covered: 0 });

    await page.getByTestId('view-evidence').click();
    await expect(page.getByTestId('gap-dock')).toBeVisible();
    await expect.poll(() => routeUnderSurfaces(page)).toEqual({ drawn: true, covered: 0 });
  });

  test('on a 390 px phone, a place name never runs under the map controls', async ({ page }) => {
    // Regression, PA-UX-04: the origin landed near the map's right edge and
    // its name ran underneath the controls. Moved up into the controls' band,
    // then toward them a step at a time, each name has to move to its point's
    // other side or give way.
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await runExample(page);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.locator('.maplibregl-canvas').focus();
    // The view moves south, so the routes move up, level with the controls.
    await page.keyboard.press('ArrowDown');

    let turned = false;
    for (let step = 0; step < 4; step += 1) {
      await expect.poll(() => labelsUnderControls(page)).toEqual([]);
      turned ||= await page.evaluate(() =>
        [
          ...document.querySelectorAll<HTMLElement>('[data-variant="endpoint"][data-side="left"]'),
        ].some((element) => element.style.visibility === 'visible'),
      );
      // The view moves west, so the routes move right, toward the controls.
      await page.keyboard.press('ArrowLeft');
    }
    // Otherwise nothing above came near the controls and the test proved nothing.
    expect(turned).toBe(true);
  });

  test('a phone opens the answer at the map, with the sheet under it', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(PLANNER);
    await waitForMapReady(page);
    // The example sits at the foot of the form, so the page is scrolled to press it.
    await runExample(page);

    // The answer opens at the map, not wherever the form was scrolled to.
    await expect(page.getByTestId('map-frame')).toBeInViewport({ ratio: 0.9 });
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Wheelchair profile');
    await expect(page.getByRole('heading', { level: 1 })).toBeInViewport();

    // Both routes and the four categories follow, in reading order.
    const order = await page.evaluate(() =>
      ['difference-accessible', 'difference-shortest', 'mobile-stairs', 'mobile-surface'].map(
        (id) => document.querySelector(`[data-testid="${id}"]`)?.getBoundingClientRect().top ?? -1,
      ),
    );
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(await hasHorizontalOverflow(page)).toBe(false);
  });

  test('320 px wide, nothing overflows and the credit stays on the map', async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 568 });
    await page.goto(PLANNER);
    await waitForMapReady(page);
    await runExample(page);

    expect(await hasHorizontalOverflow(page)).toBe(false);

    await page.evaluate(() => window.scrollTo(0, 0));
    const frame = await page.getByTestId('map-frame').boundingBox();
    const credit = await page.locator('.maplibregl-ctrl-attrib').boundingBox();
    const sheet = await page.getByRole('complementary', { name: /route planner/i }).boundingBox();
    expect(frame).not.toBeNull();
    expect(credit).not.toBeNull();
    expect(sheet).not.toBeNull();
    if (frame === null || credit === null || sheet === null) return;
    expect(credit.y + credit.height).toBeLessThanOrEqual(frame.y + frame.height + 1);
    expect(overlapArea(credit, sheet)).toBe(0);

    await page.getByTestId('attribution').scrollIntoViewIfNeeded();
    await expect(page.getByTestId('attribution')).toBeVisible();
  });

  test('at the width 200% zoom leaves, everything is still reachable', async ({ page }) => {
    // 1440 × 900 at 200% is 720 × 450 CSS pixels.
    await page.setViewportSize({ width: 720, height: 450 });
    await page.goto(PLANNER);
    await waitForMapReady(page);

    expect(await hasHorizontalOverflow(page)).toBe(false);
    await page.getByTestId('run-verified-example').scrollIntoViewIfNeeded();
    await expect(page.getByTestId('run-verified-example')).toBeInViewport();
    await runExample(page);
    await page.getByTestId('difference-shortest').scrollIntoViewIfNeeded();
    await expect(page.getByTestId('difference-shortest')).toBeInViewport();
    expect(await hasHorizontalOverflow(page)).toBe(false);
  });

  test('a landscape phone keeps the map and reaches the answer', async ({ page }) => {
    await page.setViewportSize({ width: 844, height: 390 });
    await page.goto(PLANNER);
    await waitForMapReady(page);

    const map = await page.getByTestId('map-frame').boundingBox();
    expect(map).not.toBeNull();
    if (map === null) return;
    expect(map.height).toBeGreaterThanOrEqual(200);

    await runExample(page);
    expect(await hasHorizontalOverflow(page)).toBe(false);
    await page.getByTestId('difference-shortest').scrollIntoViewIfNeeded();
    await expect(page.getByTestId('difference-shortest')).toBeInViewport();
  });
});
