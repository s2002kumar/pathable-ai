/**
 * Behaviour added by PA-UX-01: the map-first layout's controls and wording.
 *
 * Everything here is about what a viewer can do with a result — bring one route
 * forward, read how much of it is unrecorded, tell when the two routes are the
 * same path — and about the words the page uses to say so. Layout itself is
 * covered in a real browser by the e2e suite.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { RouteCompareResponse } from '@pathable/contracts';
import { SystemStatusBadge } from '@/features/system-status/SystemStatusBadge';
import { RouteComparisonView } from './RouteComparisonView';
import { RouteDifference } from './RouteDifference';
import { RoutePlanner } from './RoutePlanner';
import { RouteWorkspace } from './RouteWorkspace';
import { CAMPUS_EXAMPLE } from './verified-example';

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

const ORIGIN = { longitude: -80.5424, latitude: 43.4728 };
const DESTINATION = { longitude: -80.5449, latitude: 43.4715 };

function buildRoute(overrides: Record<string, unknown> = {}) {
  return {
    profile: 'wheelchair',
    profile_display_name: 'Wheelchair',
    distance_m: 354.1,
    effective_distance_m: 601,
    estimated_duration_seconds: 373,
    coordinates: [
      [-80.5424, 43.4728],
      [-80.5449, 43.4715],
    ],
    segments: [],
    origin: { ...ORIGIN, distance_m: 2 },
    destination: { ...DESTINATION, distance_m: 3 },
    stairway_count: 0,
    step_count: 0,
    crossing_count: 0,
    unknown_kerb_crossing_count: 0,
    steepest_incline_percent: null,
    unknown_data_fraction: 1,
    evidence_coverage: { surface: 0.61, smoothness: 1, gradient: 0.4, width: 1, kerb: 0 },
    gradient_source: 'derived_elevation',
    computation_ms: 20,
    ...overrides,
  };
}

/** The verified campus journey, as the engine returned it on 2026-09-13. */
const CAMPUS_COMPARISON = {
  profile: 'wheelchair',
  profile_display_name: 'Wheelchair',
  profile_description: 'Avoids steps entirely.',
  standard_route: buildRoute({
    profile: 'standard',
    profile_display_name: 'Standard walking',
    distance_m: 287.4,
    effective_distance_m: 287.4,
    stairway_count: 4,
    step_count: 16,
  }),
  accessible_route: buildRoute(),
  standard_failure: null,
  accessible_failure: null,
  extra_distance_m: 66.67,
  extra_distance_fraction: 0.232,
  explanations: [
    {
      code: 'avoids_stairs',
      summary: 'Avoids 4 stairways (16 steps in total, plus 2 with no recorded step count).',
      evidence: {},
    },
    { code: 'distance_difference', summary: 'The wheelchair route is 67 m longer.', evidence: {} },
  ],
  cautions: [],
  dataset: {
    dataset_id: '51585450-8ff5-409d-a02e-66d5a3c5e260',
    region: 'waterloo',
    checksum: '51e75f7896ab725d29120fe4363c607bea68eed260d830482d6677f827d2e906',
    source_type: 'osm',
    source_name: 'openstreetmap-pbf:waterloo',
    acquired_at: '2026-08-17T23:52:02+00:00',
    source_timestamp: '2026-08-16T23:08:23+00:00',
    evidence_age_days: 34,
    attribution: '© OpenStreetMap contributors, ODbL 1.0',
    elevation_attribution:
      'Contains information licensed under the Open Government Licence – Canada.',
  },
  routing_policy_version: 'test',
  ml_predictions_used: false,
} as unknown as RouteCompareResponse;

function coincident(): RouteCompareResponse {
  return {
    ...CAMPUS_COMPARISON,
    standard_route: buildRoute({ profile: 'standard', distance_m: 300 }),
    accessible_route: buildRoute({ distance_m: 302 }),
    extra_distance_m: 2,
    extra_distance_fraction: 0.006,
    explanations: [],
  } as unknown as RouteCompareResponse;
}

describe('bringing one route forward', () => {
  it('offers a keyboard-operable control for each route', () => {
    render(<RouteDifference comparison={CAMPUS_COMPARISON} />);

    const accessible = screen.getByRole('button', { name: /highlight the wheelchair route/i });
    const standard = screen.getByRole('button', {
      name: /highlight the shortest walking route/i,
    });
    expect(accessible).toHaveAttribute('aria-pressed', 'false');
    expect(standard).toHaveAttribute('aria-pressed', 'false');
  });

  it('reports the chosen route to the workspace and toggles back off', async () => {
    const user = userEvent.setup();
    const onFocusRoute = vi.fn();
    render(<RouteDifference comparison={CAMPUS_COMPARISON} onFocusRoute={onFocusRoute} />);

    await user.click(screen.getByTestId('focus-standard'));
    expect(onFocusRoute).toHaveBeenLastCalledWith('standard');

    // Pressed state is the workspace's to render; re-render as it would.
    render(
      <RouteDifference
        comparison={CAMPUS_COMPARISON}
        focusedRoute="standard"
        onFocusRoute={onFocusRoute}
      />,
    );
    const pressed = screen.getAllByTestId('focus-standard').at(-1)!;
    expect(pressed).toHaveAttribute('aria-pressed', 'true');
    expect(pressed).toHaveTextContent(/highlighted/i);

    await user.click(pressed);
    expect(onFocusRoute).toHaveBeenLastCalledWith(null);
  });

  it('never lets a highlighted route read as a cleared one', () => {
    render(<RouteDifference comparison={CAMPUS_COMPARISON} focusedRoute="accessible" />);

    const note = screen.getByTestId('focus-note');
    expect(note).toHaveTextContent(/the other stays drawn/i);
    expect(note).toHaveTextContent(/neither is certified/i);
    expect(screen.getByTestId('difference-shortest')).toHaveAttribute('data-dimmed', 'true');
    expect(screen.getByTestId('difference-accessible')).toHaveAttribute('data-focused', 'true');
  });

  it('names the highlighted route in the map key, in words', async () => {
    const user = userEvent.setup();
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify(CAMPUS_COMPARISON), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    ) as unknown as typeof fetch;

    render(
      <RouteWorkspace
        apiBaseUrl="http://api.test"
        region="waterloo"
        mapStyleUrl="/map-styles/offline-test-style.json"
        centerLat={43.4668}
        centerLon={-80.5164}
        zoom={14}
        regionName="Waterloo, Ontario"
        attribution="© OpenStreetMap contributors"
        fetchImpl={fetchImpl}
        initialExample={CAMPUS_EXAMPLE}
      />,
    );

    await waitFor(() =>
      expect(screen.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success'),
    );
    expect(screen.getByTestId('legend-accessible')).not.toHaveTextContent(/highlighted/);

    await user.click(screen.getByTestId('focus-accessible'));

    expect(screen.getByTestId('legend-accessible')).toHaveTextContent(/highlighted/);
    expect(screen.getByTestId('legend-standard')).toHaveAttribute('data-dimmed', 'true');

    // A new request means a new comparison; a stale highlight must not carry over.
    await user.click(screen.getByRole('radio', { name: /Crutches or cane/ }));
    await waitFor(() =>
      expect(screen.getByTestId('legend-accessible')).not.toHaveTextContent(/highlighted/),
    );
  });
});

describe('what "unrecorded" means', () => {
  it('says at least one attribute is missing, not that nothing is known', () => {
    // The verified journey: four recorded stairways on a route whose every
    // segment is missing some other attribute. "No accessibility detail for
    // 100%" would contradict the stairway count on the same screen.
    render(<RouteDifference comparison={CAMPUS_COMPARISON} />);

    const summary = screen.getByTestId('uncertainty-summary');
    expect(summary).toHaveTextContent('Accessibility data is incomplete');
    expect(summary).toHaveTextContent(/at least one accessibility attribute/i);
    expect(summary).toHaveTextContent('100% of this route');
    expect(summary).not.toHaveTextContent(/no accessibility detail/i);
    expect(summary).toHaveTextContent(/unrecorded is not the same as clear/i);
  });

  it('names the largest single gap from the per-category figures', () => {
    render(<RouteDifference comparison={CAMPUS_COMPARISON} />);

    // smoothness and width are both 100%; the sort is stable, so the first
    // 100% entry in contract order (smoothness) wins.
    expect(screen.getByTestId('uncertainty-summary')).toHaveTextContent(
      /largest gap: surface condition, 100%/i,
    );
  });

  it('lists the attributes the figure counts, in the fuller line', () => {
    render(<RouteDifference comparison={CAMPUS_COMPARISON} />);

    const unknown = screen.getByTestId('difference-unknown');
    expect(unknown).toHaveTextContent(/surface, surface condition, gradient, steps or kerb/);
    expect(unknown).toHaveTextContent(/missing information, not a clear path/i);
  });
});

describe('coincident routes', () => {
  it('explains that two overlapping lines are one path, not a missing route', () => {
    render(<RouteComparisonView comparison={coincident()} />);

    expect(screen.getByRole('status')).toHaveTextContent(/same length as the shortest route/i);
    expect(screen.getByTestId('coincident-note')).toHaveTextContent(/overlap on the map/i);
  });

  it('says nothing about overlap when the routes differ', () => {
    render(<RouteComparisonView comparison={CAMPUS_COMPARISON} />);

    expect(screen.queryByTestId('coincident-note')).not.toBeInTheDocument();
  });
});

describe('the answer as one block', () => {
  it('keeps the figures, the extra distance and the uncertainty line together', () => {
    render(<RouteComparisonView comparison={CAMPUS_COMPARISON} />);

    const difference = screen.getByTestId('route-difference');
    expect(within(difference).getByTestId('difference-accessible')).toHaveTextContent('354 m');
    expect(within(difference).getByTestId('difference-shortest')).toHaveTextContent('4 stairways');
    expect(within(difference).getByTestId('difference-extra')).toHaveTextContent(
      /\+67 m.*to avoid 4 stairways/,
    );
    expect(within(difference).getByTestId('uncertainty-summary')).toBeInTheDocument();
  });

  it('keeps the detail behind labelled disclosures rather than dropping it', async () => {
    const user = userEvent.setup();
    render(<RouteComparisonView comparison={CAMPUS_COMPARISON} />);

    const detail = screen.getByTestId('route-detail');
    const provenance = screen.getByTestId('route-provenance');
    expect(detail).not.toHaveAttribute('open');
    expect(provenance).not.toHaveAttribute('open');

    await user.click(within(detail).getByText('What is on this route'));
    expect(within(detail).getByText('Road crossings')).toBeVisible();
    expect(within(detail).getByText(/what the map does not say/i)).toBeVisible();

    await user.click(within(provenance).getByText('Where this comes from'));
    expect(within(provenance).getByText(/Map data published 34 days ago/)).toBeVisible();
    expect(within(provenance).getByTestId('elevation-attribution')).toBeVisible();
    expect(within(provenance).getByText(/51e75f78/)).toBeVisible();
  });

  it('keeps the no-model statement outside any disclosure', () => {
    render(<RouteComparisonView comparison={CAMPUS_COMPARISON} />);

    expect(
      screen.getByText(/no predictions, no scoring, no machine learning/i).closest('details'),
    ).toBeNull();
  });
});

describe('planner guidance', () => {
  it('tells the viewer what the next click sets once the start is placed', () => {
    render(
      <RoutePlanner
        points={{ origin: ORIGIN, destination: null }}
        profileKey="wheelchair"
        state={{ status: 'idle' }}
        apiBaseUrl="http://api.test"
        region="waterloo"
        example={CAMPUS_EXAMPLE}
        exampleActive={false}
        onRunExample={() => {}}
        onProfileChange={() => {}}
        onClearPoints={() => {}}
        onSwapPoints={() => {}}
        onRetry={() => {}}
        onSelectPlace={() => {}}
      />,
    );

    expect(screen.getByTestId('route-status')).toHaveAttribute('data-route-state', 'idle');
    expect(screen.getByTestId('awaiting-end')).toHaveTextContent(/set the end/i);
    expect(screen.getByTestId('point-end')).toHaveTextContent(/click the map to set/i);
  });
});

describe('diagnostics stay out of the visual hierarchy', () => {
  it('keeps the API version readable to assistive tech but off the badge face', () => {
    render(
      <SystemStatusBadge status={{ state: 'ready', service: 'pathable-api', version: '0.1.0' }} />,
    );

    const badge = screen.getByTestId('system-status');
    expect(badge).toHaveTextContent('API online');
    expect(badge).toHaveTextContent('pathable-api v0.1.0');
    expect(screen.getByText(/pathable-api v0\.1\.0/)).toHaveClass('visually-hidden');
    expect(badge).toHaveAttribute('title', 'pathable-api v0.1.0');
  });

  it('shows a preparing or degraded detail in full, because those are for people', () => {
    render(
      <SystemStatusBadge
        status={{
          state: 'preparing',
          service: 'pathable-api',
          version: '0.1.0',
          detail: 'loading',
        }}
      />,
    );

    expect(screen.getByText(/loading the Waterloo routing graph/)).not.toHaveClass(
      'visually-hidden',
    );
  });
});
