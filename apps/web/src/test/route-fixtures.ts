/**
 * Route comparisons for unit tests, built the way the API builds them.
 *
 * The default pair is the product's central case: a shortest route that
 * crosses one recorded stairway the wheelchair profile rules out, and a longer
 * step-free route. Every count agrees with the segments it summarises —
 * `stairway_count` is the number of segments whose `steps` is `yes`, and the
 * stairway carries `excluded_by_profile` — because a fixture whose summary
 * contradicts its own segments tests a response the API cannot send.
 */
import type {
  Route,
  RouteCompareResponse,
  RouteExplanation,
  RouteSegment,
} from '@pathable/contracts';

export function segment(overrides: Partial<RouteSegment> = {}): RouteSegment {
  return {
    edge_identity: 'way/1:0-1',
    coordinates: [
      [-80.54, 43.47],
      [-80.539, 43.47],
    ],
    length_m: 80,
    effective_metres: 80,
    cost_components: [],
    highway: 'footway',
    name: null,
    is_crossing: false,
    kerb: 'unknown',
    steps: 'no',
    step_count: null,
    surface: 'asphalt',
    surface_class: 'paved',
    smoothness_class: 'unknown',
    width_m: null,
    incline_percent: null,
    derived_grade_percent: 1.2,
    excluded_by_profile: null,
    unknown_attributes: ['smoothness'],
    ...overrides,
  };
}

/** Totals a route's summary figures from its segments, so they cannot disagree. */
function summarise(segments: readonly RouteSegment[]) {
  const distance = segments.reduce((total, item) => total + item.length_m, 0);
  const stairs = segments.filter((item) => item.steps === 'yes');
  const crossings = segments.filter((item) => item.is_crossing);
  return {
    distance_m: distance,
    stairway_count: stairs.length,
    step_count: stairs.reduce((total, item) => total + (item.step_count ?? 0), 0),
    crossing_count: crossings.length,
    unknown_kerb_crossing_count: crossings.filter((item) => item.kerb === 'unknown').length,
    coordinates: segments.flatMap((item, index) =>
      index === 0 ? item.coordinates : item.coordinates.slice(1),
    ),
  };
}

export function route(segments: readonly RouteSegment[], overrides: Partial<Route> = {}): Route {
  const summary = summarise(segments);
  return {
    profile: 'wheelchair',
    profile_display_name: 'Wheelchair',
    ...summary,
    effective_distance_m: summary.distance_m,
    estimated_duration_seconds: Math.round(summary.distance_m / 0.95),
    pace_profile: 'wheelchair',
    segments: [...segments],
    origin: { longitude: -80.54, latitude: 43.47, distance_m: 2 },
    destination: { longitude: -80.534, latitude: 43.47, distance_m: 3 },
    steepest_incline_percent: null,
    gradient: {
      steepest_uphill: {
        percent: 1.2,
        direction: 'uphill',
        source: 'derived_elevation',
        segment_index: 0,
      },
      steepest_downhill: null,
      recorded_fraction: 0,
      estimated_fraction: 1,
      unknown_fraction: 0,
    },
    unknown_data_fraction: 0.4,
    evidence_coverage: { surface: 0, smoothness: 1, gradient: 0, width: 1, kerb: 0 },
    gradient_source: null,
    computation_ms: 5,
    ...overrides,
  };
}

/** The shortest route: straight across a recorded stairway of 14 steps. */
export function shortestSegments(): RouteSegment[] {
  return [
    segment({
      edge_identity: 'way/10:0-1',
      coordinates: [
        [-80.54, 43.47],
        [-80.538, 43.47],
      ],
      length_m: 161,
      effective_metres: 161,
    }),
    segment({
      edge_identity: 'way/11:0-1',
      coordinates: [
        [-80.538, 43.47],
        [-80.5378, 43.47],
      ],
      length_m: 16,
      effective_metres: 16,
      highway: 'steps',
      steps: 'yes',
      step_count: 14,
      surface: null,
      surface_class: 'unknown',
      excluded_by_profile: 'steps',
      unknown_attributes: ['surface', 'smoothness'],
    }),
    segment({
      edge_identity: 'way/12:0-1',
      coordinates: [
        [-80.5378, 43.47],
        [-80.534, 43.47],
      ],
      length_m: 306,
      effective_metres: 306,
    }),
  ];
}

/** The step-free route: south round the stairway, over one crossing. */
export function accessibleSegments(): RouteSegment[] {
  return [
    segment({
      edge_identity: 'way/10:0-1',
      coordinates: [
        [-80.54, 43.47],
        [-80.538, 43.47],
      ],
      length_m: 161,
      effective_metres: 161,
    }),
    segment({
      edge_identity: 'way/20:0-1',
      coordinates: [
        [-80.538, 43.47],
        [-80.537, 43.469],
      ],
      length_m: 137,
      effective_metres: 150,
      incline_percent: 4,
      derived_grade_percent: 3.1,
    }),
    segment({
      edge_identity: 'way/21:0-1',
      coordinates: [
        [-80.537, 43.469],
        [-80.536, 43.469],
      ],
      length_m: 81,
      effective_metres: 100,
      highway: 'footway',
      is_crossing: true,
      kerb: 'lowered',
    }),
    segment({
      edge_identity: 'way/22:0-1',
      coordinates: [
        [-80.536, 43.469],
        [-80.534, 43.47],
      ],
      length_m: 330,
      effective_metres: 330,
    }),
  ];
}

const STAIRS_EXPLANATION: RouteExplanation = {
  code: 'avoids_stairs',
  summary:
    'Avoids 1 recorded stairway on the shortest route (14 steps in total), which this profile excludes.',
  basis: 'recorded',
  evidence: {
    hard_limit: true,
    stairway_count: 1,
    step_count: 14,
    stairways_without_step_count: 0,
    segments: ['way/11:0-1'],
  },
};

const DISTANCE_EXPLANATION: RouteExplanation = {
  code: 'distance_difference',
  summary: '226 m longer than the shortest route.',
  basis: 'profile_rule',
  evidence: {},
};

export function comparison(overrides: Partial<RouteCompareResponse> = {}): RouteCompareResponse {
  const standard = route(shortestSegments(), {
    profile: 'standard',
    profile_display_name: 'Standard walking',
    evidence_coverage: { surface: 0.03, smoothness: 1, gradient: 0, width: 1, kerb: 0 },
  });
  const accessible = route(accessibleSegments(), {
    gradient: {
      steepest_uphill: { percent: 4, direction: 'uphill', source: 'osm_incline', segment_index: 1 },
      steepest_downhill: null,
      recorded_fraction: 0.19,
      estimated_fraction: 0.81,
      unknown_fraction: 0,
    },
    unknown_data_fraction: 0.31,
  });
  const extra = accessible.distance_m - standard.distance_m;
  return {
    profile: 'wheelchair',
    profile_display_name: 'Wheelchair',
    profile_description:
      'Avoids steps entirely, prefers paved and smooth surfaces, and treats unrecorded kerbs and surfaces as risks rather than as clear paths.',
    standard_route: standard,
    accessible_route: accessible,
    standard_failure: null,
    accessible_failure: null,
    extra_distance_m: extra,
    extra_distance_fraction: extra / standard.distance_m,
    explanations: [STAIRS_EXPLANATION, DISTANCE_EXPLANATION],
    cautions: [],
    dataset: {
      dataset_id: '0c9d1b3a-0000-4000-8000-000000000000',
      region: 'waterloo',
      checksum: 'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789',
      source_type: 'osm',
      source_name: 'openstreetmap:waterloo',
      acquired_at: '2026-08-12T00:00:00+00:00',
      attribution: '© OpenStreetMap contributors, ODbL 1.0',
    },
    routing_policy_version: 2,
    ml_predictions_used: false,
    ...overrides,
  };
}

/** An explanation, for tests that need one of a particular kind. */
export function explanation(
  code: string,
  basis: RouteExplanation['basis'],
  evidence: Record<string, unknown> = {},
  summary = `Statement ${code}.`,
): RouteExplanation {
  return { code, basis, evidence, summary };
}
