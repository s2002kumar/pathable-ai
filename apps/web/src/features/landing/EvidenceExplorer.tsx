import type { CSSProperties, ReactNode } from 'react';
import { EvidenceTag, type EvidenceKind } from './EvidenceTag';
import { FIGURES, ROUTE, metres, percent, segmentEvidence, type RouteKey } from './journey';
import styles from './Landing.module.css';

type Lens = {
  readonly value: 'stairs' | 'gradient' | 'surface' | 'width';
  readonly label: string;
  readonly tags: readonly EvidenceKind[];
  readonly rows: Record<RouteKey, ReactNode>;
  readonly note: ReactNode;
  readonly key: readonly { readonly swatch: string; readonly text: string }[];
};

const NAMES: Record<RouteKey, string> = {
  standard: 'Shortest walking route',
  accessible: 'Wheelchair profile route',
};

function stairsRow(key: RouteKey): string {
  const route = ROUTE[key];
  if (route.stairways === 0) return 'No stairways recorded';
  const counted = route.stairways - route.stairwaysWithoutStepCount;
  return (
    `${route.stairways} recorded stairways · ${route.recordedSteps} steps across ${counted}, ` +
    `no step count on ${route.stairwaysWithoutStepCount}`
  );
}

function gradientRow(key: RouteKey): string {
  const { gradient } = ROUTE[key];
  const parts = [`Estimated on ${percent(gradient.estimatedFraction)}`];
  if (gradient.steepestUphillPercent !== null)
    parts.push(`steepest ${gradient.steepestUphillPercent.toFixed(1)}% up`);
  if (gradient.steepestDownhillPercent !== null)
    parts.push(`${gradient.steepestDownhillPercent.toFixed(1)}% down`);
  parts.push(`none on ${percent(gradient.unknownFraction)}`);
  return parts.join(' · ');
}

function surfaceRow(key: RouteKey): string {
  const share = ROUTE[key].evidenceCoverage.surface;
  return `Recorded on ${percent(1 - share)} · not recorded on ${FIGURES.surfaceMissing[key]}`;
}

function widthRow(key: RouteKey): string {
  const { width, smoothness } = ROUTE[key].evidenceCoverage;
  return width === 1 && smoothness === 1
    ? 'Neither recorded on any segment'
    : `Width not recorded on ${percent(width)} · smoothness on ${percent(smoothness)}`;
}

const LENSES: readonly Lens[] = [
  {
    value: 'stairs',
    label: 'Stairs',
    tags: ['recorded', 'profile'],
    rows: { standard: stairsRow('standard'), accessible: stairsRow('accessible') },
    note: 'A recorded stairway is a hard limit for the wheelchair profile, and PathAble never relaxes a hard limit to return a route.',
    key: [{ swatch: 'stairs', text: 'Recorded stairway' }],
  },
  {
    value: 'gradient',
    label: 'Gradient',
    tags: ['derived', 'missing'],
    rows: { standard: gradientRow('standard'), accessible: gradientRow('accessible') },
    note: (
      <>
        OpenStreetMap records no incline on either route. The estimates come from NRCan&rsquo;s 1 m
        HRDEM, a bare-earth model that cannot see a ramp or a step. Where there is no gradient at
        all it stays unknown, never flat.
      </>
    ),
    key: [
      { swatch: 'derived', text: 'Derived · HRDEM, brighter is steeper' },
      { swatch: 'missing', text: 'No gradient' },
    ],
  },
  {
    value: 'surface',
    label: 'Surface',
    tags: ['recorded', 'missing'],
    rows: { standard: surfaceRow('standard'), accessible: surfaceRow('accessible') },
    note: 'Where a surface is recorded it is the mapper’s value — paving stones, asphalt, concrete. Where none is, PathAble says so and adds a cost for the gap instead of assuming a smooth path.',
    key: [
      { swatch: 'recorded', text: 'Recorded · OSM' },
      { swatch: 'missing', text: 'Not recorded' },
    ],
  },
  {
    value: 'width',
    label: 'Width & smoothness',
    tags: ['missing'],
    rows: { standard: widthRow('standard'), accessible: widthRow('accessible') },
    note: 'Nobody has recorded either on these paths. A missing width is unknown, never wide enough; a missing smoothness is unknown, never smooth.',
    key: [{ swatch: 'missing', text: 'Not recorded' }],
  },
];

const AXIS_STEP_M = 100;

/**
 * Both routes drawn to scale as straight strips, one cell per segment, and
 * a lens that recolours them by what is known about each segment.
 *
 * Radio buttons and `:has()`, no script: the lens works before hydration
 * and with JavaScript off, arrow keys move between lenses, and where `:has()`
 * is unsupported every lens's text is shown at once. The strips are a
 * picture of the figures in the text beside them, so they are hidden from
 * assistive technology rather than read out cell by cell.
 */
export function EvidenceExplorer() {
  const longest = Math.max(ROUTE.standard.distanceM, ROUTE.accessible.distanceM);
  const ticks = Array.from(
    { length: Math.floor(longest / AXIS_STEP_M) + 1 },
    (_, i) => i * AXIS_STEP_M,
  );

  return (
    <div className={styles.explorer}>
      <fieldset className={styles.lensPicker}>
        <legend className={styles.lensLegend}>Choose a lens</legend>
        <div className={styles.lensOptions}>
          {LENSES.map((lens, index) => (
            <span key={lens.value} className={styles.lensOption}>
              <input
                className={styles.lensInput}
                type="radio"
                name="evidence-lens"
                id={`lens-${lens.value}`}
                value={lens.value}
                defaultChecked={index === 0}
                aria-controls="evidence-lens-panels"
              />
              <label htmlFor={`lens-${lens.value}`}>{lens.label}</label>
            </span>
          ))}
        </div>
      </fieldset>

      <div className={styles.strips} aria-hidden="true">
        {(['standard', 'accessible'] as const).map((key) => (
          <div key={key} className={styles.stripRow}>
            <p className={styles.stripLabel}>
              <span className={styles.legendLine} data-kind={key} />
              {NAMES[key]}
              <span className={styles.stripDistance}>{metres(ROUTE[key].distanceM)}</span>
            </p>
            <div
              className={styles.strip}
              data-route={key}
              style={{ width: `${(ROUTE[key].distanceM / longest) * 100}%` }}
            >
              {segmentEvidence(key).map((segment, index) => (
                <span
                  key={index}
                  className={styles.cell}
                  style={
                    {
                      flexGrow: segment.lengthM,
                      '--steep': Math.min(1, (segment.gradePercent ?? 0) / 5).toFixed(2),
                    } as CSSProperties
                  }
                  data-stairs={segment.stairs ? 'yes' : 'no'}
                  data-surface={segment.surface}
                  data-grade={segment.grade}
                  data-width={
                    segment.width === 'missing' || segment.smoothness === 'missing'
                      ? 'missing'
                      : 'recorded'
                  }
                />
              ))}
            </div>
          </div>
        ))}
        <div className={styles.axis}>
          {ticks.map((tick) => (
            <span key={tick} style={{ left: `${(tick / longest) * 100}%` }}>
              {tick} m
            </span>
          ))}
        </div>
      </div>

      <div id="evidence-lens-panels" className={styles.lensPanels}>
        {LENSES.map((lens) => (
          <div key={lens.value} className={styles.lensPanel} data-lens-panel={lens.value}>
            <p className={styles.lensTitle}>
              <span className={styles.lensName}>{lens.label}</span>
              {lens.tags.map((tag) => (
                <EvidenceTag key={tag} kind={tag} />
              ))}
            </p>
            <dl className={styles.lensRows}>
              {(['standard', 'accessible'] as const).map((key) => (
                <div key={key}>
                  <dt>{NAMES[key]}</dt>
                  <dd>{lens.rows[key]}</dd>
                </div>
              ))}
            </dl>
            <p className={styles.lensNote}>{lens.note}</p>
            <ul className={styles.lensKey} aria-hidden="true">
              {lens.key.map((item) => (
                <li key={item.text}>
                  <span className={styles.keySwatch} data-kind={item.swatch} />
                  {item.text}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
