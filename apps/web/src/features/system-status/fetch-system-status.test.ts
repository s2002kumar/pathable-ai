import { describe, expect, it, vi } from 'vitest';
import { fetchSystemStatus } from './fetch-system-status';

const API = 'http://api.test';

const READY_BODY = {
  status: 'ready',
  service: 'pathable-api',
  version: '0.1.0',
  checks: {
    database: { status: 'ok', detail: 'connected', latency_ms: 4.2 },
    postgis: { status: 'ok', detail: 'postgis 3.5.0', latency_ms: 1.1 },
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

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('fetchSystemStatus', () => {
  it('reports ready when the backend is fully healthy', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(READY_BODY));

    const status = await fetchSystemStatus({ apiBaseUrl: API, fetchImpl });

    expect(status).toEqual({ state: 'ready', service: 'pathable-api', version: '0.1.0' });
  });

  it('calls the readiness endpoint, not liveness', async () => {
    // Liveness would report a cheerful green badge while the database is down.
    const fetchImpl = vi.fn(async () => jsonResponse(READY_BODY));

    await fetchSystemStatus({ apiBaseUrl: API, fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith(
      'http://api.test/api/v1/health/ready',
      expect.objectContaining({ method: 'GET', cache: 'no-store' }),
    );
  });

  it('reports degraded, naming the failing dependencies, on a 503', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(NOT_READY_BODY, 503));

    const status = await fetchSystemStatus({ apiBaseUrl: API, fetchImpl });

    expect(status).toEqual({
      state: 'degraded',
      service: 'pathable-api',
      version: '0.1.0',
      failing: ['database', 'PostGIS'],
    });
  });

  it('reports degraded when only PostGIS is missing', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(
        {
          ...NOT_READY_BODY,
          checks: {
            database: { status: 'ok', detail: 'connected', latency_ms: 3 },
            postgis: { status: 'unavailable', detail: 'postgis extension is not installed' },
          },
        },
        503,
      ),
    );

    const status = await fetchSystemStatus({ apiBaseUrl: API, fetchImpl });

    expect(status).toMatchObject({ state: 'degraded', failing: ['PostGIS'] });
  });

  it('reports unreachable when the network call fails', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });

    const status = await fetchSystemStatus({ apiBaseUrl: API, fetchImpl });

    expect(status).toEqual({
      state: 'unreachable',
      reason: 'The API could not be reached.',
    });
  });

  it('distinguishes a timeout from a refused connection', async () => {
    const fetchImpl = vi.fn(async (_url: string, init?: RequestInit) => {
      // Never resolves on its own; the abort signal is what ends it.
      return await new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          reject(Object.assign(new Error('aborted'), { name: 'AbortError' }));
        });
      });
    });

    const status = await fetchSystemStatus({
      apiBaseUrl: API,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      timeoutMs: 20,
    });

    expect(status).toEqual({ state: 'unreachable', reason: 'The API did not respond within 0s.' });
  });

  it('reports unreachable when the body is not a readiness document', async () => {
    // A proxy returning an HTML error page must not be read as a healthy API.
    const fetchImpl = vi.fn(async () => new Response('<html>502</html>', { status: 502 }));

    const status = await fetchSystemStatus({ apiBaseUrl: API, fetchImpl });

    expect(status).toMatchObject({ state: 'unreachable' });
    expect(status).toHaveProperty('reason', expect.stringContaining('502'));
  });

  it('rejects a well-formed JSON body with the wrong shape', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ status: 'fine', uptime: 12 }));

    const status = await fetchSystemStatus({ apiBaseUrl: API, fetchImpl });

    expect(status).toMatchObject({ state: 'unreachable' });
  });

  it('never rejects — a down backend is an expected outcome', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error('kaboom');
    });

    await expect(fetchSystemStatus({ apiBaseUrl: API, fetchImpl })).resolves.toBeDefined();
  });

  it('honours an external abort signal', async () => {
    const controller = new AbortController();
    const fetchImpl = vi.fn(async (_url: string, init?: RequestInit) => {
      return await new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          reject(Object.assign(new Error('aborted'), { name: 'AbortError' }));
        });
      });
    });

    const pending = fetchSystemStatus({
      apiBaseUrl: API,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      signal: controller.signal,
    });
    controller.abort();

    expect(await pending).toMatchObject({ state: 'unreachable' });
  });
});
