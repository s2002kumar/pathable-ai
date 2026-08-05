/**
 * Typed contract surface shared by the frontend.
 *
 * Everything here is derived from `src/generated/api.ts`, which is generated from
 * the backend's OpenAPI document. Never hand-write an equivalent interface in the
 * web app: if the backend renames a field, these aliases break the build, whereas
 * a hand-copied type would silently keep compiling and fail at runtime.
 *
 * Regenerate with `pnpm contracts:generate`; CI fails on drift.
 */
import type { components, paths } from './generated/api.js';

/** Every schema defined by the API, keyed by name. */
export type ApiSchemas = components['schemas'];

/** Every path the API exposes. */
export type ApiPaths = paths;

/** `GET /api/v1/health/live` — process is serving HTTP. */
export type LivenessResponse = ApiSchemas['LivenessResponse'];

/** `GET /api/v1/health/ready` — dependency-aware traffic gate. */
export type ReadinessResponse = ApiSchemas['ReadinessResponse'];

/** Per-dependency outcome inside a readiness response. */
export type DependencyCheck = ApiSchemas['DependencyCheck'];

/** Both dependency probes. */
export type ReadinessChecks = ApiSchemas['ReadinessChecks'];

/** The single error envelope returned by every non-2xx response. */
export type ApiErrorResponse = ApiSchemas['ApiErrorResponse'];

/** A field-level problem inside a validation error. */
export type ErrorDetail = ApiSchemas['ErrorDetail'];

/** `'ok' | 'unavailable'` — narrowed from the generated union. */
export type DependencyState = DependencyCheck['status'];

/** `'ready' | 'not_ready'`. */
export type ReadinessState = ReadinessResponse['status'];

/** Route paths, so callers cannot typo a URL that the contract does not define. */
export const API_ROUTES = {
  liveness: '/api/v1/health/live',
  readiness: '/api/v1/health/ready',
} as const satisfies Record<string, keyof ApiPaths>;
