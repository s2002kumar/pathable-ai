import type { ReadinessResponse } from '@pathable/contracts';

/**
 * What the UI knows about the backend.
 *
 * `degraded` exists as a distinct state on purpose: "the API is up but its
 * database is not" is materially different from "the API is unreachable", and
 * collapsing the two would misinform anyone debugging their own setup.
 */
export type SystemStatus =
  | { readonly state: 'checking' }
  | { readonly state: 'ready'; readonly service: string; readonly version: string }
  | {
      readonly state: 'degraded';
      readonly service: string;
      readonly version: string;
      readonly failing: readonly string[];
    }
  | { readonly state: 'unreachable'; readonly reason: string };

export type SystemStatusState = SystemStatus['state'];

/** The readiness payload as published by the backend contract. */
export type Readiness = ReadinessResponse;
