/**
 * Local types for the routing UI.
 *
 * Anything describing the wire comes from `@pathable/contracts`. Only concepts
 * that exist purely in the browser — which point the next map click sets, what
 * the panel is currently showing — are defined here.
 */
import type { CustomProfileOptions, ProfileKey, RouteCompareResponse } from '@pathable/contracts';

export type LngLat = {
  readonly longitude: number;
  readonly latitude: number;
};

/** Which endpoint the next map click will set. */
export type PointRole = 'origin' | 'destination';

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
  readonly origin: LngLat | null;
  readonly destination: LngLat | null;
};

/** True once both endpoints are set and a route can be requested. */
export function isRoutable(points: PlannerPoints): points is {
  origin: LngLat;
  destination: LngLat;
} {
  return points.origin !== null && points.destination !== null;
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
