import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { RouteCompareResponse } from '@pathable/contracts';
import { comparison as fixtureComparison } from '@/test/route-fixtures';
import { RouteComparisonView } from './RouteComparisonView';
import { RoutePlanner, type RoutePlannerProps } from './RoutePlanner';
import { CAMPUS_EXAMPLE } from './verified-example';
import { RouteWorkspace } from './RouteWorkspace';
import { compareRoutes } from './compare-routes';
import { NO_RULES, type ProfileRules } from './route-facts';
import {
  formatDistance,
  formatDuration,
  hasPendingEndpointEdits,
  journeyOf,
  nextRole,
  parseUphillLimit,
  profileSelectionOf,
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

/** A route with no gradient on record anywhere: unknown, not flat. */
const NO_GRADIENT = {
  steepest_uphill: null,
  steepest_downhill: null,
  recorded_fraction: 0,
  estimated_fraction: 0,
  unknown_fraction: 1,
};

function buildRoute(overrides: Record<string, unknown> = {}) {
  return {
    profile: 'wheelchair',
    profile_display_name: 'Wheelchair',
    distance_m: 709,
    effective_distance_m: 980,
    estimated_duration_seconds: 746,
    // Both routes of a comparison are timed at the traveller's pace.
    pace_profile: 'wheelchair',
    gradient: {
      steepest_uphill: {
        percent: 4,
        direction: 'uphill',
        source: 'derived_elevation',
        segment_index: 0,
      },
      steepest_downhill: null,
      recorded_fraction: 0,
      estimated_fraction: 0.99,
      unknown_fraction: 0.01,
    },
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
    {
      code: 'avoids_stairs',
      summary: 'Avoids 1 stairway (14 steps in total).',
      basis: 'recorded',
      evidence: {},
    },
    {
      code: 'avoids_unrecorded_kerbs',
      summary: 'Avoids 1 crossing where no kerb has been recorded.',
      basis: 'not_recorded',
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

function renderPlanner(overrides: Partial<RoutePlannerProps> = {}) {
  const props = {
    layout: 'compare' as const,
    points: { origin: ORIGIN, destination: DESTINATION },
    profileKey: 'wheelchair' as const,
    state: { status: 'success' as const, comparison: COMPARISON },
    apiBaseUrl: 'http://api.test',
    region: 'waterloo',
    regionName: 'Waterloo, Ontario',
    example: CAMPUS_EXAMPLE,
    exampleActive: false,
    canCompare: true,
    pendingEdits: false,
    pickTarget: null,
    rules: NO_RULES,
    onRunExample: vi.fn(),
    onProfileChange: vi.fn(),
    onCompare: vi.fn(),
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

/** The planning form, before any answer: what the workspace shows first. */
function renderPlanForm(overrides: Partial<RoutePlannerProps> = {}) {
  return renderPlanner({
    layout: 'plan',
    points: { origin: null, destination: null },
    state: { status: 'idle' },
    canCompare: false,
    ...overrides,
  });
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
  it('states the trade-off on the profile’s own route card', () => {
    renderPlanner();

    expect(screen.getByTestId('difference-extra')).toHaveTextContent('+226 m detour');
  });

  it('shows both routes with their own figures', () => {
    renderPlanner();

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

  it('names the stairway the shortest route uses, and none on the profile’s route', () => {
    renderPlanner();

    expect(screen.getByTestId('difference-shortest')).toHaveTextContent('1 recorded stairway');
    expect(screen.getByTestId('difference-accessible')).toHaveTextContent(/Stairs\s*0 recorded/);
  });

  it('leads with the reason the engine gave, in its own words', () => {
    renderPlanner();

    expect(screen.getByTestId('main-difference')).toHaveTextContent(
      'Avoids 1 stairway (14 steps in total).',
    );
  });

  it('says what the answer rests on, and how old the map is', () => {
    renderPlanner();

    // The fixture's wheelchair route has a gradient derived from elevation, so
    // the elevation model is named; the map's age is the publication's.
    expect(screen.getByText('Evaluated with OpenStreetMap & NRCan HRDEM')).toBeInTheDocument();
    expect(screen.getByText('Map data 2 days old')).toBeInTheDocument();
  });

  it('names no elevation model for an answer that used none', () => {
    const flat = {
      ...COMPARISON,
      standard_route: buildRoute({ gradient: NO_GRADIENT, gradient_source: null }),
      accessible_route: buildRoute({ gradient: NO_GRADIENT, gradient_source: null }),
    } as unknown as RouteCompareResponse;
    renderPlanner({ state: { status: 'success', comparison: flat } });

    expect(screen.getByText('Evaluated with OpenStreetMap')).toBeInTheDocument();
    expect(screen.queryByText(/HRDEM/)).not.toBeInTheDocument();
  });

  it('shows the grade it has as an estimate, and a missing one as not recorded', () => {
    const { unmount } = renderPlanner();
    expect(screen.getByTestId('steepest-climb-tile')).toHaveTextContent('Max 4.0%');
    unmount();

    renderPlanner({
      state: {
        status: 'success',
        comparison: {
          ...COMPARISON,
          accessible_route: buildRoute({ steepest_incline_percent: null, gradient: NO_GRADIENT }),
        } as unknown as RouteCompareResponse,
      },
    });
    const tile = screen.getByTestId('steepest-climb-tile');
    expect(tile).toHaveTextContent('Not recorded');
    expect(tile).not.toHaveTextContent(/0\.0%/);
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

    expect(screen.getByRole('status')).toHaveTextContent(/No route meets the wheelchair profile/);
    expect(screen.getByRole('status')).toHaveTextContent(/does not loosen your profile’s limits/);
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

    await user.click(screen.getByRole('radio', { name: /^Crutches or cane/ }));

    expect(props.onProfileChange).toHaveBeenCalledWith('crutches');
  });

  it('announces results politely rather than stealing focus', () => {
    renderPlanner();

    expect(screen.getByTestId('route-status')).toHaveAttribute('aria-live', 'polite');
  });

  it('marks the status region busy while a request is in flight', () => {
    renderPlanForm({ state: { status: 'loading' } });

    expect(screen.getByTestId('route-status')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByTestId('compare-routes')).toBeDisabled();
  });

  it('offers nothing to act on until an endpoint exists', () => {
    renderPlanForm();

    expect(screen.getByTestId('swap-points')).toBeDisabled();
    // Nothing to clear, so there is no control that would pretend otherwise.
    expect(screen.queryByTestId('clear-journey')).not.toBeInTheDocument();
    // Nothing to compare, so the control that would ask says so rather than
    // sending an incomplete journey.
    expect(screen.getByTestId('compare-routes')).toBeDisabled();
  });

  it('clears the journey once there is one to clear', async () => {
    const user = userEvent.setup();
    const { props } = renderPlanForm({ points: { origin: ORIGIN, destination: null } });

    await user.click(screen.getByTestId('clear-journey'));
    expect(props.onClearAll).toHaveBeenCalledOnce();
  });

  it('names each endpoint separately instead of one implicit next point', async () => {
    // The old planner had a single search that filled "whichever point is
    // empty", so a person searching for their destination had no way to say
    // so. Each end is now its own labelled field with its own state.
    const user = userEvent.setup();
    renderPlanForm();

    expect(screen.getByTestId('endpoint-origin-value')).toHaveTextContent(/not set/i);
    expect(screen.getByTestId('endpoint-destination-value')).toHaveTextContent(/not set/i);
    expect(screen.getByLabelText('Start location')).toBeInTheDocument();
    expect(screen.getByLabelText('Target endpoint')).toBeInTheDocument();

    // Each field's search control has its own accessible name — a page with two
    // buttons both called "Search" is a page where neither can be addressed.
    await user.type(screen.getByLabelText('Start location'), 'Davis');
    expect(screen.getByRole('button', { name: 'Search for a start' })).toBeInTheDocument();
    await user.type(screen.getByLabelText('Target endpoint'), 'Student');
    expect(screen.getByRole('button', { name: 'Search for a destination' })).toBeInTheDocument();
  });

  it('says which field a map click will fill once one has asked for it', () => {
    renderPlanForm({ pickTarget: 'destination' });

    expect(screen.getByTestId('endpoint-destination-value')).toHaveTextContent(
      /click the map to set this point/i,
    );
    expect(screen.getByTestId('pick-destination')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('pick-origin')).toHaveAttribute('aria-pressed', 'false');
  });

  it('shows a committed endpoint by name, with the coordinate as detail', () => {
    renderPlanForm({ points: { origin: ORIGIN, destination: null } });

    expect(screen.getByLabelText('Start location')).toHaveValue('Davis Centre library');
    const origin = screen.getByTestId('endpoint-origin-value');
    expect(origin).toHaveTextContent('Davis Centre library');
    // The coordinate stays available, but as what the name resolved to.
    expect(origin).toHaveTextContent('43.47000');
  });

  it('shows the journey the answer belongs to beside it', () => {
    renderPlanner();

    expect(screen.getByLabelText('Origin')).toHaveValue('Davis Centre library');
    expect(screen.getByLabelText('Destination')).toHaveValue('Student Life Centre');
  });

  it('says an answer is out of date rather than letting it look current', async () => {
    // The one way a comparison can mislead without a single wrong number in
    // it: the figures stay on screen while the journey above them changes.
    const user = userEvent.setup();
    const { props } = renderPlanner({ pendingEdits: true });

    expect(screen.getByTestId('stale-result')).toHaveTextContent(
      /The routes below are still for the previous one/,
    );
    await user.click(screen.getByTestId('compare-routes'));
    expect(props.onCompare).toHaveBeenCalledOnce();
  });

  it('offers no Compare button beside an answer that is still current', () => {
    renderPlanner();

    expect(screen.queryByTestId('stale-result')).not.toBeInTheDocument();
    expect(screen.queryByTestId('compare-routes')).not.toBeInTheDocument();
  });

  it('runs the verified example from the empty form, and says where it came from', async () => {
    const user = userEvent.setup();
    const { props } = renderPlanForm();

    expect(screen.getByTestId('verified-example')).toBeInTheDocument();
    expect(
      screen.getByText(new RegExp(CAMPUS_EXAMPLE.provenance.slice(0, 24))),
    ).toBeInTheDocument();
    await user.click(screen.getByTestId('run-verified-example'));
    expect(props.onRunExample).toHaveBeenCalledWith(CAMPUS_EXAMPLE);
  });
});

/**
 * One route's record (17:3789): its name, the journey, and whether its record
 * has gaps — worded as a statement about the record, never a clearance.
 */
describe('the evidence panel', () => {
  it('says the route was found with gaps, and that this is no guarantee', () => {
    renderPlanner({ layout: 'evidence' });

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Wheelchair route');
    expect(screen.getByTestId('journey-origin')).toHaveTextContent('Davis Centre library');
    expect(screen.getByTestId('journey-destination')).toHaveTextContent('Student Life Centre');
    const banner = screen.getByTestId('gap-banner');
    expect(banner).toHaveAttribute('data-complete', 'false');
    expect(banner).toHaveTextContent('Route found with accessibility data gaps');
    expect(banner).toHaveTextContent('this is not an accessibility guarantee');
  });

  it('calls a gap-free record a statement about the record, not a certification', () => {
    const complete = {
      ...COMPARISON,
      accessible_route: buildRoute({
        unknown_data_fraction: 0,
        unknown_kerb_crossing_count: 0,
        evidence_coverage: { surface: 0, smoothness: 0, gradient: 0, width: 0, kerb: 0 },
      }),
    } as unknown as RouteCompareResponse;
    renderPlanner({ layout: 'evidence', state: { status: 'success', comparison: complete } });

    const banner = screen.getByTestId('gap-banner');
    expect(banner).toHaveAttribute('data-complete', 'true');
    expect(banner).toHaveTextContent('not a certification that the route is passable');
    expect(banner).not.toHaveTextContent(/accessible route|safe|verified/i);
  });

  it('describes the shortest route when that is the one chosen', () => {
    renderPlanner({ layout: 'evidence', selectedRoute: 'standard' });

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Shortest walking route');
  });

  it('opens the full record and goes back to the comparison', async () => {
    const user = userEvent.setup();
    const onRouteDetails = vi.fn();
    const onShowLayout = vi.fn();
    renderPlanner({ layout: 'evidence', onRouteDetails, onShowLayout });

    await user.click(screen.getByTestId('open-route-details'));
    expect(onRouteDetails).toHaveBeenCalledOnce();
    await user.click(screen.getByRole('button', { name: 'Back to the route comparison' }));
    expect(onShowLayout).toHaveBeenCalledWith('compare');
  });
});

/**
 * No route for the profile (17:4041). The panel states what the response
 * reports about the shortest route the engine did return — never a diagnosis
 * of every path it searched — and that the limits were not relaxed.
 */
describe('the no-route panel', () => {
  const blocked = fixtureComparison({
    accessible_route: null,
    accessible_failure: 'No route satisfies the wheelchair profile.',
    extra_distance_m: null,
    extra_distance_fraction: null,
    explanations: [],
  });
  const STEP_FREE: ProfileRules = { excludesSteps: true, uphillLimit: null, prefersUnder: 8 };

  it('says no route satisfies the profile and that nothing was relaxed', () => {
    renderPlanner({
      layout: 'no-route',
      state: { status: 'success', comparison: blocked },
      rules: STEP_FREE,
    });

    const status = screen.getByTestId('no-accessible-route');
    expect(status).toHaveAttribute('role', 'status');
    expect(status).toHaveTextContent('No route satisfies your profile requirements');
    expect(status).toHaveTextContent('It will not silently relax them.');
    // The API's own reason, verbatim.
    expect(status).toHaveTextContent('No route satisfies the wheelchair profile.');
    // Not styled or announced as a failure of the service.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('names the rule the shortest route breaks, from its recorded stairway', () => {
    renderPlanner({
      layout: 'no-route',
      state: { status: 'success', comparison: blocked },
      rules: STEP_FREE,
    });

    const stairs = screen.getByTestId('requirement-steps');
    expect(stairs).toHaveTextContent('Recorded stairway evidence');
    expect(stairs).toHaveTextContent('Recorded · OSM');
    expect(stairs).toHaveTextContent(
      'The shortest walking route uses 1 recorded stairway; your profile rules out stairs.',
    );
    expect(stairs).toHaveTextContent('[Your profile rule]');
    expect(screen.getByText('0 Recorded Stairs')).toBeInTheDocument();
  });

  it('states a custom uphill limit as the traveller set it', () => {
    renderPlanner({
      layout: 'no-route',
      state: { status: 'success', comparison: blocked },
      rules: { ...STEP_FREE, uphillLimit: 4.5 },
    });

    expect(screen.getByText('Max 4.5% Uphill')).toBeInTheDocument();
  });

  it('sends the traveller back to the profile or the destination', async () => {
    const user = userEvent.setup();
    const onEditJourney = vi.fn();
    renderPlanner({
      layout: 'no-route',
      state: { status: 'success', comparison: blocked },
      rules: STEP_FREE,
      onEditJourney,
    });

    await user.click(screen.getByTestId('edit-profile'));
    expect(onEditJourney).toHaveBeenLastCalledWith('profile');
    await user.click(screen.getByTestId('change-destination'));
    expect(onEditJourney).toHaveBeenLastCalledWith('destination');
  });
});

/**
 * The details sheet's text: everything the panel summarises, in full. The
 * sheet is modal, so it has to state the whole answer itself.
 */
describe('the full answer, as the details sheet states it', () => {
  it('states the trade-off in the headline', () => {
    render(<RouteComparisonView comparison={COMPARISON} />);

    expect(screen.getByRole('status')).toHaveTextContent(
      /wheelchair route is 226 m longer than the shortest walking route/i,
    );
  });

  it('lists the evidence-backed reasons for the detour', () => {
    render(<RouteComparisonView comparison={COMPARISON} />);

    const reasons = within(screen.getByTestId('difference-reasons'));
    expect(reasons.getByText(/Avoids 1 stairway \(14 steps in total\)/)).toBeInTheDocument();
    expect(reasons.getByText(/no kerb has been recorded/)).toBeInTheDocument();
  });

  it('shows the missing-data caution without softening it', () => {
    // The most dangerous possible UI bug here is presenting an unsurveyed route
    // as a checked one.
    render(<RouteComparisonView comparison={COMPARISON} />);

    expect(
      screen.getByText(/Missing data is not evidence that a path is clear/),
    ).toBeInTheDocument();
  });

  it('says plainly that no model was involved', () => {
    render(<RouteComparisonView comparison={COMPARISON} />);

    expect(
      screen.getByText(/no predictions, no scoring, no machine learning/i),
    ).toBeInTheDocument();
  });

  it('shows the required OpenStreetMap attribution with the route', () => {
    render(<RouteComparisonView comparison={COMPARISON} />);

    expect(screen.getByText(/© OpenStreetMap contributors, ODbL 1\.0/)).toBeInTheDocument();
  });

  it('shows the elevation licence credit whenever the dataset carries one', () => {
    // Derived gradients come from NRCan's HRDEM under the Open Government
    // Licence – Canada, which requires its statement wherever a grade is shown.
    const credit = 'Contains information licensed under the Open Government Licence – Canada.';
    render(
      <RouteComparisonView
        comparison={
          {
            ...COMPARISON,
            dataset: { ...COMPARISON.dataset, elevation_attribution: credit },
          } as unknown as RouteCompareResponse
        }
      />,
    );

    expect(screen.getByTestId('elevation-attribution')).toHaveTextContent(credit);
  });

  it('shows no elevation credit for a dataset that was never sampled', () => {
    render(<RouteComparisonView comparison={COMPARISON} />);

    expect(screen.queryByTestId('elevation-attribution')).not.toBeInTheDocument();
  });

  it('reports unrecorded gradients as unrecorded rather than zero', () => {
    render(
      <RouteComparisonView
        comparison={
          {
            ...COMPARISON,
            accessible_route: buildRoute({ steepest_incline_percent: null, gradient: NO_GRADIENT }),
          } as unknown as RouteCompareResponse
        }
      />,
    );

    // Scoped to the breakdown of the route being described.
    const breakdown = screen.getByTestId('evidence-coverage');
    expect(within(breakdown).getByTestId('steepest-climb')).toHaveTextContent('None on record');
    expect(within(breakdown).getByTestId('steepest-descent')).toHaveTextContent('None on record');
    expect(within(breakdown).queryByText(/0\.0%/)).not.toBeInTheDocument();
  });

  it('labels the answer with the journey it answered', () => {
    render(
      <RouteComparisonView
        comparison={COMPARISON}
        journeySummary="Davis Centre library to Student Life Centre"
      />,
    );

    expect(screen.getByTestId('journey-summary')).toHaveTextContent(
      'Davis Centre library to Student Life Centre',
    );
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

  it('requests no route until both endpoints are chosen', async () => {
    const fetchImpl = vi.fn(async (_url: string) => new Response('{}', { status: 503 }));

    render(<RouteWorkspace {...config} fetchImpl={fetchImpl as unknown as typeof fetch} />);

    await waitFor(() =>
      expect(screen.getByTestId('route-status')).toHaveAttribute('data-route-state', 'idle'),
    );
    // The profile rules are fetched at once; a route never is.
    const urls = fetchImpl.mock.calls.map(([url]) => String(url));
    expect(urls.filter((url) => url.includes('/routes/compare'))).toEqual([]);
    expect(urls).toContain('http://api.test/api/v1/routes/profiles');
  });

  it('opens on the planning form, with no answer to explain yet', () => {
    // Nothing is drawn or described until a journey has been asked about.
    render(<RouteWorkspace {...config} fetchImpl={vi.fn() as unknown as typeof fetch} />);

    expect(screen.getByTestId('plan-journey')).toHaveAttribute('data-layout', 'plan');
    expect(screen.queryByTestId('route-difference')).not.toBeInTheDocument();
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

    // "Surface is missing on 38% of this route" is actionable; a single
    // uncertainty number is not — two routes missing entirely different things
    // produce the same figure.
    expect(screen.getByTestId('coverage-surface')).toHaveTextContent(
      '62% recorded · 38% not recorded',
    );
    expect(screen.getByTestId('coverage-smoothness')).toHaveTextContent(
      '28% recorded · 72% not recorded',
    );
    // Kerbs are counted over crossings, not over the route's length.
    expect(screen.getByTestId('coverage-kerb')).toHaveTextContent('1 of 1 crossing recorded');
  });

  it('states a small gap as small rather than rounding it away', () => {
    render(<RouteComparisonView comparison={COMPARISON} />);

    expect(screen.getByTestId('coverage-gradient')).toHaveTextContent(
      '99% estimated · 1% not recorded',
    );
  });

  it('says a gradient was inferred from terrain rather than recorded on the path', () => {
    render(<RouteComparisonView comparison={COMPARISON} />);

    const provenance = screen.getByTestId('gradient-provenance');
    expect(provenance).toHaveTextContent(/elevation model of the ground/);
    expect(provenance).toHaveTextContent(/cannot see a ramp or a step/);
    expect(screen.getByTestId('steepest-climb')).toHaveTextContent('4.0%Estimated from elevation');
  });

  it('does not let a missing record read as evidence the path is clear', () => {
    render(<RouteComparisonView comparison={COMPARISON} />);

    expect(screen.getByText(/it means nobody has mapped it/)).toBeInTheDocument();
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
    expect(journeyOf({ origin: ORIGIN, destination: DESTINATION }, 'wheelchair')).toEqual({
      ...journey,
      uphillLimitPercent: null,
    });
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

describe('stairs, as the details sheet states them', () => {
  it('says how many, and that the step total is a floor', () => {
    render(<RouteComparisonView comparison={COMPARISON} />);

    // "recorded" is load-bearing: step_count sums only the stairways somebody
    // counted, so it is a floor and never a total.
    expect(screen.getByTestId('difference-shortest')).toHaveTextContent(
      '1 stairway · 14 recorded steps',
    );
  });

  it('calls zero "no recorded stairs" rather than "no stairs"', () => {
    // OpenStreetMap recording no stairway is not the same as somebody having
    // checked that there is none, and the difference is the whole product.
    const noStairs = {
      ...COMPARISON,
      standard_route: { ...COMPARISON.standard_route, segments: [], stairway_count: 0 },
      accessible_route: { ...COMPARISON.accessible_route, segments: [], stairway_count: 0 },
    } as unknown as RouteCompareResponse;

    render(<RouteComparisonView comparison={noStairs} />);

    for (const id of ['difference-shortest', 'difference-accessible']) {
      expect(screen.getByTestId(id)).toHaveTextContent('No recorded stairs');
      expect(screen.getByTestId(id)).not.toHaveTextContent(/\bno stairs\b/i);
    }
  });

  it('counts recorded stairways on the cards, never "no stairs"', () => {
    const noStairs = {
      ...COMPARISON,
      standard_route: { ...COMPARISON.standard_route, segments: [], stairway_count: 0 },
    } as unknown as RouteCompareResponse;

    renderPlanner({ state: { status: 'success', comparison: noStairs } });

    expect(screen.getByTestId('difference-accessible')).toHaveTextContent(/Stairs\s*0 recorded/);
    expect(screen.getByTestId('plan-journey')).not.toHaveTextContent(/\bno stairs\b/i);
  });
});

/**
 * The traveller's own uphill limit: off by default, exact when on, and a
 * custom profile built by the API rather than a copy of its rules.
 */
describe('the uphill limit', () => {
  const journey = { origin: ORIGIN, destination: DESTINATION, profileKey: 'walker' as const };

  it('is off, and sends a preset, until the traveller turns it on', () => {
    expect(parseUphillLimit({ enabled: false, text: '' })).toEqual({ ok: true, percent: null });
    expect(profileSelectionOf(journey)).toEqual({ key: 'walker' });
    expect(profileSelectionOf({ ...journey, uphillLimitPercent: null })).toEqual({
      key: 'walker',
    });
  });

  it('sends the number exactly as typed, on the chosen preset', () => {
    expect(parseUphillLimit({ enabled: true, text: ' 4.75 ' })).toEqual({
      ok: true,
      percent: 4.75,
    });
    expect(profileSelectionOf({ ...journey, uphillLimitPercent: 4.75 })).toEqual({
      key: 'custom',
      custom: { base: 'walker', max_incline_percent: 4.75 },
    });
  });

  it('refuses an empty, negative or non-numeric limit instead of guessing one', () => {
    expect(parseUphillLimit({ enabled: true, text: '' }).ok).toBe(false);
    expect(parseUphillLimit({ enabled: true, text: '-2' }).ok).toBe(false);
    expect(parseUphillLimit({ enabled: true, text: 'steep' }).ok).toBe(false);
  });

  it('keeps Compare unavailable while the limit on screen cannot be sent', async () => {
    const user = userEvent.setup();
    const onUphillLimitChange = vi.fn();
    renderPlanForm({
      uphillLimit: { enabled: true, text: '' },
      onUphillLimitChange,
    });

    expect(screen.getByTestId('uphill-limit-input')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByTestId('uphill-limit-note')).toHaveTextContent(/steepest climb/i);

    await user.type(screen.getByTestId('uphill-limit-input'), '6');
    expect(onUphillLimitChange).toHaveBeenLastCalledWith({ enabled: true, text: '6' });
  });

  it('shows no number and no field while the limit is off', () => {
    renderPlanForm();

    expect(screen.getByTestId('uphill-limit-toggle')).not.toBeChecked();
    expect(screen.queryByTestId('uphill-limit-input')).not.toBeInTheDocument();
  });
});

describe('the profile rules come from the routing service', () => {
  const WHEELCHAIR = {
    key: 'wheelchair',
    display_name: 'Wheelchair',
    description: 'Avoids steps entirely.',
    excludes_steps: true,
    max_incline_percent: null,
    min_width_m: null,
    prefers_gradient_under_percent: 8,
    prefers_width_over_m: 0.9,
    hard_requirements: ['cannot use steps'],
  };

  it('states the hard limits apart from the preferences, as the API gives them', () => {
    renderPlanner({
      profiles: { status: 'ready', profiles: new Map([['wheelchair', WHEELCHAIR]]) },
    });

    const rule = screen.getByTestId('profile-rule');
    expect(rule).toHaveTextContent('Hard limit: cannot use steps.');
    expect(rule).toHaveTextContent('Prefers climbs under 8% and paths wider than 0.9 m.');
    // Worded apart: "Hard limit" rules a path out, "Prefers" only costs more.
    expect(rule.textContent).toMatch(/^Hard limit: .*\. Prefers /);
  });

  it('says a profile has no hard limits when the API lists none', () => {
    renderPlanner({
      profileKey: 'crutches',
      profiles: {
        status: 'ready',
        profiles: new Map([
          [
            'crutches',
            {
              ...WHEELCHAIR,
              key: 'crutches',
              excludes_steps: false,
              prefers_width_over_m: null,
              prefers_gradient_under_percent: 15,
              hard_requirements: [],
            },
          ],
        ]),
      },
    });

    expect(screen.getByTestId('profile-rule')).toHaveTextContent('No hard limits.');
    expect(screen.getByTestId('profile-rule')).toHaveTextContent('Prefers climbs under 15%.');
  });

  it('says it is waiting, or that the rules could not be loaded — never a guess', () => {
    const { unmount } = renderPlanner({ profiles: { status: 'loading' } });
    expect(screen.getByTestId('profile-rule')).toHaveTextContent(/loading this profile’s rules/i);
    unmount();

    renderPlanner({ profiles: { status: 'unavailable' } });
    expect(screen.getByTestId('profile-rule')).toHaveTextContent(/could not be loaded/i);
    expect(screen.getByTestId('profile-rule')).not.toHaveTextContent(/steps|%/);
  });
});
