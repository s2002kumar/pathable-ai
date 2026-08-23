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
    baseURL: 'http://localhost:3000',
    ...devices['Desktop Chrome'],
  },
});
