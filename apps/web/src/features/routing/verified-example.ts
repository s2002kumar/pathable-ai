/**
 * One journey from the committed evaluation corpus, offered as a starting point.
 *
 * A first-time viewer cannot know where in Waterloo to click, and two arbitrary
 * points usually produce a journey where the two routes coincide — technically a
 * comparison, and an unconvincing one. This preset supplies the *inputs* to a
 * journey that is known to differ, and nothing else: no distances, no stairway
 * counts, no explanation text. Everything shown afterwards comes from the API
 * answering this request live, exactly as it would for a hand-placed pair of
 * points.
 *
 * The coordinates are lifted from `services/api/src/pathable_api/routing/
 * waterloo_cases.py`, the fixed twenty-journey corpus behind
 * `docs/evidence/waterloo-routes.json`. That file's own caveat applies and is
 * repeated to the user: they are approximate positions of the named places, not
 * surveyed points, and the engine snaps them to the nearest routable segment
 * like any other click.
 */
import type { LngLat } from './types';

export type VerifiedExample = {
  /** Stable identifier, also the deep-link value. Matches the corpus key. */
  readonly id: string;
  readonly origin: LngLat;
  readonly originLabel: string;
  readonly destination: LngLat;
  readonly destinationLabel: string;
  /** The corpus's own description of the journey. */
  readonly description: string;
  /** Where these coordinates come from, shown to the user. */
  readonly provenance: string;
};

/**
 * `campus-library-to-student-life` from the corpus: a short walk across the
 * University of Waterloo campus where the step-free route is meaningfully
 * different from the shortest one.
 */
export const CAMPUS_EXAMPLE: VerifiedExample = {
  id: 'campus-library-to-student-life',
  origin: { longitude: -80.5424, latitude: 43.4728 },
  originLabel: 'Davis Centre library',
  destination: { longitude: -80.5449, latitude: 43.4715 },
  destinationLabel: 'Student Life Centre',
  description: 'Short walk across the University of Waterloo campus',
  provenance:
    'Approximate positions from the twenty-journey evaluation corpus, not surveyed points.',
};

export const VERIFIED_EXAMPLES: readonly VerifiedExample[] = [CAMPUS_EXAMPLE];

/** The query parameter that preselects an example, for recording a walkthrough. */
export const EXAMPLE_QUERY_PARAM = 'example';

/**
 * Resolve a deep link to an example.
 *
 * `?example=` with no value, or a value naming nothing, selects the default
 * rather than failing: a mistyped link should still show the product.
 */
export function exampleFromSearch(search: string): VerifiedExample | null {
  const params = new URLSearchParams(search);
  if (!params.has(EXAMPLE_QUERY_PARAM)) return null;

  const requested = params.get(EXAMPLE_QUERY_PARAM)?.trim();
  if (!requested) return CAMPUS_EXAMPLE;

  return VERIFIED_EXAMPLES.find((example) => example.id === requested) ?? CAMPUS_EXAMPLE;
}

/** The same resolution, from the shape a Next server component is handed. */
export function exampleFromSearchParams(
  params: Record<string, string | string[] | undefined> | undefined,
): VerifiedExample | null {
  if (params === undefined || !(EXAMPLE_QUERY_PARAM in params)) return null;

  const raw = params[EXAMPLE_QUERY_PARAM];
  const requested = (Array.isArray(raw) ? raw[0] : raw)?.trim();
  if (!requested) return CAMPUS_EXAMPLE;

  return VERIFIED_EXAMPLES.find((example) => example.id === requested) ?? CAMPUS_EXAMPLE;
}
