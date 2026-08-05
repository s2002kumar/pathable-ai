import { describe, expect, it } from 'vitest';
import { GET } from './route';

describe('GET /api/healthz', () => {
  it('reports the web server as ok', async () => {
    const response = GET();

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ status: 'ok', service: 'pathable-web' });
  });

  it('is never cached', () => {
    // A cached liveness response would let Compose call a dead container healthy.
    expect(GET().headers.get('Cache-Control')).toBe('no-store');
  });

  it('does not depend on the API', async () => {
    // No fetch stub is installed here; the shared setup makes any network call
    // throw, so this passing proves the route touches nothing external.
    await expect(GET().json()).resolves.toMatchObject({ status: 'ok' });
  });
});
