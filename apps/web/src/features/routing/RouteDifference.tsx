'use client';

import type {
  EvidenceBasis,
  GradientSummary,
  Route,
  RouteCompareResponse,
} from '@pathable/contracts';
import { type RouteFocus, recordedStairs } from '@/features/map/route-layers';
import { routesSharePath } from './route-identity';
import type { StairsTarget } from './types';
import { formatDistance, formatDuration } from './types';
import styles from './RoutePlanner.module.css';

/** How each category reads when it is the largest gap on a route. */
const GAP_NAMES: Readonly<Record<string, string>> = {
  surface: 'surface',
  smoothness: 'surface condition',
  gradient: 'gradient',
  width: 'path width',
  kerb: 'kerb',
};

/** The categories `evidence_coverage` assesses, for the sentence that names them. */
const ASSESSED_CATEGORIES =
  'surface, surface condition, gradient, path width, and kerbs at crossings';

/**
 * How each kind of evidence is labelled, read from the statement's own `basis`.
 *
 * Never from its code. Tagging by code put "Recorded in OpenStreetMap" on
 * "no kerb has been recorded" — an absence of data presented as an observation.
 */
export const EVIDENCE_TAGS: Readonly<Record<EvidenceBasis, { kind: string; label: string }>> = {
  recorded: { kind: 'observed', label: 'Recorded in OpenStreetMap' },
  estimated: { kind: 'derived', label: 'Derived from an elevation model' },
  mixed: { kind: 'derived', label: 'Recorded and derived from an elevation model' },
  not_recorded: { kind: 'unknown', label: 'Not recorded' },
  profile_rule: { kind: 'profile', label: 'Your profile’s rules' },
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

/** The basis of a statement about a route's gradients, from where they came from. */
function gradientBasis(gradient: GradientSummary): EvidenceBasis {
  if (gradient.recorded_fraction > 0 && gradient.estimated_fraction > 0) return 'mixed';
  if (gradient.recorded_fraction > 0) return 'recorded';
  if (gradient.estimated_fraction > 0) return 'estimated';
  return 'not_recorded';
}

/**
 * The share of a category that is missing, worded with its own denominator.
 * Kerb coverage is measured over crossings, not route length, and the sentence
 * has to say so or "kerb, 100%" reads as the whole route.
 */
function gapPhrase(category: string, share: number): string {
  const pct = Math.round(share * 100);
  return category === 'kerb'
    ? `${GAP_NAMES[category]}, ${pct}% of crossings`
    : `${GAP_NAMES[category]}, ${pct}%`;
}

/**
 * One line, above the fold, saying how much of this route the map is silent
 * about.
 *
 * The figure is the API's `unknown_data_fraction`: the share of the route's
 * length that runs over segments on which *at least one* routing-relevant
 * attribute — surface, surface condition, gradient, steps, or the kerb at a
 * crossing — has no record. It is not the share about which nothing is known:
 * a stairway that OpenStreetMap does record is still counted as recorded, even
 * on a route where every segment is missing its surface. The wording says
 * "at least one attribute" for exactly that reason, and names the largest
 * single gap from `evidence_coverage` so the reader knows which fact is
 * absent, not just how much.
 *
 * When the response reports no gaps, the line says exactly that and no more:
 * no gaps in the categories that were assessed. It does not say everything was
 * recorded — a gradient can be present because a terrain model supplied it —
 * and it does not say the route is clear. When the response carries no
 * per-category coverage at all, the gaps are unknown and the line says so.
 *
 * It is deliberately not a score. "38% unknown" as a headline number invites
 * being read as a confidence rating, so the wording names the thing that is
 * missing and states plainly that an absence is not a clearance.
 */
function UncertaintySummary({ route }: { readonly route: Route }) {
  const unknownShare = route.unknown_data_fraction ?? 0;
  const coverage = route.evidence_coverage;
  const coverageReported = coverage !== undefined && coverage !== null;
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
        <strong>No gaps reported</strong> in the assessed categories ({ASSESSED_CATEGORIES}). That
        is a statement about the record, not a certification: a gradient may still come from an
        elevation model rather than a survey, and PathAble advises rather than guarantees.
      </p>
    );
  }

  const gapClause = largestGap !== undefined ? `; largest gap: ${gapPhrase(...largestGap)}` : '';

  return (
    <p className={styles.uncertainty} data-testid="uncertainty-summary" data-complete="false">
      <strong>Accessibility data is incomplete.</strong>{' '}
      {unknownShare > 0
        ? `At least one accessibility attribute is unrecorded on ${Math.round(unknownShare * 100)}% of this route${gapClause}`
        : `The biggest gap is ${gapPhrase(...largestGap!)} of this route`}
      . Unrecorded is not the same as clear.
    </p>
  );
}

/**
 * The stairways on a route, with the step count where the map records one.
 *
 * "1 stairway (14 recorded steps)" and "1 stairway" are different facts: the
 * second means nobody wrote down how many steps there are, and a reader
 * deciding whether they can manage it needs to know which of the two they are
 * looking at. Omitting the number silently would turn an unrecorded count into
 * an implied small one.
 *
 * The count says "recorded" because it is a floor, not a total. `step_count`
 * sums only the stairways somebody counted; a route with two counted stairways
 * and two uncounted ones reports the two.
 */
/**
 * "Show the recorded stairs" — the one evidence overlay.
 *
 * It draws the segments OpenStreetMap records as stairways on whichever route
 * carries them, and says in words what it drew. Three things it deliberately
 * is not: it is not a hazard layer, it is not a claim about segments whose
 * step state nobody recorded, and it is not a complete count of steps.
 *
 * The segments come from the response, read as data — never from an
 * explanation's prose and never from the cost breakdown, because a `steps`
 * cost component only exists when the chosen profile happens to price steps,
 * so a profile that does not would look like a route with no stairs at all.
 */
function RecordedStairsControl({
  comparison,
  target,
  onShow,
}: {
  readonly comparison: RouteCompareResponse;
  readonly target: StairsTarget;
  readonly onShow: (target: StairsTarget) => void;
}) {
  const { standard_route: standard, accessible_route: accessible } = comparison;
  const shown = target === 'standard' ? standard : target === 'accessible' ? accessible : null;
  const stairs = recordedStairs(shown);

  // Offered for the route that has any. Almost always the shortest one — that
  // is usually the whole reason the two routes differ.
  const candidate = recordedStairs(standard).stairways > 0 ? 'standard' : 'accessible';
  const candidateRoute = candidate === 'standard' ? standard : accessible;
  const available = recordedStairs(candidateRoute).stairways;

  if (!standard || !accessible) return null;

  const label = candidate === 'standard' ? 'the shortest walking route' : 'your route';

  return (
    <div className={styles.stairs} data-testid="recorded-stairs">
      {available === 0 ? (
        <p className={styles.stairsNote} data-testid="recorded-stairs-none">
          <strong>No recorded stairs</strong> on either route. OpenStreetMap records no stairway on
          the segments these routes use; it has not been confirmed that there are none.
        </p>
      ) : (
        <>
          <button
            type="button"
            className={styles.stairsButton}
            aria-pressed={target !== null}
            onClick={() => onShow(target === null ? candidate : null)}
            data-testid="show-recorded-stairs"
          >
            {target === null ? `Show the recorded stairs` : 'Hide the recorded stairs'}
          </button>
          <p className={styles.stairsNote} data-testid="recorded-stairs-note">
            {target === null ? (
              <>
                {available} {available === 1 ? 'stairway is' : 'stairways are'} recorded on {label}.
              </>
            ) : (
              <>
                Highlighted on the map: {stairs.stairways}{' '}
                {stairs.stairways === 1 ? 'stairway' : 'stairways'} recorded on {label}
                {stairs.recordedSteps > 0 ? `, ${stairs.recordedSteps} recorded steps` : ''}
                {stairs.unknownStepCount > 0
                  ? `. ${stairs.unknownStepCount} of them ${stairs.unknownStepCount === 1 ? 'has' : 'have'} no recorded step count, so that total is a floor rather than the number of steps`
                  : ''}
                .
                {stairs.unknownSegments > 0
                  ? ` A further ${stairs.unknownSegments} ${stairs.unknownSegments === 1 ? 'segment has' : 'segments have'} no recorded step information at all — neither stairs nor no stairs.`
                  : ''}
              </>
            )}
          </p>
        </>
      )}
    </div>
  );
}

/**
 * The steepest climb on the route, labelled by where that number came from.
 *
 * Read from the route's gradient summary. This used to read OpenStreetMap's
 * `steepest_incline_percent` and say it "comes from a terrain model" whenever
 * an estimate was present anywhere on the route — crediting a mapper's figure
 * to the model on every route that mixed the two, while the estimated
 * gradients themselves were never shown at all.
 */
function GradientItem({ gradient }: { readonly gradient: GradientSummary }) {
  const steepest = gradient.steepest_uphill;
  const unknown = Math.round(gradient.unknown_fraction * 100);
  const gap =
    unknown > 0 && unknown < 100 ? ` No gradient is on record for ${unknown}% of the route.` : '';

  if (steepest === null) {
    const basis = gradientBasis(gradient);
    const tag = EVIDENCE_TAGS[basis];
    return (
      <li className={styles.evidenceItem} data-testid="difference-gradient" data-basis={basis}>
        <span className={styles.evidenceTag} data-kind={tag.kind}>
          {tag.label}
        </span>
        <span>
          {basis === 'not_recorded'
            ? 'No gradient is on record for this route — not recorded, not flat.'
            : `No part of this route climbs by a recorded or estimated amount.${gap}`}
        </span>
      </li>
    );
  }

  const recorded = steepest.source === 'osm_incline';
  const tag = EVIDENCE_TAGS[recorded ? 'recorded' : 'estimated'];
  return (
    <li
      className={styles.evidenceItem}
      data-testid="difference-gradient"
      data-basis={recorded ? 'recorded' : 'estimated'}
    >
      <span className={styles.evidenceTag} data-kind={tag.kind}>
        {tag.label}
      </span>
      <span>
        The steepest climb on this route is {steepest.percent.toFixed(1)}%
        {recorded
          ? ', as recorded in OpenStreetMap.'
          : ', estimated from an elevation model of the ground rather than surveyed on the path, so it cannot see a ramp or a step.'}
        {gap}
      </span>
    </li>
  );
}

function stairwayNote(route: Route): string {
  if (route.stairway_count === 0) return 'no recorded stairways';
  const stairways = `${route.stairway_count} ${route.stairway_count === 1 ? 'stairway' : 'stairways'}`;
  return route.step_count > 0 ? `${stairways} (${route.step_count} recorded steps)` : stairways;
}

/**
 * One route's figure: distance and stairways, with a control that brings that
 * route forward on the map.
 *
 * The control dims the other line; it never removes it, and it says so in its
 * own wording. A viewer who highlights a route has been shown it more clearly,
 * not shown that it is safe.
 */
function RouteFigure({
  route,
  label,
  variant,
  testId,
  focus,
  onFocus,
  showTime,
}: {
  readonly route: Route;
  readonly label: string;
  readonly variant: 'standard' | 'accessible';
  readonly testId: string;
  readonly focus: RouteFocus;
  readonly onFocus: (focus: RouteFocus) => void;
  /** False when this estimate used a different pace from the one beside it. */
  readonly showTime: boolean;
}) {
  const focused = focus === variant;
  return (
    <div
      className={styles.figure}
      data-variant={variant}
      data-focused={focused}
      data-dimmed={focus !== null && !focused}
      data-testid={testId}
    >
      <span className={styles.figureLabel}>
        <span className={styles.swatch} data-variant={variant} aria-hidden="true" />
        {label}
      </span>
      <span className={`${styles.figureValue} tabular`}>{formatDistance(route.distance_m)}</span>
      {/* "Est." and not "takes": the figure is distance divided by an assumed
          pace plus fixed allowances, which the schema itself describes as not
          measured and not specific to any individual. Two estimates only sit
          side by side when they share that pace — otherwise part of the gap
          between them would be a difference in assumption, not in route. */}
      <span className={styles.figureMeta} data-testid={`${testId}-time`}>
        {showTime
          ? `Est. ${formatDuration(route.estimated_duration_seconds)}`
          : 'Time not comparable'}
      </span>
      <span className={styles.figureFooter}>
        <span className={styles.figureNote}>{stairwayNote(route)}</span>
        <button
          type="button"
          className={styles.figureFocus}
          aria-pressed={focused}
          aria-label={`Highlight the ${label.toLowerCase()} on the map`}
          onClick={() => onFocus(focused ? null : variant)}
          data-testid={`focus-${variant}`}
        >
          {focused ? 'Highlighted' : 'Highlight'}
        </button>
      </span>
    </div>
  );
}

/**
 * The answer to the only question the comparison exists to answer.
 *
 * Everything here is read out of the response. The engine already explains
 * itself — each explanation names something on the route it avoided — so this
 * does not paraphrase or re-derive anything; it puts the answer above the fold
 * and sorts the statements by where they came from.
 *
 * That sorting is the point. "There are four stairways on the shortest route"
 * is something a surveyor wrote down in OpenStreetMap. "The gradient is 3%" may
 * be a terrain model's estimate. "This route is 67 m longer" is a consequence of
 * the profile's own rules. "Nobody recorded the surface" is an absence. Four
 * different kinds of claim, and a viewer who cannot tell them apart cannot judge
 * any of them.
 */
export function RouteDifference({
  comparison,
  focusedRoute = null,
  onFocusRoute = () => {},
  stairsTarget = null,
  onShowStairs = () => {},
}: {
  readonly comparison: RouteCompareResponse;
  readonly focusedRoute?: RouteFocus;
  readonly onFocusRoute?: (focus: RouteFocus) => void;
  readonly stairsTarget?: StairsTarget;
  readonly onShowStairs?: (target: StairsTarget) => void;
}) {
  const { standard_route: standard, accessible_route: accessible } = comparison;

  // Only meaningful when there are two routes to compare. The contract types
  // both as optional as well as nullable, so this is a truthiness check.
  if (!standard || !accessible) return null;

  // Every constraint the engine found the routes differ on, whatever it is.
  // Profile-rule statements — the distance — are handled separately below.
  const reasons = comparison.explanations.filter(
    (explanation) => explanation.basis !== 'profile_rule',
  );
  // The distance statement is a consequence of the profile, and the headline
  // above already states the exact figure. The engine's `same_distance`
  // explanation ("essentially the same length") is not repeated here: the
  // headline carries the number, and "essentially" is not a number.
  const distance = comparison.explanations.find(
    (explanation) => explanation.code === 'distance_difference',
  );
  const unknownShare = accessible.unknown_data_fraction ?? 0;
  const extra = comparison.extra_distance_m;
  // Identity comes from the response's segments or geometry, never from the
  // distance: two routes can measure the same and be different paths.
  const samePath = routesSharePath(standard, accessible);
  // Two time estimates are comparable only at the same assumed pace. The API
  // times both routes at the traveller's pace; if a response ever disagrees,
  // the shortest route's time is withheld rather than shown beside the other.
  const sharedPace =
    standard.pace_profile === accessible.pace_profile ? accessible.pace_profile : null;

  return (
    <section
      className={styles.difference}
      aria-labelledby="route-difference-heading"
      data-testid="route-difference"
    >
      <h3 className={styles.differenceHeading} id="route-difference-heading">
        Why are they different?
      </h3>

      <div className={styles.figures} role="group" aria-label="The two routes">
        <RouteFigure
          route={accessible}
          label={`${comparison.profile_display_name} route`}
          variant="accessible"
          testId="difference-accessible"
          focus={focusedRoute}
          onFocus={onFocusRoute}
          showTime
        />
        <RouteFigure
          route={standard}
          label="Shortest walking route"
          variant="standard"
          testId="difference-shortest"
          focus={focusedRoute}
          onFocus={onFocusRoute}
          showTime={sharedPace !== null}
        />
      </div>

      {/* The figure alone. The reasons are the list below — every constraint
          the routes differ on — and naming one of them here, as this line once
          did with "to avoid N stairways", credited the whole detour to it. */}
      <p className={styles.extra} data-testid="difference-extra">
        <span>Extra distance</span>
        <span className={`${styles.extraValue} tabular`}>
          {typeof extra === 'number'
            ? `${extra >= 0 ? '+' : '−'}${formatDistance(Math.abs(extra))}`
            : 'Not reported'}
        </span>
      </p>

      {samePath ? (
        <p className={styles.coincident} data-testid="same-path-note">
          Both routes use the same segments, so their lines overlap on the map; the dashed line sits
          underneath the solid one.
        </p>
      ) : null}

      {focusedRoute !== null ? (
        <p className={styles.focusNote} data-testid="focus-note">
          Highlighting brings one route forward on the map. The other stays drawn, and neither is
          certified passable.
        </p>
      ) : null}

      <UncertaintySummary route={accessible} />

      {/* Below the uncertainty line, not above it. The figures, the detour,
          the caution and the way back to the controls are what has to fit on
          a phone's first screen; asking where the stairs are is a question
          somebody chooses to ask next. */}
      <RecordedStairsControl comparison={comparison} target={stairsTarget} onShow={onShowStairs} />

      <ul className={styles.evidenceList} data-testid="difference-reasons">
        {reasons.map((explanation) => {
          const tag = EVIDENCE_TAGS[explanation.basis];
          return (
            <li
              className={styles.evidenceItem}
              key={explanation.code}
              data-basis={explanation.basis}
            >
              <span className={styles.evidenceTag} data-kind={tag.kind}>
                {tag.label}
              </span>
              <span>{explanation.summary}</span>
            </li>
          );
        })}

        {distance ? (
          <li className={styles.evidenceItem} key={distance.code}>
            <span className={styles.evidenceTag} data-kind={EVIDENCE_TAGS.profile_rule.kind}>
              {EVIDENCE_TAGS.profile_rule.label}
            </span>
            <span>
              {distance.summary} {comparison.profile_description}
            </span>
          </li>
        ) : null}

        {sharedPace !== null ? (
          <li className={styles.evidenceItem} key="pace" data-testid="difference-pace">
            <span className={styles.evidenceTag} data-kind={EVIDENCE_TAGS.profile_rule.kind}>
              {EVIDENCE_TAGS.profile_rule.label}
            </span>
            <span>
              Both times are estimated at the same assumed {PACE_NAMES[sharedPace] ?? sharedPace}{' '}
              pace, with fixed allowances for steps and crossings. Neither is measured.
            </span>
          </li>
        ) : null}

        <GradientItem gradient={accessible.gradient} />

        {unknownShare > 0 ? (
          <li className={styles.evidenceItem} key="unknown" data-testid="difference-unknown">
            <span className={styles.evidenceTag} data-kind="unknown">
              Not recorded
            </span>
            <span>
              On {Math.round(unknownShare * 100)}% of this route at least one accessibility
              attribute — surface, surface condition, gradient, steps or kerb — has no record in
              OpenStreetMap. That is missing information, not a clear path, and it is why this
              comparison advises rather than guarantees.
            </span>
          </li>
        ) : null}
      </ul>
    </section>
  );
}
