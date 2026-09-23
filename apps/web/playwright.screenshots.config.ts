import { defineConfig, devices } from '@playwright/test';

/**
 * Product screenshots over the real, active Waterloo dataset.
 *
 * Never part of a CI run: these specs need an API, a database and a
 * 180,000-segment network, and they stub nothing.
 */

/**
 * Extra Chromium flags, the same mechanism and the same reason as the
 * full-stack configuration: on a Windows host where `localhost` resolves to
 * `::1` first and Docker Desktop's IPv6 proxy resets the connection, the
 * page's own calls to the API origin baked into the image die before IPv4 is
 * tried.
 *
 *   PLAYWRIGHT_CHROMIUM_ARGS="--host-resolver-rules=MAP localhost 127.0.0.1"
 *
 * Several flags are separated by `;`. See docs/deployment/PRODUCTION_SMOKE.md.
 */
const EXTRA_CHROMIUM_ARGS = (process.env.PLAYWRIGHT_CHROMIUM_ARGS ?? '')
  .split(';')
  .map((arg) => arg.trim())
  .filter((arg) => arg.length > 0);

export default defineConfig({
  testDir: './tests/screenshots',
  timeout: 300_000,
  expect: { timeout: 180_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    // Overridable so the same specs can be pointed at the isolated envelope
    // preview (3001) as well as a local dev server (3000). Both must be
    // serving a build of the branch under review, against the real API.
    baseURL: process.env.SCREENSHOT_BASE_URL ?? 'http://localhost:3000',
    ...devices['Desktop Chrome'],
    launchOptions: {
      // Headless Chromium has no GPU; SwiftShader provides the WebGL 2
      // context MapLibre requires, exactly as the stubbed suite does.
      args: [
        '--use-gl=angle',
        '--use-angle=swiftshader',
        '--enable-unsafe-swiftshader',
        ...EXTRA_CHROMIUM_ARGS,
      ],
    },
  },
});
