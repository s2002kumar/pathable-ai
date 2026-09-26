'use client';

import type { RouteCompareResponse } from '@pathable/contracts';
import {
  EvidenceCoverage,
  ReasonGroups,
  RouteDifference,
  SingleRoute,
  UncertaintySummary,
  routeLabel,
} from './RouteDifference';
import { type RouteVariant, exclusionLabel, exclusionsOf, verdictOf } from './route-evidence';
import { formatDistance } from './types';
import styles from './RoutePlanner.module.css';

/**
 * The comparison, in text.
 *
 * This is not a caption for the map — it is the answer, and it has to stand on
 * its own. Somebody using a screen reader, or looking at a phone in bright sun,
 * or deciding whether a journey is possible before leaving the house, gets the
 * whole story here without ever interpreting two coloured lines.
 *
 * Order is the design: the verdict and the two routes first, the reason that
 * decided it, and how much of the route the map is silent about — all on the
 * first screen. Then every reason by topic, then the per-category record, and
 * where the data came from last.
 */
export function RouteComparisonView({
  comparison,
  selectedRoute,
  onSelectRoute = () => {},
  onEditJourney,
  journeySummary,
  pendingEdits = false,
}: {
  readonly comparison: RouteCompareResponse;
  /** Which route the map brings forward; the profile's own route by default. */
  readonly selectedRoute?: RouteVariant;
  readonly onSelectRoute?: (variant: RouteVariant) => void;
  /** Takes the viewer to the planning controls below, keeping this result. */
  readonly onEditJourney?: () => void;
  /** The journey this answer belongs to, named. */
  readonly journeySummary?: string;
  /** True when the panel's draft has moved on from that journey. */
  readonly pendingEdits?: boolean;
}) {
  const { standard_route: standard, accessible_route: accessible } = comparison;
  const bothRoutes = Boolean(standard && accessible);
  // The route the detail below describes: the chosen one, or whichever exists.
  const shown: RouteVariant =
    bothRoutes && selectedRoute ? selectedRoute : accessible ? 'accessible' : 'standard';
  const shownRoute = shown === 'standard' ? standard : accessible;

  return (
    <div className={styles.results}>
      <div className={styles.result}>
        {/* The answer names the journey it answered. Without this, editing an
            endpoint would leave a figure on screen that looks current and is
            not — the one way a comparison can lie without a single wrong
            number in it. */}
        {journeySummary ? (
          <p className={styles.journeyLine} data-testid="journey-summary">
            <span className={styles.journeyPlaces}>{journeySummary}</span>
            <span className={styles.journeyProfile}>{comparison.profile_display_name}</span>
            {onEditJourney ? (
              <button
                type="button"
                className={styles.editButton}
                onClick={onEditJourney}
                // The accessible name is the full phrase at every width; only
                // the glyphs shorten, because at 390 px the five-word label
                // wrapped the journey line to three lines.
                aria-label="Edit journey or profile"
                data-testid="edit-journey"
              >
                <span className={styles.editLong}>Edit journey or profile</span>
                <span className={styles.editShort}>Edit</span>
              </button>
            ) : null}
          </p>
        ) : null}

        {pendingEdits ? (
          <p className={styles.staleNote} role="status" data-testid="stale-result">
            You have changed the journey. This answer is still for the one named above — press
            Compare routes to update it.
          </p>
        ) : null}

        <RouteHeadline comparison={comparison} />

        {bothRoutes ? (
          <RouteDifference
            comparison={comparison}
            selectedRoute={shown}
            onSelectRoute={onSelectRoute}
          />
        ) : (
          <div className={styles.options}>
            {accessible ? <SingleRoute comparison={comparison} variant="accessible" /> : null}
            {standard ? <SingleRoute comparison={comparison} variant="standard" /> : null}
          </div>
        )}

        {shownRoute ? <UncertaintySummary route={shownRoute} /> : null}
      </div>

      <ReasonGroups comparison={comparison} />

      {shownRoute ? (
        <EvidenceCoverage route={shownRoute} label={routeLabel(comparison, shown)} />
      ) : null}

      {comparison.cautions.length > 0 ? (
        <section className={styles.section} aria-labelledby="route-cautions-heading">
          <h3 className={styles.sectionHeading} id="route-cautions-heading">
            Before you rely on this
          </h3>
          <ul className={styles.cautionList}>
            {comparison.cautions.map((caution) => (
              <li key={caution.code} className={styles.caution}>
                {caution.summary}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* The statements behind a single route, where there is no pair to group
          them under. */}
      {comparison.explanations.length > 0 && !bothRoutes ? (
        <section className={styles.section} aria-labelledby="route-explanations-heading">
          <h3 className={styles.sectionHeading} id="route-explanations-heading">
            Every statement behind this route
          </h3>
          <ul className={styles.reasonList}>
            {comparison.explanations.map((explanation) => (
              <li key={explanation.code} className={styles.reason}>
                {explanation.summary}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <details className="disclosure" data-testid="route-provenance">
        <summary>Where this comes from</summary>
        <div className={`${styles.disclosureBody} ${styles.provenance}`}>
          <p>
            “Recorded” means a mapper wrote it down in OpenStreetMap. “Estimated from elevation”
            means PathAble derived it from a terrain model of the ground. “Not recorded” means
            nobody has.
          </p>
          <MapAge dataset={comparison.dataset} />
          <p className={styles.attribution}>
            {comparison.dataset.attribution} · dataset{' '}
            <code>{comparison.dataset.checksum.slice(0, 8)}</code>
          </p>
          <p>
            Routing policy <code>{comparison.routing_policy_version}</code>. Machine-learning
            predictions used: <code>{String(comparison.ml_predictions_used)}</code>.
          </p>
        </div>
      </details>

      {/* Outside the disclosure above, deliberately. The elevation licence
          asks to be carried by anything that uses the data, and a credit
          somebody has to open a control to find is not being carried. The
          map's own OpenStreetMap attribution is always on the canvas; this is
          the one that would otherwise have been hidden. */}
      {comparison.dataset.elevation_attribution ? (
        <p className={styles.attribution} data-testid="elevation-attribution">
          {comparison.dataset.elevation_attribution}
        </p>
      ) : null}

      <p className={styles.noModel}>
        Routing uses recorded map attributes only — no predictions, no scoring, no machine learning.
        PathAble advises; it cannot guarantee a journey is passable.
      </p>
    </div>
  );
}

/** Beyond this the map is old enough that a user should be told plainly. */
const STALE_AFTER_DAYS = 180;

/**
 * How old the map is.
 *
 * Reported against when the source published the data, not when PathAble
 * fetched it — an extract downloaded this morning from a two-year-old
 * publication is two years old, and reporting the download date would make
 * stale data look fresh.
 */
function MapAge({ dataset }: { readonly dataset: RouteCompareResponse['dataset'] }) {
  const days = dataset.evidence_age_days;
  if (days === null || days === undefined) return null;

  const when = days === 0 ? 'today' : days === 1 ? 'yesterday' : `${days} days ago`;

  return (
    <p className={styles.attribution}>
      Map data published {when}.
      {days >= STALE_AFTER_DAYS
        ? ' Anything changed since then — kerbs, closures, resurfacing — is not reflected here.'
        : ''}
    </p>
  );
}

/**
 * The one-sentence answer.
 *
 * It states the difference the response reports, in the profile's own name,
 * and it never rounds a real difference away: a 10 m detour is "10 m longer".
 * The only time it says "the same length" is when the two distances display
 * as the same number — differences under half a metre — and then it says "to
 * the nearest metre". "The same route" is said only from segment identity. A
 * missing difference is reported as missing, not as equality.
 *
 * When no route meets the profile it says so calmly, says what rules the
 * shortest route out, and says the limits were not loosened to find one:
 * quietly relaxing them would hand back a route the traveller told us they
 * cannot use.
 */
function RouteHeadline({ comparison }: { readonly comparison: RouteCompareResponse }) {
  const profile = comparison.profile_display_name.toLowerCase();
  const verdict = verdictOf(comparison);

  switch (verdict.kind) {
    case 'no_accessible_route': {
      const blocked = exclusionsOf(comparison.standard_route);
      return (
        <div className={styles.noRoute} role="status" data-testid="no-accessible-route">
          <p className={styles.noRouteTitle}>
            No route meets the {profile} profile between these points.
          </p>
          {blocked.length > 0 ? (
            <p>
              The shortest walking route is ruled out by {blocked.map(exclusionLabel).join(', ')}.
            </p>
          ) : null}
          {verdict.failure ? <p className={styles.noRouteDetail}>{verdict.failure}</p> : null}
          <p className={styles.noRouteDetail}>
            PathAble does not loosen your profile’s limits to find one.
          </p>
        </div>
      );
    }
    case 'no_shortest_route':
      return (
        <p className={styles.headline} role="status">
          A route was found for {profile}.
        </p>
      );
    case 'difference_not_reported':
      return (
        <p className={styles.headline} role="status">
          A {profile} route and the shortest walking route were both found; the response did not
          report the difference in length.
        </p>
      );
    case 'same_route':
      return (
        <p className={styles.headlineGood} role="status">
          The shortest walking route already fits the {profile} profile’s rules — both are the same
          route.
        </p>
      );
    case 'same_length':
      return (
        <p className={styles.headlineGood} role="status">
          The {profile} route and the shortest walking route are the same length to the nearest
          metre.
        </p>
      );
    case 'shorter':
      return (
        <p className={styles.headline} role="status">
          The {profile} route is{' '}
          <strong className="tabular">{formatDistance(verdict.savedM)}</strong> shorter than the
          shortest walking route.
        </p>
      );
    case 'detour': {
      const fraction = verdict.fraction ?? 0;
      return (
        <p className={styles.headline} role="status">
          The {profile} route is{' '}
          <strong className="tabular">{formatDistance(verdict.extraM)}</strong> longer than the
          shortest walking route
          {Math.abs(fraction) >= 0.01 ? ` (${Math.round(Math.abs(fraction) * 100)}%)` : ''}.
        </p>
      );
    }
  }
}
