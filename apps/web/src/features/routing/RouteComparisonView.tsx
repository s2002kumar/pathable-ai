'use client';

import type { Route, RouteCompareResponse } from '@pathable/contracts';
import { formatDistance, formatDuration } from './types';
import styles from './RoutePlanner.module.css';

/**
 * The comparison, in text.
 *
 * This is not a caption for the map — it is the answer, and it has to stand on
 * its own. Somebody using a screen reader, or looking at a phone in bright sun,
 * or deciding whether a journey is possible before leaving the house, gets the
 * whole story here without ever interpreting two coloured lines.
 */
export function RouteComparisonView({ comparison }: { readonly comparison: RouteCompareResponse }) {
  const { standard_route: standard, accessible_route: accessible } = comparison;

  return (
    <div className={styles.results}>
      <RouteHeadline comparison={comparison} />

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

      {comparison.explanations.length > 0 ? (
        <section className={styles.section} aria-labelledby="route-explanations-heading">
          <h3 className={styles.sectionHeading} id="route-explanations-heading">
            Why this route
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

      <ObstacleBreakdown route={accessible ?? standard ?? null} />

      <footer className={styles.provenance}>
        <p>
          Routing uses recorded map attributes only — no predictions, no scoring, no machine
          learning. PathAble advises; it cannot guarantee a journey is passable.
        </p>
        <MapAge dataset={comparison.dataset} />
        <p className={styles.attribution}>
          {comparison.dataset.attribution} · dataset{' '}
          <code>{comparison.dataset.checksum.slice(0, 8)}</code>
        </p>
      </footer>
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

function RouteHeadline({ comparison }: { readonly comparison: RouteCompareResponse }) {
  if (comparison.accessible_route === null) {
    return (
      <p className={styles.headlineBad} role="status">
        {comparison.accessible_failure ??
          `No route meets the ${comparison.profile_display_name.toLowerCase()} profile between these points.`}
      </p>
    );
  }

  if (comparison.standard_route === null) {
    return (
      <p className={styles.headline} role="status">
        A route was found for {comparison.profile_display_name.toLowerCase()}.
      </p>
    );
  }

  const extra = comparison.extra_distance_m ?? 0;
  if (Math.abs(extra) < 15) {
    return (
      <p className={styles.headlineGood} role="status">
        The accessible route is the same length as the shortest route.
      </p>
    );
  }

  const fraction = comparison.extra_distance_fraction ?? 0;
  return (
    <p className={styles.headline} role="status">
      The accessible route is <strong>{formatDistance(Math.abs(extra))}</strong>{' '}
      {extra > 0 ? 'longer' : 'shorter'} than the shortest route
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
    <section className={styles.section} aria-labelledby="route-detail-heading">
      <h3 className={styles.sectionHeading} id="route-detail-heading">
        What is on this route
      </h3>
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
