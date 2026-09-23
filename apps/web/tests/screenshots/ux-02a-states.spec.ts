import { expect, test } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';

/**
 * The two states PA-UX-02A exists to prove, at the three viewports it was
 * reviewed at, over the real Waterloo network.
 *
 * NO ROUTE HANDLERS, like its sibling `real-waterloo.spec.ts`. Nothing here may
 * stub the API: the point of these images is that the map-led composition is
 * holding a live answer, and a screenshot of a fixture would be a picture of
 * nothing.
 *
 * Not part of the normal suite. It needs a running API, a database and a
 * 180,000-segment network, and CI has none of them. Point it at the preview:
 *
 *   SCREENSHOT_BASE_URL=http://localhost:3001 \
 *     pnpm --filter @pathable/web exec playwright test \
 *     --config=playwright.screenshots.config.ts ux-02a-states
 *
 * Alongside each pair of images it writes the measurements the evidence
 * document quotes — the map's area, whether the whole answer is in the
 * viewport, horizontal overflow, console errors — so those figures come from a
 * run rather than from a reading of the CSS.
 */

const OUT = 'docs/evidence/screenshots/ux-02a';

/**
 * The viewports the direction was reviewed at.
 *
 * 1000 x 700 is the one that matters: it is an ordinary laptop window, and it
 * is where the previous layout fell back to the phone composition because its
 * desktop breakpoint sat at 64rem.
 */
const VIEWPORTS = [
  { name: '1000x700', width: 1000, height: 700, mobile: false },
  { name: '1366x768', width: 1366, height: 768, mobile: false },
  { name: '390x844', width: 390, height: 844, mobile: true },
] as const;

type Observation = Record<string, unknown>;

const observations: Observation[] = [];

test.describe('PA-UX-02A candidate', () => {
  test.slow();

  for (const viewport of VIEWPORTS) {
    test(`initial and result at ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await mkdir(OUT, { recursive: true });

      const problems: string[] = [];
      page.on('console', (message) => {
        if (message.type() === 'error') problems.push(`console: ${message.text().slice(0, 200)}`);
      });
      page.on('pageerror', (error) => problems.push(`pageerror: ${String(error).slice(0, 200)}`));

      await page.goto('/');
      await page.waitForFunction(
        () =>
          document.querySelector('[data-testid="map-frame"]')?.getAttribute('data-map-state') ===
          'ready',
        undefined,
        { timeout: 60_000 },
      );
      // The basemap is fetched over the internet and rasterised on the CPU;
      // this is a picture for a person to look at, so let it finish drawing.
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(5_000);

      const environment = await page.evaluate(() => ({
        innerWidth: window.innerWidth,
        innerHeight: window.innerHeight,
        devicePixelRatio: window.devicePixelRatio,
        rootFontPx: Number.parseFloat(getComputedStyle(document.documentElement).fontSize),
        visualViewport: window.visualViewport
          ? {
              width: window.visualViewport.width,
              height: window.visualViewport.height,
              scale: window.visualViewport.scale,
            }
          : null,
        // Recorded because a screenshot does not carry a browser's zoom level,
        // and the breakpoint this revision moved is the thing in question.
        matched: {
          'min-width: 48rem': matchMedia('(min-width: 48rem)').matches,
          'min-width: 64rem': matchMedia('(min-width: 64rem)').matches,
          'min-height: 34rem': matchMedia('(min-height: 34rem)').matches,
        },
      }));

      await page.screenshot({ path: `${OUT}/${viewport.name}-initial.png` });

      // One press, and everything after it is the live engine answering.
      const startedAt = Date.now();
      await page.getByTestId('run-verified-example').click();
      await expect(page.getByTestId('route-status')).toHaveAttribute(
        'data-route-state',
        'success',
        { timeout: 240_000 },
      );
      const answeredMs = Date.now() - startedAt;

      // Two separate waits, both learned the hard way. `fitBounds` runs a
      // timed camera move, so a short pause catches a half-flown camera; and
      // the basemap then has to fetch and rasterise the tiles for wherever it
      // landed, on a CPU renderer. Capturing too early produced images with
      // the route missing entirely and most labels absent — which looks
      // exactly like a product that failed to draw its answer.
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(8_000);
      await page.screenshot({ path: `${OUT}/${viewport.name}-result.png` });

      const layout = await page.evaluate(() => {
        const rect = (selector: string) => {
          const element = document.querySelector(selector);
          if (element === null) return null;
          const box = element.getBoundingClientRect();
          return {
            x: Math.round(box.x),
            y: Math.round(box.y),
            width: Math.round(box.width),
            height: Math.round(box.height),
          };
        };
        const whollyVisible = (selector: string) => {
          const element = document.querySelector(selector);
          if (element === null) return false;
          const box = element.getBoundingClientRect();
          return (
            box.top >= 0 &&
            box.bottom <= window.innerHeight &&
            box.left >= 0 &&
            box.right <= window.innerWidth &&
            box.height > 0
          );
        };
        return {
          map: rect('[data-testid="map-frame"]'),
          panel: rect('[aria-label="Route planner"]'),
          credit: rect('.maplibregl-ctrl-attrib'),
          horizontalOverflow:
            document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
          // The whole answer, without scrolling and without opening anything.
          answerInViewport: {
            accessible: whollyVisible('[data-testid="difference-accessible"]'),
            shortest: whollyVisible('[data-testid="difference-shortest"]'),
            detour: whollyVisible('[data-testid="difference-extra"]'),
            uncertainty: whollyVisible('[data-testid="uncertainty-summary"]'),
            mapKey: whollyVisible('[data-testid="map-legend"]'),
          },
        };
      });

      observations.push({ viewport: viewport.name, environment, answeredMs, layout, problems });
      await writeFile(`${OUT}/observations.json`, JSON.stringify(observations, null, 2), 'utf8');

      // The images are the deliverable, but a capture that quietly lost the
      // answer is worse than no capture, so the run asserts it too.
      expect(layout.horizontalOverflow).toBe(false);
      expect(layout.answerInViewport).toEqual({
        accessible: true,
        shortest: true,
        detour: true,
        uncertainty: true,
        mapKey: true,
      });
    });
  }
});
