import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { RouteCompareResponse } from '@pathable/contracts';
import { RouteComparisonView } from './RouteComparisonView';
import { RoutePlanner } from './RoutePlanner';
import { RouteWorkspace } from './RouteWorkspace';
import { compareRoutes } from './compare-routes';
import { formatDistance, formatDuration, nextRole } from './types';

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

const ORIGIN = { longitude: -80.54, latitude: 43.47 };
const DESTINATION = { longitude: -80.534, latitude: 43.47 };

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
    stairway_count: 1,
    step_count: 14,
    unknown_kerb_crossing_count: 1,
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
        'OpenStreetMap has no accessibility details for some of this route (31% of its length). ' +
        'Missing data is not evidence that a path is clear.',
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
    onProfileChange: vi.fn(),
    onClearPoints: vi.fn(),
    onSwapPoints: vi.fn(),
    onRetry: vi.fn(),
    onSelectPlace: vi.fn(),
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
      /accessible route is 226 m longer than the shortest route/i,
    );
  });

  it('shows both routes with their own figures', () => {
    renderPlanner();

    expect(screen.getByTestId('route-card-accessible')).toHaveTextContent('709 m');
    expect(screen.getByTestId('route-card-standard')).toHaveTextContent('483 m');
  });

  it('reports the stairway the shortest route uses', () => {
    renderPlanner();

    expect(screen.getByTestId('route-card-standard')).toHaveTextContent('1 (14 steps)');
    expect(screen.getByTestId('route-card-accessible')).toHaveTextContent('None');
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

    expect(screen.getByText('Not recorded')).toBeInTheDocument();
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

    await user.click(screen.getByRole('radio', { name: /Crutches or cane/ }));

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

  it('disables swap and clear until there is something to act on', () => {
    renderPlanner({
      points: { origin: null, destination: null },
      state: { status: 'idle' },
    });

    expect(screen.getByRole('button', { name: 'Swap' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Clear' })).toBeDisabled();
  });

  it('tells the user which point the next click will set', () => {
    renderPlanner({
      points: { origin: null, destination: null },
      state: { status: 'idle' },
    });

    expect(screen.getByTestId('point-start')).toHaveTextContent(/click the map to set/i);
    expect(screen.getByTestId('point-end')).toHaveTextContent(/not set/i);
  });
});

describe('compareRoutes', () => {
  const options = {
    apiBaseUrl: 'http://api.test',
    region: 'waterloo',
    origin: ORIGIN,
    destination: DESTINATION,
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

  it('shows the map key alongside the map', () => {
    render(<RouteWorkspace {...config} fetchImpl={vi.fn() as unknown as typeof fetch} />);

    expect(screen.getByTestId('map-legend')).toBeInTheDocument();
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
