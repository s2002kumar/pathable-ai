import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  CAMPUS_PATHS,
  STAGE_FRAME,
  bounds,
  centroid,
  midpointAlong,
  pathData,
  sharedPrefix,
  sharedSuffix,
  toStage,
} from './stage-frame';

/** A path from the repository root; the unit tests run from apps/web. */
const repo = (file: string) => path.resolve(process.cwd(), '../..', file);

describe('the stage frame', () => {
  it('puts the origin at zero, east to the right and north up', () => {
    expect(toStage([STAGE_FRAME.longitude, STAGE_FRAME.latitude])).toEqual([0, 0]);
    const [east] = toStage([STAGE_FRAME.longitude + 0.001, STAGE_FRAME.latitude]);
    const [, north] = toStage([STAGE_FRAME.longitude, STAGE_FRAME.latitude + 0.001]);
    expect(east).toBeGreaterThan(0);
    expect(north).toBeLessThan(0);
  });

  it('draws ground distance in metres, one scale on both axes', () => {
    // A thousandth of a degree of latitude is 111.2 m; of longitude at 43.47° N, 80.7 m.
    const [, dy] = toStage([STAGE_FRAME.longitude, STAGE_FRAME.latitude - 0.001]);
    const [dx] = toStage([STAGE_FRAME.longitude + 0.001, STAGE_FRAME.latitude]);
    expect(dy).toBeCloseTo(111.2, 0);
    expect(dx).toBeCloseTo(80.7, 0);
  });

  it('is the frame the generated network backdrop was drawn in', () => {
    // A backdrop drawn in a different frame would put the routes on the wrong
    // paths while still looking plausible. Hold the three copies together.
    const script = readFileSync(repo('scripts/landing-data.mjs'), 'utf8');
    expect(script).toContain(
      `const FRAME = { longitude: ${STAGE_FRAME.longitude}, latitude: ${STAGE_FRAME.latitude}, metresPerDegree: ${STAGE_FRAME.metresPerDegree} };`,
    );
    expect(script).toContain(`const HALF = { x: ${-CAMPUS_PATHS.x}, y: ${-CAMPUS_PATHS.y} };`);

    const svg = readFileSync(repo(`apps/web/public${CAMPUS_PATHS.href}`), 'utf8');
    expect(svg).toContain(
      `viewBox="${CAMPUS_PATHS.x} ${CAMPUS_PATHS.y} ${CAMPUS_PATHS.width} ${CAMPUS_PATHS.height}"`,
    );
    expect(svg).toContain(`Frame: metres from ${STAGE_FRAME.longitude}, ${STAGE_FRAME.latitude}`);
  });

  it('credits OpenStreetMap inside the backdrop file itself', () => {
    const svg = readFileSync(repo(`apps/web/public${CAMPUS_PATHS.href}`), 'utf8');
    expect(svg).toContain('© OpenStreetMap contributors, ODbL 1.0');
    expect(svg).toContain('not a basemap');
  });
});

describe('stage geometry helpers', () => {
  const a = [
    [0, 0],
    [1, 0],
    [2, 0],
    [3, 0],
  ] as const;
  const b = [
    [0, 0],
    [1, 0],
    [1, 1],
    [3, 0],
  ] as const;

  it('counts the coordinates two routes share at each end', () => {
    expect(sharedPrefix(a, b)).toBe(2);
    expect(sharedSuffix(a, b)).toBe(1);
    expect(sharedPrefix(a, [[9, 9]])).toBe(0);
    expect(sharedSuffix(a, a)).toBe(4);
  });

  it('writes a path through the points in order', () => {
    expect(
      pathData([
        [0, 0],
        [10, 5.5],
      ]),
    ).toBe('M0 0 L10 5.5');
  });

  it('finds the halfway point by length, not by vertex', () => {
    // Most of this line's length is in its last piece.
    expect(
      midpointAlong([
        [0, 0],
        [1, 0],
        [11, 0],
      ]),
    ).toEqual([5.5, 0]);
  });

  it('boxes points with a margin and averages them', () => {
    expect(
      bounds(
        [
          [0, 0],
          [10, 4],
        ],
        2,
      ),
    ).toEqual({ x: -2, y: -2, width: 14, height: 8 });
    expect(
      centroid([
        [0, 0],
        [10, 4],
      ]),
    ).toEqual([5, 2]);
  });
});
