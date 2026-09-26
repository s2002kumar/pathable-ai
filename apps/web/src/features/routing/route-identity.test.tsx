/**
 * PA-UX-01F: claims the result may make about identity, length and coverage.
 *
 * Each case is a way the earlier candidate could have said more than the
 * response supports — a distance threshold read as "same path", a real detour
 * rounded away, "everything recorded" over a derived gradient — and the words
 * the page uses instead.
 */
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Route, RouteCompareResponse } from '@pathable/contracts';
import { RouteComparisonView } from './RouteComparisonView';
import { RouteDifference } from './RouteDifference';
import { RoutePlanner } from './RoutePlanner';
import {
  DISPLAY_EQUAL_BELOW_M,
  differenceIsBelowDisplayPrecision,
  routesSharePath,
} from './route-identity';
import { CAMPUS_EXAMPLE } from './verified-example';

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

const DIRECT: Array<[number, number]> = [
  [-80.5424, 43.4728],
  [-80.5449, 43.4715],
];
const DETOUR: Array<[number, number]> = [
  [-80.5424, 43.4728],
  [-80.543, 43.474],
  [-80.5449, 43.4715],
];

function segment(edgeIdentity: string, coordinates: Array<[number, number]>) {
  return {
    edge_identity: edgeIdentity,
    length_m: 100,
    coordinates,
    steps: 'no',
    surface: null,
    smoothness: null,
    incline_percent: null,
    derived_grade_percent: null,
    kerb: 'unknown',
    is_crossing: false,
    unknown_attributes: [],
  };
}

function route(overrides: Record<string, unknown> = {}): Route {
  return {
    profile: 'wheelchair',
    profile_display_name: 'Wheelchair',
    distance_m: 300,
    effective_distance_m: 300,
    estimated_duration_seconds: 250,
    coordinates: DIRECT,
    segments: [],
    origin: { ...ORIGIN, distance_m: 2 },
    destination: { ...DESTINATION, distance_m: 3 },
    stairway_count: 0,
    step_count: 0,
    crossing_count: 0,
    unknown_kerb_crossing_count: 0,
    steepest_incline_percent: null,
    unknown_data_fraction: 0.2,
    evidence_coverage: { surface: 0.2, smoothness: 0.2, gradient: 0, width: 0.2, kerb: 0 },
    gradient_source: null,
    computation_ms: 5,
    ...overrides,
  } as unknown as Route;
}

function comparison(
  standard: Route | null,
  accessible: Route | null,
  extra: number | null,
): RouteCompareResponse {
  return {
    profile: 'wheelchair',
    profile_display_name: 'Wheelchair',
    profile_description: 'Avoids steps entirely.',
    standard_route: standard,
    accessible_route: accessible,
    standard_failure: null,
    accessible_failure: null,
    extra_distance_m: extra,
    extra_distance_fraction:
      extra === null || standard === null ? null : extra / standard.distance_m,
    explanations: [],
    cautions: [],
    dataset: {
      dataset_id: '51585450-8ff5-409d-a02e-66d5a3c5e260',
      region: 'waterloo',
      checksum: '51e75f7896ab725d29120fe4363c607bea68eed260d830482d6677f827d2e906',
      source_type: 'osm',
      source_name: 'openstreetmap-pbf:waterloo',
      acquired_at: '2026-08-17T23:52:02+00:00',
      attribution: '© OpenStreetMap contributors, ODbL 1.0',
    },
    routing_policy_version: 'test',
    ml_predictions_used: false,
  } as unknown as RouteCompareResponse;
}

describe('routesSharePath', () => {
  it('is established by identical ordered segment identities', () => {
    const a = route({ segments: [segment('e1', DIRECT), segment('e2', DIRECT)] });
    const b = route({ segments: [segment('e1', DIRECT), segment('e2', DIRECT)] });
    expect(routesSharePath(a, b)).toBe(true);
  });

  it('is not established by equal length', () => {
    // Same distance, different segments: a detour that happens to measure the
    // same as the direct path.
    const a = route({ segments: [segment('e1', DIRECT)], coordinates: DIRECT });
    const b = route({ segments: [segment('e7', DETOUR)], coordinates: DETOUR });
    expect(a.distance_m).toBe(b.distance_m);
    expect(routesSharePath(a, b)).toBe(false);
  });

  it('is not established by equal geometry when the segments differ', () => {
    const a = route({ segments: [segment('e1', DIRECT)] });
    const b = route({ segments: [segment('e2', DIRECT)] });
    expect(routesSharePath(a, b)).toBe(false);
  });

  it('falls back to identical nonempty geometry only when neither route carries segments', () => {
    expect(routesSharePath(route({ coordinates: DIRECT }), route({ coordinates: DIRECT }))).toBe(
      true,
    );
    expect(routesSharePath(route({ coordinates: DIRECT }), route({ coordinates: DETOUR }))).toBe(
      false,
    );
  });

  it('makes no claim when identity data is missing', () => {
    expect(routesSharePath(route({ coordinates: [] }), route({ coordinates: [] }))).toBe(false);
    expect(routesSharePath(route({ segments: [segment('e1', DIRECT)] }), route())).toBe(false);
    expect(routesSharePath(null, route())).toBe(false);
  });
});

describe('the same-path note', () => {
  it('appears only for identical segments, never for equal distances', () => {
    const shared = [segment('e1', DIRECT)];
    render(
      <RouteDifference
        comparison={comparison(route({ segments: shared }), route({ segments: shared }), 0)}
      />,
    );
    expect(screen.getByTestId('same-path-note')).toHaveTextContent(/same segments/i);
  });

  it('stays silent on a same-length pair of different paths', () => {
    render(
      <RouteDifference
        comparison={comparison(
          route({ segments: [segment('e1', DIRECT)], coordinates: DIRECT }),
          route({ segments: [segment('e7', DETOUR)], coordinates: DETOUR }),
          0,
        )}
      />,
    );
    expect(screen.queryByTestId('same-path-note')).not.toBeInTheDocument();
    expect(screen.queryByText(/same path|overlap/i)).not.toBeInTheDocument();
  });

  it('stays silent on a 10 m detour and on missing identity data', () => {
    const { unmount } = render(
      <RouteDifference
        comparison={comparison(
          route({ distance_m: 300, coordinates: DIRECT }),
          route({ distance_m: 310, coordinates: DETOUR }),
          10,
        )}
      />,
    );
    expect(screen.queryByTestId('same-path-note')).not.toBeInTheDocument();
    unmount();

    render(
      <RouteDifference
        comparison={comparison(route({ coordinates: [] }), route({ coordinates: [] }), 0)}
      />,
    );
    expect(screen.queryByTestId('same-path-note')).not.toBeInTheDocument();
  });
});

describe('the headline', () => {
  it('keeps a 10 m detour as 10 m longer, in the profile’s name', () => {
    render(
      <RouteComparisonView
        comparison={comparison(route({ distance_m: 300 }), route({ distance_m: 310 }), 10)}
      />,
    );
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent(/wheelchair route is 10 m longer than the shortest walking/i);
    expect(status).not.toHaveTextContent(/same length/i);
  });

  it('says "same length" only under display precision, and says so', () => {
    expect(DISPLAY_EQUAL_BELOW_M).toBe(0.5);
    expect(differenceIsBelowDisplayPrecision(0.4)).toBe(true);
    expect(differenceIsBelowDisplayPrecision(0.5)).toBe(false);
    expect(differenceIsBelowDisplayPrecision(null)).toBe(false);

    render(
      <RouteComparisonView
        comparison={comparison(route({ distance_m: 300 }), route({ distance_m: 300.3 }), 0.3)}
      />,
    );
    expect(screen.getByRole('status')).toHaveTextContent(/same length to the nearest metre/i);
    expect(screen.getByRole('status')).not.toHaveTextContent(/same path|same route/i);
  });

  it('does not infer equality from a missing difference', () => {
    render(<RouteComparisonView comparison={comparison(route(), route(), null)} />);
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent(/did not report the difference/i);
    expect(status).not.toHaveTextContent(/same length/i);
    expect(screen.getByTestId('difference-extra')).toHaveTextContent(/not reported/i);
  });
});

describe('what the uncertainty line may claim', () => {
  it('never says nothing is known when a stairway is recorded beside a missing field', () => {
    const standard = route({
      profile: 'standard',
      profile_display_name: 'Standard walking',
      stairway_count: 4,
      step_count: 16,
      unknown_data_fraction: 1,
      evidence_coverage: { surface: 0.4, smoothness: 1, gradient: 0.4, width: 1, kerb: 0 },
    });
    const accessible = route({
      unknown_data_fraction: 1,
      evidence_coverage: { surface: 0.4, smoothness: 1, gradient: 0.4, width: 1, kerb: 0 },
    });
    render(
      <RouteComparisonView
        comparison={{
          ...comparison(standard, accessible, 66.67),
          cautions: [
            {
              code: 'missing_accessibility_data',
              summary:
                'On most of the wheelchair route (100% of its length) at least one accessibility ' +
                'attribute — surface, surface condition, gradient, steps or kerb — has no record in ' +
                'OpenStreetMap. Missing data is not evidence that a path is clear.',
              evidence: {},
            },
          ],
        }}
      />,
    );

    expect(screen.getByTestId('uncertainty-summary')).toHaveTextContent(
      /at least one accessibility attribute/i,
    );
    expect(screen.getByTestId('difference-unknown')).toHaveTextContent(
      /at least one accessibility attribute/i,
    );
    const cautions = screen.getByRole('heading', {
      name: /before you rely on this/i,
    }).parentElement!;
    expect(cautions).toHaveTextContent(/at least one accessibility attribute/i);
    expect(cautions).not.toHaveTextContent(/no accessibility details/i);
    expect(screen.getByTestId('difference-shortest')).toHaveTextContent('4 stairways');
  });

  it('reports "no gaps" as a statement about the record, not as everything recorded', () => {
    const complete = route({
      unknown_data_fraction: 0,
      evidence_coverage: { surface: 0, smoothness: 0, gradient: 0, width: 0, kerb: 0 },
      gradient_source: 'derived_elevation',
      steepest_incline_percent: 3,
    });
    render(<RouteDifference comparison={comparison(route(), complete, 5)} />);

    const summary = screen.getByTestId('uncertainty-summary');
    expect(summary).toHaveAttribute('data-complete', 'true');
    expect(summary).toHaveTextContent(/no gaps reported in the assessed categories/i);
    expect(summary).not.toHaveTextContent(/every accessibility category/i);
    expect(summary).not.toHaveTextContent(/recorded in OpenStreetMap/i);
    expect(summary).toHaveTextContent(/not a certification/i);
    // Provenance stays distinct: the derived-gradient line is still there.
    expect(screen.getByText(/terrain model of the ground/i)).toBeInTheDocument();
  });

  it('keeps the gaps unknown when the response carries no coverage at all', () => {
    const uncovered = route({ unknown_data_fraction: 0, evidence_coverage: undefined });
    render(<RouteDifference comparison={comparison(route(), uncovered, 5)} />);

    const summary = screen.getByTestId('uncertainty-summary');
    expect(summary).toHaveAttribute('data-complete', 'unknown');
    expect(summary).toHaveTextContent(/gaps are unknown/i);
    expect(summary).not.toHaveTextContent(/no gaps reported/i);
  });

  it('names the crossings denominator when kerb is the largest gap', () => {
    const kerbs = route({
      unknown_data_fraction: 0.3,
      evidence_coverage: { surface: 0.1, smoothness: 0.1, gradient: 0, width: 0.1, kerb: 0.75 },
    });
    render(<RouteDifference comparison={comparison(route(), kerbs, 5)} />);

    expect(screen.getByTestId('uncertainty-summary')).toHaveTextContent(
      /largest gap: kerb, 75% of crossings/i,
    );
  });
});

describe('editing the journey from the result', () => {
  const scrollIntoView = vi.fn();

  beforeEach(() => {
    Element.prototype.scrollIntoView = scrollIntoView;
  });

  afterEach(() => {
    scrollIntoView.mockReset();
  });

  it('moves focus to the planning controls without touching the comparison', async () => {
    const user = userEvent.setup();
    const onProfileChange = vi.fn();
    const onClearPoints = vi.fn();
    render(
      <RoutePlanner
        points={{ origin: ORIGIN, destination: DESTINATION }}
        profileKey="wheelchair"
        state={{
          status: 'success',
          comparison: comparison(route({ distance_m: 287.4 }), route({ distance_m: 354.1 }), 66.67),
        }}
        apiBaseUrl="http://api.test"
        region="waterloo"
        example={CAMPUS_EXAMPLE}
        exampleActive
        canCompare
        pendingEdits={false}
        pickTarget={null}
        submittedSummary="Davis Centre library to Student Life Centre"
        stairsTarget={null}
        onRunExample={() => {}}
        onProfileChange={onProfileChange}
        onCompare={() => {}}
        onClearPoint={onClearPoints}
        onClearAll={onClearPoints}
        onSwapPoints={() => {}}
        onRetry={() => {}}
        onPickOnMap={() => {}}
        onSelectPlace={() => {}}
      />,
    );

    const edit = screen.getByRole('button', { name: /edit journey or profile/i });
    edit.focus();
    await user.keyboard('{Enter}');

    const plan = screen.getByTestId('plan-journey');
    expect(plan).toHaveFocus();
    expect(plan).toHaveAccessibleName(/plan a journey/i);
    expect(scrollIntoView).toHaveBeenCalledTimes(1);

    // The result is still there, and nothing about the journey was reset.
    expect(screen.getByTestId('route-difference')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/67 m longer/);
    expect(onProfileChange).not.toHaveBeenCalled();
    expect(onClearPoints).not.toHaveBeenCalled();
    expect(within(plan).getByLabelText(/how do you travel/i)).toHaveValue('wheelchair');
  });

  it('scrolls instantly when the viewer prefers reduced motion', async () => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => ({ matches: query === '(prefers-reduced-motion: reduce)' })),
    );
    const user = userEvent.setup();
    render(
      <RoutePlanner
        points={{ origin: ORIGIN, destination: DESTINATION }}
        profileKey="wheelchair"
        state={{ status: 'success', comparison: comparison(route(), route(), 5) }}
        apiBaseUrl="http://api.test"
        region="waterloo"
        example={CAMPUS_EXAMPLE}
        exampleActive={false}
        canCompare
        pendingEdits={false}
        pickTarget={null}
        submittedSummary="Davis Centre library to Student Life Centre"
        stairsTarget={null}
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

    await user.click(screen.getByTestId('edit-journey'));

    expect(scrollIntoView).toHaveBeenCalledWith(expect.objectContaining({ behavior: 'auto' }));
    vi.unstubAllGlobals();
  });
});
