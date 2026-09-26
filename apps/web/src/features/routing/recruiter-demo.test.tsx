/**
 * The one-press example, and the honesty of what it shows.
 *
 * The whole risk of a demo preset is that it becomes a picture of a route
 * rather than a route. These tests exist mostly to make that impossible to do
 * by accident: the preset supplies coordinates and a profile, the request goes
 * to the API with exactly those coordinates, and every number on screen comes
 * out of the response the API gave.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { RouteCompareResponse } from '@pathable/contracts';
import { RouteComparisonView } from './RouteComparisonView';
import { RouteDifference } from './RouteDifference';
import { RouteWorkspace } from './RouteWorkspace';
import { CAMPUS_EXAMPLE, exampleFromSearch } from './verified-example';

vi.mock('@/features/map/MapPanel', () => ({
  MapPanel: ({
    standardRoute,
    accessibleRoute,
  }: {
    standardRoute: unknown;
    accessibleRoute: unknown;
  }) => (
    <div
      data-testid="map-panel"
      data-has-standard={standardRoute !== null && standardRoute !== undefined}
      data-has-accessible={accessibleRoute !== null && accessibleRoute !== undefined}
    />
  ),
}));

/**
 * Shaped like the real answer for the campus journey, with the figures the live
 * API returned for it on 2026-09-13. Nothing in the application may contain
 * these numbers — they live here, in the test, which is the point.
 */
const CAMPUS_RESPONSE = {
  profile: 'wheelchair',
  profile_display_name: 'Wheelchair',
  profile_description: 'Avoids steps and unpaved surfaces.',
  standard_route: {
    distance_m: 287.4,
    estimated_duration_seconds: 302.9,
    pace_profile: 'wheelchair',
    gradient: {
      steepest_uphill: {
        percent: 3.4,
        direction: 'uphill',
        source: 'derived_elevation',
        segment_index: 2,
      },
      steepest_downhill: null,
      recorded_fraction: 0,
      estimated_fraction: 0.57,
      unknown_fraction: 0.43,
    },
    stairway_count: 4,
    step_count: 16,
    crossing_count: 0,
    unknown_kerb_crossing_count: 0,
    steepest_incline_percent: null,
    gradient_source: 'derived_elevation',
    unknown_data_fraction: 1,
    evidence_coverage: { surface: 0.29, smoothness: 1, gradient: 0.43, width: 1, kerb: 0 },
    segments: [],
    coordinates: [],
  },
  accessible_route: {
    distance_m: 354.1,
    estimated_duration_seconds: 372.7,
    pace_profile: 'wheelchair',
    gradient: {
      steepest_uphill: {
        percent: 2.1,
        direction: 'uphill',
        source: 'derived_elevation',
        segment_index: 1,
      },
      steepest_downhill: null,
      recorded_fraction: 0,
      estimated_fraction: 0.61,
      unknown_fraction: 0.39,
    },
    stairway_count: 0,
    step_count: 0,
    crossing_count: 0,
    unknown_kerb_crossing_count: 0,
    steepest_incline_percent: null,
    gradient_source: 'derived_elevation',
    unknown_data_fraction: 1,
    evidence_coverage: { surface: 0.18, smoothness: 1, gradient: 0.39, width: 1, kerb: 0 },
    segments: [],
    coordinates: [],
  },
  extra_distance_m: 66.67,
  extra_distance_fraction: 0.232,
  explanations: [
    {
      code: 'avoids_stairs',
      summary: 'Avoids 4 stairways (16 steps in total).',
      basis: 'recorded',
      evidence: { stairway_count: 4, step_count: 16 },
    },
    {
      code: 'distance_difference',
      summary: '67 m longer than the shortest route (354 m instead of 287 m, 23% longer).',
      basis: 'profile_rule',
      evidence: { extra_distance_m: 67 },
    },
  ],
  cautions: [
    {
      code: 'missing_accessibility_data',
      summary:
        'On most of the wheelchair route (100% of its length) at least one accessibility ' +
        'attribute — surface, surface condition, gradient, steps or kerb — has no record in ' +
        'OpenStreetMap. Missing data is not evidence that a path is clear.',
      evidence: { unknown_data_fraction: 1 },
    },
  ],
  dataset: {
    dataset_id: '51585450-8ff5-409d-a02e-66d5a3c5e260',
    region: 'waterloo',
    checksum: '51e75f7896ab725d29120fe4363c607bea68eed260d830482d6677f827d2e906',
    source_type: 'osm',
    source_name: 'openstreetmap-pbf:waterloo',
    acquired_at: '2026-08-17T23:52:02+00:00',
    evidence_age_days: 27,
    attribution: '© OpenStreetMap contributors, ODbL 1.0',
    elevation_attribution:
      'Contains information licensed under the Open Government Licence – Canada.',
  },
  ml_predictions_used: false,
} as unknown as RouteCompareResponse;

function jsonResponse(body: unknown) {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

/** The comparison requests a mocked fetch received, leaving the profile list aside. */
function compareCalls(fetchImpl: ReturnType<typeof vi.fn>) {
  return fetchImpl.mock.calls.filter(([url]) => String(url).endsWith('/api/v1/routes/compare'));
}

function renderWorkspace(fetchImpl: typeof fetch) {
  return render(
    <RouteWorkspace
      apiBaseUrl="http://api.test"
      region="waterloo"
      mapStyleUrl="http://style.test/style.json"
      centerLat={43.4668}
      centerLon={-80.5164}
      zoom={14}
      regionName="Waterloo, Ontario"
      attribution="© OpenStreetMap contributors"
      fetchImpl={fetchImpl}
      initialExample={null}
    />,
  );
}

describe('the verified example', () => {
  it('sends the corpus coordinates and the wheelchair profile to the real API', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(CAMPUS_RESPONSE));
    const user = userEvent.setup();
    renderWorkspace(fetchImpl as unknown as typeof fetch);

    await user.click(screen.getByTestId('run-verified-example'));

    await waitFor(() => expect(compareCalls(fetchImpl)).toHaveLength(1));
    const [, init] = compareCalls(fetchImpl)[0] as [string, RequestInit];
    const sent = JSON.parse(String(init.body)) as Record<string, unknown>;

    expect(sent.region).toBe('waterloo');
    expect(sent.profile).toBe('wheelchair');
    // The verified case is the preset as verified: no limit of the viewer's own.
    expect(sent).not.toHaveProperty('custom');
    expect(sent.origin).toEqual({
      longitude: CAMPUS_EXAMPLE.origin.longitude,
      latitude: CAMPUS_EXAMPLE.origin.latitude,
    });
    expect(sent.destination).toEqual({
      longitude: CAMPUS_EXAMPLE.destination.longitude,
      latitude: CAMPUS_EXAMPLE.destination.latitude,
    });
  });

  it('reaches a comparison in one interaction', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(CAMPUS_RESPONSE));
    const user = userEvent.setup();
    renderWorkspace(fetchImpl as unknown as typeof fetch);

    await user.click(screen.getByTestId('run-verified-example'));

    await screen.findByTestId('route-difference');
    expect(screen.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
  });

  it('carries no route data of its own', () => {
    // If the preset ever gains a distance or a stairway count, the demo stops
    // being a demo of the engine.
    const serialised = JSON.stringify(CAMPUS_EXAMPLE);
    expect(serialised).not.toMatch(/distance|stairway|segment|route_|metres|\bm\b/i);
    expect(Object.keys(CAMPUS_EXAMPLE).sort()).toEqual([
      'description',
      'destination',
      'destinationLabel',
      'id',
      'origin',
      'originLabel',
      'provenance',
    ]);
  });

  it('draws both routes on the map once the answer arrives', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(CAMPUS_RESPONSE));
    const user = userEvent.setup();
    renderWorkspace(fetchImpl as unknown as typeof fetch);

    await user.click(screen.getByTestId('run-verified-example'));

    await waitFor(() => {
      const map = screen.getByTestId('map-panel');
      expect(map).toHaveAttribute('data-has-standard', 'true');
      expect(map).toHaveAttribute('data-has-accessible', 'true');
    });
  });

  it('still lets a person place their own points afterwards', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(CAMPUS_RESPONSE));
    const user = userEvent.setup();
    renderWorkspace(fetchImpl as unknown as typeof fetch);

    await user.click(screen.getByTestId('run-verified-example'));
    await screen.findByTestId('route-difference');

    await user.click(screen.getByTestId('clear-journey'));

    expect(screen.getByTestId('endpoint-origin-value')).toHaveTextContent(/not set/i);
    expect(screen.getByTestId('endpoint-destination-value')).toHaveTextContent(/not set/i);
    // Clearing clears the request too: the answer for the example's journey
    // must not be left on screen with nothing naming it.
    expect(screen.getByTestId('route-status')).toHaveAttribute('data-route-state', 'idle');
  });
});

describe('the deep link', () => {
  it('selects the example, and an unknown one falls back rather than failing', () => {
    expect(exampleFromSearch('')).toBeNull();
    expect(exampleFromSearch('?example=campus-library-to-student-life')?.id).toBe(
      CAMPUS_EXAMPLE.id,
    );
    expect(exampleFromSearch('?example=')?.id).toBe(CAMPUS_EXAMPLE.id);
    expect(exampleFromSearch('?example=not-a-journey')?.id).toBe(CAMPUS_EXAMPLE.id);
  });
});

describe('why the routes differ', () => {
  it('states both distances, the detour and what it buys, from the response', () => {
    render(<RouteDifference comparison={CAMPUS_RESPONSE} />);

    expect(
      within(screen.getByTestId('difference-shortest')).getByText('287 m'),
    ).toBeInTheDocument();
    expect(
      // "recorded" is load-bearing: step_count sums only the stairways
      // somebody counted, and two of these four have no recorded count.
      within(screen.getByTestId('difference-shortest')).getByText(
        '4 stairways · 16 recorded steps',
      ),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId('difference-accessible')).getByText('354 m'),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId('difference-accessible')).getByText('No recorded stairs'),
    ).toBeInTheDocument();

    const extra = screen.getByTestId('difference-extra');
    expect(extra).toHaveTextContent('+67 m longer');
    // The figure alone: why it is longer is the list of reasons below, not a
    // single cause named beside the number (D7).
    expect(extra).not.toHaveTextContent(/to avoid|because|stairway/i);
  });

  it('labels each statement with the kind of claim it is', () => {
    render(<RouteComparisonView comparison={CAMPUS_RESPONSE} />);

    // An observed fact, a consequence of the profile, an estimate and an
    // absence are four different things, and the UI says which is which.
    const reasons = within(screen.getByTestId('difference-reasons'));
    expect(reasons.getByText(/Avoids 4 stairways/).closest('li')).toHaveTextContent('Recorded');
    expect(reasons.getAllByText('Your profile rule').length).toBeGreaterThan(0);
    expect(
      within(screen.getByTestId('steepest-climb')).getByText('Estimated from elevation'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('coverage-smoothness')).toHaveTextContent('100% not recorded');
  });

  it('says the data is incomplete before a viewer has scrolled anywhere', () => {
    // The distances are the flattering half of the answer. This is the other
    // half, in the same glance — the detailed per-category version is further
    // down the panel and below the fold on both demo viewports.
    render(<RouteComparisonView comparison={CAMPUS_RESPONSE} />);

    const summary = screen.getByTestId('uncertainty-summary');
    expect(summary).toHaveAttribute('data-complete', 'false');
    expect(summary).toHaveTextContent('Incomplete data');
    expect(summary).toHaveTextContent('100% of this route');
    expect(summary).toHaveTextContent(/unrecorded is not the same as clear/i);
    expect(summary).not.toHaveTextContent(/\b(safe|verified|confident|guaranteed)\b/i);
  });

  it('reports the largest gap when the route is not wholly unrecorded', () => {
    const partly = {
      ...CAMPUS_RESPONSE,
      accessible_route: {
        ...CAMPUS_RESPONSE.accessible_route,
        unknown_data_fraction: 0,
        evidence_coverage: { surface: 0.12, smoothness: 0.61, gradient: 0.2 },
      },
    } as unknown as RouteCompareResponse;

    render(<RouteComparisonView comparison={partly} />);

    const summary = screen.getByTestId('uncertainty-summary');
    expect(summary).toHaveTextContent(/surface condition/i);
    expect(summary).toHaveTextContent('61%');
  });

  it('says so plainly when nothing is missing, without claiming more', () => {
    const complete = {
      ...CAMPUS_RESPONSE,
      accessible_route: {
        ...CAMPUS_RESPONSE.accessible_route,
        unknown_data_fraction: 0,
        evidence_coverage: {},
      },
    } as unknown as RouteCompareResponse;

    render(<RouteComparisonView comparison={complete} />);

    const summary = screen.getByTestId('uncertainty-summary');
    expect(summary).toHaveAttribute('data-complete', 'true');
    // PA-UX-01F: a statement about the record, not "everything was recorded".
    expect(summary).toHaveTextContent(
      /no gaps reported in surface, surface condition, gradient, steps or kerb/i,
    );
    expect(summary).not.toHaveTextContent(/every accessibility category/i);
    expect(summary).not.toHaveTextContent(/\b(safe|accessible route|verified|guaranteed)\b/i);
  });

  it('never presents missing data as a clear path', () => {
    render(<RouteComparisonView comparison={CAMPUS_RESPONSE} />);

    const coverage = screen.getByTestId('evidence-coverage');
    // Width and surface condition are wholly unrecorded, and say so.
    expect(screen.getByTestId('coverage-width')).toHaveTextContent('100% not recorded');
    expect(coverage).toHaveTextContent(/not recorded is not the same as clear/i);
    expect(coverage).not.toHaveTextContent(/\b(safe|verified|confiden\w*|accessible route)\b/i);
  });

  it('says nothing when there is only one route to talk about', () => {
    const { container } = render(
      <RouteDifference
        comparison={{ ...CAMPUS_RESPONSE, accessible_route: null } as RouteCompareResponse}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
