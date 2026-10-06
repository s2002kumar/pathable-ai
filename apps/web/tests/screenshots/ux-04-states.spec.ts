import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

/**
 * PA-UX-04 evidence: the seven Golden Master states, over the real Waterloo
 * network.
 *
 * Never part of CI: it needs the API, the database and the 180,554-segment
 * graph, and it stubs nothing. Point it at a build of this branch whose API
 * serves the real Waterloo dataset — the local production envelope, say:
 *
 *   SCREENSHOT_BASE_URL=http://localhost:3001 \
 *   PLAYWRIGHT_CHROMIUM_ARGS="--host-resolver-rules=MAP localhost 127.0.0.1" \
 *     pnpm exec playwright test --config=playwright.screenshots.config.ts ux-04
 *
 * Each capture is taken at its Figma frame's size, so it can be laid beside
 * the frame. Every figure in the images is the API's answer at the time of the
 * run; `observations.json` records what each state said, and when.
 */

function outputDir(testInfo: { config: { rootDir: string } }): string {
  // <repo>/apps/web/tests/screenshots -> <repo>
  return path.resolve(testInfo.config.rootDir, '../../../..', 'docs/evidence/screenshots/ux-04');
}

const observations: Record<string, unknown>[] = [];

async function settle(page: Page, ms = 6_000): Promise<void> {
  // The camera's fit is a timed move, then the basemap fetches and draws the
  // tiles where it landed on a software renderer. Early captures show a
  // half-flown camera and missing labels.
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(ms);
}

async function mapReady(page: Page): Promise<void> {
  await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready', {
    timeout: 120_000,
  });
}

async function runExample(page: Page): Promise<void> {
  await page.getByTestId('run-verified-example').click();
  await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success', {
    timeout: 240_000,
  });
}

async function texts(page: Page, ids: readonly string[]): Promise<Record<string, string | null>> {
  const result: Record<string, string | null> = {};
  for (const id of ids) {
    const locator = page.getByTestId(id).first();
    result[id] =
      (await locator.count()) > 0 ? (await locator.innerText()).replace(/\s+/g, ' ').trim() : null;
  }
  return result;
}

async function capture(
  page: Page,
  testInfo: TestInfo,
  name: string,
  fullPage: boolean,
  ids: readonly string[],
): Promise<void> {
  const dir = outputDir(testInfo);
  await mkdir(dir, { recursive: true });
  await page.screenshot({ path: path.join(dir, `${name}.png`), fullPage, animations: 'disabled' });
  observations.push({
    state: name,
    url: page.url(),
    viewport: page.viewportSize(),
    capturedAt: new Date().toISOString(),
    text: await texts(page, ids),
  });
}

test.describe.configure({ mode: 'serial' });

test.afterAll(async ({}, testInfo) => {
  await writeFile(
    path.join(outputDir(testInfo), 'observations.json'),
    `${JSON.stringify(observations, null, 2)}\n`,
  );
});

test('10:2318 — landing, desktop', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/');
  await settle(page, 1_500);
  await capture(page, testInfo, '10-2318-landing-desktop', true, ['hero-visual']);
});

test('17:3167 — landing, phone', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await settle(page, 1_500);
  await capture(page, testInfo, '17-3167-landing-phone', true, []);
});

test('17:3555 — planning, desktop', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 1204 });
  await page.goto('/planner');
  await mapReady(page);
  await expect(page.getByTestId('system-status')).toHaveAttribute('data-status', 'ready', {
    timeout: 120_000,
  });
  await settle(page);
  await capture(page, testInfo, '17-3555-plan-desktop', false, ['system-status', 'profile-rule']);
});

test('9:1905 — comparison, desktop', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 1152 });
  await page.goto('/planner');
  await mapReady(page);
  await runExample(page);
  await settle(page);
  await capture(page, testInfo, '9-1905-compare-desktop', false, [
    'difference-accessible',
    'difference-shortest',
    'main-difference',
    'dock-stairs',
    'dock-grade',
    'dock-crossings',
    'dock-surface',
  ]);
});

test('17:3789 — one route’s evidence, desktop', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 1152 });
  await page.goto('/planner');
  await mapReady(page);
  await runExample(page);
  await page.getByTestId('view-evidence').click();
  await expect(page.getByTestId('gap-dock')).toBeVisible();
  await settle(page);
  await capture(page, testInfo, '17-3789-evidence-desktop', false, [
    'gap-banner',
    'gap-stairs',
    'gap-grade',
    'gap-crossings',
    'gap-surface',
  ]);
});

test('17:4041 — no route for the profile, desktop', async ({ page }, testInfo) => {
  // A real no-route answer, not a stub: the verified journey with a 1% uphill
  // limit, which every path between the two buildings breaks.
  await page.setViewportSize({ width: 1280, height: 1152 });
  await page.goto('/planner');
  await mapReady(page);
  await runExample(page);
  await page.getByTestId('uphill-limit-toggle').click();
  await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success', {
    timeout: 240_000,
  });
  await page.getByTestId('uphill-limit-range').focus();
  await page.keyboard.press('Home');
  await expect(page.getByTestId('route-workspace')).toHaveAttribute('data-layout', 'no-route', {
    timeout: 240_000,
  });
  await settle(page);
  await capture(page, testInfo, '17-4041-no-route-desktop', false, [
    'no-accessible-route',
    'requirement-steps',
    'requirement-too_steep',
  ]);
});

test('17:2865 — comparison, phone', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/planner');
  await mapReady(page);
  await runExample(page);
  await settle(page);
  // A full-page capture resizes the viewport while it shoots, and the map's
  // WebGL canvas is caught blank mid-resize. Make the viewport the page first.
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  await page.setViewportSize({ width: 390, height });
  await settle(page, 4_000);
  await capture(page, testInfo, '17-2865-compare-phone', false, [
    'difference-accessible',
    'difference-shortest',
    'mobile-stairs',
    'mobile-grade',
    'mobile-crossings',
    'mobile-surface',
  ]);
});
