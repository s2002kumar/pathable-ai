import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end configuration.
 *
 * Two hard rules, both enforced here rather than left to convention:
 *
 *  1. No test may depend on public tile availability. The web server is started
 *     with a local, source-less map style, so MapLibre reaches `load` with zero
 *     network traffic and the suite passes offline and in CI.
 *  2. No test may depend on a running backend. The API base URL points at a port
 *     nothing listens on, so the default expectation is "backend offline"; tests
 *     that need a healthy backend install a route stub.
 */

const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 3100);
const BASE_URL = `http://127.0.0.1:${WEB_PORT}`;

/** Deliberately closed: the offline experience is the default under test. */
const UNREACHABLE_API = 'http://127.0.0.1:9';

export default defineConfig({
  testDir: './tests/e2e',
  outputDir: './test-results',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  // Capped deliberately. Every test renders MapLibre through SwiftShader, which
  // is software rasterisation and entirely CPU-bound — Playwright's default of
  // one worker per two cores starves them and produces timeouts, not speed.
  workers: 2,
  timeout: 60_000,
  // Generous because SwiftShader rasterises the map on the CPU: two workers on a
  // laptop can push a normally-instant assertion past a tight budget.
  expect: { timeout: 15_000 },

  reporter: process.env.CI
    ? [['github'], ['html', { outputFolder: 'playwright-report', open: 'never' }]]
    : [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],

  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },

  projects: [
    {
      name: 'desktop-chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        launchOptions: {
          // Headless Chromium has no GPU; SwiftShader provides the WebGL 2
          // context MapLibre requires. Without this the suite would only ever
          // exercise the unsupported-browser fallback.
          args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
        },
      },
    },
    {
      name: 'mobile-chromium',
      use: {
        ...devices['Pixel 7'],
        launchOptions: {
          args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
        },
      },
    },
  ],

  webServer: {
    // `next start` against a production build: the same artefact CI ships, and
    // free of dev-mode double rendering that would muddy the map lifecycle tests.
    command: `pnpm exec next build && pnpm exec next start --port ${WEB_PORT}`,
    url: `${BASE_URL}/api/healthz`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    stdout: 'pipe',
    stderr: 'pipe',
    env: {
      NODE_ENV: 'production',
      NEXT_PUBLIC_API_BASE_URL: process.env.E2E_API_BASE_URL ?? UNREACHABLE_API,
      NEXT_PUBLIC_MAP_STYLE_URL: '/map-styles/offline-test-style.json',
      NEXT_PUBLIC_PILOT_CENTER_LAT: '43.4668',
      NEXT_PUBLIC_PILOT_CENTER_LON: '-80.5164',
      NEXT_PUBLIC_PILOT_ZOOM: '14',
      NEXT_PUBLIC_PILOT_REGION_NAME: 'Waterloo, Ontario',
    },
  },
});
