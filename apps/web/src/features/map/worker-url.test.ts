import { describe, expect, it, vi } from 'vitest';
import {
  MAPLIBRE_WORKER_PATH,
  configureMapLibreWorker,
  currentOrigin,
  resolveWorkerUrl,
} from './worker-url';

/**
 * Regression cover for KI-1.
 *
 * MapLibre derives its worker URL from `import.meta.url` and returns an empty
 * string when that is not an http(s) URL — which is always the case once it is
 * bundled. `new Worker("")` then resolves to the page itself, the worker never
 * answers, and the map silently renders nothing at all. These tests pin the
 * property that prevents it: an absolute http(s) URL is always handed to
 * MapLibre before a map is constructed.
 */
describe('resolveWorkerUrl', () => {
  it('produces an absolute URL', () => {
    expect(resolveWorkerUrl('http://localhost:3000')).toBe(
      'http://localhost:3000/maplibre/maplibre-gl-worker.mjs',
    );
  });

  it('is absolute, not root-relative', () => {
    // MapLibre rejects anything that is not http(s), so a bare path would put us
    // straight back into the empty-worker-URL failure.
    const url = resolveWorkerUrl('https://pathable.example');

    expect(url.startsWith('https://')).toBe(true);
    expect(url).not.toBe(MAPLIBRE_WORKER_PATH);
  });

  it('preserves a non-default port', () => {
    expect(resolveWorkerUrl('http://127.0.0.1:3200')).toContain('127.0.0.1:3200');
  });
});

describe('configureMapLibreWorker', () => {
  it('sets an absolute worker URL on the MapLibre module', () => {
    const setWorkerUrl = vi.fn();

    const result = configureMapLibreWorker({ setWorkerUrl }, 'http://localhost:3000');

    expect(result).toBe('http://localhost:3000/maplibre/maplibre-gl-worker.mjs');
    expect(setWorkerUrl).toHaveBeenCalledWith(
      'http://localhost:3000/maplibre/maplibre-gl-worker.mjs',
    );
  });

  it('always passes an http(s) URL, never an empty string', () => {
    const setWorkerUrl = vi.fn();

    configureMapLibreWorker({ setWorkerUrl }, 'https://pathable.example');

    const [url] = setWorkerUrl.mock.calls[0] ?? [];
    expect(url).toMatch(/^https?:\/\//);
    expect(url).not.toBe('');
  });

  it('does nothing without a browser origin', () => {
    // Server rendering: there is no origin to resolve against, and calling
    // setWorkerUrl with a bad value would be worse than not calling it.
    const setWorkerUrl = vi.fn();

    expect(configureMapLibreWorker({ setWorkerUrl }, null)).toBeNull();
    expect(setWorkerUrl).not.toHaveBeenCalled();
  });

  it('reads a usable origin from the browser', () => {
    expect(currentOrigin()).toMatch(/^https?:\/\//);
  });

  it.each(['', 'null'])('ignores the unusable origin %j', (origin) => {
    const setWorkerUrl = vi.fn();

    expect(configureMapLibreWorker({ setWorkerUrl }, origin)).toBeNull();
    expect(setWorkerUrl).not.toHaveBeenCalled();
  });

  it('is safe to call repeatedly', () => {
    const setWorkerUrl = vi.fn();

    configureMapLibreWorker({ setWorkerUrl }, 'http://localhost:3000');
    configureMapLibreWorker({ setWorkerUrl }, 'http://localhost:3000');

    expect(setWorkerUrl).toHaveBeenCalledTimes(2);
    expect(new Set(setWorkerUrl.mock.calls.map(([u]) => u)).size).toBe(1);
  });
});
