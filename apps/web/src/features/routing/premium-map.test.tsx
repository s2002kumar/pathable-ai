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

const ORIGIN = {
  position: { longitude: -80.5424, latitude: 43.4728 },
  label: 'Davis Centre library',
  source: 'example' as const,
};
const DESTINATION = {
  position: { longitude: -80.5449, latitude: 43.4715 },
  label: 'Student Life Centre',
  source: 'example' as const,
};

function buildRoute(overrides: Record<string, unknown> = {}) {
  return {
    profile: 'wheelchair',
    profile_display_name: 'Wheelchair',
    distance_m: 354.1,
    effective_distance_m: 601,
    estimated_duration_seconds: 373,
    pace_profile: 'wheelchair',
    gradient: {
      steepest_uphill: {
        percent: 2.1,
        direction: 'uphill',
        source: 'derived_elevation',
        segment_index: 0,
      },
      steepest_downhill: null,
      recorded_fraction: 0,
      estimated_fraction: 0.6,
      unknown_fraction: 0.4,
    },
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
    // A different path from the wheelchair route's, as the real one is.
    coordinates: [
      [-80.5424, 43.4728],
      [-80.5436, 43.4722],
      [-80.5449, 43.4715],
    ],
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
      basis: 'recorded',
      evidence: {},
    },
    {
      code: 'distance_difference',
      summary: 'The wheelchair route is 67 m longer.',
      basis: 'profile_rule',
      evidence: {},
    },
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
    standard_route: buildRoute({
      profile: 'standard',
      distance_m: 300,
      coordinates: [
        [-80.5424, 43.4728],
        [-80.5436, 43.4722],
        [-80.5449, 43.4715],
      ],
    }),
    accessible_route: buildRoute({ distance_m: 302 }),
    extra_distance_m: 2,
    extra_distance_fraction: 0.006,
    explanations: [],
  } as unknown as RouteCompareResponse;
}

describe('choosing which route is drawn in front', () => {
  it('offers the two routes as radio buttons, named by route and distance', () => {
    render(<RouteDifference comparison={CAMPUS_COMPARISON} />);

    const accessible = screen.getByRole('radio', { name: 'Wheelchair route 354 m' });
    const standard = screen.getByRole('radio', { name: 'Shortest walking route 287 m' });
    expect(accessible).toHaveAttribute('aria-checked', 'true');
    expect(standard).toHaveAttribute('aria-checked', 'false');
  });

  it('reports the chosen route to the workspace', async () => {
    const user = userEvent.setup();
    const onSelectRoute = vi.fn();
    const { rerender } = render(
      <RouteDifference comparison={CAMPUS_COMPARISON} onSelectRoute={onSelectRoute} />,
    );

    await user.click(screen.getByTestId('difference-shortest'));
    expect(onSelectRoute).toHaveBeenLastCalledWith('standard');

    // The checked state is the workspace's to render; re-render as it would.
    rerender(
      <RouteDifference
        comparison={CAMPUS_COMPARISON}
        selectedRoute="standard"
        onSelectRoute={onSelectRoute}
      />,
    );
    expect(screen.getByTestId('difference-shortest')).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByTestId('difference-accessible')).toHaveAttribute('aria-checked', 'false');
  });

  it('names the route in front in the map key, and never calls either one cleared', async () => {
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
    // The profile's own route is in front until the viewer chooses otherwise.
    expect(screen.getByTestId('legend-accessible')).toHaveTextContent(/in front/);
    expect(screen.getByTestId('legend-standard')).toHaveAttribute('data-dimmed', 'true');
    expect(screen.getByTestId('focus-note')).toHaveTextContent(
      'Neither route is certified passable.',
    );

    await user.click(screen.getByTestId('difference-shortest'));
    expect(screen.getByTestId('legend-standard')).toHaveTextContent(/in front/);
    expect(screen.getByTestId('legend-accessible')).toHaveAttribute('data-dimmed', 'true');

    // A new request means a new comparison; a stale choice must not carry over.
    await user.click(screen.getByRole('radio', { name: 'Crutches or cane' }));
    await waitFor(() =>
      expect(screen.getByTestId('legend-accessible')).toHaveTextContent(/in front/),
    );
    expect(screen.getByTestId('legend-standard')).not.toHaveTextContent(/in front/);
  });
});

describe('what "unrecorded" means', () => {
  it('says at least one record is missing, not that nothing is known', () => {
    // The verified journey: four recorded stairways on a route whose every
    // segment is missing some other attribute. "No accessibility detail for
    // 100%" would contradict the stairway count on the same screen.
    render(<RouteComparisonView comparison={CAMPUS_COMPARISON} />);

    const summary = screen.getByTestId('uncertainty-summary');
    expect(summary).toHaveTextContent('Incomplete data');
    expect(summary).toHaveTextContent('100% of this route is missing at least one record');
    expect(summary).not.toHaveTextContent(/no accessibility detail/i);
    expect(summary).toHaveTextContent(/unrecorded is not the same as clear/i);
  });

  it('names the largest single gap from the per-category figures', () => {
    render(<RouteComparisonView comparison={CAMPUS_COMPARISON} />);

    expect(screen.getByTestId('uncertainty-summary')).toHaveTextContent(
      /largest gap: surface condition, 100%/i,
    );
  });

  it('never names width as the largest gap of a figure that does not count width', () => {
    // PA-UX-03B regression. `unknown_data_fraction` counts surface, surface
    // condition, gradient, steps and kerb. The line read "unrecorded on 42% of
    // this route; largest gap: path width, 100%" — a gap larger than the
    // figure it was a part of, because width was never in that figure.
    const widthless = {
      ...CAMPUS_COMPARISON,
      accessible_route: buildRoute({
        unknown_data_fraction: 0.3,
        evidence_coverage: { surface: 0.2, smoothness: 0.3, gradient: 0, width: 1, kerb: 0 },
      }),
    } as unknown as RouteCompareResponse;
    render(<RouteComparisonView comparison={widthless} />);

    const summary = screen.getByTestId('uncertainty-summary');
    expect(summary).toHaveTextContent('largest gap: surface condition, 30%');
    expect(summary).not.toHaveTextContent(/width/i);
    // Width is still reported — beside its own denominator.
    expect(screen.getByTestId('coverage-width')).toHaveTextContent('100% not recorded');
  });

  it('says which attributes the figure counts, where the categories are broken down', () => {
    render(<RouteComparisonView comparison={CAMPUS_COMPARISON} />);

    expect(screen.getByTestId('evidence-coverage')).toHaveTextContent(
      /counts surface, surface condition, gradient, steps and kerb — not width/,
    );
    expect(screen.getByTestId('evidence-coverage')).toHaveTextContent(
      /Not recorded is not the same as clear/,
    );
  });
});

describe('nearly equal routes', () => {
  it('states a 2 m difference as 2 m, and infers nothing about the path from it', () => {
    // PA-UX-01F. A distance under a threshold once produced "the same length"
    // and "the same path". Neither follows from a number.
    render(<RouteComparisonView comparison={coincident()} />);

    const status = screen.getByRole('status');
    expect(status).toHaveTextContent(/wheelchair route is 2 m longer than the shortest walking/i);
    expect(status).not.toHaveTextContent(/same length/i);
    expect(screen.queryByTestId('same-path-note')).not.toBeInTheDocument();
  });

  it('says nothing about overlap when the routes differ', () => {
    render(<RouteComparisonView comparison={CAMPUS_COMPARISON} />);

    expect(screen.queryByTestId('same-path-note')).not.toBeInTheDocument();
  });
});

describe('the answer as one block', () => {
  it('keeps the figures, the extra distance, the reason and the uncertainty line together', () => {
    render(<RouteComparisonView comparison={CAMPUS_COMPARISON} />);

    const difference = screen.getByTestId('route-difference');
    const answer = difference.parentElement as HTMLElement;
    expect(within(difference).getByTestId('difference-accessible')).toHaveTextContent('354 m');
    expect(within(difference).getByTestId('difference-shortest')).toHaveTextContent('4 stairways');
    // The figure, and not a single cause beside it (D7): the stairs are the
    // reason stated separately, with their own evidence label.
    const extra = within(difference).getByTestId('difference-extra');
    expect(extra).toHaveTextContent('+67 m longer');
    expect(extra).not.toHaveTextContent(/to avoid/);
    expect(within(difference).getByTestId('main-difference')).toHaveTextContent(
      'Avoids 4 stairways',
    );
    expect(within(answer).getByTestId('uncertainty-summary')).toBeInTheDocument();
  });

  it('puts the per-category record on the page and the provenance behind a disclosure', async () => {
    const user = userEvent.setup();
    render(<RouteComparisonView comparison={CAMPUS_COMPARISON} />);

    // The breakdown is evidence a reviewer drills into, so it is on the page;
    // only where the data came from waits behind a control.
    expect(screen.getByTestId('evidence-coverage').closest('details')).toBeNull();
    expect(screen.getByTestId('coverage-kerb')).toHaveTextContent('No crossings on this route');

    const provenance = screen.getByTestId('route-provenance');
    expect(provenance).not.toHaveAttribute('open');
    await user.click(within(provenance).getByText('Where this comes from'));
    expect(within(provenance).getByText(/Map data published 34 days ago/)).toBeVisible();
    expect(within(provenance).getByText(/51e75f78/)).toBeVisible();
    expect(within(provenance).getByText(/“Recorded” means a mapper wrote it down/)).toBeVisible();
  });

  it('keeps the no-model statement outside any disclosure', () => {
    render(<RouteComparisonView comparison={CAMPUS_COMPARISON} />);

    expect(
      screen.getByText(/no predictions, no scoring, no machine learning/i).closest('details'),
    ).toBeNull();
  });

  it('keeps the elevation licence outside any disclosure too', () => {
    // The Open Government Licence asks to be carried by anything that uses
    // the data. A credit somebody has to open a control to find is not being
    // carried — and this one used to sit inside "Where this comes from".
    // OpenStreetMap's own credit is always on the map canvas; this is the one
    // that would otherwise have been hidden.
    render(<RouteComparisonView comparison={CAMPUS_COMPARISON} />);

    const elevation = screen.getByTestId('elevation-attribution');
    expect(elevation).toHaveTextContent(/Open Government Licence/i);
    expect(elevation.closest('details')).toBeNull();
  });
});

describe('planner guidance', () => {
  it('shows a half-finished journey as one end named and one end empty', () => {
    render(
      <RoutePlanner
        points={{ origin: ORIGIN, destination: null }}
        profileKey="wheelchair"
        state={{ status: 'idle' }}
        apiBaseUrl="http://api.test"
        region="waterloo"
        example={CAMPUS_EXAMPLE}
        exampleActive={false}
        canCompare={false}
        pendingEdits={false}
        pickTarget={null}
        submittedSummary="Davis Centre library to Student Life Centre"
        onRunExample={() => {}}
        onProfileChange={() => {}}
        onCompare={() => {}}
        onClearPoint={() => {}}
        onClearAll={() => {}}
        onSwapPoints={() => {}}
        onRetry={() => {}}
        onPickOnMap={() => {}}
        onSelectPlace={() => {}}
      />,
    );

    // There is no "what does the next click set?" question any more: each end
    // is its own field, so the answer is which field is empty. The status line
    // stays idle because nothing has been asked for yet.
    expect(screen.getByTestId('route-status')).toHaveAttribute('data-route-state', 'idle');
    expect(screen.getByTestId('route-status')).toHaveTextContent(
      'Start set. Now choose a destination.',
    );
    expect(screen.getByTestId('endpoint-origin-value')).toHaveTextContent('Davis Centre library');
    expect(screen.getByTestId('endpoint-destination-value')).toHaveTextContent(/not set/i);
    expect(screen.getByTestId('compare-routes')).toBeDisabled();
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
