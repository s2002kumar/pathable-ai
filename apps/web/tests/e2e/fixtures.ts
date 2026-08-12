import type { Page } from '@playwright/test';

/**
 * Shared e2e helpers.
 *
 * Two invariants these exist to protect:
 *   - no test may reach the public internet (no tile servers, no CDNs)
 *   - no test may require a running backend or database
 *
 * The backend is therefore stubbed at the network layer when a test needs a
 * particular status, and left genuinely unreachable otherwise.
 */

export const READINESS_PATTERN = '**/api/v1/health/ready';
export const MAP_STYLE_PATTERN = '**/map-styles/offline-test-style.json';

export const SCREENSHOT_DIR = 'artifacts/screenshots';

const READY_BODY = {
  status: 'ready',
  service: 'pathable-api',
  version: '0.1.0',
  checks: {
    database: { status: 'ok', detail: 'connected', latency_ms: 3.4 },
    postgis: { status: 'ok', detail: 'postgis 3.5.0', latency_ms: 1.2 },
  },
};

const NOT_READY_BODY = {
  status: 'not_ready',
  service: 'pathable-api',
  version: '0.1.0',
  checks: {
    database: { status: 'unavailable', detail: 'database unreachable', latency_ms: null },
    postgis: {
      status: 'unavailable',
      detail: 'not probed: database unreachable',
      latency_ms: null,
    },
  },
};

/** Serve the readiness payload a healthy full stack would return. */
export async function stubHealthyApi(page: Page): Promise<void> {
  await page.route(READINESS_PATTERN, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(READY_BODY),
    });
  });
}

/** Serve what a running API with a dead database returns. */
export async function stubDegradedApi(page: Page): Promise<void> {
  await page.route(READINESS_PATTERN, async (route) => {
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify(NOT_READY_BODY),
    });
  });
}

/** Make the map style 404, which drives MapLibre's initialisation-failure path. */
export async function breakMapStyle(page: Page): Promise<void> {
  await page.route(MAP_STYLE_PATTERN, async (route) => {
    await route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
  });
}

/**
 * Hold the map style until the caller releases it.
 *
 * A gate rather than a timed delay on purpose: with a fixed `setTimeout`, a
 * loaded machine can spend the whole delay just getting through `page.goto`, and
 * the loading state is gone before the assertion runs. Blocking until the test
 * says so makes the loading state observable regardless of how slow the host is.
 */
export async function holdMapStyle(page: Page): Promise<{ release: () => void }> {
  let release = (): void => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });

  await page.route(MAP_STYLE_PATTERN, async (route) => {
    await gate;
    await route.continue();
  });

  return { release: () => release() };
}

/** True when the page overflows sideways — always a layout bug, never a feature. */
export async function hasHorizontalOverflow(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const doc = document.documentElement;
    // 1px of tolerance for sub-pixel rounding on fractional device ratios.
    return doc.scrollWidth > doc.clientWidth + 1;
  });
}
