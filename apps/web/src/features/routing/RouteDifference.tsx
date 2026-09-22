'use client';

import type { Route, RouteCompareResponse } from '@pathable/contracts';
import type { RouteFocus } from '@/features/map/route-layers';
import { formatDistance } from './types';
import styles from './RoutePlanner.module.css';

/** How each category reads when it is the largest gap on a route. */
const GAP_NAMES: Readonly<Record<string, string>> = {
  surface: 'surface',
  smoothness: 'surface condition',
  gradient: 'gradient',
  width: 'path width',
  kerb: 'kerb',
};

/** Below this, two routes are the same journey drawn twice. */
export const COINCIDENT_THRESHOLD_M = 15;

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
 * It is deliberately not a score. "38% unknown" as a headline number invites
 * being read as a confidence rating, so the wording names the thing that is
 * missing and states plainly that an absence is not a clearance.
 */
function UncertaintySummary({ route }: { readonly route: Route }) {
  const unknownShare = route.unknown_data_fraction ?? 0;
  const coverage = route.evidence_coverage ?? {};
  const [largestGap] =
    Object.entries(coverage)
      .filter(([category, share]) => share > 0 && category in GAP_NAMES)
      .sort(([, a], [, b]) => b - a) ?? [];

  if (unknownShare <= 0 && largestGap === undefined) {
    return (
      <p className={styles.uncertainty} data-testid="uncertainty-summary" data-complete="true">
        Every accessibility category this route touches is recorded in OpenStreetMap.
      </p>
    );
  }

  const gapClause =
    largestGap !== undefined
      ? `; largest gap: ${GAP_NAMES[largestGap[0]]}, ${Math.round(largestGap[1] * 100)}%`
      : '';

  return (
    <p className={styles.uncertainty} data-testid="uncertainty-summary" data-complete="false">
      <strong>Accessibility data is incomplete.</strong>{' '}
      {unknownShare > 0
        ? `At least one accessibility attribute is unrecorded on ${Math.round(unknownShare * 100)}% of this route${gapClause}`
        : `The biggest gap is ${GAP_NAMES[largestGap![0]]}, missing for ${Math.round(largestGap![1] * 100)}% of this route`}
      . Unrecorded is not the same as clear.
    </p>
  );
}

function stairwayNote(route: Route): string {
  if (route.stairway_count === 0) return 'no stairways';
  return `${route.stairway_count} ${route.stairway_count === 1 ? 'stairway' : 'stairways'}`;
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
}: {
  readonly route: Route;
  readonly label: string;
  readonly variant: 'standard' | 'accessible';
  readonly testId: string;
  readonly focus: RouteFocus;
  readonly onFocus: (focus: RouteFocus) => void;
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
}: {
  readonly comparison: RouteCompareResponse;
  readonly focusedRoute?: RouteFocus;
  readonly onFocusRoute?: (focus: RouteFocus) => void;
}) {
  const { standard_route: standard, accessible_route: accessible } = comparison;

  // Only meaningful when there are two routes to compare. The contract types
  // both as optional as well as nullable, so this is a truthiness check.
  if (!standard || !accessible) return null;

  const avoided = comparison.explanations.filter(
    (explanation) => explanation.code !== 'distance_difference',
  );
  const distance = comparison.explanations.find(
    (explanation) => explanation.code === 'distance_difference',
  );
  const stairsAvoided = standard.stairway_count - accessible.stairway_count;
  const gradientDerived =
    accessible.gradient_source === 'derived_elevation' || accessible.gradient_source === 'mixed';
  const unknownShare = accessible.unknown_data_fraction ?? 0;
  const extra = comparison.extra_distance_m;
  const coincident = typeof extra === 'number' && Math.abs(extra) < COINCIDENT_THRESHOLD_M;

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
        />
        <RouteFigure
          route={standard}
          label="Shortest walking route"
          variant="standard"
          testId="difference-shortest"
          focus={focusedRoute}
          onFocus={onFocusRoute}
        />
      </div>

      <p className={styles.extra} data-testid="difference-extra">
        <span>Extra distance</span>
        <span className={`${styles.extraValue} tabular`}>
          {typeof extra === 'number'
            ? `${extra >= 0 ? '+' : '−'}${formatDistance(Math.abs(extra))}`
            : 'None'}
        </span>
        {stairsAvoided > 0 ? (
          <span>
            to avoid {stairsAvoided} {stairsAvoided === 1 ? 'stairway' : 'stairways'}
          </span>
        ) : null}
      </p>

      {coincident ? (
        <p className={styles.coincident} data-testid="coincident-note">
          The two routes follow the same path here, so their lines overlap on the map; the dashed
          line sits underneath the solid one.
        </p>
      ) : null}

      {focusedRoute !== null ? (
        <p className={styles.focusNote} data-testid="focus-note">
          Highlighting brings one route forward on the map. The other stays drawn, and neither is
          certified passable.
        </p>
      ) : null}

      <UncertaintySummary route={accessible} />

      <ul className={styles.evidenceList}>
        {avoided.map((explanation) => (
          <li className={styles.evidenceItem} key={explanation.code}>
            <span className={styles.evidenceTag} data-kind="observed">
              Recorded in OpenStreetMap
            </span>
            <span>{explanation.summary}</span>
          </li>
        ))}

        {distance ? (
          <li className={styles.evidenceItem} key={distance.code}>
            <span className={styles.evidenceTag} data-kind="profile">
              Your profile&rsquo;s rules
            </span>
            <span>
              {distance.summary} {comparison.profile_description}
            </span>
          </li>
        ) : null}

        {gradientDerived ? (
          <li className={styles.evidenceItem} key="gradient-provenance">
            <span className={styles.evidenceTag} data-kind="derived">
              Derived from an elevation model
            </span>
            <span>
              {accessible.steepest_incline_percent === null
                ? 'No gradient is recorded on this route, so slope came from a terrain model of the ground rather than a survey of the path.'
                : `The steepest gradient here, ${Math.abs(accessible.steepest_incline_percent ?? 0).toFixed(0)}%, comes from a terrain model of the ground rather than a survey of the path.`}
            </span>
          </li>
        ) : null}

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
