import { EXAMPLE_QUERY_PARAM } from './verified-example';

/**
 * Where a link to the planner's old address should go now.
 *
 * The planner lived at `/` until the landing page took it, and recorded demos,
 * the README and the evidence pack all link `/?example=…`. Those links keep
 * working: any request for `/` that carries the example parameter is sent to
 * `/planner` with its whole query string intact. Returns null when the request
 * is for the landing page itself.
 */
export function legacyPlannerUrl(
  params: Record<string, string | string[] | undefined> | undefined,
): string | null {
  if (params === undefined || !(EXAMPLE_QUERY_PARAM in params)) return null;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue;
    for (const item of Array.isArray(value) ? value : [value]) query.append(key, item);
  }
  return `/planner?${query.toString()}`;
}
