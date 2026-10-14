import { describe, expect, it } from 'vitest';
import {
  FIGURES,
  ROUTE,
  compass,
  journeyGeometry,
  lengthShare,
  segmentEvidence,
  sharedLengths,
  stairGroups,
  type RouteKey,
} from './journey';

const ROUTES: readonly RouteKey[] = ['standard', 'accessible'];

describe('the recorded journey', () => {
  it('was produced by no model', () => {
    expect(ROUTE.mlPredictionsUsed).toBe(false);
  });

  it.each(ROUTES)('%s: its segments add up to the route the API measured', (key) => {
    const total = segmentEvidence(key).reduce((sum, segment) => sum + segment.lengthM, 0);
    // Segment lengths are rounded to 0.1 m each in the response.
    expect(total).toBeCloseTo(ROUTE[key].distanceM, 0);
    expect(ROUTE[key].segments).toHaveLength(ROUTE[key].coordinates.length - 1);
  });

  it.each(ROUTES)('%s: reading each segment gives back the API’s own coverage figures', (key) => {
    // The page draws per-segment evidence and quotes the API's per-route
    // shares beside it. If the per-segment reading drifted from the API's
    // definition — counting a recorded value as missing, or the reverse —
    // the picture and the numbers would disagree. Hold them together.
    const segments = segmentEvidence(key);
    const { evidenceCoverage, gradient } = ROUTE[key];
    const share = (predicate: Parameters<typeof lengthShare>[1]) =>
      lengthShare(segments, predicate);

    expect(share((s) => s.surface === 'missing')).toBeCloseTo(evidenceCoverage.surface, 2);
    expect(share((s) => s.width === 'missing')).toBeCloseTo(evidenceCoverage.width, 2);
    expect(share((s) => s.smoothness === 'missing')).toBeCloseTo(evidenceCoverage.smoothness, 2);
    expect(share((s) => s.grade === 'derived')).toBeCloseTo(gradient.estimatedFraction, 2);
    expect(share((s) => s.grade === 'recorded')).toBeCloseTo(gradient.recordedFraction, 2);
    expect(share((s) => s.grade === 'missing')).toBeCloseTo(gradient.unknownFraction, 2);
  });

  it('never reads a missing gradient as flat', () => {
    // unknown ≠ false: a segment with no gradient has no magnitude at all,
    // rather than 0 %, which would draw it as level ground.
    for (const key of ROUTES) {
      for (const segment of segmentEvidence(key)) {
        if (segment.grade === 'missing') expect(segment.gradePercent).toBeNull();
        else expect(segment.gradePercent).not.toBeNull();
      }
    }
  });

  it('marks exactly the stairways the API counted, and none on the profile route', () => {
    const stairs = segmentEvidence('standard').filter((segment) => segment.stairs);
    expect(stairs).toHaveLength(ROUTE.standard.stairways);
    expect(segmentEvidence('accessible').some((segment) => segment.stairs)).toBe(false);
  });

  it('groups neighbouring stairways without losing a count or inventing one', () => {
    const groups = stairGroups();
    expect(groups.reduce((sum, group) => sum + group.stairways, 0)).toBe(ROUTE.standard.stairways);
    expect(groups.reduce((sum, group) => sum + (group.steps ?? 0), 0)).toBe(
      ROUTE.standard.recordedSteps,
    );
    // A group with no recorded count says so, rather than showing zero steps.
    const uncounted = groups.filter((group) => group.steps === null);
    expect(uncounted.reduce((sum, group) => sum + group.stairways, 0)).toBe(
      ROUTE.standard.stairwaysWithoutStepCount,
    );
  });
});

describe('the journey as the stage draws it', () => {
  const g = journeyGeometry();

  it('splits where the routes part and joins where they meet again', () => {
    const { startM, endM } = sharedLengths();
    expect(startM).toBeGreaterThan(0);
    expect(endM).toBeGreaterThan(0);
    expect(startM + endM).toBeLessThan(ROUTE.standard.distanceM);
    expect(g.sharedStart.at(-1)).toEqual(g.fork);
    expect(g.sharedEnd[0]).toEqual(g.rejoin);
    expect(g.sharedStart[0]).toEqual(g.origin);
    expect(g.sharedEnd.at(-1)).toEqual(g.destination);
  });

  it('labels the stairways on the side away from the detour', () => {
    // A stairway label on top of the other route would make the picture lie
    // about which line it belongs to.
    const away = {
      n: [0, -1],
      ne: [1, -1],
      e: [1, 0],
      se: [1, 1],
      s: [0, 1],
      sw: [-1, 1],
      w: [-1, 0],
      nw: [-1, -1],
    }[g.stairLabelSide] as [number, number];
    const detour = [g.detourAt[0] - g.stairsAt[0], g.detourAt[1] - g.stairsAt[1]];
    expect(away[0] * (detour[0] ?? 0) + away[1] * (detour[1] ?? 0)).toBeLessThan(0);
  });

  it('frames the whole journey inside its drawing box', () => {
    const { x, y, width, height } = g.viewBox;
    for (const [px, py] of [...g.standard, ...g.accessible]) {
      expect(px).toBeGreaterThan(x);
      expect(px).toBeLessThan(x + width);
      expect(py).toBeGreaterThan(y);
      expect(py).toBeLessThan(y + height);
    }
  });

  it('draws one coloured piece per profile-route segment', () => {
    expect(g.accessibleSegments).toHaveLength(ROUTE.accessible.segments.length);
  });
});

describe('wording', () => {
  it('quotes the figures the claims ledger quotes for this journey', () => {
    // Ledger 3.1: 287.4 m with 4 stairways against 354.1 m, 66.67 m and 23% longer.
    expect(FIGURES.standardDistance).toBe('287.4 m');
    expect(FIGURES.accessibleDistance).toBe('354.1 m');
    expect(FIGURES.extra).toBe('66.7 m');
    expect(FIGURES.extraPercent).toBe('23%');
    expect(FIGURES.datasetShort).toBe('51e75f78');
  });

  it('turns a vector into the nearest compass point', () => {
    expect(compass(1, 0)).toBe('e');
    expect(compass(0, -1)).toBe('n');
    expect(compass(-1, -1)).toBe('nw');
    expect(compass(-1, 0)).toBe('w');
    expect(compass(1, 1)).toBe('se');
    expect(compass(-0.2, 1)).toBe('s');
  });
});
