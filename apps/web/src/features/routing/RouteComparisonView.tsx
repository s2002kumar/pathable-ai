'use client';

import type { Route, RouteCompareResponse } from '@pathable/contracts';
import type { RouteFocus } from '@/features/map/route-layers';
import { RouteDifference } from './RouteDifference';
import { differenceIsBelowDisplayPrecision } from './route-identity';
import type { StairsTarget } from './types';
import { formatDistance, formatDuration } from './types';
import styles from './RoutePlanner.module.css';

/**
 * The comparison, in text.
 *
 * This is not a caption for the map — it is the answer, and it has to stand on
 * its own. Somebody using a screen reader, or looking at a phone in bright sun,
 * or deciding whether a journey is possible before leaving the house, gets the
 * whole story here without ever interpreting two coloured lines.
 *
 * Order matters: the headline and the figures first, the per-route cards and
 * cautions next, and the fuller detail — what is on the route, where the data
 * came from — behind labelled disclosures. Nothing is removed; the parts a
 * viewer opens are the parts they asked for.
 */
export function RouteComparisonView({
  comparison,
  focusedRoute = null,
  onFocusRoute = () => {},
  onEditJourney,
  stairsTarget = null,
  onShowStairs = () => {},
  journeySummary,
  pendingEdits = false,
}: {
  readonly comparison: RouteCompareResponse;
  readonly focusedRoute?: RouteFocus;
  readonly onFocusRoute?: (focus: RouteFocus) => void;
  /** Takes the viewer to the planning controls below, keeping this result. */
  readonly onEditJourney?: () => void;
  readonly stairsTarget?: StairsTarget;
  readonly onShowStairs?: (target: StairsTarget) => void;
  /** The journey this answer belongs to, named. */
  readonly journeySummary?: string;
  /** True when the panel's draft has moved on from that journey. */
  readonly pendingEdits?: boolean;
}) {
  const { standard_route: standard, accessible_route: accessible } = comparison;
  const bothRoutes = Boolean(standard && accessible);

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
          </p>
        ) : null}

        {pendingEdits ? (
          <p className={styles.staleNote} role="status" data-testid="stale-result">
            You have changed the journey. This answer is still for the one named above — press
            Compare routes to update it.
          </p>
        ) : null}

        <RouteHeadline comparison={comparison} />
        <RouteDifference
          comparison={comparison}
          focusedRoute={focusedRoute}
          onFocusRoute={onFocusRoute}
          stairsTarget={stairsTarget}
          onShowStairs={onShowStairs}
          {...(onEditJourney ? { onEditJourney } : {})}
        />
      </div>

      {/* Only where there is nothing to compare against. With both routes
          present, `RouteDifference` above already carries each route's
          distance, walking time and stairways beside the control that
          highlights it on the map; a second pair of cards repeating those
          figures was the longest block in the panel and said nothing new. */}
      {bothRoutes ? null : (
        <div className={styles.routeCards}>
          {accessible ? (
            <RouteCard
              route={accessible}
              label={comparison.profile_display_name}
              variant="accessible"
              emphasis
            />
          ) : null}
          {standard ? (
            <RouteCard route={standard} label="Shortest walking route" variant="standard" />
          ) : null}
        </div>
      )}

      {/* RouteDifference above already carries these statements, sorted by
          where each came from. It only renders when there are two routes to
          compare, so this stays for the single-route cases. */}
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

      <details className="disclosure" data-testid="route-detail">
        <summary>What is on this route</summary>
        <div className={styles.disclosureBody}>
          <ObstacleBreakdown route={accessible ?? standard ?? null} />
        </div>
      </details>

      <details className="disclosure" data-testid="route-provenance">
        <summary>Where this comes from</summary>
        <div className={`${styles.disclosureBody} ${styles.provenance}`}>
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
 * as the same number — differences under half a metre, the display precision
 * of `formatDistance` — and then it says "to the nearest metre". A missing
 * difference is reported as missing, not as equality. Nothing here says the
 * routes are the same path; that is a question of geometry, answered by
 * `routesSharePath` from the response's own segments.
 */
function RouteHeadline({ comparison }: { readonly comparison: RouteCompareResponse }) {
  const profile = comparison.profile_display_name.toLowerCase();

  if (comparison.accessible_route === null) {
    return (
      <p className={styles.headlineBad} role="status">
        {comparison.accessible_failure ??
          `No route meets the ${profile} profile between these points.`}
      </p>
    );
  }

  if (comparison.standard_route === null) {
    return (
      <p className={styles.headline} role="status">
        A route was found for {profile}.
      </p>
    );
  }

  const extra = comparison.extra_distance_m;
  if (typeof extra !== 'number') {
    return (
      <p className={styles.headline} role="status">
        A {profile} route and the shortest walking route were both found; the response did not
        report the difference in length.
      </p>
    );
  }

  if (differenceIsBelowDisplayPrecision(extra)) {
    return (
      <p className={styles.headlineGood} role="status">
        The {profile} route and the shortest walking route are the same length to the nearest metre.
      </p>
    );
  }

  const fraction = comparison.extra_distance_fraction ?? 0;
  return (
    <p className={styles.headline} role="status">
      The {profile} route is <strong className="tabular">{formatDistance(Math.abs(extra))}</strong>{' '}
      {extra > 0 ? 'longer' : 'shorter'} than the shortest walking route
      {Math.abs(fraction) >= 0.01 ? ` (${Math.round(Math.abs(fraction) * 100)}%)` : ''}.
    </p>
  );
}

function RouteCard({
  route,
  label,
  variant,
  emphasis = false,
}: {
  readonly route: Route;
  readonly label: string;
  readonly variant: 'standard' | 'accessible';
  readonly emphasis?: boolean;
}) {
  return (
    <article
      className={emphasis ? `${styles.routeCard} ${styles.routeCardPrimary}` : styles.routeCard}
      data-variant={variant}
      data-testid={`route-card-${variant}`}
    >
      <header className={styles.routeCardHeader}>
        {/* A swatch alone would not be a label; the text carries the meaning and
            the swatch only helps someone match it to the map. */}
        <span className={styles.swatch} data-variant={variant} aria-hidden="true" />
        <h3 className={styles.routeCardTitle}>{label}</h3>
      </header>
      <dl className={styles.stats}>
        <div className={styles.stat}>
          <dt>Distance</dt>
          <dd>{formatDistance(route.distance_m)}</dd>
        </div>
        <div className={styles.stat}>
          <dt>Estimated time</dt>
          <dd>{formatDuration(route.estimated_duration_seconds)}</dd>
        </div>
        <div className={styles.stat}>
          <dt>Stairways</dt>
          <dd>
            {route.stairway_count === 0
              ? 'None'
              : `${route.stairway_count}${route.step_count > 0 ? ` (${route.step_count} steps)` : ''}`}
          </dd>
        </div>
      </dl>
    </article>
  );
}

/** How each missing category reads in a sentence, singular to the user's concern. */
const GAP_LABELS: Readonly<Record<string, string>> = {
  surface: 'Surface data is missing',
  smoothness: 'Surface condition is missing',
  gradient: 'Gradient data is missing',
  width: 'Path width is missing',
  kerb: 'Kerb information is missing',
};

/** Below this, naming the gap is noise rather than information. */
const GAP_THRESHOLD = 0.05;

/**
 * What the map does not say about this route, one category at a time.
 *
 * "Surface data is missing for 38% of this route" tells somebody what to expect
 * and what to check. A single combined uncertainty figure does not: a route
 * missing every surface tag and one missing every gradient produce the same
 * number and are completely different journeys.
 */
function EvidenceGaps({ route }: { readonly route: Route | null }) {
  if (route === null) return null;

  const gaps = Object.entries(route.evidence_coverage ?? {})
    .filter(([category, share]) => share >= GAP_THRESHOLD && category in GAP_LABELS)
    .sort(([, a], [, b]) => b - a);

  if (gaps.length === 0) return null;

  return (
    <section className={styles.section} aria-labelledby="route-gaps-heading">
      <h3 className={styles.sectionHeading} id="route-gaps-heading">
        What the map does not say
      </h3>
      <ul className={styles.cautionList}>
        {gaps.map(([category, share]) => (
          <li className={styles.caution} key={category}>
            {GAP_LABELS[category]} for {Math.round(share * 100)}% of this route
            {category === 'kerb' ? "'s crossings" : ''}.
          </li>
        ))}
      </ul>
      <p className={styles.hint}>
        Missing information is not a sign that a path is clear. It means nobody has recorded it.
      </p>
    </section>
  );
}

/** Whether a gradient was measured on the path or inferred from the terrain. */
function GradientProvenance({ route }: { readonly route: Route | null }) {
  if (route === null || route.steepest_incline_percent === null) return null;

  switch (route.gradient_source) {
    case 'derived_elevation':
      return (
        <p className={styles.hint}>
          Gradient is estimated from an elevation model of the ground, not surveyed on the path
          itself, so it cannot see a ramp or a step.
        </p>
      );
    case 'mixed':
      return (
        <p className={styles.hint}>
          Some gradients here are recorded in OpenStreetMap; the rest are estimated from an
          elevation model of the ground.
        </p>
      );
    case 'osm_incline':
      return <p className={styles.hint}>Gradient is as recorded in OpenStreetMap.</p>;
    default:
      return null;
  }
}

/**
 * What the route actually contains.
 *
 * Reported as counts of recorded facts, with unknowns named as unknowns. An
 * "accessibility score" would be easier to read and would be an invention.
 */
function ObstacleBreakdown({ route }: { readonly route: Route | null }) {
  if (route === null) return null;

  return (
    <section className={styles.section} aria-label="What is on this route">
      <dl className={styles.stats}>
        <div className={styles.stat}>
          <dt>Road crossings</dt>
          <dd>{route.crossing_count}</dd>
        </div>
        <div className={styles.stat}>
          <dt>Crossings with no recorded kerb</dt>
          <dd>{route.unknown_kerb_crossing_count}</dd>
        </div>
        <div className={styles.stat}>
          <dt>Steepest recorded gradient</dt>
          <dd>
            {route.steepest_incline_percent === null
              ? 'Not recorded'
              : `${Math.abs(route.steepest_incline_percent).toFixed(0)}%`}
          </dd>
        </div>
      </dl>
      <GradientProvenance route={route} />
      <EvidenceGaps route={route} />
    </section>
  );
}
