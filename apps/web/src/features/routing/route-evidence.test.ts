/**
 * The rules that decide what a person is told about a comparison.
 *
 * Each group names the promise it protects. They are tested here, as rules,
 * because the components only arrange what these functions return.
 */
import { describe, expect, it } from 'vitest';
import {
  accessibleSegments,
  comparison,
  explanation,
  route,
  segment,
  shortestSegments,
} from '@/test/route-fixtures';
import {
  categoryOf,
  coverageRows,
  evidenceMarkers,
  exclusionLabel,
  exclusionsOf,
  formatShare,
  reasonGroups,
  rankedReasons,
  routeTime,
  segmentMidpoint,
  verdictOf,
} from './route-evidence';

describe('hard incompatibility is read from the segments', () => {
  it('groups the segments the profile rules out, with the steps they record', () => {
    const shortest = route(shortestSegments());
    expect(exclusionsOf(shortest)).toEqual([
      { reason: 'steps', segmentIndexes: [1], recordedSteps: 14 },
    ]);
  });

  it('counts two segments of one stairway as two, as the API’s stairway_count does', () => {
    const twoFlights = route([
      segment({ steps: 'yes', step_count: 8, excluded_by_profile: 'steps' }),
      segment({ steps: 'yes', step_count: null, excluded_by_profile: 'steps' }),
    ]);
    const [stairs] = exclusionsOf(twoFlights);
    expect(stairs?.segmentIndexes).toHaveLength(twoFlights.stairway_count);
    expect(exclusionLabel(stairs!)).toBe('2 stairways');
    // A floor, not a total: the second flight has no recorded count.
    expect(stairs?.recordedSteps).toBe(8);
  });

  it('does not treat a stairway as a barrier when the profile allows stairs', () => {
    // Crutches: the stairway is on the route, priced but not excluded.
    const shortest = route(
      shortestSegments().map((item) => ({ ...item, excluded_by_profile: null })),
    );
    expect(shortest.stairway_count).toBe(1);
    expect(exclusionsOf(shortest)).toEqual([]);
  });

  it('orders reasons by kind, not by where they happen to sit on the route', () => {
    const mixed = route([
      segment({ excluded_by_profile: 'too_steep', incline_percent: 11 }),
      segment({ excluded_by_profile: 'steps', steps: 'yes', step_count: 3 }),
      segment({ excluded_by_profile: 'too_steep', derived_grade_percent: 9 }),
    ]);
    expect(exclusionsOf(mixed).map((item) => item.reason)).toEqual(['steps', 'too_steep']);
    expect(exclusionLabel(exclusionsOf(mixed)[1]!)).toBe('2 segments above your gradient limit');
  });

  it('has nothing to group without a route', () => {
    expect(exclusionsOf(null)).toEqual([]);
  });
});

describe('a route the profile cannot use gets no travel time', () => {
  it('shows “unavailable” for a shortest route with a ruled-out stairway', () => {
    const data = comparison();
    expect(routeTime(data.standard_route!, 'standard', data.accessible_route!)).toEqual({
      kind: 'unavailable',
    });
  });

  it('gives the profile’s own route its estimate', () => {
    const data = comparison();
    expect(routeTime(data.accessible_route!, 'accessible', data.standard_route!)).toEqual({
      kind: 'estimate',
      seconds: data.accessible_route!.estimated_duration_seconds,
    });
  });

  it('times a usable shortest route when it shares the traveller’s pace', () => {
    const usable = route(accessibleSegments(), { profile: 'standard' });
    const other = route(accessibleSegments());
    expect(routeTime(usable, 'standard', other).kind).toBe('estimate');
  });

  it('withholds a time estimated at a different pace, rather than compare unlike figures', () => {
    const usable = route(accessibleSegments(), { pace_profile: 'standard' });
    const other = route(accessibleSegments());
    expect(routeTime(usable, 'standard', other)).toEqual({ kind: 'not_comparable' });
  });

  it('prefers “unavailable” over “not comparable”: the route cannot be used at all', () => {
    const shortest = route(shortestSegments(), { pace_profile: 'standard' });
    expect(routeTime(shortest, 'standard', route(accessibleSegments())).kind).toBe('unavailable');
  });
});

describe('the one-line verdict', () => {
  it('reports the detour and its share', () => {
    const data = comparison();
    expect(verdictOf(data)).toEqual({
      kind: 'detour',
      extraM: data.extra_distance_m,
      fraction: data.extra_distance_fraction,
    });
  });

  it('says “same route” only from segment identity', () => {
    const same = route(accessibleSegments());
    expect(
      verdictOf(comparison({ standard_route: same, accessible_route: same, extra_distance_m: 0 })),
    ).toEqual({ kind: 'same_route' });
  });

  it('reports the figure, not identity, when the two disagree', () => {
    const same = route(accessibleSegments());
    expect(
      verdictOf(comparison({ standard_route: same, accessible_route: same, extra_distance_m: 40 }))
        .kind,
    ).toBe('detour');
  });

  it('keeps an equal length on different paths as equal length, not the same route', () => {
    const data = comparison({ extra_distance_m: 0.2, extra_distance_fraction: 0 });
    expect(verdictOf(data)).toEqual({ kind: 'same_length' });
  });

  it('reports a missing difference as missing, not as zero', () => {
    expect(verdictOf(comparison({ extra_distance_m: null })).kind).toBe('difference_not_reported');
  });

  it('carries the API’s reason when no route meets the profile', () => {
    const verdict = verdictOf(
      comparison({ accessible_route: null, accessible_failure: 'No route satisfies the profile.' }),
    );
    expect(verdict).toEqual({
      kind: 'no_accessible_route',
      failure: 'No route satisfies the profile.',
    });
  });

  it('reports a profile route with no shortest route beside it', () => {
    expect(verdictOf(comparison({ standard_route: null })).kind).toBe('no_shortest_route');
  });

  it('reports a shorter profile route as shorter', () => {
    expect(verdictOf(comparison({ extra_distance_m: -12 }))).toEqual({
      kind: 'shorter',
      savedM: 12,
    });
  });
});

describe('reasons are ranked by what decided the route', () => {
  const data = comparison({
    explanations: [
      explanation('avoids_rough_surface', 'recorded', { cost_difference_effective_m: 40 }),
      explanation('avoids_unrecorded_kerbs', 'not_recorded', { cost_difference_effective_m: 90 }),
      explanation('distance_difference', 'profile_rule'),
      explanation('avoids_stairs', 'recorded', { hard_limit: true }),
      explanation('avoids_steep_gradient', 'estimated', { cost_difference_effective_m: 60 }),
    ],
  });

  it('puts a hard limit first, then the largest cost, and leaves profile rules out', () => {
    expect(rankedReasons(data).map((reason) => reason.explanation.code)).toEqual([
      'avoids_stairs',
      'avoids_unrecorded_kerbs',
      'avoids_steep_gradient',
      'avoids_rough_surface',
    ]);
  });

  it('files a statement about an absence under missing information, whatever its topic', () => {
    expect(categoryOf(explanation('avoids_unrecorded_kerbs', 'not_recorded'))).toBe('missing');
    expect(categoryOf(explanation('avoids_raised_kerbs', 'recorded'))).toBe('crossings');
    expect(categoryOf(explanation('fewer_unmarked_crossings', 'recorded'))).toBe('crossings');
  });

  it('files each code under its topic', () => {
    expect(categoryOf(explanation('avoids_steps', 'recorded'))).toBe('stairs');
    expect(categoryOf(explanation('avoids_gradient_above_limit', 'mixed'))).toBe('gradient');
    expect(categoryOf(explanation('avoids_too_steep', 'estimated'))).toBe('gradient');
    expect(categoryOf(explanation('avoids_excluded_surface', 'recorded'))).toBe('surface');
    expect(categoryOf(explanation('avoids_smoothness_excluded', 'recorded'))).toBe('surface');
    expect(categoryOf(explanation('avoids_narrow_paths', 'recorded'))).toBe('width');
    expect(categoryOf(explanation('avoids_width_below_limit', 'recorded'))).toBe('width');
    expect(categoryOf(explanation('avoids_foot_prohibited', 'recorded'))).toBe('access');
    expect(categoryOf(explanation('something_new', 'recorded'))).toBe('other');
  });

  it('groups by topic in the order of each group’s strongest statement', () => {
    const groups = reasonGroups(data);
    expect(groups.map((group) => group.category)).toEqual([
      'stairs',
      'missing',
      'gradient',
      'surface',
    ]);
    expect(groups[0]).toMatchObject({ label: 'Stairs', hardLimit: true });
    expect(groups[1]).toMatchObject({ label: 'Missing information', hardLimit: false });
  });

  it('keeps a statement without evidence, ranked after those with a cost', () => {
    const bare = comparison({
      explanations: [
        { code: 'avoids_narrow_paths', summary: 'Narrow.', basis: 'recorded' },
        explanation('avoids_rough_surface', 'recorded', { cost_difference_effective_m: 5 }),
      ],
    });
    expect(rankedReasons(bare).map((reason) => reason.explanation.code)).toEqual([
      'avoids_rough_surface',
      'avoids_narrow_paths',
    ]);
  });
});

describe('coverage keeps each category’s own denominator', () => {
  it('splits gradient into recorded, estimated and unknown, never merged', () => {
    const [gradient] = coverageRows(comparison().accessible_route!);
    expect(gradient).toMatchObject({ key: 'gradient', denominator: 'route length' });
    expect(gradient?.parts).toEqual([
      { kind: 'recorded', share: 0.19 },
      { kind: 'estimated', share: 0.81 },
      { kind: 'unknown', share: 0 },
    ]);
  });

  it('reads surface, condition and width as the complement of what is missing', () => {
    const rows = coverageRows(
      route(accessibleSegments(), {
        evidence_coverage: { surface: 0.25, smoothness: 1, gradient: 0, width: 0.6, kerb: 0 },
      }),
    );
    const byKey = Object.fromEntries(rows.map((row) => [row.key, row]));
    expect(byKey.surface?.parts).toEqual([
      { kind: 'recorded', share: 0.75 },
      { kind: 'unknown', share: 0.25 },
    ]);
    expect(byKey.smoothness?.parts).toEqual([
      { kind: 'recorded', share: 0 },
      { kind: 'unknown', share: 1 },
    ]);
    expect(byKey.width?.parts?.[1]).toEqual({ kind: 'unknown', share: 0.6 });
  });

  it('sums the step state from the segments by length, unknown kept apart', () => {
    const rows = coverageRows(
      route([
        segment({ length_m: 30, steps: 'unknown' }),
        segment({ length_m: 60, steps: 'no' }),
        segment({ length_m: 10, steps: 'yes', step_count: 4 }),
      ]),
    );
    expect(rows.find((row) => row.key === 'steps')?.parts).toEqual([
      { kind: 'recorded', share: 0.7 },
      { kind: 'unknown', share: 0.3 },
    ]);
    // A route that carries no segments has not reported its steps.
    expect(coverageRows(route([])).find((row) => row.key === 'steps')?.status).toBe('not_reported');
  });

  it('counts kerbs over crossings, with the exact counts', () => {
    const rows = coverageRows(
      route(accessibleSegments(), { crossing_count: 4, unknown_kerb_crossing_count: 3 }),
    );
    const kerb = rows.find((row) => row.key === 'kerb');
    expect(kerb).toMatchObject({
      denominator: 'crossings',
      status: 'measured',
      counts: { recorded: 1, total: 4 },
    });
    expect(kerb?.parts).toEqual([
      { kind: 'recorded', share: 0.25 },
      { kind: 'unknown', share: 0.75 },
    ]);
  });

  it('says a route with no crossings has no kerbs to record, not that every kerb is recorded', () => {
    // The API reports kerb coverage 0.0 here; drawn as a bar it would read as
    // "every kerb recorded" about kerbs that do not exist.
    const kerb = coverageRows(
      route(shortestSegments(), { crossing_count: 0, unknown_kerb_crossing_count: 0 }),
    ).find((row) => row.key === 'kerb');
    expect(kerb).toMatchObject({ status: 'not_applicable', parts: [] });
  });

  it('marks a category the response does not report as not reported, not as complete', () => {
    const rows = coverageRows(route(accessibleSegments(), { evidence_coverage: { surface: 0.1 } }));
    const byKey = Object.fromEntries(rows.map((row) => [row.key, row]));
    expect(byKey.width).toMatchObject({ status: 'not_reported', parts: [] });
    expect(byKey.smoothness).toMatchObject({ status: 'not_reported', parts: [] });
  });

  it('does not invent coverage when the response carries none', () => {
    const bare = route(accessibleSegments());
    delete (bare as { evidence_coverage?: unknown }).evidence_coverage;
    expect(
      coverageRows(bare)
        .filter((row) => ['surface', 'smoothness', 'width'].includes(row.key))
        .every((row) => row.status === 'not_reported'),
    ).toBe(true);
  });

  it('clamps a share the API reports out of range instead of drawing past the bar', () => {
    const rows = coverageRows(
      route(accessibleSegments(), { evidence_coverage: { surface: 1.2, smoothness: -0.1 } }),
    );
    expect(rows.find((row) => row.key === 'surface')?.parts).toEqual([
      { kind: 'recorded', share: 0 },
      { kind: 'unknown', share: 1 },
    ]);
  });
});

describe('shares as people read them', () => {
  it('never rounds a real amount to nothing or a partial amount to everything', () => {
    expect(formatShare(0)).toBe('0%');
    expect(formatShare(0.003)).toBe('<1%');
    expect(formatShare(0.994)).toBe('>99%');
    expect(formatShare(1)).toBe('100%');
    expect(formatShare(0.4649)).toBe('46%');
  });
});

describe('map evidence comes from the response', () => {
  it('marks the ruled-out stairway on the shortest route, where it is', () => {
    const [marker] = evidenceMarkers(comparison(), 'accessible');
    expect(marker).toMatchObject({
      id: 'barrier-steps',
      kind: 'barrier',
      route: 'standard',
      label: '1 stairway',
      basis: 'recorded',
    });
    expect(marker?.position[0]).toBeCloseTo(-80.5379, 6);
    expect(marker?.position[1]).toBeCloseTo(43.47, 6);
  });

  it('marks the steepest climb of the route being looked at, with its source', () => {
    const accessible = evidenceMarkers(comparison(), 'accessible').find(
      (marker) => marker.kind === 'gradient',
    );
    expect(accessible).toMatchObject({
      route: 'accessible',
      label: 'Steepest climb 4.0%',
      basis: 'recorded',
    });
    const standard = evidenceMarkers(comparison(), 'standard').find(
      (marker) => marker.kind === 'gradient',
    );
    expect(standard).toMatchObject({ route: 'standard', basis: 'estimated' });
  });

  it('labels a gradient barrier estimated when only the elevation model saw it', () => {
    const steep = comparison({
      standard_route: route([
        segment({ excluded_by_profile: 'too_steep', derived_grade_percent: 9.5 }),
      ]),
    });
    expect(evidenceMarkers(steep, 'accessible')[0]).toMatchObject({
      label: '1 segment above your gradient limit',
      basis: 'estimated',
    });
  });

  it('labels a gradient barrier mixed when recorded and estimated segments both break it', () => {
    const steep = comparison({
      standard_route: route([
        segment({ excluded_by_profile: 'too_steep', incline_percent: 12 }),
        segment({ excluded_by_profile: 'too_steep', derived_grade_percent: 9.5 }),
      ]),
    });
    expect(evidenceMarkers(steep, 'accessible')[0]?.basis).toBe('mixed');
  });

  it('draws nothing it cannot place, and nothing at all without a response route', () => {
    const noGeometry = comparison({
      standard_route: route([segment({ excluded_by_profile: 'steps', coordinates: [] })]),
      accessible_route: null,
    });
    expect(evidenceMarkers(noGeometry, 'accessible')).toEqual([]);
  });

  it('places a marker on the middle of the segment it names', () => {
    expect(
      segmentMidpoint(
        segment({
          coordinates: [
            [0, 0],
            [1, 1],
            [4, 4],
          ],
        }),
      ),
    ).toEqual([1, 1]);
    expect(
      segmentMidpoint(
        segment({
          coordinates: [
            [0, 0],
            [2, 2],
          ],
        }),
      ),
    ).toEqual([1, 1]);
    expect(segmentMidpoint(segment({ coordinates: [] }))).toBeNull();
  });
});
