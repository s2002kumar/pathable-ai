import { defineConfig, devices } from '@playwright/test';

/**
 * Full-stack end-to-end configuration.
 *
 * This is the opposite of `playwright.config.ts` in one specific way: nothing is
 * stubbed. The default suite points the app at a closed port and mocks the API at
 * the network layer, which makes it deterministic but proves nothing about
 * whether the frontend and backend actually agree.
 *
 * Here the real chain runs end to end:
 *
 *     Browser -> Next.js -> FastAPI -> PostgreSQL/PostGIS
 *
 * Both servers are started by Playwright. The API needs a real PostGIS database:
 * `DATABASE_URL` must be set and reachable, and migrations must have been
 * applied. If the database is missing, readiness returns 503 and these tests
 * fail — deliberately. Silently skipping would defeat the entire purpose of this
 * suite.
 *
 * The map still uses the local source-less style: proving frontend-to-backend
 * integration is this suite's job, and depending on a public tile server would
 * add an unrelated failure mode.
 */

const API_PORT = Number(process.env.FULLSTACK_API_PORT ?? 8100);
const WEB_PORT = Number(process.env.FULLSTACK_WEB_PORT ?? 3200);

/**
 * Two modes.
 *
 * By default Playwright starts the API and web server itself, against whatever
 * database `DATABASE_URL` points at.
 *
 * Setting `FULLSTACK_TARGET=compose` instead points the browser at an
 * already-running Compose stack, so the request path is
 * `browser -> web container -> api container -> postgis container`. That is the
 * only configuration that exercises Compose networking, the container
 * entrypoint and the published ports, so it is what the Docker acceptance
 * evidence uses.
 */
const againstCompose = process.env.FULLSTACK_TARGET === 'compose';

/**
 * Extra Chromium flags, separated by ';', for the machine this runs on.
 *
 * Exists for one documented reason: on a Windows host where `localhost`
 * resolves to `::1` first and Docker Desktop's IPv6 proxy resets the
 * connection, the page's own calls to the API die before IPv4 is tried.
 * `PLAYWRIGHT_CHROMIUM_ARGS="--host-resolver-rules=MAP localhost 127.0.0.1"`
 * pins the browser to IPv4 without touching the app or the containers. CI
 * leaves it unset.
 */
const EXTRA_CHROMIUM_ARGS = (process.env.PLAYWRIGHT_CHROMIUM_ARGS ?? '')
  .split(';')
  .map((arg) => arg.trim())
  .filter((arg) => arg.length > 0);

const API_BASE_URL = againstCompose
  ? (process.env.FULLSTACK_API_URL ?? 'http://localhost:8000')
  : `http://127.0.0.1:${API_PORT}`;
const WEB_BASE_URL = againstCompose
  ? (process.env.FULLSTACK_WEB_URL ?? 'http://localhost:3000')
  : `http://127.0.0.1:${WEB_PORT}`;

if (!againstCompose && !process.env.DATABASE_URL) {
  throw new Error(
    'DATABASE_URL is not set.\n\n' +
      'The full-stack suite runs against a real PostgreSQL/PostGIS database and will\n' +
      'not fall back to mocks. Start one and export the URL, for example:\n\n' +
      '  docker compose up -d db\n' +
      '  export DATABASE_URL="postgresql+psycopg://pathable:pathable_local_dev_only@localhost:5433/pathable"\n' +
      '  uv --directory services/api run alembic upgrade head\n',
  );
}

export default defineConfig({
  testDir: './tests/fullstack',
  outputDir: './test-results-fullstack',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  // Serial: these tests share one live backend, and one of them takes it away.
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 20_000 },

  reporter: process.env.CI
    ? [['github'], ['html', { outputFolder: 'playwright-report-fullstack', open: 'never' }]]
    : [['list'], ['html', { outputFolder: 'playwright-report-fullstack', open: 'never' }]],

  use: {
    baseURL: WEB_BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'fullstack-chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        launchOptions: {
          args: [
            '--use-gl=angle',
            '--use-angle=swiftshader',
            '--enable-unsafe-swiftshader',
            ...EXTRA_CHROMIUM_ARGS,
          ],
        },
      },
    },
  ],

  // Against Compose the servers are already running in containers; Playwright
  // must not start its own.
  ...(againstCompose ? {} : { webServer: buildWebServers() }),
});

function buildWebServers() {
  return [
    {
      // The real API, against the real database.
      command: `node ../../scripts/uv.mjs run python -m pathable_api`,
      url: `${API_BASE_URL}/api/v1/health/ready`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stdout: 'pipe' as const,
      stderr: 'pipe' as const,
      env: {
        ENVIRONMENT: 'test',
        // Guaranteed non-empty: this branch only runs when not targeting
        // Compose, and that path asserts DATABASE_URL above.
        DATABASE_URL: process.env.DATABASE_URL ?? '',
        ALLOWED_ORIGINS: WEB_BASE_URL,
        LOG_FORMAT: 'console',
        LOG_LEVEL: 'WARNING',
        API_HOST: '127.0.0.1',
        API_PORT: String(API_PORT),
      },
    },
    {
      // `pnpm run build` so the `prebuild` hook runs — see playwright.config.ts.
      command: `pnpm run build && pnpm exec next start --port ${WEB_PORT}`,
      url: `${WEB_BASE_URL}/api/healthz`,
      reuseExistingServer: !process.env.CI,
      timeout: 240_000,
      stdout: 'pipe' as const,
      stderr: 'pipe' as const,
      env: {
        NODE_ENV: 'production',
        // The real API origin — not a closed port, and not a stub.
        NEXT_PUBLIC_API_BASE_URL: API_BASE_URL,
        NEXT_PUBLIC_MAP_STYLE_URL: '/map-styles/offline-test-style.json',
        NEXT_PUBLIC_PILOT_CENTER_LAT: '43.4668',
        NEXT_PUBLIC_PILOT_CENTER_LON: '-80.5164',
        NEXT_PUBLIC_PILOT_ZOOM: '14',
        NEXT_PUBLIC_PILOT_REGION_NAME: 'Waterloo, Ontario',
      },
    },
  ];
}
