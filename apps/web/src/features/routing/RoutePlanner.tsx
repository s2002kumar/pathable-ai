'use client';

import type { ProfileKey } from '@pathable/contracts';
import { PlaceSearch } from '@/features/geocoding/PlaceSearch';
import { RouteComparisonView } from './RouteComparisonView';
import { VerifiedExampleCard } from './VerifiedExample';
import type { VerifiedExample } from './verified-example';
import {
  type LngLat,
  type PlannerPoints,
  type RouteRequestState,
  formatCoordinate,
  nextRole,
} from './types';
import styles from './RoutePlanner.module.css';

/**
 * The profiles offered in the UI.
 *
 * Held here rather than fetched from `/routes/profiles` so the panel renders
 * immediately and stays usable when the backend is down — the profile list is
 * part of the contract, and a network round trip to learn five stable labels
 * would trade a real cost for no benefit. The API still validates the key.
 */
const PROFILE_OPTIONS: ReadonlyArray<{ key: ProfileKey; label: string; hint: string }> = [
  { key: 'wheelchair', label: 'Wheelchair', hint: 'No steps, paved surfaces, gentle grades' },
  { key: 'walker', label: 'Walker or rollator', hint: 'No steps, even surfaces' },
  { key: 'crutches', label: 'Crutches or cane', hint: 'Steps allowed but avoided where possible' },
  { key: 'stroller', label: 'Stroller or pram', hint: 'No steps, dropped kerbs preferred' },
  { key: 'reduced_mobility', label: 'Reduced mobility', hint: 'Shorter, flatter, smoother' },
];

/**
 * Presentational: every piece of state lives in the workspace above it.
 *
 * The routes have to be drawn on the map *and* described here, so the request
 * cannot live inside this component without the map reaching into it.
 */
export type RoutePlannerProps = {
  readonly points: PlannerPoints;
  readonly profileKey: ProfileKey;
  readonly state: RouteRequestState;
  readonly apiBaseUrl: string;
  readonly region: string;
  readonly example: VerifiedExample;
  readonly exampleActive: boolean;
  readonly onRunExample: (example: VerifiedExample) => void;
  readonly onProfileChange: (key: ProfileKey) => void;
  readonly onClearPoints: () => void;
  readonly onSwapPoints: () => void;
  readonly onRetry: () => void;
  readonly onSelectPlace: (position: LngLat) => void;
  readonly fetchImpl?: typeof fetch;
};

export function RoutePlanner({
  points,
  profileKey,
  state,
  apiBaseUrl,
  region,
  example,
  exampleActive,
  onRunExample,
  onProfileChange,
  onClearPoints,
  onSwapPoints,
  onRetry,
  onSelectPlace,
  fetchImpl,
}: RoutePlannerProps) {
  return (
    <section className={styles.panel} aria-labelledby="route-planner-heading">
      <header className={styles.header}>
        <p className={styles.eyebrow}>Plan a journey</p>
        <h2 className={styles.title} id="route-planner-heading">
          Compare routes
        </h2>
      </header>

      <VerifiedExampleCard
        example={example}
        onRun={onRunExample}
        active={exampleActive}
        busy={state.status === 'loading'}
      />

      {/* Directly under the example, because that is where the answer to
          pressing it belongs. Measured during the PA-RR-06 audit: with the
          inputs above it, pressing the example changed the map and left the
          panel showing the coordinates it had just filled in, with the
          comparison two screens down. The region is always rendered and
          never empty — an aria-live container has to exist before anything
          is put into it, and an empty box is not something a viewer can
          see. */}
      <div
        className={styles.status}
        // Results replace one another in place, so the region has to announce
        // itself rather than relying on focus moving somewhere.
        aria-live="polite"
        aria-busy={state.status === 'loading'}
        data-route-state={state.status}
        data-testid="route-status"
      >
        {state.status === 'idle' ? (
          <p className={styles.hint}>
            Choose a start and an end on the map, or press the example above, and PathAble will
            compare the shortest walking route with one that suits how you travel.
          </p>
        ) : null}

        {state.status === 'loading' ? (
          <p className={styles.hint}>
            Comparing routes… The first request after the service starts also waits for the Waterloo
            routing graph to load.
          </p>
        ) : null}

        {state.status === 'error' ? (
          <div className={styles.error} role="alert">
            <p>{state.message}</p>
            <button type="button" className={styles.secondaryButton} onClick={onRetry}>
              Try again
            </button>
          </div>
        ) : null}

        {state.status === 'success' ? <RouteComparisonView comparison={state.comparison} /> : null}
      </div>

      <PlaceSearch
        apiBaseUrl={apiBaseUrl}
        region={region}
        onSelect={onSelectPlace}
        {...(fetchImpl ? { fetchImpl } : {})}
      />

      <PointFields points={points} onClear={onClearPoints} onSwap={onSwapPoints} />

      <fieldset className={styles.fieldset}>
        <legend className={styles.legend}>How do you travel?</legend>
        <div className={styles.profiles} role="radiogroup" aria-label="Mobility profile">
          {PROFILE_OPTIONS.map((option) => (
            <label
              key={option.key}
              className={styles.profileOption}
              data-selected={option.key === profileKey}
            >
              <input
                type="radio"
                name="mobility-profile"
                value={option.key}
                checked={option.key === profileKey}
                onChange={() => onProfileChange(option.key)}
                className={styles.profileInput}
              />
              <span className={styles.profileLabel}>{option.label}</span>
              <span className={styles.profileHint}>{option.hint}</span>
            </label>
          ))}
        </div>
      </fieldset>
    </section>
  );
}

function PointFields({
  points,
  onClear,
  onSwap,
}: {
  readonly points: PlannerPoints;
  readonly onClear: () => void;
  readonly onSwap: () => void;
}) {
  const pending = nextRole(points);

  return (
    <div className={styles.points}>
      <PointRow
        label="Start"
        marker="A"
        point={points.origin}
        awaiting={points.origin === null && pending === 'origin'}
      />
      <PointRow
        label="End"
        marker="B"
        point={points.destination}
        awaiting={points.destination === null && pending === 'destination'}
      />

      <div className={styles.pointActions}>
        <button
          type="button"
          className={styles.secondaryButton}
          onClick={onSwap}
          disabled={points.origin === null || points.destination === null}
        >
          Swap
        </button>
        <button
          type="button"
          className={styles.secondaryButton}
          onClick={onClear}
          disabled={points.origin === null && points.destination === null}
        >
          Clear
        </button>
      </div>
    </div>
  );
}

function PointRow({
  label,
  marker,
  point,
  awaiting,
}: {
  readonly label: string;
  readonly marker: string;
  readonly point: LngLat | null;
  readonly awaiting: boolean;
}) {
  return (
    <div
      className={styles.point}
      data-awaiting={awaiting}
      data-testid={`point-${label.toLowerCase()}`}
    >
      <span className={styles.pointMarker} data-marker={marker} aria-hidden="true">
        {marker}
      </span>
      <span className={styles.pointLabel}>{label}</span>
      <span className={styles.pointValue}>
        {point === null ? (
          <span className={styles.pointEmpty}>{awaiting ? 'Click the map to set' : 'Not set'}</span>
        ) : (
          formatCoordinate(point)
        )}
      </span>
    </div>
  );
}
