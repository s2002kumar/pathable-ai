/**
 * Local types for the routing UI.
 *
 * Anything describing the wire comes from `@pathable/contracts`. Only concepts
 * that exist purely in the browser — which point the next map click sets, what
 * the panel is currently showing — are defined here.
 */
export type { CustomProfileOptions } from '@pathable/contracts';

import type { CustomProfileOptions, ProfileKey, RouteCompareResponse } from '@pathable/contracts';

export type LngLat = {
  readonly longitude: number;
  readonly latitude: number;
};

/** Which endpoint the next map click will set. */
export type PointRole = 'origin' | 'destination';

/**
 * Where an endpoint's name came from.
 *
 * Kept because the three are not interchangeable to a reader. A name from
 * search is somebody else's record of a place; a map click has no name at all
 * and must say so rather than borrow one; the example's names come from the
 * evaluation corpus and are approximate by its own admission.
 */
export type EndpointSource = 'search' | 'map' | 'example';

/**
 * One end of a journey: a position, and what to call it.
 *
 * The label travels with the coordinate rather than being looked up later, so
 * a result can always say which places it compared. A map click is labelled
 * `Selected map point` — the product does not reverse-geocode a click, and
 * inventing a street name for one would be inventing evidence.
 */
export type Endpoint = {
  readonly position: LngLat;
  readonly label: string;
  readonly source: EndpointSource;
};

/**
 * A journey that has been submitted for comparison.
 *
 * Distinct from the draft the panel holds. The two exist separately so an
 * answer on screen can always be attributed to the journey that produced it,
 * even while the viewer is part-way through editing a different one.
 */
export type Journey = {
  readonly origin: Endpoint;
  readonly destination: Endpoint;
  readonly profileKey: ProfileKey;
};

/**
 * Which route's recorded stairways are highlighted on the map, if any.
 *
 * Named after the route rather than being a boolean, because the answer to
 * "where are the stairs" is different for each of the two routes on screen and
 * the overlay has to say which one it is describing.
 */
export type StairsTarget = 'standard' | 'accessible' | null;

/** Same place, to the precision the product displays and requests. */
export function endpointsEqual(a: Endpoint | null, b: Endpoint | null): boolean {
  if (a === null || b === null) return a === b;
  return (
    a.position.longitude === b.position.longitude &&
    a.position.latitude === b.position.latitude &&
    a.label === b.label
  );
}

export type ProfileSelection = {
  readonly key: ProfileKey;
  readonly custom?: CustomProfileOptions;
};

/**
 * What the planner is doing.
 *
 * `error` carries the message the API gave rather than a generic string: the
 * backend already explains *why* a route failed — a point too far from any
 * mapped path, a region with no dataset — and discarding that would replace a
 * useful sentence with "something went wrong".
 */
export type RouteRequestState =
  | { readonly status: 'idle' }
  | { readonly status: 'loading' }
  | { readonly status: 'success'; readonly comparison: RouteCompareResponse }
  | { readonly status: 'error'; readonly message: string; readonly code: string };

export type PlannerPoints = {
  readonly origin: Endpoint | null;
  readonly destination: Endpoint | null;
};

/** True once both endpoints are set and a comparison can be requested. */
export function isRoutable(points: PlannerPoints): points is {
  origin: Endpoint;
  destination: Endpoint;
} {
  return points.origin !== null && points.destination !== null;
}

/** The journey these endpoints and this profile describe, or null if incomplete. */
export function journeyOf(points: PlannerPoints, profileKey: ProfileKey): Journey | null {
  if (!isRoutable(points)) return null;
  return { origin: points.origin, destination: points.destination, profileKey };
}

/**
 * Whether the draft has moved away from what was last submitted.
 *
 * Only the endpoints count. A profile change is allowed to re-run on its own,
 * so it is not a "pending edit" — but an endpoint change is, and while one is
 * outstanding the answer on screen belongs to a different journey.
 */
export function hasPendingEndpointEdits(points: PlannerPoints, submitted: Journey | null): boolean {
  if (submitted === null) return false;
  return (
    !endpointsEqual(points.origin, submitted.origin) ||
    !endpointsEqual(points.destination, submitted.destination)
  );
}

/** Which endpoint a click should fill next: origin first, then destination. */
export function nextRole(points: PlannerPoints): PointRole {
  if (points.origin === null) return 'origin';
  if (points.destination === null) return 'destination';
  // Both are set: further clicks move the origin and clear the destination, so
  // planning a second journey does not require a reset button.
  return 'origin';
}

export function formatDistance(metres: number): string {
  if (metres >= 1000) return `${(metres / 1000).toFixed(1)} km`;
  return `${Math.round(metres)} m`;
}

export function formatDuration(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  if (minutes < 1) return 'under a minute';
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder === 0 ? `${hours} h` : `${hours} h ${remainder} min`;
}

export function formatCoordinate({ longitude, latitude }: LngLat): string {
  // Five decimal places is about a metre — enough to identify a doorway, and no
  // more precision than a map click actually carries.
  return `${latitude.toFixed(5)}, ${longitude.toFixed(5)}`;
}
