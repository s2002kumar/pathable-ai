/**
 * Point MapLibre at a worker served from our own origin.
 *
 * ## Why this exists
 *
 * MapLibre 6 runs tile parsing in a separate module worker and works out where
 * to load it from using its own `import.meta.url`:
 *
 * ```js
 * let e = import.meta.url;
 * if (!/^https?:/.test(e)) return "";                        // <- the trap
 * return new URL("./maplibre-gl-worker.mjs", e).href;
 * ```
 *
 * Once MapLibre is bundled, `import.meta.url` is no longer an `http(s)` URL, so
 * that returns an **empty string** and MapLibre calls `new Worker("")`. An empty
 * URL resolves to the current document, so the browser starts a worker whose
 * script is the HTML page. It loads, it never answers, and nothing throws.
 *
 * The visible result is a map that stays blank forever: the style document,
 * TileJSON and sprites are all fetched successfully, then **not one vector tile
 * is requested**, `style.load` never fires, and the console stays clean.
 *
 * This was tracked as KI-1. It was invisible to the test suite because the
 * deterministic offline style has no sources — with nothing to parse, the worker
 * is never needed and `load` fires anyway.
 *
 * ## The fix
 *
 * Serve MapLibre's own worker chunk from `/maplibre/` and pass an absolute URL to
 * `setWorkerUrl()`. `scripts/sync-maplibre-worker.mjs` copies the file (and the
 * shared chunk it imports) out of node_modules on predev/prebuild, so the served
 * worker always matches the installed version.
 *
 * Verified in Chrome 150 with a real GPU: 8 vector tiles requested, all HTTP 200,
 * `style.load` then `load`, and a recognisable Waterloo basemap.
 */

/** Public path the worker is served from. Kept in sync by the prebuild script. */
export const MAPLIBRE_WORKER_PATH = '/maplibre/maplibre-gl-worker.mjs';

/** The subset of the MapLibre module this needs — keeps the tests honest. */
export type MapLibreWorkerApi = {
  readonly setWorkerUrl: (url: string) => void;
  readonly getWorkerUrl?: () => string;
};

/**
 * Resolve the worker URL against an origin.
 *
 * MapLibre rejects anything that is not `http(s)`, so this must be absolute —
 * a root-relative path would silently put us back where we started.
 */
export function resolveWorkerUrl(origin: string): string {
  return new URL(MAPLIBRE_WORKER_PATH, origin).href;
}

/**
 * The current browser origin, or `null` when there is not one.
 *
 * Kept separate from {@link configureMapLibreWorker} so the origin is always an
 * explicit argument. A defaulted parameter cannot tell "caller omitted it" from
 * "caller passed undefined deliberately", which made the no-origin path
 * untestable.
 */
export function currentOrigin(): string | null {
  if (typeof window === 'undefined') return null;
  const { origin } = window.location;
  return origin === '' || origin === 'null' ? null : origin;
}

/**
 * Configure MapLibre's worker URL. Idempotent and safe to call before every map.
 *
 * Returns the URL that was set, or `null` when there is no origin to resolve
 * against (server rendering, or a sandboxed document with an opaque origin).
 */
export function configureMapLibreWorker(
  maplibre: MapLibreWorkerApi,
  origin: string | null,
): string | null {
  if (origin === null || origin === '' || origin === 'null') return null;

  const url = resolveWorkerUrl(origin);
  maplibre.setWorkerUrl(url);
  return url;
}
