'use client';

import type { RouteCompareResponse } from '@pathable/contracts';
import { formatDistance } from './types';
import styles from './RoutePlanner.module.css';

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
export function RouteDifference({ comparison }: { readonly comparison: RouteCompareResponse }) {
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

  return (
    <section
      className={styles.difference}
      aria-labelledby="route-difference-heading"
      data-testid="route-difference"
    >
      <h3 className={styles.differenceHeading} id="route-difference-heading">
        Why are they different?
      </h3>

      <dl className={styles.differenceFigures}>
        <div className={styles.differenceFigure} data-testid="difference-shortest">
          <dt>Shortest walking route</dt>
          <dd>
            {formatDistance(standard.distance_m)}
            <span className={styles.differenceNote}>
              {standard.stairway_count === 0
                ? 'no stairways'
                : `${standard.stairway_count} ${standard.stairway_count === 1 ? 'stairway' : 'stairways'}`}
            </span>
          </dd>
        </div>
        <div className={styles.differenceFigure} data-testid="difference-accessible">
          <dt>{comparison.profile_display_name} route</dt>
          <dd>
            {formatDistance(accessible.distance_m)}
            <span className={styles.differenceNote}>
              {accessible.stairway_count === 0
                ? 'no stairways'
                : `${accessible.stairway_count} ${accessible.stairway_count === 1 ? 'stairway' : 'stairways'}`}
            </span>
          </dd>
        </div>
        <div className={styles.differenceFigure} data-testid="difference-extra">
          <dt>Extra distance</dt>
          <dd>
            {typeof comparison.extra_distance_m === 'number'
              ? `${comparison.extra_distance_m >= 0 ? '+' : '−'}${formatDistance(Math.abs(comparison.extra_distance_m))}`
              : 'None'}
            {stairsAvoided > 0 ? (
              <span className={styles.differenceNote}>
                to avoid {stairsAvoided} {stairsAvoided === 1 ? 'stairway' : 'stairways'}
              </span>
            ) : null}
          </dd>
        </div>
      </dl>

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
              OpenStreetMap has no accessibility details for {Math.round(unknownShare * 100)}% of
              this route. That is missing information, not a clear path, and it is why this
              comparison advises rather than guarantees.
            </span>
          </li>
        ) : null}
      </ul>
    </section>
  );
}
