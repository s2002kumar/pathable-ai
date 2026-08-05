/**
 * Liveness endpoint for the web container.
 *
 * Answers "is the Next.js server process serving?" and nothing more — it must not
 * probe the API, or a backend outage would mark the frontend unhealthy and
 * Compose would restart a perfectly functional web server.
 */

export const dynamic = 'force-dynamic';

export function GET(): Response {
  return Response.json(
    { status: 'ok', service: 'pathable-web' },
    { headers: { 'Cache-Control': 'no-store' } },
  );
}
