/**
 * Regressions for four ways the comparison could mislead without a single wrong
 * number in it. Each test names the defect it guards (PA-UX-03A audit, D1–D7).
 */
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { RouteCompareResponse } from '@pathable/contracts';
import { RouteComparisonView } from './RouteComparisonView';
import { RouteDifference } from './RouteDifference';
import { compareRoutes } from './compare-routes';

type Overrides = Record<string, unknown>;

function route(overrides: Overrides = {}) {
  return {
    profile: 'wheelchair',
    profile_display_name: 'Wheelchair',
    distance_m: 412,
    effective_distance_m: 690,
    estimated_duration_seconds: 471,
    pace_profile: 'wheelchair',
    coordinates: [
      [-80.54, 43.47],
      [-80.534, 43.47],
    ],
    segments: [],
    origin: { longitude: -80.54, latitude: 43.47, distance_m: 2 },
    destination: { longitude: -80.534, latitude: 43.47, distance_m: 3 },
    stairway_count: 0,
    step_count: 0,
    crossing_count: 2,
    unknown_kerb_crossing_count: 0,
    steepest_incline_percent: null,
    gradient: {
      steepest_uphill: null,
      steepest_downhill: null,
      recorded_fraction: 0,
      estimated_fraction: 0,
      unknown_fraction: 1,
    },
    unknown_data_fraction: 0.4,
    evidence_coverage: { surface: 0.2, smoothness: 1, gradient: 0.3, width: 1, kerb: 0 },
    gradient_source: null,
    computation_ms: 7,
    ...overrides,
  };
}

function comparison(overrides: Overrides = {}): RouteCompareResponse {
  return {
    profile: 'wheelchair',
    profile_display_name: 'Wheelchair',
    profile_description: 'Avoids steps entirely.',
    standard_route: route({
      profile: 'standard',
      profile_display_name: 'Standard walking',
      distance_m: 318,
      estimated_duration_seconds: 380,
      stairway_count: 1,
      step_count: 12,
    }),
    accessible_route: route(),
    standard_failure: null,
    accessible_failure: null,
    extra_distance_m: 94,
    extra_distance_fraction: 0.296,
    explanations: [
      {
        code: 'avoids_stairs',
        summary: 'Avoids 1 recorded stairway on the shortest route (12 steps in total).',
        basis: 'recorded',
        evidence: {},
      },
      {
        code: 'avoids_unrecorded_kerbs',
        summary: 'Avoids 2 crossings where no kerb has been recorded.',
        basis: 'not_recorded',
        evidence: {},
      },
      {
        code: 'avoids_rough_surface',
        summary: 'Avoids 60 m of recorded rough surface (gravel).',
        basis: 'recorded',
        evidence: {},
      },
      {
        code: 'fewer_unmarked_crossings',
        summary: 'Has no unmarked or unspecified road crossings, against 2 on the shortest route.',
        basis: 'recorded',
        evidence: {},
      },
      {
        code: 'distance_difference',
        summary: '94 m longer than the shortest route.',
        basis: 'profile_rule',
        evidence: {},
      },
    ],
    cautions: [],
    dataset: {
      dataset_id: 'd',
      region: 'waterloo',
      checksum: 'abcdef0123456789',
      source_type: 'osm',
      source_name: 'openstreetmap:waterloo',
      acquired_at: '2026-08-12T00:00:00+00:00',
      attribution: '© OpenStreetMap contributors, ODbL 1.0',
    },
    routing_policy_version: 2,
    ml_predictions_used: false,
    ...overrides,
  } as unknown as RouteCompareResponse;
}

function withAccessibleGradient(gradient: Overrides, extra: Overrides = {}) {
  return comparison({ accessible_route: route({ gradient, ...extra }) });
}

describe('where a gradient came from (D1)', () => {
  it('credits a recorded steepest climb to OpenStreetMap on a route that mixes the two', () => {
    // The old line read OSM's figure and said it "comes from a terrain model"
    // whenever any estimate was present — exactly this route.
    render(
      <RouteDifference
        comparison={withAccessibleGradient(
          {
            steepest_uphill: {
              percent: 4,
              direction: 'uphill',
              source: 'osm_incline',
              segment_index: 1,
            },
            steepest_downhill: null,
            recorded_fraction: 0.6,
            estimated_fraction: 0.3,
            unknown_fraction: 0.1,
          },
          { steepest_incline_percent: 4, gradient_source: 'mixed' },
        )}
      />,
    );

    const item = screen.getByTestId('difference-gradient');
    expect(item).toHaveAttribute('data-basis', 'recorded');
    expect(within(item).getByText('Recorded in OpenStreetMap')).toBeInTheDocument();
    expect(item).toHaveTextContent('4.0%, as recorded in OpenStreetMap');
    expect(item).not.toHaveTextContent(/terrain|elevation model/i);
  });

  it('shows an estimated steepest climb as an estimate, with its number', () => {
    // Before, an all-estimated route never showed a number at all.
    render(
      <RouteDifference
        comparison={withAccessibleGradient({
          steepest_uphill: {
            percent: 6.2,
            direction: 'uphill',
            source: 'derived_elevation',
            segment_index: 0,
          },
          steepest_downhill: null,
          recorded_fraction: 0,
          estimated_fraction: 0.7,
          unknown_fraction: 0.3,
        })}
      />,
    );

    const item = screen.getByTestId('difference-gradient');
    expect(item).toHaveAttribute('data-basis', 'estimated');
    expect(within(item).getByText('Derived from an elevation model')).toBeInTheDocument();
    expect(item).toHaveTextContent('6.2%, estimated from an elevation model');
    expect(item).toHaveTextContent('No gradient is on record for 30% of the route');
  });

  it('says no gradient is on record rather than implying the route is flat', () => {
    render(<RouteDifference comparison={comparison()} />);

    const item = screen.getByTestId('difference-gradient');
    expect(item).toHaveAttribute('data-basis', 'not_recorded');
    expect(item).toHaveTextContent('No gradient is on record for this route');
  });

  it('labels each steepest figure in the breakdown recorded or estimated', () => {
    render(
      <RouteComparisonView
        comparison={withAccessibleGradient({
          steepest_uphill: {
            percent: 4,
            direction: 'uphill',
            source: 'osm_incline',
            segment_index: 1,
          },
          steepest_downhill: {
            percent: 3.1,
            direction: 'downhill',
            source: 'derived_elevation',
            segment_index: 3,
          },
          recorded_fraction: 0.4,
          estimated_fraction: 0.5,
          unknown_fraction: 0.1,
        })}
      />,
    );

    expect(screen.getByTestId('steepest-climb')).toHaveTextContent('4.0% (recorded)');
    expect(screen.getByTestId('steepest-descent')).toHaveTextContent('3.1% (estimated)');
    expect(screen.getByTestId('gradient-provenance')).toHaveTextContent(
      'recorded in OpenStreetMap for 40% of it',
    );
  });
});

describe('comparable times (D5)', () => {
  it('shows both times, and the pace they share, when they were estimated alike', () => {
    render(<RouteDifference comparison={comparison()} />);

    expect(screen.getByTestId('difference-accessible-time')).toHaveTextContent('Est. 8 min');
    expect(screen.getByTestId('difference-shortest-time')).toHaveTextContent('Est. 6 min');
    expect(screen.getByTestId('difference-pace')).toHaveTextContent('same assumed wheelchair pace');
  });

  it('withholds the shortest route’s time when it was estimated at another pace', () => {
    // An older backend timed the shortest route at a standard walking pace,
    // and the page put the two figures side by side as if they compared.
    render(
      <RouteDifference
        comparison={comparison({
          standard_route: route({
            profile: 'standard',
            distance_m: 318,
            estimated_duration_seconds: 236,
            pace_profile: 'standard',
          }),
        })}
      />,
    );

    expect(screen.getByTestId('difference-accessible-time')).toHaveTextContent('Est. 8 min');
    expect(screen.getByTestId('difference-shortest-time')).toHaveTextContent('Time not comparable');
    expect(screen.queryByTestId('difference-pace')).not.toBeInTheDocument();
  });

  it('refuses a response that does not say whose pace its times use', async () => {
    const skewed = comparison({ accessible_route: route({ pace_profile: undefined }) });
    const result = await compareRoutes({
      apiBaseUrl: 'http://api.test',
      region: 'waterloo',
      origin: { longitude: -80.54, latitude: 43.47 },
      destination: { longitude: -80.534, latitude: 43.47 },
      profile: { key: 'wheelchair' },
      fetchImpl: async () => new Response(JSON.stringify(skewed), { status: 200 }),
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.code).toBe('unexpected_response');
  });
});

describe('evidence labels come from the statement’s basis (D6)', () => {
  it('never labels a statement about missing kerbs as recorded', () => {
    // The old list tagged every statement "Recorded in OpenStreetMap",
    // including "no kerb has been recorded".
    render(<RouteDifference comparison={comparison()} />);

    const reasons = within(screen.getByTestId('difference-reasons'));
    const kerbs = reasons.getByText(/no kerb has been recorded/).closest('li');
    expect(kerbs).not.toBeNull();
    expect(kerbs).toHaveAttribute('data-basis', 'not_recorded');
    expect(within(kerbs as HTMLElement).getByText('Not recorded')).toBeInTheDocument();
    expect(
      within(kerbs as HTMLElement).queryByText('Recorded in OpenStreetMap'),
    ).not.toBeInTheDocument();
  });

  it('reads the label from the basis, whatever the code says', () => {
    const relabelled = comparison({
      explanations: [
        {
          code: 'avoids_steep_gradient',
          summary: 'Gentler gradients than the shortest route.',
          basis: 'mixed',
          evidence: {},
        },
      ],
    });
    render(<RouteDifference comparison={relabelled} />);

    const item = screen.getByText('Gentler gradients than the shortest route.').closest('li');
    expect(item).toHaveTextContent('Recorded and derived from an elevation model');
  });
});

describe('why the route is longer (D7)', () => {
  it('states the extra distance without naming a single cause', () => {
    render(<RouteDifference comparison={comparison()} />);

    const extra = screen.getByTestId('difference-extra');
    expect(extra).toHaveTextContent('+94 m');
    expect(extra).not.toHaveTextContent(/to avoid|stairway/i);
  });

  it('lists every reason the engine gives, not only the stairs', () => {
    render(<RouteDifference comparison={comparison()} />);

    const reasons = screen.getByTestId('difference-reasons');
    expect(reasons).toHaveTextContent('Avoids 1 recorded stairway');
    expect(reasons).toHaveTextContent('no kerb has been recorded');
    expect(reasons).toHaveTextContent('recorded rough surface');
    expect(reasons).toHaveTextContent('unmarked or unspecified road crossings');
  });
});
