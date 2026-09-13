/**
 * Backend status probe.
 *
 * Deliberately reads `/health/ready` rather than `/health/live`: liveness only
 * says a process answered, which would show a reassuring green badge while the
 * database is down. Readiness distinguishes the two, and its 503 body carries the
 * same shape as its 200 body so one parse covers both.
 */
import { API_ROUTES, type ReadinessResponse } from '@pathable/contracts';
import type { SystemStatus } from './types';

/** Bounded so a hanging backend cannot leave the badge spinning forever. */
export const STATUS_TIMEOUT_MS = 5_000;

const DEPENDENCY_LABELS: Record<string, string> = {
  database: 'database',
  postgis: 'PostGIS',
  graph: 'routing graph',
};

function isReadinessResponse(value: unknown): value is ReadinessResponse {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<ReadinessResponse>;
  return (
    (candidate.status === 'ready' || candidate.status === 'not_ready') &&
    typeof candidate.service === 'string' &&
    typeof candidate.version === 'string' &&
    typeof candidate.checks === 'object' &&
    candidate.checks !== null
  );
}

/**
 * Whether the only thing not ready is a routing graph that is still loading.
 *
 * The backend distinguishes the cases in the check's own words: a graph being
 * built reads "loading <region>" or "pending", while a graph that will never
 * arrive reads "no active dataset" or names a failure. Only the first is a
 * waiting state, and treating the others as one would hide a real fault behind
 * a spinner forever.
 */
function isPreparingGraph(body: ReadinessResponse): boolean {
  const checks = body.checks as Record<string, { status: string; detail: string } | undefined>;
  const graph = checks.graph;
  if (graph === undefined || graph.status === 'ok') return false;

  const everythingElseIsFine = Object.entries(checks).every(
    ([name, check]) => name === 'graph' || check?.status === 'ok',
  );
  if (!everythingElseIsFine) return false;

  return /^\s*(loading|pending)\b/i.test(graph.detail);
}

function failingDependencies(body: ReadinessResponse): string[] {
  return Object.entries(body.checks)
    .filter(([, check]) => check.status !== 'ok')
    .map(([name]) => DEPENDENCY_LABELS[name] ?? name);
}

export type FetchOptions = {
  readonly apiBaseUrl: string;
  readonly signal?: AbortSignal;
  readonly timeoutMs?: number;
  readonly fetchImpl?: typeof fetch;
};

/**
 * Probe the backend. Resolves to a status; never rejects, because "the backend
 * is down" is an expected outcome the UI must render, not an exception.
 */
export async function fetchSystemStatus({
  apiBaseUrl,
  signal,
  timeoutMs = STATUS_TIMEOUT_MS,
  fetchImpl,
}: FetchOptions): Promise<SystemStatus> {
  const doFetch = fetchImpl ?? globalThis.fetch;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const onAbort = () => controller.abort();
  signal?.addEventListener('abort', onAbort);

  try {
    const response = await doFetch(`${apiBaseUrl}${API_ROUTES.readiness}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: controller.signal,
      cache: 'no-store',
    });

    const body: unknown = await response.json().catch(() => null);

    if (!isReadinessResponse(body)) {
      return {
        state: 'unreachable',
        reason: `The API responded with an unexpected body (HTTP ${response.status}).`,
      };
    }

    if (response.ok && body.status === 'ready') {
      return { state: 'ready', service: body.service, version: body.version };
    }

    if (isPreparingGraph(body)) {
      return {
        state: 'preparing',
        service: body.service,
        version: body.version,
        detail: body.checks.graph.detail,
      };
    }

    return {
      state: 'degraded',
      service: body.service,
      version: body.version,
      failing: failingDependencies(body),
    };
  } catch (error) {
    // Distinguishing the timeout matters: "we gave up waiting" and "nothing is
    // listening" lead a developer to check different things.
    const timedOut = error instanceof Error && error.name === 'AbortError';
    return {
      state: 'unreachable',
      reason: timedOut
        ? `The API did not respond within ${Math.round(timeoutMs / 1000)}s.`
        : 'The API could not be reached.',
    };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}
