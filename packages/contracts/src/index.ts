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

// ---------------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------------

/** `POST /api/v1/routes/compare` request body. */
export type RouteCompareRequest = ApiSchemas['RouteCompareRequest'];

/** The shortest route, the accessible route, and the difference between them. */
export type RouteCompareResponse = ApiSchemas['RouteCompareResponse'];

/** One computed route. */
export type Route = ApiSchemas['RouteModel'];

/** One mapped segment as traversed by a route. */
export type RouteSegment = ApiSchemas['RouteSegmentModel'];

/** One contribution to a segment's cost, with the reason that produced it. */
export type CostComponent = ApiSchemas['CostComponentModel'];

/** An evidence-backed statement about why the accessible route differs. */
export type RouteExplanation = ApiSchemas['ExplanationModel'];

/**
 * What a statement rests on: recorded in OpenStreetMap, estimated from the
 * elevation model, both, a record that is missing, or the profile's own rules.
 * Label a statement from this, never from its code.
 */
export type EvidenceBasis = RouteExplanation['basis'];

/**
 * The gradients a route was costed on — recorded where OpenStreetMap has one,
 * estimated from the elevation model otherwise — kept apart, with direction.
 */
export type GradientSummary = ApiSchemas['GradientSummaryModel'];

/** The steepest gradient on a route in one direction, and where it came from. */
export type GradeExtreme = ApiSchemas['GradeExtremeModel'];

/** Something to weigh before relying on a route. */
export type RouteCaution = ApiSchemas['CautionModel'];

/** Which dataset answered a request, and the attribution it requires. */
export type DatasetProvenance = ApiSchemas['DatasetProvenance'];

/** A mobility profile a client can offer. */
export type MobilityProfile = ApiSchemas['MobilityProfileModel'];

/** `GET /api/v1/routes/profiles`. */
export type MobilityProfileListResponse = ApiSchemas['MobilityProfileListResponse'];

/** Narrow overrides for the `custom` profile. */
export type CustomProfileOptions = ApiSchemas['CustomProfileOptions'];

/** A WGS84 position, `{ longitude, latitude }`. */
export type Coordinate = ApiSchemas['Coordinate'];

/** Which mobility profile the accessible route is computed for. */
export type ProfileKey = RouteCompareRequest['profile'];

/**
 * `'yes' | 'no' | 'unknown'`.
 *
 * Not a boolean, and never coerce it to one. `unknown` means nobody has recorded
 * this, which is a different claim from `no` — treating them alike is how a UI
 * ends up telling somebody an unsurveyed path is step-free.
 */
export type TriState = RouteSegment['steps'];

/** How coarse a segment's surface is, or `unknown`. */
export type SurfaceClass = RouteSegment['surface_class'];

/** How even a segment's surface is, or `unknown`. */
export type SmoothnessClass = RouteSegment['smoothness_class'];

/** What kind of kerb a crossing has, or `unknown`. */
export type KerbType = RouteSegment['kerb'];

// ---------------------------------------------------------------------------
// Geocoding
// ---------------------------------------------------------------------------

/** `POST /api/v1/geocode/search` request body. */
export type GeocodeRequest = ApiSchemas['GeocodeRequest'];

/**
 * Search results.
 *
 * `enabled: false` means no provider is configured — nothing was searched. That
 * is a different answer from an empty `matches`, and a UI that collapses the two
 * tells the user their query failed when it was never sent.
 */
export type GeocodeResponse = ApiSchemas['GeocodeResponse'];

/** One candidate location. */
export type GeocodeMatch = ApiSchemas['GeocodeMatch'];

/** Route paths, so callers cannot typo a URL that the contract does not define. */
export const API_ROUTES = {
  liveness: '/api/v1/health/live',
  readiness: '/api/v1/health/ready',
  compareRoutes: '/api/v1/routes/compare',
  mobilityProfiles: '/api/v1/routes/profiles',
  searchPlaces: '/api/v1/geocode/search',
} as const satisfies Record<string, keyof ApiPaths>;
