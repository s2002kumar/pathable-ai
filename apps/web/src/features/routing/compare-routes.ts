/**
 * The route comparison request.
 *
 * The response shape is checked at runtime, not merely typed. The generated
 * types describe what the API *promises*; a version skew between a deployed
 * frontend and a deployed backend would otherwise surface as `undefined` deep
 * inside a render, which is a far worse failure than an explicit message.
 */
import { API_ROUTES, type RouteCompareResponse } from '@pathable/contracts';
import type { LngLat, ProfileSelection } from './types';

/** Bounded so a slow route search cannot leave the UI spinning forever. */
export const ROUTE_TIMEOUT_MS = 20_000;

export type CompareRoutesOptions = {
  readonly apiBaseUrl: string;
  readonly region: string;
  readonly origin: LngLat;
  readonly destination: LngLat;
  readonly profile: ProfileSelection;
  readonly signal?: AbortSignal;
  readonly timeoutMs?: number;
  readonly fetchImpl?: typeof fetch;
};

export type CompareRoutesResult =
  | { readonly ok: true; readonly data: RouteCompareResponse }
  | { readonly ok: false; readonly message: string; readonly code: string };

/**
 * A route this version can render honestly: it says whose pace its time uses,
 * and it carries its gradients with their sources. An older backend without
 * either would have the page compare unlike times and guess at provenance.
 */
function isRenderableRoute(value: unknown): boolean {
  // An absent route is a real answer ("no route for this profile"), not skew.
  if (value === null || value === undefined) return true;
  if (typeof value !== 'object') return false;
  const route = value as { pace_profile?: unknown; gradient?: unknown };
  return (
    typeof route.pace_profile === 'string' &&
    typeof route.gradient === 'object' &&
    route.gradient !== null
  );
}

function isRouteCompareResponse(value: unknown): value is RouteCompareResponse {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<RouteCompareResponse>;
  return (
    typeof candidate.profile === 'string' &&
    Array.isArray(candidate.explanations) &&
    // Every statement must say what it rests on; its label is read from that.
    candidate.explanations.every(
      (explanation: unknown) =>
        typeof explanation === 'object' &&
        explanation !== null &&
        typeof (explanation as { basis?: unknown }).basis === 'string',
    ) &&
    Array.isArray(candidate.cautions) &&
    typeof candidate.dataset === 'object' &&
    candidate.dataset !== null &&
    candidate.ml_predictions_used === false &&
    isRenderableRoute(candidate.standard_route) &&
    isRenderableRoute(candidate.accessible_route)
  );
}

function errorMessage(body: unknown, status: number): { message: string; code: string } {
  if (typeof body === 'object' && body !== null) {
    const candidate = body as { message?: unknown; code?: unknown };
    if (typeof candidate.message === 'string' && candidate.message.length > 0) {
      return {
        message: candidate.message,
        code: typeof candidate.code === 'string' ? candidate.code : 'error',
      };
    }
  }
  return { message: `The routing service responded with HTTP ${status}.`, code: 'error' };
}

/**
 * Ask the API to compare a standard route with an accessibility-aware one.
 *
 * Never rejects: a failed route is an outcome the UI has to render, not an
 * exception to escape into an error boundary.
 */
export async function compareRoutes({
  apiBaseUrl,
  region,
  origin,
  destination,
  profile,
  signal,
  timeoutMs = ROUTE_TIMEOUT_MS,
  fetchImpl,
}: CompareRoutesOptions): Promise<CompareRoutesResult> {
  const doFetch = fetchImpl ?? globalThis.fetch;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const onAbort = () => controller.abort();
  signal?.addEventListener('abort', onAbort);

  try {
    const response = await doFetch(`${apiBaseUrl}${API_ROUTES.compareRoutes}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        region,
        origin: { longitude: origin.longitude, latitude: origin.latitude },
        destination: { longitude: destination.longitude, latitude: destination.latitude },
        profile: profile.key,
        ...(profile.custom ? { custom: profile.custom } : {}),
      }),
      signal: controller.signal,
      // A route query says where somebody is and how they move. Caching it in a
      // shared HTTP cache is not something to do by default.
      cache: 'no-store',
    });

    const body: unknown = await response.json().catch(() => null);

    if (!response.ok) {
      const { message, code } = errorMessage(body, response.status);
      return { ok: false, message, code };
    }

    if (!isRouteCompareResponse(body)) {
      return {
        ok: false,
        code: 'unexpected_response',
        message: 'The routing service returned a response this version does not understand.',
      };
    }

    return { ok: true, data: body };
  } catch (error) {
    const timedOut = error instanceof Error && error.name === 'AbortError';
    return {
      ok: false,
      code: timedOut ? 'timeout' : 'unreachable',
      message: timedOut
        ? `The routing service did not respond within ${Math.round(timeoutMs / 1000)} seconds.`
        : 'The routing service could not be reached.',
    };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}
