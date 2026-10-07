import { VERIFIED_ROUTE } from './verified-route';
import styles from './Landing.module.css';

type Point = readonly [number, number];

/** The drawing box the routes are fitted into, in SVG units. */
export type Box = {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
};

/**
 * Project longitude/latitude into a box, preserving shape.
 *
 * Equirectangular with the longitude scaled by cos(latitude): at the scale of
 * a campus walk that is indistinguishable from a proper projection, and it
 * keeps the drawing honest — east is right, north is up, and distances along
 * both axes share one scale.
 */
export function projector(points: readonly Point[], box: Box): (point: Point) => [number, number] {
  const lats = points.map(([, lat]) => lat);
  const midLat = (Math.min(...lats) + Math.max(...lats)) / 2;
  const kx = Math.cos((midLat * Math.PI) / 180);
  const xs = points.map(([lng]) => lng * kx);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...lats);
  const maxY = Math.max(...lats);
  const scale = Math.min(box.width / (maxX - minX || 1), box.height / (maxY - minY || 1));
  const offsetX = box.x + (box.width - (maxX - minX) * scale) / 2;
  const offsetY = box.y + (box.height - (maxY - minY) * scale) / 2;
  return ([lng, lat]) => [
    Math.round((offsetX + (lng * kx - minX) * scale) * 10) / 10,
    Math.round((offsetY + (maxY - lat) * scale) * 10) / 10,
  ];
}

function path(points: readonly Point[], project: (point: Point) => [number, number]): string {
  return points
    .map((point, index) => {
      const [x, y] = project(point);
      return `${index === 0 ? 'M' : 'L'}${x} ${y}`;
    })
    .join(' ');
}

/**
 * The verified example drawn from its recorded geometry (10:2365): the
 * shortest route dashed, its recorded stairways marked, the wheelchair route
 * solid, A and B named. No basemap is drawn — the faint grid is a backdrop, not
 * streets — so nothing on it can be mistaken for map evidence.
 */
export function RouteVisual({
  box,
  width,
  height,
  compact = false,
}: {
  readonly box: Box;
  readonly width: number;
  readonly height: number;
  readonly compact?: boolean;
}) {
  const { standard, accessible } = VERIFIED_ROUTE;
  const all: readonly Point[] = [...standard.coordinates, ...accessible.coordinates];
  const project = projector(all, box);
  const [ox, oy] = project(accessible.coordinates[0] as Point);
  const [dx, dy] = project(accessible.coordinates[accessible.coordinates.length - 1] as Point);
  const stairPoints = standard.stairs.flat();
  const [sx, sy] = project(
    stairPoints.reduce<[number, number]>(
      ([lng, lat], [a, b]) => [lng + a / stairPoints.length, lat + b / stairPoints.length],
      [0, 0],
    ),
  );
  const detourAt = project(
    accessible.coordinates[Math.floor(accessible.coordinates.length * 0.6)] as Point,
  );

  return (
    <svg
      className={styles.visualSvg}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-labelledby="route-visual-title route-visual-desc"
      preserveAspectRatio="xMidYMid slice"
    >
      <title id="route-visual-title">
        The verified Waterloo example, as the routing API recorded it
      </title>
      <desc id="route-visual-desc">
        The shortest walking route from the Davis Centre library to the Student Life Centre, dashed,
        with its four recorded stairways marked; and the wheelchair route, solid, which avoids them
        and is 66.7 metres longer.
      </desc>
      <defs>
        <pattern id="landing-grid" width="48" height="48" patternUnits="userSpaceOnUse">
          <path d="M48 0H0V48" fill="none" stroke="#131b2e" strokeWidth="1" />
        </pattern>
        <filter id="landing-glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="4" />
        </filter>
      </defs>
      <rect width={width} height={height} fill="#080d1a" />
      <rect width={width} height={height} fill="url(#landing-grid)" />

      <path
        d={path(standard.coordinates, project)}
        fill="none"
        stroke="#ffb4ab"
        strokeOpacity="0.75"
        strokeWidth={compact ? 2.5 : 3}
        strokeDasharray="7 6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {standard.stairs.map((stair, index) => (
        <path
          key={index}
          d={path(stair, project)}
          fill="none"
          stroke="#ff6b5e"
          strokeWidth={compact ? 6 : 8}
          strokeLinecap="round"
        />
      ))}
      <path
        d={path(accessible.coordinates, project)}
        fill="none"
        stroke="#00f090"
        strokeOpacity="0.35"
        strokeWidth={compact ? 8 : 12}
        filter="url(#landing-glow)"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d={path(accessible.coordinates, project)}
        fill="none"
        stroke="#00f090"
        strokeWidth={compact ? 3 : 4}
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Origin (A) and destination (B). */}
      <circle cx={ox} cy={oy} r={compact ? 9 : 14} fill="#7bd0ff" />
      <circle cx={ox} cy={oy} r={compact ? 3.5 : 5} fill="#060e20" />
      <circle cx={dx} cy={dy} r={compact ? 10 : 16} fill="#00f090" />
      <path
        d={`M${dx - 5} ${dy} l3.5 3.5 l7 -7`}
        fill="none"
        stroke="#060e20"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {compact ? null : (
        <>
          <g transform={`translate(${ox - 66} ${oy + 22})`}>
            <rect width="132" height="16" rx="4" fill="#060e20" />
            <text x="8" y="11.5" className={styles.visualLabel}>
              ORIGIN: DC LIBRARY
            </text>
          </g>
          <g transform={`translate(${dx - 76} ${dy + 24})`}>
            <rect width="152" height="16" rx="4" fill="#060e20" />
            <text x="8" y="11.5" className={styles.visualLabel}>
              DEST: STUDENT LIFE CTR.
            </text>
          </g>
          <g transform={`translate(${sx - 46} ${sy - 44})`}>
            <rect width="92" height="20" rx="4" fill="#93000a" />
            <text x="9" y="14" className={styles.visualBarrier}>
              4 STAIRWAYS
            </text>
            <rect x="45" y="20" width="2" height="12" fill="#ffb4ab" />
          </g>
          <g transform={`translate(${detourAt[0] + 18} ${detourAt[1] - 10})`}>
            <rect width="122" height="18" rx="4" fill="#93000a" />
            <text x="9" y="12.5" className={styles.visualBarrier}>
              +66.7 M DETOUR
            </text>
          </g>
        </>
      )}
    </svg>
  );
}
