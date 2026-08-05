/**
 * jsdom test environment setup.
 *
 * jsdom implements neither WebGL nor the observer APIs MapLibre relies on, so the
 * browser-only surface the map code touches is stubbed here once. The map module
 * itself is exercised through its own state machine and through Playwright, not
 * by pretending jsdom can render a map.
 */
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';

class ResizeObserverStub implements ResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

class IntersectionObserverStub implements IntersectionObserver {
  readonly root = null;
  readonly rootMargin = '';
  readonly thresholds: readonly number[] = [];
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}

globalThis.ResizeObserver ??= ResizeObserverStub;
globalThis.IntersectionObserver ??=
  IntersectionObserverStub as unknown as typeof IntersectionObserver;

if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  // Every test that cares about network behaviour installs its own fetch stub.
  // Failing loudly by default stops a forgotten stub from silently hitting the
  // real network and turning a unit test into a flaky integration test.
  vi.stubGlobal(
    'fetch',
    vi.fn(() => {
      throw new Error(
        'Unstubbed fetch call in a unit test. Stub globalThis.fetch explicitly in the test.',
      );
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
