import { defineConfig, devices } from '@playwright/test';

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
  },
});
