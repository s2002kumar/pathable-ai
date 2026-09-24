import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { RouteCompareResponse } from '@pathable/contracts';
import { RouteComparisonView } from './RouteComparisonView';
import { RoutePlanner } from './RoutePlanner';
import { CAMPUS_EXAMPLE } from './verified-example';
import { RouteWorkspace } from './RouteWorkspace';
import { compareRoutes } from './compare-routes';
import {
  formatDistance,
  formatDuration,
  hasPendingEndpointEdits,
  journeyOf,
  nextRole,
} from './types';

vi.mock('maplibre-gl', () => ({
  setWorkerUrl: () => {},
  getWorkerUrl: () => '',
  Map: class {
    on() {}
    off() {}
    addControl() {}
    remove() {}
  },
  NavigationControl: class {},
  ScaleControl: class {},
  AttributionControl: class {},
}));

const ORIGIN_AT = { longitude: -80.54, latitude: 43.47 };
const DESTINATION_AT = { longitude: -80.534, latitude: 43.47 };
/** Endpoints now carry the name of the place as well as its position. */
const ORIGIN = { position: ORIGIN_AT, label: 'Davis Centre library', source: 'search' as const };
const DESTINATION = {
  position: DESTINATION_AT,
  label: 'Student Life Centre',
  source: 'search' as const,
};

function buildRoute(overrides: Record<string, unknown> = {}) {
  return {
    profile: 'wheelchair',
    profile_display_name: 'Wheelchair',
    distance_m: 709,
    effective_distance_m: 980,
    estimated_duration_seconds: 746,
    coordinates: [
      [-80.54, 43.47],
      [-80.534, 43.47],
    ],
    segments: [],
    origin: { ...ORIGIN, distance_m: 2 },
    destination: { ...DESTINATION, distance_m: 3 },
    stairway_count: 0,
    step_count: 0,
    crossing_count: 1,
    unknown_kerb_crossing_count: 0,
    steepest_incline_percent: 4,
    unknown_data_fraction: 0.31,
    evidence_coverage: { surface: 0.38, smoothness: 0.72, gradient: 0.01, width: 0.9, kerb: 0.5 },
    gradient_source: 'derived_elevation',
    computation_ms: 8,
    ...overrides,
  };
}

const COMPARISON = {
  profile: 'wheelchair',
  profile_display_name: 'Wheelchair',
  profile_description: 'Avoids steps entirely.',
  standard_route: buildRoute({
    profile: 'standard',
    profile_display_name: 'Standard walking',
    distance_m: 483,
    effective_distance_m: 483,
    // Distinct from the accessible route's, so a figure showing the wrong
    // route's walking time cannot pass by coincidence.
    estimated_duration_seconds: 508,
    stairway_count: 1,
    step_count: 14,
    unknown_kerb_crossing_count: 1,
    // A real stairway segment behind the aggregate: the overlay reads the
    // segments, not the counts, so a fixture with an empty `segments` array
    // would silently exercise the "nothing recorded" branch instead.
    segments: [
      {
        edge_identity: '1->2#0',
        name: null,
        length_m: 4.2,
        effective_metres: 4.2,
        coordinates: [
          [-80.537, 43.47],
          [-80.5369, 43.4701],
        ],
        highway: 'steps',
        surface: null,
        surface_class: 'unknown',
        smoothness_class: 'unknown',
        steps: 'yes',
        step_count: 14,
        incline_percent: null,
        kerb: 'unknown',
        is_crossing: false,
        width_m: null,
        unknown_attributes: ['smoothness'],
        cost_components: [],
      },
    ],
  }),
  accessible_route: buildRoute(),
  standard_failure: null,
  accessible_failure: null,
  extra_distance_m: 226,
  extra_distance_fraction: 0.468,
  explanations: [
    { code: 'avoids_stairs', summary: 'Avoids 1 stairway (14 steps in total).', evidence: {} },
    {
      code: 'avoids_unrecorded_kerbs',
      summary: 'Avoids 1 crossing where no kerb has been recorded.',
      evidence: {},
    },
  ],
  cautions: [
    {
      code: 'missing_accessibility_data',
      summary:
        'On some of the wheelchair route (31% of its length) at least one accessibility ' +
        'attribute — surface, surface condition, gradient, steps or kerb — has no record in ' +
        'OpenStreetMap. Missing data is not evidence that a path is clear.',
      evidence: {},
    },
  ],
  dataset: {
    dataset_id: '0c9d1b3a-0000-4000-8000-000000000000',
    region: 'waterloo',
    checksum: 'abcdef0123456789',
    source_type: 'osm',
    source_name: 'openstreetmap:waterloo',
    acquired_at: '2026-08-12T00:00:00+00:00',
    source_timestamp: '2026-08-10T00:00:00+00:00',
    evidence_age_days: 2,
    attribution: '© OpenStreetMap contributors, ODbL 1.0',
  },
  ml_predictions_used: false,
} as unknown as RouteCompareResponse;

function renderPlanner(overrides: Partial<Parameters<typeof RoutePlanner>[0]> = {}) {
  const props = {
    points: { origin: ORIGIN, destination: DESTINATION },
    profileKey: 'wheelchair' as const,
    state: { status: 'success' as const, comparison: COMPARISON },
    apiBaseUrl: 'http://api.test',
    region: 'waterloo',
    example: CAMPUS_EXAMPLE,
    exampleActive: false,
    canCompare: true,
    pendingEdits: false,
    pickTarget: null,
    submittedSummary: 'Davis Centre library to Student Life Centre',
    stairsTarget: null,
    onRunExample: vi.fn(),
    onProfileChange: vi.fn(),
    onCompare: vi.fn(),
    onClearPoint: vi.fn(),
    onClearAll: vi.fn(),
    onSwapPoints: vi.fn(),
    onRetry: vi.fn(),
    onSelectPlace: vi.fn(),
    onPickOnMap: vi.fn(),
    fetchImpl: vi.fn() as unknown as typeof fetch,
    ...overrides,
  };
  return { ...render(<RoutePlanner {...props} />), props };
}

describe('formatting', () => {
  it('switches to kilometres above a kilometre', () => {
    expect(formatDistance(940)).toBe('940 m');
    expect(formatDistance(1240)).toBe('1.2 km');
  });

  it('describes very short journeys without a misleading "0 min"', () => {
    expect(formatDuration(20)).toBe('under a minute');
    expect(formatDuration(600)).toBe('10 min');
    expect(formatDuration(3600)).toBe('1 h');
    expect(formatDuration(3900)).toBe('1 h 5 min');
  });
});

describe('nextRole', () => {
  it('fills the origin first', () => {
    expect(nextRole({ origin: null, destination: null })).toBe('origin');
  });

  it('fills the destination once the origin is set', () => {
    expect(nextRole({ origin: ORIGIN, destination: null })).toBe('destination');
  });

  it('starts a new journey once both are set', () => {
    expect(nextRole({ origin: ORIGIN, destination: DESTINATION })).toBe('origin');
  });
});

describe('RoutePlanner', () => {
  it('states the trade-off in the headline', () => {
    renderPlanner();

    expect(screen.getByTestId('route-status')).toHaveTextContent(
      /wheelchair route is 226 m longer than the shortest walking route/i,
    );
  });

  it('shows both routes with their own figures', () => {
    renderPlanner();

    // The figures beside the highlight controls, which is where both routes'
    // numbers live now that the duplicate pair of cards below them is gone.
    expect(screen.getByTestId('difference-accessible')).toHaveTextContent('709 m');
    expect(screen.getByTestId('difference-shortest')).toHaveTextContent('483 m');
  });

  it('reports the walking time the response gave for each route', () => {
    renderPlanner();

    // 746 s and 508 s in the fixture. Read as an estimate, not a measurement:
    // the figure is distance over an assumed pace plus fixed allowances, which
    // the schema itself describes as "not measured, and not specific to any
    // individual" — so the UI says "Est." rather than asserting a duration.
    expect(screen.getByTestId('difference-accessible')).toHaveTextContent('Est. 12 min');
    expect(screen.getByTestId('difference-shortest')).toHaveTextContent('Est. 8 min');
  });

  it('reports the stairway the shortest route uses, with its step count', () => {
    renderPlanner();

    // "1 stairway" and "1 stairway (14 recorded steps)" are different facts:
    // the first means nobody recorded how many steps there are. "recorded"
    // is load-bearing in the second — step_count sums only the stairways
    // somebody counted, so it is a floor and never a total.
    expect(screen.getByTestId('difference-shortest')).toHaveTextContent(
      '1 stairway (14 recorded steps)',
    );
    expect(screen.getByTestId('difference-accessible')).toHaveTextContent('no recorded stairways');
  });

  it('lists the evidence-backed reasons for the detour', () => {
    renderPlanner();

    expect(screen.getByText(/Avoids 1 stairway \(14 steps in total\)/)).toBeInTheDocument();
    expect(screen.getByText(/no kerb has been recorded/)).toBeInTheDocument();
  });

  it('shows the missing-data caution without softening it', () => {
    // The most dangerous possible UI bug here is presenting an unsurveyed route
    // as a checked one.
    renderPlanner();

    expect(
      screen.getByText(/Missing data is not evidence that a path is clear/),
    ).toBeInTheDocument();
  });

  it('says plainly that no model was involved', () => {
    renderPlanner();

    expect(
      screen.getByText(/no predictions, no scoring, no machine learning/i),
    ).toBeInTheDocument();
  });

  it('shows the required OpenStreetMap attribution with the route', () => {
    renderPlanner();

    expect(screen.getByText(/© OpenStreetMap contributors, ODbL 1\.0/)).toBeInTheDocument();
  });

  it('shows the elevation licence credit whenever the dataset carries one', () => {
    // Derived gradients come from NRCan's HRDEM under the Open Government
    // Licence – Canada, which requires its statement wherever a grade is shown.
    const credit = 'Contains information licensed under the Open Government Licence – Canada.';
    renderPlanner({
      state: {
        status: 'success',
        comparison: {
          ...COMPARISON,
          dataset: { ...COMPARISON.dataset, elevation_attribution: credit },
        } as unknown as RouteCompareResponse,
      },
    });

    expect(screen.getByTestId('elevation-attribution')).toHaveTextContent(credit);
  });

  it('shows no elevation credit for a dataset that was never sampled', () => {
    renderPlanner();

    expect(screen.queryByTestId('elevation-attribution')).not.toBeInTheDocument();
  });

  it('reports unrecorded gradients as unrecorded rather than zero', () => {
    renderPlanner({
      state: {
        status: 'success',
        comparison: {
          ...COMPARISON,
          accessible_route: buildRoute({ steepest_incline_percent: null }),
        } as unknown as RouteCompareResponse,
      },
    });

    // Scoped to the breakdown: "Not recorded" is also the name of an evidence
    // class in the difference block, and the assertion is about the gradient.
    const breakdown = screen.getByRole('region', { name: /what is on this route/i });
    expect(within(breakdown).getByText('Not recorded')).toBeInTheDocument();
  });

  it('explains a profile with no possible route instead of failing silently', () => {
    renderPlanner({
      state: {
        status: 'success',
        comparison: {
          ...COMPARISON,
          accessible_route: null,
          accessible_failure: 'No route satisfies the wheelchair profile between these points.',
          explanations: [],
        } as unknown as RouteCompareResponse,
      },
    });

    expect(screen.getByRole('status')).toHaveTextContent(/No route satisfies the wheelchair/);
  });

  it('surfaces a request failure with a retry', async () => {
    const user = userEvent.setup();
    const { props } = renderPlanner({
      state: { status: 'error', message: 'The routing service could not be reached.', code: 'x' },
    });

    expect(screen.getByRole('alert')).toHaveTextContent(/could not be reached/);
    await user.click(screen.getByRole('button', { name: /try again/i }));
    expect(props.onRetry).toHaveBeenCalledOnce();
  });

  it('changing the profile notifies the workspace', async () => {
    const user = userEvent.setup();
    const { props } = renderPlanner();

    await user.selectOptions(screen.getByTestId('mobility-profile'), 'crutches');

    expect(props.onProfileChange).toHaveBeenCalledWith('crutches');
  });

  it('announces results politely rather than stealing focus', () => {
    renderPlanner();

    expect(screen.getByTestId('route-status')).toHaveAttribute('aria-live', 'polite');
  });

  it('marks the status region busy while a request is in flight', () => {
    renderPlanner({ state: { status: 'loading' } });

    expect(screen.getByTestId('route-status')).toHaveAttribute('aria-busy', 'true');
  });

  it('offers nothing to act on until an endpoint exists', () => {
    renderPlanner({
      points: { origin: null, destination: null },
      state: { status: 'idle' },
      canCompare: false,
    });

    expect(screen.getByTestId('swap-points')).toBeDisabled();
    expect(screen.getByTestId('clear-journey')).toBeDisabled();
    // Nothing to compare, so the control that would ask says so rather than
    // sending an incomplete journey.
    expect(screen.getByTestId('compare-routes')).toBeDisabled();
  });

  it('names each endpoint separately instead of one implicit next point', () => {
    // The old planner had a single search that filled "whichever point is
    // empty", so a person searching for their destination had no way to say
    // so. Each end is now its own labelled field with its own state.
    renderPlanner({
      points: { origin: null, destination: null },
      state: { status: 'idle' },
      canCompare: false,
    });

    expect(screen.getByTestId('endpoint-origin-value')).toHaveTextContent(/not set/i);
    expect(screen.getByTestId('endpoint-destination-value')).toHaveTextContent(/not set/i);
    // Two fields, each with its own label, and two submit controls with
    // distinct accessible names — a page with two buttons both called
    // "Search" is a page where neither can be addressed.
    expect(screen.getByLabelText('Start')).toBeInTheDocument();
    expect(screen.getByLabelText('Destination')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Search for a start' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Search for a destination' })).toBeInTheDocument();
  });

  it('says which field a map click will fill once one has asked for it', () => {
    renderPlanner({
      points: { origin: null, destination: null },
      state: { status: 'idle' },
      canCompare: false,
      pickTarget: 'destination',
    });

    expect(screen.getByTestId('endpoint-destination-value')).toHaveTextContent(
      /click the map to set this point/i,
    );
    expect(screen.getByTestId('pick-destination')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('pick-origin')).toHaveAttribute('aria-pressed', 'false');
  });

  it('shows a committed endpoint by name, with the coordinate as detail', () => {
    renderPlanner({ points: { origin: ORIGIN, destination: null }, canCompare: false });

    const origin = screen.getByTestId('endpoint-origin-value');
    expect(origin).toHaveTextContent('Davis Centre library');
    // The coordinate stays visible, but as what the name resolved to.
    expect(origin).toHaveTextContent('43.47000');
  });

  it('labels the answer with the journey it answered', () => {
    renderPlanner();

    expect(screen.getByTestId('journey-summary')).toHaveTextContent(
      'Davis Centre library to Student Life Centre',
    );
  });

  it('says an answer is out of date rather than letting it look current', () => {
    // The one way a comparison can mislead without a single wrong number in
    // it: the figures stay on screen while the journey above them changes.
    renderPlanner({ pendingEdits: true });

    expect(screen.getByTestId('stale-result')).toHaveTextContent(/press compare routes to update/i);
  });
});

describe('compareRoutes', () => {
  const options = {
    apiBaseUrl: 'http://api.test',
    region: 'waterloo',
    // The wire takes positions; the name an endpoint carries is the panel's
    // business and is deliberately not sent.
    origin: ORIGIN_AT,
    destination: DESTINATION_AT,
    profile: { key: 'wheelchair' as const },
  };

  it('posts the request rather than putting a location in a URL', async () => {
    const fetchImpl = vi.fn(
      async () => new Response(JSON.stringify(COMPARISON), { status: 200 }),
    ) as unknown as typeof fetch;

    await compareRoutes({ ...options, fetchImpl });

    const [url, init] = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe('http://api.test/api/v1/routes/compare');
    expect(init.method).toBe('POST');
    expect(url).not.toContain('43.47');
  });

  it('returns the comparison on success', async () => {
    const fetchImpl = vi.fn(
      async () => new Response(JSON.stringify(COMPARISON), { status: 200 }),
    ) as unknown as typeof fetch;

    const result = await compareRoutes({ ...options, fetchImpl });

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.data.profile).toBe('wheelchair');
  });

  it('passes the API error message through rather than replacing it', async () => {
    // The backend already explains *why* — a point too far from any mapped path,
    // a region with no dataset. Replacing that with "something went wrong" would
    // discard the only useful part.
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({ code: 'no_route', message: 'The origin is 812 m from any path.' }),
          { status: 422 },
        ),
    ) as unknown as typeof fetch;

    const result = await compareRoutes({ ...options, fetchImpl });

    expect(result).toEqual({
      ok: false,
      code: 'no_route',
      message: 'The origin is 812 m from any path.',
    });
  });

  it('rejects a response that does not match the contract', async () => {
    const fetchImpl = vi.fn(
      async () => new Response(JSON.stringify({ hello: 'world' }), { status: 200 }),
    ) as unknown as typeof fetch;

    const result = await compareRoutes({ ...options, fetchImpl });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.code).toBe('unexpected_response');
  });

  it('refuses a response claiming a model was used', async () => {
    // `ml_predictions_used` is a literal false in the contract. A true would mean
    // this client is talking to something it does not understand.
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify({ ...COMPARISON, ml_predictions_used: true }), { status: 200 }),
    ) as unknown as typeof fetch;

    const result = await compareRoutes({ ...options, fetchImpl });

    expect(result.ok).toBe(false);
  });

  it('never rejects when the network fails', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }) as unknown as typeof fetch;

    const result = await compareRoutes({ ...options, fetchImpl });

    expect(result).toEqual({
      ok: false,
      code: 'unreachable',
      message: 'The routing service could not be reached.',
    });
  });
});

describe('RouteWorkspace', () => {
  const config = {
    apiBaseUrl: 'http://api.test',
    region: 'waterloo',
    mapStyleUrl: '/map-styles/offline-test-style.json',
    centerLat: 43.4668,
    centerLon: -80.5164,
    zoom: 14,
    regionName: 'Waterloo, Ontario',
    attribution: '© test',
  };

  it('requests nothing until both endpoints are chosen', async () => {
    const fetchImpl = vi.fn() as unknown as typeof fetch;

    render(<RouteWorkspace {...config} fetchImpl={fetchImpl} />);

    await waitFor(() =>
      expect(screen.getByTestId('route-status')).toHaveAttribute('data-route-state', 'idle'),
    );
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('shows no map key until there are routes for it to explain', () => {
    // A key to two lines that do not exist yet is furniture, and on a phone it
    // is furniture sitting on the map.
    render(<RouteWorkspace {...config} fetchImpl={vi.fn() as unknown as typeof fetch} />);

    expect(screen.queryByTestId('map-legend')).not.toBeInTheDocument();
  });
});

describe('map age', () => {
  it('reports how old the map is, not when it was downloaded', () => {
    // An extract fetched this morning from a two-year-old publication is two
    // years old. Reporting the fetch date would make stale data look fresh.
    render(
      <RouteComparisonView
        comparison={{
          ...COMPARISON,
          dataset: { ...COMPARISON.dataset, evidence_age_days: 3 },
        }}
      />,
    );

    expect(screen.getByText(/Map data published 3 days ago/)).toBeInTheDocument();
  });

  it('warns plainly once the map is old enough to have moved on', () => {
    render(
      <RouteComparisonView
        comparison={{
          ...COMPARISON,
          dataset: { ...COMPARISON.dataset, evidence_age_days: 400 },
        }}
      />,
    );

    expect(screen.getByText(/kerbs, closures, resurfacing/)).toBeInTheDocument();
  });

  it('says nothing when the source published no timestamp', () => {
    // Silence beats inventing an age for data whose age is unknown.
    render(
      <RouteComparisonView
        comparison={{
          ...COMPARISON,
          dataset: { ...COMPARISON.dataset, evidence_age_days: null },
        }}
      />,
    );

    expect(screen.queryByText(/Map data published/)).not.toBeInTheDocument();
  });
});

describe('evidence gaps', () => {
  it('names which fact is missing rather than reporting one combined figure', () => {
    render(<RouteComparisonView comparison={COMPARISON} />);

    // "Surface data is missing for 38% of this route" is actionable; a single
    // uncertainty number is not — two routes missing entirely different things
    // produce the same figure.
    expect(screen.getByText(/Surface data is missing for 38% of this route/)).toBeInTheDocument();
    expect(
      screen.getByText(/Surface condition is missing for 72% of this route/),
    ).toBeInTheDocument();
  });

  it('does not clutter the answer with gaps too small to act on', () => {
    render(<RouteComparisonView comparison={COMPARISON} />);

    expect(screen.queryByText(/Gradient data is missing/)).not.toBeInTheDocument();
  });

  it('says a gradient was inferred from terrain rather than recorded on the path', () => {
    render(<RouteComparisonView comparison={COMPARISON} />);

    expect(screen.getByText(/estimated from an elevation model/)).toBeInTheDocument();
    expect(screen.getByText(/cannot see a ramp or a step/)).toBeInTheDocument();
  });

  it('does not let a missing record read as evidence the path is clear', () => {
    render(<RouteComparisonView comparison={COMPARISON} />);

    expect(screen.getByText(/It means nobody has recorded it/)).toBeInTheDocument();
  });
});

/**
 * What the panel commits, and when.
 *
 * A draft is not a request. These cover the rule that decides whether a
 * profile change may re-run on its own or has to wait for Compare — the one
 * place the two pieces of state can produce an answer to a question nobody
 * asked.
 */
describe('draft versus submitted journey', () => {
  const journey = { origin: ORIGIN, destination: DESTINATION, profileKey: 'wheelchair' as const };

  it('is not a journey until both ends exist', () => {
    expect(journeyOf({ origin: null, destination: null }, 'wheelchair')).toBeNull();
    expect(journeyOf({ origin: ORIGIN, destination: null }, 'wheelchair')).toBeNull();
    expect(journeyOf({ origin: ORIGIN, destination: DESTINATION }, 'wheelchair')).toEqual(journey);
  });

  it('sees no pending edit while the draft still matches what was asked', () => {
    expect(hasPendingEndpointEdits({ origin: ORIGIN, destination: DESTINATION }, journey)).toBe(
      false,
    );
  });

  it('sees a pending edit when an endpoint moves', () => {
    const moved = {
      position: { longitude: -80.5, latitude: 43.5 },
      label: 'Somewhere else',
      source: 'map' as const,
    };

    expect(hasPendingEndpointEdits({ origin: moved, destination: DESTINATION }, journey)).toBe(
      true,
    );
  });

  it('sees a pending edit when only the name changes', () => {
    // Same coordinate under a different name is a different answer to "where
    // am I going?", and the result on screen would be labelled with the old
    // one. Treating it as unchanged is how a route acquires somebody else's
    // name.
    const renamed = { ...DESTINATION, label: 'Somewhere else entirely' };

    expect(hasPendingEndpointEdits({ origin: ORIGIN, destination: renamed }, journey)).toBe(true);
  });

  it('has nothing to be pending against before anything is submitted', () => {
    expect(hasPendingEndpointEdits({ origin: ORIGIN, destination: DESTINATION }, null)).toBe(false);
  });
});

describe('the recorded-stairs overlay', () => {
  it('offers the route that has stairs, and says how many', () => {
    renderPlanner();

    expect(screen.getByTestId('show-recorded-stairs')).toHaveTextContent(
      /show the recorded stairs/i,
    );
    expect(screen.getByTestId('recorded-stairs-note')).toHaveTextContent(
      /1 stairway is recorded on the shortest walking route/i,
    );
  });

  it('says what it highlighted, and that the step total is a floor', () => {
    renderPlanner({ stairsTarget: 'standard' });

    const note = screen.getByTestId('recorded-stairs-note');
    expect(note).toHaveTextContent(/1 stairway recorded/i);
    expect(note).toHaveTextContent(/14 recorded steps/i);
  });

  it('calls zero "no recorded stairs" rather than "no stairs"', () => {
    // OpenStreetMap recording no stairway is not the same as somebody having
    // checked that there is none, and the difference is the whole product.
    const noStairs = {
      ...COMPARISON,
      standard_route: { ...COMPARISON.standard_route, segments: [], stairway_count: 0 },
      accessible_route: { ...COMPARISON.accessible_route, segments: [], stairway_count: 0 },
    } as unknown as RouteCompareResponse;

    renderPlanner({ state: { status: 'success', comparison: noStairs } });

    expect(screen.getByTestId('recorded-stairs-none')).toHaveTextContent(/no recorded stairs/i);
    expect(screen.getByTestId('recorded-stairs-none')).toHaveTextContent(
      /has not been confirmed that there are none/i,
    );
    expect(screen.queryByTestId('show-recorded-stairs')).not.toBeInTheDocument();
  });
});
