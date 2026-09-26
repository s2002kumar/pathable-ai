/**
 * When may the interface say two routes are the same route?
 *
 * Only when the response says so. Two routes of equal length are not thereby
 * the same path — a detour and a direct route can measure the same — and a
 * distance threshold is a statement about numbers, not geometry. So the claim
 * "these lines overlap on the map" is made from identity the API already
 * carries, and from nothing else:
 *
 *  1. Segment identity, when both routes carry segments: the ordered list of
 *     `edge_identity` values must be equal. This is the dataset's own stable
 *     identity for each segment and is authoritative.
 *  2. Otherwise the drawn geometry, when both routes carry a polyline: the
 *     ordered coordinate sequences must be equal, position for position.
 *
 * Anything short of that — one side missing segments, empty geometry, a
 * mismatch anywhere — is "not established", and the interface says nothing
 * about overlap. Distance is never consulted.
 */
import type { Route } from '@pathable/contracts';

/** How close two coordinates must be to count as the same position. */
const POSITION_EPSILON = 1e-9;

function sameSequence<T>(a: readonly T[], b: readonly T[], equal: (x: T, y: T) => boolean) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (!equal(a[i]!, b[i]!)) return false;
  }
  return true;
}

function samePosition(a: readonly number[], b: readonly number[]): boolean {
  return (
    a.length === 2 &&
    b.length === 2 &&
    Math.abs(a[0]! - b[0]!) <= POSITION_EPSILON &&
    Math.abs(a[1]! - b[1]!) <= POSITION_EPSILON
  );
}

/**
 * True only when the response establishes that both routes are the same path.
 *
 * Conservative on purpose: uncertain identity returns false, and false means
 * "no claim", not "different".
 */
export function routesSharePath(a: Route | null | undefined, b: Route | null | undefined): boolean {
  if (!a || !b) return false;

  const aSegments = a.segments ?? [];
  const bSegments = b.segments ?? [];
  if (aSegments.length > 0 && bSegments.length > 0) {
    return sameSequence(
      aSegments.map((segment) => segment.edge_identity),
      bSegments.map((segment) => segment.edge_identity),
      (x, y) => x === y,
    );
  }
  // One route with segments and one without is an inconsistency, not identity.
  if (aSegments.length > 0 || bSegments.length > 0) return false;

  const aCoordinates = a.coordinates ?? [];
  const bCoordinates = b.coordinates ?? [];
  if (aCoordinates.length < 2 || bCoordinates.length < 2) return false;
  return sameSequence(aCoordinates, bCoordinates, samePosition);
}

/**
 * Distances are displayed to the nearest metre (`formatDistance`). Two routes
 * whose difference is below half a metre display as the same number, and that
 * — display precision, not a threshold chosen to look tidy — is the only
 * ground on which the interface says "the same length". It says it with the
 * qualifier "to the nearest metre" and never says "the same route".
 */
export const DISPLAY_EQUAL_BELOW_M = 0.5;

export function differenceIsBelowDisplayPrecision(extraDistanceM: number | null | undefined) {
  return typeof extraDistanceM === 'number' && Math.abs(extraDistanceM) < DISPLAY_EQUAL_BELOW_M;
}
