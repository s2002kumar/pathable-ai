import {
  bounds,
  centroid,
  midpointAlong,
  sharedPrefix,
  sharedSuffix,
  toStage,
  type Box,
  type LngLat,
  type StagePoint,
} from './stage-frame';
import { VERIFIED_ROUTE } from './verified-route';

/**
 * Everything the landing page draws or says about the verified journey,
 * derived from the one recorded API response and nothing else.
 *
 * The page never states a figure this module did not compute from
 * `VERIFIED_ROUTE`, and the tests hold its per-segment reading against the
 * API's own coverage figures, so the drawing and the numbers beside it cannot
 * drift apart.
 */

export type RouteKey = 'standard' | 'accessible';

/** One segment as the record keeps it. */
export type RecordedSegment = {
  readonly lengthM: number;
  readonly highway: string | null;
  readonly steps: 'yes' | 'no' | 'unknown';
  readonly stepCount: number | null;
  readonly surface: string | null;
  readonly smoothnessClass: string;
  readonly widthM: number | null;
  readonly inclinePercent: number | null;
  readonly derivedGradePercent: number | null;
  readonly excludedByProfile: string | null;
};

/** Where each kind of evidence stands on one segment. */
export type SegmentEvidence = {
  readonly lengthM: number;
  /** Metres from the start of the route to the start of this segment. */
  readonly startM: number;
  /** A stairway recorded in OpenStreetMap. */
  readonly stairs: boolean;
  readonly surface: 'recorded' | 'missing';
  /** Recorded in OSM, estimated from the elevation model, or neither. */
  readonly grade: 'recorded' | 'derived' | 'missing';
  /** Size of the gradient in percent, whichever source it came from. */
  readonly gradePercent: number | null;
  readonly width: 'recorded' | 'missing';
  readonly smoothness: 'recorded' | 'missing';
};

export const ROUTE = VERIFIED_ROUTE;

const SEGMENTS: Record<RouteKey, readonly RecordedSegment[]> = {
  standard: VERIFIED_ROUTE.standard.segments,
  accessible: VERIFIED_ROUTE.accessible.segments,
};

const COORDINATES: Record<RouteKey, readonly LngLat[]> = {
  standard: VERIFIED_ROUTE.standard.coordinates,
  accessible: VERIFIED_ROUTE.accessible.coordinates,
};

export function segmentEvidence(route: RouteKey): readonly SegmentEvidence[] {
  let startM = 0;
  return SEGMENTS[route].map((segment) => {
    const grade =
      segment.inclinePercent !== null
        ? 'recorded'
        : segment.derivedGradePercent !== null
          ? 'derived'
          : 'missing';
    const evidence: SegmentEvidence = {
      lengthM: segment.lengthM,
      startM: Math.round(startM * 10) / 10,
      stairs: segment.steps === 'yes',
      surface: segment.surface === null ? 'missing' : 'recorded',
      grade,
      gradePercent:
        segment.inclinePercent !== null
          ? Math.abs(segment.inclinePercent)
          : segment.derivedGradePercent !== null
            ? Math.abs(segment.derivedGradePercent)
            : null,
      width: segment.widthM === null ? 'missing' : 'recorded',
      smoothness: segment.smoothnessClass === 'unknown' ? 'missing' : 'recorded',
    };
    startM += segment.lengthM;
    return evidence;
  });
}

/** Share of a route's segment length where the predicate holds. */
export function lengthShare(
  segments: readonly SegmentEvidence[],
  predicate: (segment: SegmentEvidence) => boolean,
): number {
  const total = segments.reduce((sum, segment) => sum + segment.lengthM, 0);
  const matching = segments.filter(predicate).reduce((sum, segment) => sum + segment.lengthM, 0);
  return total === 0 ? 0 : matching / total;
}

export type StairGroup = {
  /** Midpoint of the group, in stage metres. */
  readonly at: StagePoint;
  /** Stairways in the group: adjacent stair segments are one place on the map. */
  readonly stairways: number;
  /** Recorded steps, or null when no stairway in the group has a count. */
  readonly steps: number | null;
};

/** The shortest route's recorded stairways, with neighbours grouped. */
export function stairGroups(): readonly StairGroup[] {
  const segments = SEGMENTS.standard;
  const points = COORDINATES.standard;
  const groups: { indexes: number[] }[] = [];
  segments.forEach((segment, index) => {
    if (segment.steps !== 'yes') return;
    const last = groups[groups.length - 1];
    if (last && last.indexes[last.indexes.length - 1] === index - 1) last.indexes.push(index);
    else groups.push({ indexes: [index] });
  });
  return groups.map(({ indexes }) => {
    const ends = indexes.flatMap((index) => [
      toStage(points[index] as LngLat),
      toStage(points[index + 1] as LngLat),
    ]);
    const counts = indexes
      .map((index) => (segments[index] as RecordedSegment).stepCount)
      .filter((count): count is number => count !== null);
    return {
      at: centroid(ends),
      stairways: indexes.length,
      steps: counts.length === 0 ? null : counts.reduce((sum, count) => sum + count, 0),
    };
  });
}

/** The pieces of the journey the stage draws, in stage metres. */
export type JourneyGeometry = {
  readonly standard: readonly StagePoint[];
  readonly accessible: readonly StagePoint[];
  /** Each route's segments as separate two-point pieces, for per-segment colour. */
  readonly accessibleSegments: readonly (readonly [StagePoint, StagePoint])[];
  /** The path both routes take, before they part and after they meet again. */
  readonly sharedStart: readonly StagePoint[];
  readonly sharedEnd: readonly StagePoint[];
  readonly fork: StagePoint;
  readonly rejoin: StagePoint;
  /** Midpoint of the wheelchair route's own section, where the detour is. */
  readonly detourAt: StagePoint;
  /** Centre of the stretch where the two routes differ. */
  readonly divergenceAt: StagePoint;
  readonly stairs: readonly StairGroup[];
  readonly stairsAt: StagePoint;
  /**
   * Which side of the shortest route to label its stairways on: across the
   * journey's axis from the wheelchair route's detour, so a label never sits
   * on the other line.
   */
  readonly stairLabelSide: Anchor;
  /** Midpoint of the longest run of wheelchair-route path with no recorded surface. */
  readonly surfaceGapAt: StagePoint;
  readonly origin: StagePoint;
  readonly destination: StagePoint;
  /** The drawing box: the journey with room around it for labels. */
  readonly viewBox: Box;
};

export type Anchor = 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w' | 'nw';

const COMPASS: readonly Anchor[] = ['w', 'nw', 'n', 'ne', 'e', 'se', 's', 'sw'];

/** The nearest of eight compass directions to a vector in stage space (y down). */
export function compass(dx: number, dy: number): Anchor {
  const turn = Math.round((Math.atan2(dy, dx) + Math.PI) / (Math.PI / 4)) % 8;
  return COMPASS[turn] as Anchor;
}

export function journeyGeometry(): JourneyGeometry {
  const standardLL = COORDINATES.standard;
  const accessibleLL = COORDINATES.accessible;
  const standard = standardLL.map(toStage);
  const accessible = accessibleLL.map(toStage);
  const prefix = sharedPrefix(standardLL, accessibleLL);
  const suffix = sharedSuffix(standardLL, accessibleLL);
  const ownStart = prefix - 1;
  const ownEnd = accessible.length - suffix;
  const stairs = stairGroups();

  // Longest run of consecutive wheelchair-route segments with no surface.
  const evidence = segmentEvidence('accessible');
  let best = { start: 0, end: 0, length: 0 };
  let run = { start: 0, length: 0 };
  evidence.forEach((segment, index) => {
    if (segment.surface === 'missing') {
      if (run.length === 0) run = { start: index, length: 0 };
      run.length += segment.lengthM;
      if (run.length > best.length) best = { start: run.start, end: index + 1, length: run.length };
    } else {
      run = { start: index, length: 0 };
    }
  });

  const ownAccessible = accessible.slice(ownStart, ownEnd + 1);
  const ownStandard = standard.slice(ownStart, standard.length - suffix + 1);
  const divergence = bounds([...ownAccessible, ...ownStandard], 0);
  const origin = accessible[0] as StagePoint;
  const destination = accessible[accessible.length - 1] as StagePoint;
  // The journey's axis, and the normal to it that points away from the detour.
  const [ax, ay] = [destination[0] - origin[0], destination[1] - origin[1]];
  const [mx, my] = centroid(ownAccessible);
  const side = ax * (my - origin[1]) - ay * (mx - origin[0]);
  const [nx, ny] = side > 0 ? [ay, -ax] : [-ay, ax];

  return {
    standard,
    accessible,
    accessibleSegments: accessible
      .slice(1)
      .map((point, index) => [accessible[index] as StagePoint, point] as const),
    sharedStart: accessible.slice(0, prefix),
    sharedEnd: accessible.slice(ownEnd),
    fork: accessible[ownStart] as StagePoint,
    rejoin: accessible[ownEnd] as StagePoint,
    detourAt: midpointAlong(ownAccessible),
    divergenceAt: [divergence.x + divergence.width / 2, divergence.y + divergence.height / 2],
    stairs,
    stairsAt: centroid(stairs.map((group) => group.at)),
    stairLabelSide: compass(nx, ny),
    surfaceGapAt: midpointAlong(accessible.slice(best.start, best.end + 1)),
    origin,
    destination,
    viewBox: bounds([...standard, ...accessible], 48),
  };
}

/** Metres the two routes share at the start and at the end. */
export function sharedLengths(): { readonly startM: number; readonly endM: number } {
  const prefix = sharedPrefix(COORDINATES.standard, COORDINATES.accessible);
  const suffix = sharedSuffix(COORDINATES.standard, COORDINATES.accessible);
  const segments = SEGMENTS.accessible;
  const sum = (list: readonly RecordedSegment[]) =>
    Math.round(list.reduce((total, segment) => total + segment.lengthM, 0) * 10) / 10;
  return {
    startM: sum(segments.slice(0, prefix - 1)),
    endM: sum(segments.slice(segments.length - (suffix - 1))),
  };
}

// ---------------------------------------------------------------------------
// Wording
// ---------------------------------------------------------------------------

/** A distance as the page prints it: one decimal, a thin space, "m". */
export function metres(value: number, digits = 1): string {
  return `${value.toFixed(digits)} m`;
}

/** A fraction as a whole percentage. */
export function percent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

/** The figures every section quotes, computed once. */
export const FIGURES = {
  extra: metres(ROUTE.extraDistanceM),
  extraPercent: percent(ROUTE.extraDistanceFraction),
  standardDistance: metres(ROUTE.standard.distanceM),
  accessibleDistance: metres(ROUTE.accessible.distanceM),
  surfaceMissing: {
    standard: metres(ROUTE.standard.evidenceCoverage.surface * ROUTE.standard.distanceM, 0),
    accessible: metres(ROUTE.accessible.evidenceCoverage.surface * ROUTE.accessible.distanceM, 0),
  },
  datasetShort: ROUTE.datasetChecksum.slice(0, 8),
} as const;
