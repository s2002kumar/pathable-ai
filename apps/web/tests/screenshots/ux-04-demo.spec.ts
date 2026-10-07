import { chromium, expect, test, type Page } from '@playwright/test';
import { copyFile, mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

/**
 * The PA-UX-04 demo, recorded from one real browser session.
 *
 * Never part of CI: it needs the API, the database and the real Waterloo
 * network, and it stubs nothing. Playwright's video recorder captures the
 * session as it happens; nothing is edited, spliced or re-timed afterwards.
 *
 * It renders on the machine's GPU (ANGLE over Direct3D 11) rather than the
 * suite's SwiftShader: recording while software WebGL draws the basemap
 * stalled the page for half a minute, which no viewer of the product sees.
 *
 *   SCREENSHOT_BASE_URL=http://localhost:3001 \
 *   PLAYWRIGHT_CHROMIUM_ARGS="--host-resolver-rules=MAP localhost 127.0.0.1" \
 *     pnpm exec playwright test --config=playwright.screenshots.config.ts ux-04-demo
 *
 * The path: landing → Explore Planner → the verified example → the comparison
 * → the recorded stairs → what is not recorded → the derived grade → one
 * route's evidence → the full record → stop.
 */

const VIEWPORT = { width: 1280, height: 800 };

function repoRoot(testInfo: { config: { rootDir: string } }): string {
  // <repo>/apps/web/tests/screenshots -> <repo>
  return path.resolve(testInfo.config.rootDir, '../../../..');
}

async function hold(page: Page, ms: number): Promise<void> {
  await page.waitForTimeout(ms);
}

test('records the demo', async ({ baseURL }, testInfo) => {
  test.setTimeout(300_000);
  const browser = await chromium.launch({
    args: [
      '--use-angle=d3d11',
      '--ignore-gpu-blocklist',
      ...(process.env.PLAYWRIGHT_CHROMIUM_ARGS ?? '')
        .split(';')
        .map((arg) => arg.trim())
        .filter((arg) => arg.length > 0),
    ],
  });
  const videoDir = testInfo.outputPath('video');
  const context = await browser.newContext({
    baseURL: baseURL ?? 'http://localhost:3001',
    viewport: VIEWPORT,
    recordVideo: { dir: videoDir, size: VIEWPORT },
  });
  const page = await context.newPage();
  const marks: Array<{ at: number; step: string }> = [];
  const started = Date.now();
  const mark = (step: string) => marks.push({ at: (Date.now() - started) / 1000, step });
  page.on('request', (request) => {
    if (request.url().includes('/routes/compare')) mark('request sent');
  });
  page.on('response', (reply) => {
    if (reply.url().includes('/routes/compare')) mark('response received');
  });

  // The landing page: what it is, and the example as the API recorded it.
  mark('landing');
  await page.goto('/');
  await hold(page, 6_000);
  await page.locator('#how-it-works').scrollIntoViewIfNeeded();
  await hold(page, 5_000);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
  await hold(page, 1_500);

  // Into the planner, which asks the live API.
  mark('planner');
  await page.getByTestId('hero-explore').click();
  // The panel and a ready routing service are enough to begin; the basemap
  // finishes drawing on camera rather than in dead air before the first press.
  await expect(page.getByTestId('plan-journey')).toBeVisible();
  await expect(page.getByTestId('system-status')).toHaveAttribute('data-status', 'ready', {
    timeout: 60_000,
  });
  await hold(page, 4_000);

  // One press: the verified example, computed now.
  mark('verified example');
  const answer = page.waitForResponse(
    (response) => response.url().includes('/api/v1/routes/compare') && response.status() === 200,
  );
  await page.getByTestId('run-verified-example').click();
  const response = await answer;
  // Read now: the body is gone once the context closes to finish the video.
  const body = (await response.json()) as {
    standard_route: { distance_m: number; stairway_count: number; step_count: number };
    accessible_route: { distance_m: number; stairway_count: number };
    extra_distance_m: number;
    dataset: { dataset_id: string; checksum: string };
    routing_policy_version: number | string;
    ml_predictions_used: boolean;
  };
  await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
  mark('comparison');
  await hold(page, 7_000);

  // The recorded stairs: bring the shortest route forward, then back.
  mark('recorded stairs');
  await page.getByTestId('difference-shortest').click();
  await hold(page, 5_000);
  await page.getByTestId('difference-accessible').click();
  await hold(page, 2_500);

  // One route's record, gaps drawn on the map: what is not recorded, and the
  // grade derived from elevation, each under its own label.
  mark('evidence');
  await page.getByTestId('view-evidence').click();
  await expect(page.getByTestId('gap-dock')).toBeVisible();
  await hold(page, 4_000);
  mark('missing evidence');
  await page.getByTestId('gap-surface').hover();
  await hold(page, 4_500);
  mark('derived elevation');
  await page.getByTestId('gap-grade').hover();
  await hold(page, 4_500);

  // The whole answer in text.
  mark('details');
  await page.getByTestId('open-route-details').click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await hold(page, 4_000);
  await page.getByTestId('evidence-coverage').scrollIntoViewIfNeeded();
  await hold(page, 5_000);
  await page.getByText(/no predictions, no scoring, no machine learning/i).scrollIntoViewIfNeeded();
  await hold(page, 4_000);
  await page.keyboard.press('Escape');
  await hold(page, 2_000);
  mark('stop');

  const video = page.video();
  await context.close();
  await browser.close();
  const recorded = await video!.path();

  const root = repoRoot(testInfo);
  const media = path.join(root, 'docs/evidence/media');
  await mkdir(media, { recursive: true });
  await copyFile(recorded, path.join(media, 'pathable-ux04-demo.webm'));

  await writeFile(
    path.join(root, 'docs/evidence/screenshots/ux-04/demo-session.json'),
    `${JSON.stringify(
      {
        recordedAt: new Date(started).toISOString(),
        viewport: VIEWPORT,
        sessionSeconds: (Date.now() - started) / 1000,
        marks,
        response: {
          shortestDistanceM: body.standard_route.distance_m,
          shortestStairways: body.standard_route.stairway_count,
          shortestRecordedSteps: body.standard_route.step_count,
          profileDistanceM: body.accessible_route.distance_m,
          profileStairways: body.accessible_route.stairway_count,
          extraDistanceM: body.extra_distance_m,
          datasetId: body.dataset.dataset_id,
          datasetChecksum: body.dataset.checksum,
          routingPolicyVersion: body.routing_policy_version,
          mlPredictionsUsed: body.ml_predictions_used,
        },
      },
      null,
      2,
    )}\n`,
  );
});
