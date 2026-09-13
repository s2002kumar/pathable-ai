import type { ReadinessResponse } from '@pathable/contracts';

/**
 * What the UI knows about the backend.
 *
 * `degraded` exists as a distinct state on purpose: "the API is up but its
 * database is not" is materially different from "the API is unreachable", and
 * collapsing the two would misinform anyone debugging their own setup. The same
 * argument gives `preparing` its own state: a graph that is still loading is on
 * its way to working, and a badge that calls that "degraded" is wrong.
 */
export type SystemStatus =
  | { readonly state: 'checking' }
  | { readonly state: 'ready'; readonly service: string; readonly version: string }
  | {
      /**
       * The API is up and its database is fine; it is still building the
       * routing graph it needs before it can answer a route. That is a normal
       * twenty-second window on start, not a fault, and reporting it as one
       * sends people to debug a system that is working.
       */
      readonly state: 'preparing';
      readonly service: string;
      readonly version: string;
      readonly detail: string;
    }
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
