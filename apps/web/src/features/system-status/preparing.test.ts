/**
 * A routing graph that is still loading is not a fault.
 *
 * The API takes about twenty seconds after start to build the Waterloo graph,
 * during which readiness is honestly 503. Reporting that as "API degraded"
 * tells a first-time viewer the system is broken at the exact moment it is
 * working correctly, and sends anyone running it locally to debug nothing.
 *
 * The distinction is in the backend's own words, so these tests pin it: a graph
 * that says "loading" is on its way, and a graph that says anything else is a
 * problem that will not resolve on its own.
 */
import { describe, expect, it, vi } from 'vitest';
import { fetchSystemStatus } from './fetch-system-status';
import { describeStatus } from './SystemStatusBadge';

const OK = { status: 'ok', detail: 'connected', latency_ms: 1 };

function readiness(graph: { status: string; detail: string }, ready = false) {
  return {
    status: ready ? 'ready' : 'not_ready',
    service: 'pathable-api',
    version: '0.1.0',
    checks: { database: OK, postgis: { ...OK, detail: 'postgis 3.5.2' }, graph },
  };
}

function respond(body: unknown, status = 503) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response) as unknown as typeof fetch;
}

const options = { apiBaseUrl: 'http://api.test' };

describe('a graph that is still loading', () => {
  it('is reported as preparing, not degraded', async () => {
    const status = await fetchSystemStatus({
      ...options,
      fetchImpl: respond(readiness({ status: 'unavailable', detail: 'loading waterloo' })),
    });

    expect(status.state).toBe('preparing');
  });

  it('is reported as preparing while it is still pending', async () => {
    const status = await fetchSystemStatus({
      ...options,
      fetchImpl: respond(readiness({ status: 'unavailable', detail: 'pending' })),
    });

    expect(status.state).toBe('preparing');
  });

  it('tells the viewer what is happening rather than that something failed', () => {
    const presentation = describeStatus({
      state: 'preparing',
      service: 'pathable-api',
      version: '0.1.0',
      detail: 'loading waterloo',
    });

    expect(presentation.label).toBe('Preparing routes');
    expect(presentation.detail).toMatch(/loading the waterloo routing graph/i);
    expect(presentation.label).not.toMatch(/degraded|offline|error|fail/i);
  });
});

describe('a graph that will not arrive on its own', () => {
  it('is still degraded when the region has no dataset', async () => {
    const status = await fetchSystemStatus({
      ...options,
      fetchImpl: respond(
        readiness({ status: 'unavailable', detail: 'waterloo: no active dataset' }),
      ),
    });

    expect(status.state).toBe('degraded');
  });

  it('is still degraded when the preload failed outright', async () => {
    const status = await fetchSystemStatus({
      ...options,
      fetchImpl: respond(
        readiness({ status: 'unavailable', detail: 'waterloo: preload failed (RuntimeError)' }),
      ),
    });

    expect(status.state).toBe('degraded');
  });

  it('is degraded, not preparing, when the database is the problem too', async () => {
    // A loading graph beside a dead database is a dead database.
    const body = readiness({ status: 'unavailable', detail: 'loading waterloo' });
    const status = await fetchSystemStatus({
      ...options,
      fetchImpl: respond({
        ...body,
        checks: {
          ...body.checks,
          database: { status: 'unavailable', detail: 'database unreachable' },
        },
      }),
    });

    expect(status.state).toBe('degraded');
  });

  it('is ready once the graph has loaded', async () => {
    const status = await fetchSystemStatus({
      ...options,
      fetchImpl: respond(
        readiness(
          { status: 'ok', detail: 'waterloo: 155714 nodes, 180554 segments loaded in 28.7 s' },
          true,
        ),
        200,
      ),
    });

    expect(status.state).toBe('ready');
  });
});
