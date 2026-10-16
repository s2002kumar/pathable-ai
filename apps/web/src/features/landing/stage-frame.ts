/**
 * The landing stage's drawing frame: metres from a fixed origin on campus,
 * x east and y south, so SVG coordinates are ground distances.
 *
 * Equirectangular with the longitude scaled at the origin's latitude. Over a
 * kilometre that is indistinguishable from a proper projection, and it keeps
 * the drawing honest: east is right, north is up, one scale on both axes.
 *
 * The same constants are in `scripts/landing-data.mjs`, which draws the
 * pedestrian-network backdrop in this frame; `stage-frame.test.ts` reads the
 * generated file and fails if the two ever disagree, because a backdrop
 * shifted by a few metres would put a route on the wrong path.
 */
export const STAGE_FRAME = {
  longitude: -80.5435,
  latitude: 43.4721,
  /** Metres per degree of latitude on a sphere of radius 6,371,008.8 m. */
  metresPerDegree: 111195.08,
} as const;

/** The generated backdrop and the extent it covers, in frame metres. */
export const CAMPUS_PATHS = {
  href: '/landing/campus-paths.svg',
  x: -340,
  y: -240,
  width: 680,
  height: 480,
} as const;

export type LngLat = readonly [number, number];
export type StagePoint = readonly [number, number];

const COS_LAT = Math.cos((STAGE_FRAME.latitude * Math.PI) / 180);

/** A longitude/latitude pair in frame metres, to the nearest 10 cm. */
export function toStage([longitude, latitude]: LngLat): StagePoint {
  const x = (longitude - STAGE_FRAME.longitude) * COS_LAT * STAGE_FRAME.metresPerDegree;
  const y = (STAGE_FRAME.latitude - latitude) * STAGE_FRAME.metresPerDegree;
  return [Math.round(x * 10) / 10, Math.round(y * 10) / 10];
}

/** An SVG path through the points, in order. */
export function pathData(points: readonly StagePoint[]): string {
  return points.map(([x, y], index) => `${index === 0 ? 'M' : 'L'}${x} ${y}`).join(' ');
}

function samePoint(a: LngLat | undefined, b: LngLat | undefined): boolean {
  return a !== undefined && b !== undefined && a[0] === b[0] && a[1] === b[1];
}

/** How many leading coordinates two routes share. */
export function sharedPrefix(a: readonly LngLat[], b: readonly LngLat[]): number {
  let count = 0;
  while (count < a.length && count < b.length && samePoint(a[count], b[count])) count += 1;
  return count;
}

/** How many trailing coordinates two routes share. */
export function sharedSuffix(a: readonly LngLat[], b: readonly LngLat[]): number {
  let count = 0;
  while (
    count < a.length &&
    count < b.length &&
    samePoint(a[a.length - 1 - count], b[b.length - 1 - count])
  ) {
    count += 1;
  }
  return count;
}

export type Box = {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
};

/** The box around the points, grown by a margin on every side. */
export function bounds(points: readonly StagePoint[], margin: number): Box {
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  const minX = Math.min(...xs) - margin;
  const minY = Math.min(...ys) - margin;
  return {
    x: Math.floor(minX),
    y: Math.floor(minY),
    width: Math.ceil(Math.max(...xs) + margin - minX),
    height: Math.ceil(Math.max(...ys) + margin - minY),
  };
}

/** The point halfway along a polyline, by length rather than by vertex. */
export function midpointAlong(points: readonly StagePoint[]): StagePoint {
  const lengths = points.slice(1).map(([x, y], index) => {
    const [px, py] = points[index] as StagePoint;
    return Math.hypot(x - px, y - py);
  });
  let remaining = lengths.reduce((sum, length) => sum + length, 0) / 2;
  for (let index = 0; index < lengths.length; index += 1) {
    const length = lengths[index] as number;
    const [ax, ay] = points[index] as StagePoint;
    const [bx, by] = points[index + 1] as StagePoint;
    if (remaining <= length && length > 0) {
      const t = remaining / length;
      return [
        Math.round((ax + (bx - ax) * t) * 10) / 10,
        Math.round((ay + (by - ay) * t) * 10) / 10,
      ];
    }
    remaining -= length;
  }
  return points[points.length - 1] ?? [0, 0];
}

/** The average of some points. */
export function centroid(points: readonly StagePoint[]): StagePoint {
  const n = points.length || 1;
  const [sx, sy] = points.reduce<[number, number]>(([ax, ay], [x, y]) => [ax + x, ay + y], [0, 0]);
  return [Math.round((sx / n) * 10) / 10, Math.round((sy / n) * 10) / 10];
}
