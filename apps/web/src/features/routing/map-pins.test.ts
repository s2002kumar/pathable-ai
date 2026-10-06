/**
 * What the map pins. Every pin repeats a statement the panel makes, with the
 * same evidence label; none carries a fact the panel does not, and no more
 * than three are prominent at once.
 */
import { describe, expect, it } from 'vitest';
import type { Route } from '@pathable/contracts';
import { comparison, route, segment, shortestSegments } from '@/test/route-fixtures';
import {
  MAX_PINS,
  barrierPins,
  climbPin,
  comparePins,
  endpointLabels,
  gapCallouts,
  kerbPin,
  phonePins,
} from './map-pins';
import { NO_RULES } from './route-facts';

const ORIGIN = {
  position: { longitude: -80.54, latitude: 43.47 },
  label: 'Davis Centre library',
  source: 'search' as const,
};
const DESTINATION = {
  position: { longitude: -80.534, latitude: 43.47 },
  label: 'Student Life Centre',
  source: 'search' as const,
};

/** A shortest route with one climb the profile rules out, recorded or not. */
function steepShortest(recorded: boolean) {
  return route(
    [
      segment({ edge_identity: 'a', length_m: 50 }),
      segment({
        edge_identity: 'b',
        coordinates: [
          [-80.539, 43.47],
          [-80.538, 43.471],
        ],
        incline_percent: recorded ? 9 : null,
        derived_grade_percent: 7.4,
        excluded_by_profile: 'too_steep',
      }),
    ],
    { profile: 'standard' },
  );
}

describe('what the profile rules out', () => {
  it('pins a ruled-out stairway at its own segment, labelled as recorded', () => {
    const [pin, ...rest] = barrierPins(comparison(), NO_RULES);

    expect(rest).toEqual([]);
    expect(pin).toMatchObject({
      id: 'barrier-steps',
      tone: 'barrier',
      label: '1 recorded stairway',
      tag: 'Recorded · OSM',
      detail: '14 recorded steps · shortest route, ruled out',
    });
    // The stairway's midpoint, not somewhere on the route.
    expect(pin?.position?.[0]).toBeCloseTo(-80.5379, 6);
    expect(pin?.position?.[1]).toBeCloseTo(43.47, 6);
  });

  it('says a stairway with no recorded count is ruled out without inventing one', () => {
    const uncounted = route(
      shortestSegments().map((item) =>
        item.steps === 'yes' ? { ...item, step_count: null } : item,
      ),
      { profile: 'standard' },
    );
    const [pin] = barrierPins(comparison({ standard_route: uncounted }), NO_RULES);

    expect(pin?.detail).toBe('Shortest route · ruled out by your profile');
  });

  it('labels a ruled-out climb by the gradient routing used, recorded or derived', () => {
    const recorded = barrierPins(comparison({ standard_route: steepShortest(true) }), {
      ...NO_RULES,
      uphillLimit: 5,
    });
    expect(recorded[0]).toMatchObject({
      label: '9.0% climb on the shortest route',
      tag: 'Recorded · OSM',
      detail: 'Exceeds your 5.0% uphill limit',
    });

    const derived = barrierPins(comparison({ standard_route: steepShortest(false) }), NO_RULES);
    expect(derived[0]).toMatchObject({
      label: '7.4% climb on the shortest route',
      tag: 'Derived · HRDEM',
      detail: '1 segment above your limit',
    });
  });

  it('pins nothing for a route the profile can use, or no route at all', () => {
    const priced = route(
      shortestSegments().map((item) => ({ ...item, excluded_by_profile: null })),
      { profile: 'standard' },
    );
    expect(barrierPins(comparison({ standard_route: priced }), NO_RULES)).toEqual([]);
    expect(barrierPins(comparison({ standard_route: null }), NO_RULES)).toEqual([]);
  });
});

describe('the climb on the route being looked at', () => {
  it('says whether the steepest climb was recorded or estimated', () => {
    const pair = comparison();

    expect(climbPin(pair, 'accessible')).toMatchObject({
      id: 'gradient-accessible',
      label: 'Max grade 4.0%',
      tag: 'Recorded · OSM',
      detail: 'Steepest climb on the wheelchair route',
    });
    expect(climbPin(pair, 'standard')).toMatchObject({
      label: 'Max estimated grade 1.2%',
      tag: 'Derived · HRDEM',
      detail: 'Steepest climb on the shortest route',
    });
  });

  it('pins no climb that the route does not report', () => {
    const flat = comparison({
      accessible_route: {
        ...(comparison().accessible_route as Route),
        gradient: {
          steepest_uphill: null,
          steepest_downhill: null,
          recorded_fraction: 0,
          estimated_fraction: 0,
          unknown_fraction: 1,
        },
      },
    });
    expect(climbPin(flat, 'accessible')).toBeNull();
  });
});

describe('crossings nobody recorded a kerb for', () => {
  it('pins the first, and counts them all', () => {
    const gaps = route([
      segment({ edge_identity: 'x', is_crossing: true, kerb: 'unknown' }),
      segment({ edge_identity: 'y', is_crossing: true, kerb: 'unknown' }),
    ]);

    expect(kerbPin(gaps, 'kerb-accessible')).toMatchObject({
      tone: 'unknown',
      label: '2 crossings have no kerb record',
      tag: 'Not recorded',
    });
  });

  it('pins nothing where every kerb is recorded', () => {
    expect(kerbPin(comparison().accessible_route as Route, 'k')).toBeNull();
    expect(kerbPin(null, 'k')).toBeNull();
  });
});

describe('the comparison’s pins', () => {
  it('puts the hard limit first and never shows more than three', () => {
    const crowded = comparison({
      accessible_route: route(
        [
          segment({ edge_identity: 'p', is_crossing: true, kerb: 'unknown' }),
          segment({ edge_identity: 'q' }),
        ],
        {},
      ),
    });
    const pins = comparePins(crowded, 'accessible', NO_RULES, 'Wheelchair');

    expect(pins.length).toBeLessThanOrEqual(MAX_PINS);
    expect(pins.map((pin) => pin.id)).toEqual([
      'barrier-steps',
      'gradient-accessible',
      'kerb-accessible',
    ]);
  });
});

describe('the phone’s annotations', () => {
  it('badges what is ruled out and the shortest route’s climb, then names both ends', () => {
    const markers = phonePins(comparison(), { origin: ORIGIN, destination: DESTINATION });

    expect(markers.map((marker) => marker.id)).toEqual([
      'badge-steps',
      'badge-climb',
      'endpoint-origin',
      'endpoint-destination',
    ]);
    expect(markers[0]).toMatchObject({ label: '1 stairway', tone: 'barrier' });
    expect(markers[1]).toMatchObject({ label: '1.2% climb' });
  });

  it('names only the ends that exist', () => {
    expect(
      phonePins(comparison({ standard_route: null }), { origin: ORIGIN, destination: null }),
    ).toEqual([
      expect.objectContaining({
        id: 'endpoint-origin',
        label: 'Davis Centre library',
        tag: 'Origin',
      }),
    ]);
    expect(endpointLabels({ origin: null, destination: DESTINATION })).toEqual([
      expect.objectContaining({ id: 'endpoint-destination', tag: 'Destination' }),
    ]);
  });
});

describe('the evidence view’s callouts', () => {
  it('calls out the first unrecorded kerb and the longest unrecorded surface', () => {
    const gappy = route([
      segment({ edge_identity: 'k', is_crossing: true, kerb: 'unknown' }),
      segment({ edge_identity: 's1', surface_class: 'unknown', length_m: 20 }),
      segment({
        edge_identity: 's2',
        surface_class: 'unknown',
        length_m: 90,
        coordinates: [
          [-80.53, 43.46],
          [-80.52, 43.46],
        ],
      }),
    ]);
    const callouts = gapCallouts(gappy);

    expect(callouts.map((callout) => callout.id)).toEqual(['gap-kerb', 'gap-surface']);
    expect(callouts[0]).toMatchObject({ label: 'Unrecorded kerb state', tone: 'unknown' });
    expect(callouts[1]?.position).toEqual([-80.525, 43.46]);
  });

  it('calls out nothing on a route whose record has no gaps', () => {
    expect(gapCallouts(route([segment()]))).toEqual([]);
    expect(gapCallouts(null)).toEqual([]);
  });
});
