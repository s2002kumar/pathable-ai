'use client';

import { type KeyboardEvent, useId } from 'react';
import type { EvidenceBasis, GradeExtreme, Route, RouteCompareResponse } from '@pathable/contracts';
import {
  type CoverageRow,
  type RouteExclusion,
  type RouteVariant,
  coverageRows,
  exclusionLabel,
  exclusionsOf,
  formatShare,
  gradeBasis,
  rankedReasons,
  reasonGroups,
  routeTime,
  CATEGORY_LABELS,
} from './route-evidence';
import { routesSharePath } from './route-identity';
import { formatDistance, formatDuration } from './types';
import styles from './RoutePlanner.module.css';

/**
 * How each kind of evidence is labelled, read from the statement's own `basis`.
 *
 * Never from its code. Tagging by code put "Recorded in OpenStreetMap" on
 * "no kerb has been recorded" — an absence of data presented as an observation.
 */
export const EVIDENCE_TAGS: Readonly<Record<EvidenceBasis, { kind: string; label: string }>> = {
  recorded: { kind: 'observed', label: 'Recorded' },
  estimated: { kind: 'derived', label: 'Estimated from elevation' },
  mixed: { kind: 'derived', label: 'Recorded and estimated' },
  not_recorded: { kind: 'unknown', label: 'Not recorded' },
  profile_rule: { kind: 'profile', label: 'Your profile rule' },
};

/** Whose assumed pace a time estimate uses, as a sentence names it. */
const PACE_NAMES: Readonly<Record<string, string>> = {
  standard: 'standard walking',
  wheelchair: 'wheelchair',
  walker: 'walker or rollator',
  crutches: 'crutches or cane',
  stroller: 'stroller or pram',
  reduced_mobility: 'reduced-mobility',
};

function EvidenceTag({ basis }: { readonly basis: EvidenceBasis }) {
  const tag = EVIDENCE_TAGS[basis];
  return (
    <span className={styles.evidenceTag} data-kind={tag.kind}>
      {tag.label}
    </span>
  );
}

/** The route's name as the panel uses it. */
export function routeLabel(comparison: RouteCompareResponse, variant: RouteVariant): string {
  return variant === 'standard'
    ? 'Shortest walking route'
    : `${comparison.profile_display_name} route`;
}

/** One ruled-out group as the badge says it, with the steps a stairway records. */
function badgeLabel(exclusion: RouteExclusion): string {
  const label = exclusionLabel(exclusion);
  return exclusion.reason === 'steps' && exclusion.recordedSteps > 0
    ? `${label} · ${exclusion.recordedSteps} recorded steps`
    : label;
}

function stairwayNote(route: Route): string {
  if (route.stairway_count === 0) return 'No recorded stairs';
  const stairways = `${route.stairway_count} ${route.stairway_count === 1 ? 'stairway' : 'stairways'}`;
  // "Recorded": the total is a floor, since a stairway may carry no count.
  return route.step_count > 0 ? `${stairways} · ${route.step_count} recorded steps` : stairways;
}

// ---------------------------------------------------------------------------
// The two routes
// ---------------------------------------------------------------------------

type OptionProps = {
  readonly comparison: RouteCompareResponse;
  readonly route: Route;
  readonly other: Route | null;
  readonly variant: RouteVariant;
  readonly testId: string;
  /** Present when the card is one of two choices; absent when it stands alone. */
  readonly choice?: {
    readonly checked: boolean;
    readonly onSelect: (variant: RouteVariant) => void;
    readonly onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
  };
};

/**
 * One route's card: distance first, then time, stairs, and — on the shortest
 * route — what the chosen profile cannot use on it.
 *
 * Time is withheld from a route the profile cannot use. "16 min" printed
 * beside a flight of stairs reads as a trip a wheelchair user could take, and
 * the one error this product must not make is calling a blocked path passable.
 */
function RouteOption({ comparison, route, other, variant, testId, choice }: OptionProps) {
  const titleId = useId();
  const valueId = useId();
  const detailId = useId();
  const time = routeTime(route, variant, other);
  const exclusions = variant === 'standard' ? exclusionsOf(route) : [];
  const extra = comparison.extra_distance_m;
  // When every stairway on the route is one the profile rules out, the badge
  // says it all — count and recorded steps — and a separate stairs line would
  // repeat it. Otherwise the line stays: some stairs are costs, not walls.
  const stairsRuledOut = exclusions.find((exclusion) => exclusion.reason === 'steps');
  const stairsSaidByBadge =
    stairsRuledOut !== undefined && stairsRuledOut.segmentIndexes.length === route.stairway_count;

  const body = (
    <>
      <span className={styles.optionHead}>
        <span className={styles.optionTitle} id={titleId}>
          <span className={styles.swatch} data-variant={variant} aria-hidden="true" />
          {routeLabel(comparison, variant)}
        </span>
        <span className={`${styles.optionValue} tabular`} id={valueId}>
          {formatDistance(route.distance_m)}
        </span>
      </span>
      <span className={styles.optionDetail} id={detailId}>
        <span className={styles.optionTime} data-kind={time.kind} data-testid={`${testId}-time`}>
          {time.kind === 'estimate'
            ? `Est. ${formatDuration(time.seconds)}`
            : time.kind === 'unavailable'
              ? 'Time unavailable for this profile'
              : 'Time not comparable'}
        </span>
        {stairsSaidByBadge ? null : (
          <span className={styles.optionNote}>{stairwayNote(route)}</span>
        )}
        {variant === 'accessible' && other !== null ? (
          <span className={`${styles.optionExtra} tabular`} data-testid="difference-extra">
            {typeof extra !== 'number'
              ? 'Extra distance not reported'
              : extra >= 0.5
                ? `+${formatDistance(extra)} longer`
                : extra <= -0.5
                  ? `${formatDistance(-extra)} shorter`
                  : 'Same length'}
          </span>
        ) : null}
      </span>
      {exclusions.length > 0 ? (
        <span className={styles.optionBlocked} data-testid="route-blocked">
          Ruled out: {exclusions.map(badgeLabel).join(', ')}
        </span>
      ) : null}
    </>
  );

  if (!choice) {
    return (
      <div className={styles.option} data-variant={variant} data-testid={testId}>
        {body}
      </div>
    );
  }

  return (
    <button
      type="button"
      role="radio"
      aria-checked={choice.checked}
      // A radio group is one tab stop; the arrow keys move between its options.
      tabIndex={choice.checked ? 0 : -1}
      aria-labelledby={`${titleId} ${valueId}`}
      aria-describedby={detailId}
      className={styles.option}
      data-variant={variant}
      data-checked={choice.checked}
      data-testid={testId}
      onClick={() => choice.onSelect(variant)}
      onKeyDown={choice.onKeyDown}
    >
      {body}
    </button>
  );
}

/**
 * The reason that decided the route, above everything that qualifies it.
 *
 * The engine's own statement, ranked first by `rankedReasons`: a limit the
 * profile cannot relax before any penalty, then the penalty that cost the
 * shortest route most. Its label comes from its basis, so "a mapper recorded
 * this" and "an elevation model estimated this" never read alike.
 */
function MainDifference({ comparison }: { readonly comparison: RouteCompareResponse }) {
  const [top] = rankedReasons(comparison);
  if (!top) return null;
  return (
    <p className={styles.mainDifference} data-testid="main-difference">
      <span className={styles.categoryChip} data-category={top.category}>
        {CATEGORY_LABELS[top.category]}
      </span>{' '}
      <EvidenceTag basis={top.explanation.basis} /> {top.explanation.summary}
    </p>
  );
}

/**
 * One line, above the fold, saying how much of this route the map is silent
 * about.
 *
 * The figure is the API's `unknown_data_fraction`: the share of the route's
 * length over segments where *at least one* routing-relevant attribute has no
 * record. It is not the share about which nothing is known, and the wording
 * says "at least one attribute" for that reason. It is deliberately not a
 * score: "38% unknown" as a headline invites being read as a confidence
 * rating, so the line names what is missing and states that an absence is not
 * a clearance. The per-category breakdown is below it, each with its own
 * denominator.
 */
export function UncertaintySummary({ route }: { readonly route: Route }) {
  const unknownShare = route.unknown_data_fraction ?? 0;
  const coverage = route.evidence_coverage;
  const coverageReported = coverage !== undefined && coverage !== null;
  // Only the categories that figure counts. Width is not one of them, and
  // naming "path width, 100%" as the largest gap beside "42%" of the route
  // read as a contradiction — the first figure never included width at all.
  const [largestGap] = Object.entries(coverage ?? {})
    .filter(([category, share]) => share > 0 && category in GAP_NAMES)
    .sort(([, a], [, b]) => b - a);

  if (unknownShare <= 0 && !coverageReported) {
    return (
      <p className={styles.uncertainty} data-testid="uncertainty-summary" data-complete="unknown">
        <strong>Coverage not reported.</strong> The response carries no per-category record of what
        is missing on this route, so its gaps are unknown. Unknown is not the same as clear.
      </p>
    );
  }

  if (unknownShare <= 0 && largestGap === undefined) {
    return (
      <p className={styles.uncertainty} data-testid="uncertainty-summary" data-complete="true">
        <strong>No gaps reported</strong> in surface, surface condition, gradient, steps or kerb.
        That is a statement about the record, not a certification: a gradient may come from an
        elevation model rather than a survey.
      </p>
    );
  }

  const gapClause = largestGap !== undefined ? ` — largest gap: ${gapPhrase(...largestGap)}` : '';

  return (
    <p className={styles.uncertainty} data-testid="uncertainty-summary" data-complete="false">
      <strong>Incomplete data.</strong>{' '}
      {unknownShare > 0
        ? `${capitalise(formatShare(unknownShare))} of this route is missing at least one record${gapClause}`
        : `The biggest gap is ${gapPhrase(...largestGap!)} of this route`}
      . Unrecorded is not the same as clear.
    </p>
  );
}

/**
 * How each category reads when it is the largest gap on a route.
 *
 * The categories `unknown_data_fraction` counts, and only those: surface,
 * surface condition, gradient and the kerb at a crossing (steps too, which
 * `evidence_coverage` does not break out). Path width is reported in the
 * breakdown below, against its own denominator, not here.
 */
const GAP_NAMES: Readonly<Record<string, string>> = {
  surface: 'surface',
  smoothness: 'surface condition',
  gradient: 'gradient',
  kerb: 'kerb',
};

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * The share of a category that is missing, worded with its own denominator.
 * Kerb coverage is measured over crossings, not route length, and the phrase
 * has to say so or "kerb, 100%" reads as the whole route.
 */
function gapPhrase(category: string, share: number): string {
  return category === 'kerb'
    ? `${GAP_NAMES[category]}, ${formatShare(share)} of crossings`
    : `${GAP_NAMES[category]}, ${formatShare(share)}`;
}

/**
 * The answer: two routes, one chosen, and the reason they differ.
 *
 * The cards are a radio group because choosing one is choosing which line the
 * map brings forward, and the arrow keys move between them. The other route
 * always stays drawn: a viewer who picks one has been shown it more clearly,
 * not shown that it is safe.
 */
export function RouteDifference({
  comparison,
  selectedRoute,
  onSelectRoute = () => {},
}: {
  readonly comparison: RouteCompareResponse;
  /** Which route the map brings forward; defaults to the profile's own route. */
  readonly selectedRoute?: RouteVariant;
  readonly onSelectRoute?: (variant: RouteVariant) => void;
}) {
  const { standard_route: standard, accessible_route: accessible } = comparison;
  if (!standard || !accessible) return null;

  const selected: RouteVariant = selectedRoute ?? 'accessible';
  const samePath = routesSharePath(standard, accessible);

  // The arrow keys move the choice and the focus together, as a radio group
  // does. With two options every arrow goes to the other one.
  const move = (event: KeyboardEvent<HTMLButtonElement>) => {
    const keys = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    const next: RouteVariant = selected === 'accessible' ? 'standard' : 'accessible';
    onSelectRoute(next);
    event.currentTarget
      .closest('[role="radiogroup"]')
      ?.querySelector<HTMLButtonElement>(`[role="radio"][data-variant="${next}"]`)
      ?.focus();
  };

  const choice = (variant: RouteVariant) => ({
    checked: selected === variant,
    onSelect: onSelectRoute,
    onKeyDown: move,
  });

  return (
    <section
      className={styles.difference}
      aria-label="The two routes"
      data-testid="route-difference"
    >
      <div
        className={styles.options}
        role="radiogroup"
        aria-label="Route drawn in front on the map"
      >
        <RouteOption
          comparison={comparison}
          route={accessible}
          other={standard}
          variant="accessible"
          testId="difference-accessible"
          choice={choice('accessible')}
        />
        <RouteOption
          comparison={comparison}
          route={standard}
          other={accessible}
          variant="standard"
          testId="difference-shortest"
          choice={choice('standard')}
        />
      </div>

      {samePath ? (
        <p className={styles.coincident} data-testid="same-path-note">
          Both routes use the same segments, so their lines overlap on the map; the dashed line sits
          underneath the solid one.
        </p>
      ) : (
        <MainDifference comparison={comparison} />
      )}
    </section>
  );
}

/** A route standing alone, when there is nothing to compare it against. */
export function SingleRoute({
  comparison,
  variant,
}: {
  readonly comparison: RouteCompareResponse;
  readonly variant: RouteVariant;
}) {
  const route = variant === 'standard' ? comparison.standard_route : comparison.accessible_route;
  if (!route) return null;
  return (
    <RouteOption
      comparison={comparison}
      route={route}
      other={null}
      variant={variant}
      testId={variant === 'standard' ? 'route-card-standard' : 'route-card-accessible'}
    />
  );
}

// ---------------------------------------------------------------------------
// Why they differ
// ---------------------------------------------------------------------------

/**
 * Every statement the engine made, grouped by what it is about.
 *
 * Stairs, crossings, gradient, surface, width — then what nobody recorded —
 * then the profile's own rules, which are consequences rather than reasons and
 * are said last. Each statement carries its own evidence label; a group is
 * marked "Hard limit" only when the profile cannot use what it names.
 */
export function ReasonGroups({ comparison }: { readonly comparison: RouteCompareResponse }) {
  const { standard_route: standard, accessible_route: accessible } = comparison;
  if (!standard || !accessible) return null;

  const groups = reasonGroups(comparison);
  const distance = comparison.explanations.find((item) => item.code === 'distance_difference');
  const sharedPace =
    standard.pace_profile === accessible.pace_profile ? accessible.pace_profile : null;

  return (
    <section className={styles.section} aria-labelledby="route-reasons-heading">
      <h3 className={styles.sectionHeading} id="route-reasons-heading">
        Why the routes differ
      </h3>
      <div className={styles.reasonGroups} data-testid="difference-reasons">
        {groups.map((group) => (
          <div
            className={styles.reasonGroup}
            key={group.category}
            data-category={group.category}
            data-testid={`reason-group-${group.category}`}
          >
            <h4 className={styles.reasonGroupHeading}>
              {group.label}
              {group.hardLimit ? <span className={styles.hardChip}>Hard limit</span> : null}
            </h4>
            <ul className={styles.evidenceList}>
              {group.reasons.map(({ explanation }) => (
                <li
                  className={styles.evidenceItem}
                  key={explanation.code}
                  data-basis={explanation.basis}
                >
                  <EvidenceTag basis={explanation.basis} />
                  <span>{explanation.summary}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}

        <div
          className={styles.reasonGroup}
          data-category="profile"
          data-testid="reason-group-profile"
        >
          <h4 className={styles.reasonGroupHeading}>Profile rules</h4>
          <ul className={styles.evidenceList}>
            {distance ? (
              <li className={styles.evidenceItem} data-basis="profile_rule">
                <EvidenceTag basis="profile_rule" />
                <span>
                  {distance.summary} {comparison.profile_description}
                </span>
              </li>
            ) : null}
            {sharedPace !== null ? (
              <li
                className={styles.evidenceItem}
                data-basis="profile_rule"
                data-testid="difference-pace"
              >
                <EvidenceTag basis="profile_rule" />
                <span>
                  Times use the same assumed {PACE_NAMES[sharedPace] ?? sharedPace} pace, with fixed
                  allowances for steps and crossings. Neither is measured.
                </span>
              </li>
            ) : null}
          </ul>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// What the map records
// ---------------------------------------------------------------------------

const PART_NAMES = { recorded: 'recorded', estimated: 'estimated', unknown: 'not recorded' };

function coverageText(row: CoverageRow): string {
  if (row.status === 'not_applicable') return 'No crossings on this route';
  if (row.status === 'not_reported') return 'Not reported';
  if (row.counts) {
    const { recorded, total } = row.counts;
    return `${recorded} of ${total} ${total === 1 ? 'crossing' : 'crossings'} recorded`;
  }
  return row.parts
    .filter((part) => part.share > 0)
    .map((part) => `${formatShare(part.share)} ${PART_NAMES[part.kind]}`)
    .join(' · ');
}

function CoverageItem({ row }: { readonly row: CoverageRow }) {
  return (
    <li
      className={styles.coverageItem}
      data-status={row.status}
      data-testid={`coverage-${row.key}`}
    >
      <span className={styles.coverageLabel}>{row.label}</span>
      {/* The bar repeats the sentence beside it and is hidden from assistive
          technology; the sentence is the fact. An empty bar is drawn for a row
          with nothing to measure, so the rows still line up. */}
      <span className={styles.coverageBar} aria-hidden="true">
        {row.parts.map((part) =>
          part.share > 0 ? (
            <span
              key={part.kind}
              className={styles.coveragePart}
              data-kind={part.kind}
              style={{ width: `${part.share * 100}%` }}
            />
          ) : null,
        )}
      </span>
      <span className={styles.coverageText}>{coverageText(row)}</span>
    </li>
  );
}

function gradeText(extreme: GradeExtreme | null): string {
  if (extreme === null) return 'None on record';
  return `${extreme.percent.toFixed(1)}%`;
}

/**
 * Per category, how much of the route the map records — and, for gradient,
 * how much an elevation model estimated instead.
 *
 * Each row keeps its own denominator (route length, or crossings for kerbs)
 * and there is no total: a combined "% known" would add a surface to a width.
 */
export function EvidenceCoverage({
  route,
  label,
}: {
  readonly route: Route;
  readonly label: string;
}) {
  const rows = coverageRows(route);
  const climb = route.gradient.steepest_uphill;
  const descent = route.gradient.steepest_downhill;
  const anyEstimated = [climb, descent].some(
    (extreme) => extreme !== null && gradeBasis(extreme) === 'estimated',
  );

  return (
    <section
      className={styles.section}
      aria-labelledby="route-coverage-heading"
      data-testid="evidence-coverage"
    >
      <h3 className={styles.sectionHeading} id="route-coverage-heading">
        What the map records on the {label.toLowerCase()}
      </h3>
      <p className={styles.coverageKey}>
        <span className={styles.keyItem}>
          <span className={styles.keySwatch} data-kind="recorded" aria-hidden="true" />
          Recorded
        </span>
        <span className={styles.keyItem}>
          <span className={styles.keySwatch} data-kind="estimated" aria-hidden="true" />
          Estimated
        </span>
        <span className={styles.keyItem}>
          <span className={styles.keySwatch} data-kind="unknown" aria-hidden="true" />
          Not recorded
        </span>
        <span className={styles.keyNote}>
          Shares of the route’s length; kerbs are counted per crossing. The “missing at least one
          record” figure above counts surface, surface condition, gradient, steps and kerb — not
          width.
        </span>
      </p>
      <ul className={styles.coverageList}>
        {rows.map((row) => (
          <CoverageItem key={row.key} row={row} />
        ))}
      </ul>

      <dl
        className={styles.gradeFacts}
        data-testid="difference-gradient"
        data-basis={climb === null ? 'not_recorded' : gradeBasis(climb)}
      >
        <div className={styles.gradeFact}>
          <dt>Steepest climb</dt>
          <dd data-testid="steepest-climb">
            {gradeText(climb)}
            {climb !== null ? <EvidenceTag basis={gradeBasis(climb)} /> : null}
          </dd>
        </div>
        <div className={styles.gradeFact}>
          <dt>Steepest descent</dt>
          <dd data-testid="steepest-descent">
            {gradeText(descent)}
            {descent !== null ? <EvidenceTag basis={gradeBasis(descent)} /> : null}
          </dd>
        </div>
      </dl>
      {anyEstimated ? (
        <p className={styles.hint} data-testid="gradient-provenance">
          An estimated gradient comes from an elevation model of the ground, not a survey of the
          path, so it cannot see a ramp or a step.
        </p>
      ) : null}
      <p className={styles.hint}>
        Not recorded is not the same as clear: it means nobody has mapped it.
      </p>
    </section>
  );
}
