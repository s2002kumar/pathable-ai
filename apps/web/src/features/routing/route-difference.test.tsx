/**
 * Regressions for the ways the comparison could mislead without a single wrong
 * number in it. Each test names the defect it guards: D1–D7 from the PA-UX-03A
 * audit, and the PA-UX-03B rules for time, hard limits and route choice.
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { GradientSummary, RouteCompareResponse } from '@pathable/contracts';
import {
  accessibleSegments,
  comparison as fixtureComparison,
  explanation,
  route as fixtureRoute,
  segment,
  shortestSegments,
} from '@/test/route-fixtures';
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
        evidence: { hard_limit: true },
      },
      {
        code: 'avoids_unrecorded_kerbs',
        summary: 'Avoids 2 crossings where no kerb has been recorded.',
        basis: 'not_recorded',
        evidence: { cost_difference_effective_m: 180 },
      },
      {
        code: 'avoids_rough_surface',
        summary: 'Avoids 60 m of recorded rough surface (gravel).',
        basis: 'recorded',
        evidence: { cost_difference_effective_m: 40 },
      },
      {
        code: 'fewer_unmarked_crossings',
        summary: 'Has no unmarked or unspecified road crossings, against 2 on the shortest route.',
        basis: 'recorded',
        evidence: { cost_difference_effective_m: 30 },
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

function withAccessibleGradient(gradient: GradientSummary, extra: Overrides = {}) {
  return comparison({ accessible_route: route({ gradient, ...extra }) });
}

describe('where a gradient came from (D1)', () => {
  it('credits a recorded steepest climb to OpenStreetMap on a route that mixes the two', () => {
    // The old line read OSM's figure and said it "comes from a terrain model"
    // whenever any estimate was present — exactly this route.
    render(
      <RouteComparisonView
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

    expect(screen.getByTestId('difference-gradient')).toHaveAttribute('data-basis', 'recorded');
    const climb = screen.getByTestId('steepest-climb');
    expect(climb).toHaveTextContent('4.0%');
    expect(within(climb).getByText('Recorded')).toBeInTheDocument();
    expect(climb).not.toHaveTextContent(/estimated/i);
    // The shares stay apart: recorded, estimated and unknown, never merged.
    expect(screen.getByTestId('coverage-gradient')).toHaveTextContent(
      '60% recorded · 30% estimated · 10% not recorded',
    );
  });

  it('shows an estimated steepest climb as an estimate, with its number', () => {
    // Before, an all-estimated route never showed a number at all.
    render(
      <RouteComparisonView
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

    expect(screen.getByTestId('difference-gradient')).toHaveAttribute('data-basis', 'estimated');
    const climb = screen.getByTestId('steepest-climb');
    expect(climb).toHaveTextContent('6.2%');
    expect(within(climb).getByText('Estimated from elevation')).toBeInTheDocument();
    expect(screen.getByTestId('gradient-provenance')).toHaveTextContent(
      /elevation model of the ground, not a survey of the path/,
    );
    expect(screen.getByTestId('coverage-gradient')).toHaveTextContent(
      '70% estimated · 30% not recorded',
    );
  });

  it('says no gradient is on record rather than implying the route is flat', () => {
    render(<RouteComparisonView comparison={comparison()} />);

    expect(screen.getByTestId('difference-gradient')).toHaveAttribute('data-basis', 'not_recorded');
    expect(screen.getByTestId('steepest-climb')).toHaveTextContent('None on record');
    expect(screen.getByTestId('coverage-gradient')).toHaveTextContent('100% not recorded');
  });

  it('labels each steepest figure recorded or estimated', () => {
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

    expect(screen.getByTestId('steepest-climb')).toHaveTextContent('4.0%Recorded');
    expect(screen.getByTestId('steepest-descent')).toHaveTextContent(
      '3.1%Estimated from elevation',
    );
  });
});

describe('comparable times (D5)', () => {
  it('shows both times, and the pace they share, when they were estimated alike', () => {
    render(<RouteComparisonView comparison={comparison()} />);

    expect(screen.getByTestId('difference-accessible-time')).toHaveTextContent('Est. 8 min');
    expect(screen.getByTestId('difference-shortest-time')).toHaveTextContent('Est. 6 min');
    expect(screen.getByTestId('difference-pace')).toHaveTextContent('same assumed wheelchair pace');
  });

  it('withholds the shortest route’s time when it was estimated at another pace', () => {
    // An older backend timed the shortest route at a standard walking pace,
    // and the page put the two figures side by side as if they compared.
    render(
      <RouteComparisonView
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

describe('a route the profile cannot use has no time (PA-UX-03B)', () => {
  it('shows “Time unavailable for this profile” instead of a time, and says why', () => {
    render(<RouteComparisonView comparison={fixtureComparison()} />);

    const shortest = screen.getByTestId('difference-shortest');
    const time = screen.getByTestId('difference-shortest-time');
    expect(time).toHaveTextContent('Time unavailable for this profile');
    expect(time).not.toHaveTextContent(/\d+\s*min/);
    expect(within(shortest).getByTestId('route-blocked')).toHaveTextContent(
      'Ruled out: 1 stairway',
    );
    // The profile's own route keeps its estimate.
    expect(screen.getByTestId('difference-accessible-time')).toHaveTextContent(/^Est\. \d+ min$/);
  });

  it('keeps the time when the stairway is only a cost, as for crutches', () => {
    // A route with a recorded stairway is not thereby unusable: crutches allow
    // stairs. Feasibility comes from `excluded_by_profile`, never the count.
    const priced = fixtureComparison({
      profile: 'crutches',
      profile_display_name: 'Crutches or cane',
      standard_route: fixtureRoute(
        shortestSegments().map((item) => ({ ...item, excluded_by_profile: null })),
        { profile: 'standard' },
      ),
    });
    render(<RouteComparisonView comparison={priced} />);

    expect(screen.getByTestId('difference-shortest-time')).toHaveTextContent(/^Est\. \d+ min$/);
    expect(screen.getByTestId('difference-shortest')).toHaveTextContent('1 stairway');
    expect(screen.queryByTestId('route-blocked')).not.toBeInTheDocument();
  });

  it('withholds the time from the shortest route shown alone when no route fits', () => {
    render(
      <RouteComparisonView
        comparison={fixtureComparison({
          accessible_route: null,
          accessible_failure: 'No route satisfies the wheelchair profile.',
          extra_distance_m: null,
          extra_distance_fraction: null,
        })}
      />,
    );

    expect(screen.getByTestId('route-card-standard-time')).toHaveTextContent(
      'Time unavailable for this profile',
    );
  });
});

describe('no route for the profile is said calmly, and never relaxed', () => {
  it('explains what rules the shortest route out, and that the limits stay', () => {
    render(
      <RouteComparisonView
        comparison={fixtureComparison({
          accessible_route: null,
          accessible_failure: 'No route satisfies the wheelchair profile.',
          extra_distance_m: null,
          extra_distance_fraction: null,
        })}
      />,
    );

    const status = screen.getByTestId('no-accessible-route');
    expect(status).toHaveAttribute('role', 'status');
    expect(status).toHaveTextContent('No route meets the wheelchair profile');
    expect(status).toHaveTextContent('ruled out by 1 stairway');
    expect(status).toHaveTextContent('No route satisfies the wheelchair profile.');
    expect(status).toHaveTextContent('does not loosen your profile’s limits');
    // Not styled or announced as a failure of the service.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('choosing a route (PA-UX-03B)', () => {
  it('offers the two routes as one radio group, the profile’s route chosen first', () => {
    render(<RouteDifference comparison={fixtureComparison()} />);

    const group = screen.getByRole('radiogroup', { name: /route drawn in front/i });
    const [accessible, shortest] = within(group).getAllByRole('radio');
    expect(accessible).toHaveAccessibleName('Wheelchair route 709 m');
    expect(accessible).toHaveAttribute('aria-checked', 'true');
    expect(accessible).toHaveAttribute('tabindex', '0');
    expect(shortest).toHaveAttribute('aria-checked', 'false');
    // One tab stop for the group; the arrow keys move within it.
    expect(shortest).toHaveAttribute('tabindex', '-1');
  });

  it('moves the choice with the arrow keys and reports it', () => {
    const onSelectRoute = vi.fn();
    render(
      <RouteDifference
        comparison={fixtureComparison()}
        selectedRoute="accessible"
        onSelectRoute={onSelectRoute}
      />,
    );

    fireEvent.keyDown(screen.getByTestId('difference-accessible'), { key: 'ArrowDown' });
    expect(onSelectRoute).toHaveBeenCalledWith('standard');
    expect(screen.getByTestId('difference-shortest')).toHaveFocus();

    fireEvent.click(screen.getByTestId('difference-accessible'));
    expect(onSelectRoute).toHaveBeenLastCalledWith('accessible');
  });

  it('describes the chosen route in the evidence below it', () => {
    const { rerender } = render(<RouteComparisonView comparison={fixtureComparison()} />);
    expect(screen.getByTestId('evidence-coverage')).toHaveTextContent(
      'What the map records on the wheelchair route',
    );

    rerender(<RouteComparisonView comparison={fixtureComparison()} selectedRoute="standard" />);
    expect(screen.getByTestId('evidence-coverage')).toHaveTextContent(
      'What the map records on the shortest walking route',
    );
    expect(screen.getByTestId('difference-shortest')).toHaveAttribute('aria-checked', 'true');
  });
});

describe('the reason that decided it comes first', () => {
  it('puts the hard limit above every penalty, with its topic and evidence label', () => {
    // Listed after two penalties would be the same; the hard limit still leads.
    const [stairs, ...penalties] = comparison().explanations;
    render(
      <RouteDifference comparison={fixtureComparison({ explanations: [...penalties, stairs!] })} />,
    );

    const main = screen.getByTestId('main-difference');
    expect(main).toHaveTextContent('Stairs');
    expect(main).toHaveTextContent('Recorded');
    expect(main).toHaveTextContent('Avoids 1 recorded stairway');
  });

  it('says nothing about a difference when both routes are the same path', () => {
    const same = fixtureRoute(accessibleSegments());
    render(
      <RouteComparisonView
        comparison={fixtureComparison({
          standard_route: same,
          accessible_route: same,
          extra_distance_m: 0,
          extra_distance_fraction: 0,
          explanations: [explanation('same_distance', 'profile_rule')],
        })}
      />,
    );

    expect(screen.getByRole('status')).toHaveTextContent('both are the same route');
    expect(screen.getByTestId('same-path-note')).toBeInTheDocument();
    expect(screen.queryByTestId('main-difference')).not.toBeInTheDocument();
  });
});

describe('evidence labels come from the statement’s basis (D6)', () => {
  it('never labels a statement about missing kerbs as recorded', () => {
    // The old list tagged every statement "Recorded in OpenStreetMap",
    // including "no kerb has been recorded".
    render(<RouteComparisonView comparison={comparison()} />);

    const reasons = within(screen.getByTestId('difference-reasons'));
    const kerbs = reasons.getByText(/no kerb has been recorded/).closest('li');
    expect(kerbs).not.toBeNull();
    expect(kerbs).toHaveAttribute('data-basis', 'not_recorded');
    expect(within(kerbs as HTMLElement).getByText('Not recorded')).toBeInTheDocument();
    expect(within(kerbs as HTMLElement).queryByText('Recorded')).not.toBeInTheDocument();
    // And it is filed under missing information, not under kerbs.
    expect(screen.getByTestId('reason-group-missing')).toContainElement(kerbs as HTMLElement);
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
    render(<RouteComparisonView comparison={relabelled} />);

    const item = within(screen.getByTestId('difference-reasons'))
      .getByText('Gentler gradients than the shortest route.')
      .closest('li');
    expect(item).toHaveTextContent('Recorded and estimated');
  });
});

describe('why the route is longer (D7)', () => {
  it('states the extra distance without naming a single cause', () => {
    render(<RouteDifference comparison={comparison()} />);

    const extra = screen.getByTestId('difference-extra');
    expect(extra).toHaveTextContent('+94 m longer');
    expect(extra).not.toHaveTextContent(/to avoid|stairway/i);
  });

  it('lists every reason the engine gives, grouped by what it is about', () => {
    render(<RouteComparisonView comparison={comparison()} />);

    const reasons = screen.getByTestId('difference-reasons');
    expect(reasons).toHaveTextContent('Avoids 1 recorded stairway');
    expect(reasons).toHaveTextContent('no kerb has been recorded');
    expect(reasons).toHaveTextContent('recorded rough surface');
    expect(reasons).toHaveTextContent('unmarked or unspecified road crossings');
    expect(screen.getByTestId('reason-group-stairs')).toHaveTextContent('Hard limit');
    expect(screen.getByTestId('reason-group-crossings')).not.toHaveTextContent('Hard limit');
  });
});

describe('what the map records keeps its denominators', () => {
  it('counts kerbs per crossing, exactly', () => {
    render(<RouteComparisonView comparison={fixtureComparison()} />);
    expect(screen.getByTestId('coverage-kerb')).toHaveTextContent('1 of 1 crossing recorded');
  });

  it('says a route without crossings has none, rather than “all recorded”', () => {
    render(<RouteComparisonView comparison={fixtureComparison()} selectedRoute="standard" />);
    expect(screen.getByTestId('coverage-kerb')).toHaveTextContent('No crossings on this route');
    expect(screen.getByTestId('coverage-kerb')).toHaveAttribute('data-status', 'not_applicable');
  });

  it('never folds a missing category into the recorded share', () => {
    render(<RouteComparisonView comparison={fixtureComparison()} />);
    expect(screen.getByTestId('coverage-width')).toHaveTextContent('100% not recorded');
    expect(screen.getByTestId('coverage-smoothness')).toHaveTextContent('100% not recorded');
  });

  it('sums the step record from the segments, unknown kept apart', () => {
    const unknownSteps = fixtureComparison({
      accessible_route: fixtureRoute([
        segment({ length_m: 25, steps: 'unknown' }),
        segment({ length_m: 75 }),
      ]),
    });
    render(<RouteComparisonView comparison={unknownSteps} />);
    expect(screen.getByTestId('coverage-steps')).toHaveTextContent(
      '75% recorded · 25% not recorded',
    );
  });
});
