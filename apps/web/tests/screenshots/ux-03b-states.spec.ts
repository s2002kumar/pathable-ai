import { expect, test, type Page } from '@playwright/test';
import { mkdir, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';

/**
 * PA-UX-03B evidence, over the real Waterloo network.
 *
 * Never part of CI: it needs the API, the database and the 180,554-segment
 * graph, and it stubs nothing. Point it at a build of this branch whose API is
 * this branch's API (the 03A contract), for example:
 *
 *   SCREENSHOT_BASE_URL=http://127.0.0.1:3200 \
 *     pnpm exec playwright test --config=playwright.screenshots.config.ts ux-03b
 *
 * Every figure in the images is the API's answer at the time of the run; the
 * observations file records what each state said, so a reader can check the
 * pictures against the words.
 */

function outputDir(testInfo: { config: { rootDir: string } }): string {
  // <repo>/apps/web/tests/screenshots -> <repo>
  return path.resolve(testInfo.config.rootDir, '../../../..', 'docs/evidence/screenshots/ux-03b');
}

/**
 * Every viewport is checked; only the images that show something the others
 * do not are kept, so the evidence stays a size somebody will look through.
 */
const VIEWPORTS = [
  { name: '1440x900', width: 1440, height: 900, start: false, evidence: false },
  { name: '1366x768', width: 1366, height: 768, start: false, evidence: true },
  { name: '1000x700', width: 1000, height: 700, start: true, evidence: false },
  { name: '412x915', width: 412, height: 915, start: false, evidence: false },
  { name: '390x844', width: 390, height: 844, start: true, evidence: true },
] as const;

const observations: Record<string, unknown>[] = [];

async function settle(page: Page, ms = 6_000): Promise<void> {
  // The camera's fit is a timed move, then the basemap has to fetch and draw
  // the tiles where it landed on a software renderer. A capture taken early
  // shows a half-flown camera and missing labels.
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(ms);
}

async function runExample(page: Page): Promise<number> {
  const startedAt = Date.now();
  await page.getByTestId('run-verified-example').click();
  await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success', {
    timeout: 240_000,
  });
  return Date.now() - startedAt;
}

async function answerText(page: Page) {
  const text = async (id: string) =>
    (await page.getByTestId(id).count()) > 0
      ? ((await page.getByTestId(id).first().innerText()) ?? '').replace(/\s+/g, ' ').trim()
      : null;
  return {
    headline: (await page.getByTestId('route-status').getByRole('status').first().innerText())
      .replace(/\s+/g, ' ')
      .trim(),
    accessible: await text('difference-accessible'),
    shortest: await text('difference-shortest'),
    reason: await text('main-difference'),
    uncertainty: await text('uncertainty-summary'),
    markers: await page
      .getByTestId('map-evidence')
      .locator('[data-testid^="map-marker-"]')
      .allInnerTexts()
      .catch(() => []),
  };
}

async function inViewport(page: Page, ids: readonly string[]) {
  return page.evaluate((list) => {
    const result: Record<string, boolean> = {};
    for (const id of list) {
      const element = document.querySelector(`[data-testid="${id}"]`);
      const box = element?.getBoundingClientRect();
      result[id] = Boolean(
        box && box.height > 0 && box.top >= 0 && box.bottom <= window.innerHeight,
      );
    }
    return result;
  }, ids);
}

test.describe('PA-UX-03B over real Waterloo', () => {
  test.slow();

  for (const viewport of VIEWPORTS) {
    test(`the campus example at ${viewport.name}`, async ({ page }, testInfo) => {
      const OUT = outputDir(testInfo);
      await mkdir(OUT, { recursive: true });
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto('/');
      await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready', {
        timeout: 60_000,
      });
      await settle(page, 3_000);
      if (viewport.start) await page.screenshot({ path: `${OUT}/${viewport.name}-01-start.png` });

      const answeredMs = await runExample(page);
      await settle(page);
      await page.screenshot({ path: `${OUT}/${viewport.name}-02-result.png` });

      const firstScreen = await inViewport(page, [
        'difference-accessible',
        'difference-shortest',
        'difference-extra',
        'main-difference',
        'uncertainty-summary',
      ]);

      await page.getByTestId('evidence-coverage').scrollIntoViewIfNeeded();
      await page.waitForTimeout(400);
      if (viewport.evidence) {
        await page.screenshot({ path: `${OUT}/${viewport.name}-03-evidence.png` });
      }

      observations.push({
        state: 'campus example, wheelchair',
        viewport: viewport.name,
        answeredMs,
        answer: await answerText(page),
        firstScreen,
      });
      await writeFile(`${OUT}/observations.json`, `${JSON.stringify(observations, null, 2)}\n`);
    });
  }

  test('the shortest route chosen, and the traveller’s own uphill limit', async ({
    page,
  }, testInfo) => {
    const OUT = outputDir(testInfo);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/');
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready', {
      timeout: 60_000,
    });
    await runExample(page);
    await settle(page);

    await page.getByTestId('difference-shortest').click();
    await page.waitForTimeout(1_500);
    await page.screenshot({ path: `${OUT}/1440x900-04-shortest-chosen.png` });
    observations.push({
      state: 'campus example, shortest route chosen',
      viewport: '1440x900',
      coverageHeading: await page.getByTestId('evidence-coverage').locator('h3').innerText(),
      answer: await answerText(page),
    });

    // A limit low enough that the elevation model's estimates start ruling
    // segments out — the recorded/estimated split then shows on the answer.
    await page.getByTestId('uphill-limit-toggle').check();
    await page.getByTestId('uphill-limit-input').fill('2.5');
    await page.getByTestId('uphill-limit-input').press('Enter');
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success', {
      timeout: 240_000,
    });
    await settle(page);
    await page
      .getByTestId('route-difference')
      .scrollIntoViewIfNeeded()
      .catch(() => {});
    await page.screenshot({ path: `${OUT}/1440x900-05-uphill-2.5.png` });
    observations.push({
      state: 'campus example, custom uphill limit 2.5%',
      viewport: '1440x900',
      answer: await answerText(page),
      noRoute:
        (await page.getByTestId('no-accessible-route').count()) > 0
          ? await page.getByTestId('no-accessible-route').innerText()
          : null,
      reasons: (await page.getByTestId('difference-reasons').count())
        ? (await page.getByTestId('difference-reasons').innerText()).split('\n')
        : [],
    });
    await writeFile(`${OUT}/observations.json`, `${JSON.stringify(observations, null, 2)}\n`);
  });

  test('a short recording of the demo', async ({ browser }, testInfo) => {
    const OUT = outputDir(testInfo);
    const context = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      recordVideo: { dir: OUT, size: { width: 1280, height: 800 } },
    });
    const page = await context.newPage();
    await page.goto('/');
    await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready', {
      timeout: 60_000,
    });
    await settle(page, 2_500);
    await runExample(page);
    await settle(page, 5_000);
    await page.getByTestId('difference-shortest').click();
    await page.waitForTimeout(2_500);
    await page.getByTestId('difference-accessible').click();
    await page.waitForTimeout(1_500);
    await page.getByTestId('difference-reasons').scrollIntoViewIfNeeded();
    await page.waitForTimeout(2_500);
    await page.getByTestId('evidence-coverage').scrollIntoViewIfNeeded();
    await page.waitForTimeout(3_000);
    const video = page.video();
    await context.close();
    if (video) await rename(await video.path(), `${OUT}/pathable-03b-demo.webm`);
  });
});
