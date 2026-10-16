import type { CSSProperties, ReactNode } from 'react';
import { CAMPUS_PATHS, pathData, type StagePoint } from './stage-frame';
import { FIGURES, ROUTE, journeyGeometry, segmentEvidence, type Anchor } from './journey';
import styles from './Landing.module.css';

/**
 * Every story step the stage can show. `overview` is the server-rendered
 * default, so with no script, or before it runs, the stage shows the whole
 * answer at once.
 */
export const STAGE_STEPS = ['overview', 'together', 'stairs', 'rule', 'unknown'] as const;
export type StageStep = (typeof STAGE_STEPS)[number];

type Label = {
  readonly at: StagePoint;
  /** An origin or destination name, which a small stage can drop. */
  readonly endpoint?: boolean;
  readonly text: ReactNode;
  /** The steps this label is shown in. */
  readonly show: readonly StageStep[];
  readonly anchor: Anchor;
  readonly tone?: 'barrier' | 'good' | 'unknown' | 'neutral';
};

function vars(values: Record<string, string | number>): CSSProperties {
  return values as CSSProperties;
}

function at([x, y]: StagePoint): CSSProperties {
  return vars({ '--x': x, '--y': y });
}

/**
 * The verified journey drawn over the real pedestrian network around it.
 *
 * Geometry is the recorded response's, in ground metres; the faint lines
 * behind it are the routing graph PathAble ingested from OpenStreetMap (see
 * `scripts/landing-data.mjs`), not a basemap and not decoration, so nothing
 * here is placed by eye. Labels are HTML pinned to ground coordinates by CSS
 * (`--x`/`--y` against the drawing's own scale), so they stay crisp and on
 * their point at any size.
 *
 * The parent sets `data-step`; the stage only reacts. Everything it shows is
 * also said in text beside it, so it is one labelled image to assistive
 * technology rather than a second, partial copy of the story.
 */
export function RouteStage() {
  const g = journeyGeometry();
  const vb = g.viewBox;
  const surface = segmentEvidence('accessible');
  const standardD = pathData(g.standard);
  const accessibleD = pathData(g.accessible);
  const centre: StagePoint = [vb.x + vb.width / 2, vb.y + vb.height / 2];
  const viewBox = `${vb.x} ${vb.y} ${vb.width} ${vb.height}`;
  // Masks cover the drawing and a margin for the widest stroke, not the
  // whole backdrop: a mask is an offscreen surface the size of its region.
  const maskBox = { x: vb.x - 24, y: vb.y - 24, width: vb.width + 48, height: vb.height + 48 };

  // Endpoint names stay off the steps whose camera move would crop them.
  const labels: readonly Label[] = [
    {
      at: g.origin,
      text: 'Davis Centre library',
      show: ['overview', 'together', 'unknown'],
      anchor: 'nw',
      tone: 'neutral',
      endpoint: true,
    },
    {
      at: g.destination,
      text: 'Student Life Centre',
      show: ['overview', 'together', 'unknown'],
      anchor: 'se',
      tone: 'neutral',
      endpoint: true,
    },
    { at: g.fork, text: 'Routes part', show: ['together'], anchor: 'e' },
    { at: g.rejoin, text: '…and meet again', show: ['together'], anchor: 'n' },
    {
      at: g.stairsAt,
      text: `${ROUTE.standard.stairways} recorded stairways`,
      show: ['overview'],
      anchor: g.stairLabelSide,
      tone: 'barrier',
    },
    ...g.stairs.map(
      (group): Label => ({
        at: group.at,
        text:
          group.steps === null
            ? `${group.stairways} stairways · no step count`
            : `${group.stairways === 1 ? 'Stairway' : `${group.stairways} stairways`} · ${group.steps} steps`,
        show: ['stairs'],
        anchor: g.stairLabelSide,
        tone: 'barrier',
      }),
    ),
    {
      at: g.stairsAt,
      text: 'Ruled out by the wheelchair profile',
      show: ['rule'],
      anchor: 'n',
      tone: 'barrier',
    },
    {
      at: g.detourAt,
      text: `+${FIGURES.extra} · ${FIGURES.extraPercent} longer`,
      show: ['overview', 'rule'],
      anchor: 's',
      tone: 'good',
    },
    {
      at: g.surfaceGapAt,
      text: 'No surface recorded',
      show: ['unknown'],
      anchor: 'w',
      tone: 'unknown',
    },
  ];

  const focus = {
    together: { point: centre, zoom: 1 },
    stairs: { point: g.stairsAt, zoom: 1.18 },
    rule: { point: g.divergenceAt, zoom: 1.06 },
    unknown: { point: centre, zoom: 1.04 },
  };

  return (
    <div
      className={styles.stage}
      data-testid="hero-visual"
      role="img"
      aria-label={
        `Drawing of the verified journey over the campus path network. The shortest route, ` +
        `dashed, takes ${ROUTE.standard.stairways} recorded stairways; the wheelchair route, ` +
        `solid, goes around them and is ${FIGURES.extra} longer.`
      }
      style={vars({
        '--vb-x': vb.x,
        '--vb-y': vb.y,
        '--vb-w': vb.width,
        '--vb-h': vb.height,
        '--cx': centre[0],
        '--cy': centre[1],
        '--f-together-x': focus.together.point[0],
        '--f-together-y': focus.together.point[1],
        '--z-together': focus.together.zoom,
        '--f-stairs-x': focus.stairs.point[0],
        '--f-stairs-y': focus.stairs.point[1],
        '--z-stairs': focus.stairs.zoom,
        '--f-rule-x': focus.rule.point[0],
        '--f-rule-y': focus.rule.point[1],
        '--z-rule': focus.rule.zoom,
        '--f-unknown-x': focus.unknown.point[0],
        '--f-unknown-y': focus.unknown.point[1],
        '--z-unknown': focus.unknown.zoom,
      })}
    >
      <div className={styles.stageTilt}>
        <div className={styles.stageCamera}>
          {/* The backdrop is its own layer, so drawing the routes never
              repaints two thousand segments of network. */}
          <svg
            className={styles.stageBackdrop}
            viewBox={viewBox}
            preserveAspectRatio="xMidYMid meet"
            aria-hidden="true"
            focusable="false"
          >
            <defs>
              {/* Light falls off away from the journey, over the backdrop only. */}
              <radialGradient
                id="pa-vignette"
                gradientUnits="userSpaceOnUse"
                cx={centre[0]}
                cy={centre[1]}
                r={Math.max(vb.width, vb.height) * 0.95}
              >
                <stop offset="0.45" stopColor="#050a17" stopOpacity="0" />
                <stop offset="1" stopColor="#050a17" stopOpacity="0.92" />
              </radialGradient>
            </defs>
            <image
              className={styles.network}
              href={CAMPUS_PATHS.href}
              x={CAMPUS_PATHS.x}
              y={CAMPUS_PATHS.y}
              width={CAMPUS_PATHS.width}
              height={CAMPUS_PATHS.height}
            />
            <rect
              x={CAMPUS_PATHS.x}
              y={CAMPUS_PATHS.y}
              width={CAMPUS_PATHS.width}
              height={CAMPUS_PATHS.height}
              fill="url(#pa-vignette)"
            />
          </svg>

          <svg
            className={styles.stageSvg}
            viewBox={viewBox}
            preserveAspectRatio="xMidYMid meet"
            aria-hidden="true"
            focusable="false"
          >
            <defs>
              {/* Each route once; every line below is a <use> of it. */}
              <path id="pa-route-standard" d={standardD} vectorEffect="non-scaling-stroke" />
              <path id="pa-route-accessible" d={accessibleD} vectorEffect="non-scaling-stroke" />
              {(
                [
                  ['pa-draw-standard', standardD, styles.drawStandard],
                  ['pa-draw-accessible', accessibleD, styles.drawAccessible],
                  ['pa-redraw-accessible', accessibleD, styles.redrawAccessible],
                ] as const
              ).map(([id, d, className]) => (
                <mask
                  key={id}
                  id={id}
                  maskUnits="userSpaceOnUse"
                  x={maskBox.x}
                  y={maskBox.y}
                  width={maskBox.width}
                  height={maskBox.height}
                >
                  <path d={d} className={className} pathLength={1} />
                </mask>
              ))}
            </defs>

            <g className={styles.standardLayer} mask="url(#pa-draw-standard)">
              <use href="#pa-route-standard" className={styles.casing} />
              <use href="#pa-route-standard" className={styles.standardLine} />
            </g>
            <g className={styles.accessibleLayer} mask="url(#pa-draw-accessible)">
              <use href="#pa-route-accessible" className={styles.accessibleHalo} />
              <use href="#pa-route-accessible" className={styles.casing} />
              <use href="#pa-route-accessible" className={styles.accessibleLine} />
            </g>
            <g className={styles.redrawLayer} mask="url(#pa-redraw-accessible)">
              <use href="#pa-route-accessible" className={styles.accessibleHalo} />
              <use href="#pa-route-accessible" className={styles.accessibleLine} />
            </g>
            <g className={styles.sharedLayer}>
              <path d={pathData(g.sharedStart)} className={styles.sharedLine} />
              <path d={pathData(g.sharedEnd)} className={styles.sharedLine} />
            </g>
            <g className={styles.surfaceLayer}>
              {g.accessibleSegments.map((segment, index) => (
                <path
                  key={index}
                  d={pathData(segment)}
                  className={styles.surfaceSegment}
                  data-surface={surface[index]?.surface}
                />
              ))}
            </g>
          </svg>

          {g.stairs.map((group, index) => (
            <span key={index} className={styles.stairMarker} style={at(group.at)}>
              <svg viewBox="0 0 12 12" aria-hidden="true" focusable="false">
                <path d="M2 10h2.5V7.5H7V5h2.5V2.5" />
              </svg>
            </span>
          ))}
          <span className={styles.endpoint} data-end="origin" style={at(g.origin)}>
            A
          </span>
          <span className={styles.endpoint} data-end="destination" style={at(g.destination)}>
            B
          </span>

          {labels.map((label, index) => (
            <span
              key={index}
              className={styles.pin}
              style={at(label.at)}
              data-anchor={label.anchor}
              data-tone={label.tone ?? 'neutral'}
              data-show={label.show.join(' ')}
              data-endpoint={label.endpoint ? '' : undefined}
            >
              {label.text}
            </span>
          ))}
        </div>
      </div>

      <div className={styles.stageTop}>
        <span className={styles.stageChip}>
          <span className={styles.liveDot} aria-hidden="true" />
          Recorded journey · Waterloo pilot
        </span>
        <span className={styles.scale}>
          <span className={styles.scaleBar} />
          50 m
        </span>
      </div>
      <div className={styles.stageNote} data-show="unknown">
        Width and smoothness: not recorded on any segment of either route
      </div>
      <ul className={styles.legend}>
        <li>
          <span className={styles.legendLine} data-kind="standard" />
          Shortest
        </li>
        <li>
          <span className={styles.legendLine} data-kind="accessible" />
          Wheelchair profile
        </li>
        <li>
          <span className={styles.legendDot} data-kind="stairs" />
          Recorded stairway
        </li>
        <li data-show="unknown">
          <span className={styles.legendLine} data-kind="missing" />
          Not recorded
        </li>
        {/* The backdrop is OpenStreetMap data: ODbL wants the credit where the map is. */}
        <li className={styles.legendCredit}>Paths © OpenStreetMap contributors</li>
      </ul>
    </div>
  );
}
