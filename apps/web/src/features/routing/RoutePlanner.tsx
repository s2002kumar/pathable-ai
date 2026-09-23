'use client';

import { type ReactNode, useCallback, useRef } from 'react';
import type { ProfileKey } from '@pathable/contracts';
import { PlaceSearch } from '@/features/geocoding/PlaceSearch';
import { type RouteFocus, prefersReducedMotion } from '@/features/map/route-layers';
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
  /** Which route is brought forward on the map; optional for callers without a map. */
  readonly focusedRoute?: RouteFocus;
  readonly onFocusRoute?: (focus: RouteFocus) => void;
  readonly onRunExample: (example: VerifiedExample) => void;
  readonly onProfileChange: (key: ProfileKey) => void;
  readonly onClearPoints: () => void;
  readonly onSwapPoints: () => void;
  readonly onRetry: () => void;
  readonly onSelectPlace: (position: LngLat) => void;
  readonly fetchImpl?: typeof fetch;
  /** The page's purpose statement, placed after the answer and before the controls. */
  readonly intro?: ReactNode;
};

export function RoutePlanner({
  points,
  profileKey,
  state,
  apiBaseUrl,
  region,
  example,
  exampleActive,
  focusedRoute = null,
  onFocusRoute = () => {},
  onRunExample,
  onProfileChange,
  onClearPoints,
  onSwapPoints,
  onRetry,
  onSelectPlace,
  fetchImpl,
  intro,
}: RoutePlannerProps) {
  const awaitingEnd = points.origin !== null && points.destination === null;
  const planRef = useRef<HTMLDivElement>(null);

  // "Edit journey or profile" from the result: scroll the planning section
  // into view and move focus to it. Nothing about the request changes — the
  // comparison stays rendered and the map keeps its routes — the viewer is
  // simply taken to the controls that are already there. A reduced-motion
  // preference makes the scroll instant.
  const handleEditJourney = useCallback(() => {
    const plan = planRef.current;
    if (plan === null) return;
    if (typeof plan.scrollIntoView === 'function') {
      plan.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
    }
    plan.focus({ preventScroll: true });
  }, []);

  return (
    <section className={styles.panel} aria-labelledby="route-planner-heading">
      {/* The answer, at the top of the panel.

          PA-RR-06 measured the failure this avoids: with the *inputs* above
          it, pressing the example changed the map and left the panel showing
          the coordinates it had just filled in, with the comparison two
          screens down. Putting the result first is that finding taken
          further — it is what makes the figures, the detour and the
          uncertainty line fit together inside a phone's sheet.

          Before there is an answer this is one line of instruction, and the
          offer below it is still the first thing the keyboard reaches. The
          region is always rendered and never empty: an aria-live container
          has to exist before anything is put into it, and an empty box is
          not something a viewer can see. */}
      <div
        className={styles.status}
        // Results replace one another in place, so the region has to announce
        // itself rather than relying on focus moving somewhere.
        aria-live="polite"
        aria-busy={state.status === 'loading'}
        data-route-state={state.status}
        data-testid="route-status"
      >
        {state.status === 'idle' && !awaitingEnd ? (
          <p className={styles.hint}>
            Click the map to set a start and an end, or run the example below.
          </p>
        ) : null}

        {state.status === 'idle' && awaitingEnd ? (
          <p className={styles.hint} data-testid="awaiting-end">
            Start is set. Click the map again, or search for a place, to set the end.
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

        {state.status === 'success' ? (
          <RouteComparisonView
            comparison={state.comparison}
            focusedRoute={focusedRoute}
            onFocusRoute={onFocusRoute}
            onEditJourney={handleEditJourney}
          />
        ) : null}
      </div>

      {/* One slot, whatever the state. Rendering it above the result while
          planning and below it afterwards would move it in the DOM, and a
          keyboard user who pressed it would have their focus dropped on the
          floor the moment the answer arrived. */}
      <VerifiedExampleCard
        example={example}
        onRun={onRunExample}
        active={exampleActive}
        journeyStarted={points.origin !== null || points.destination !== null}
        busy={state.status === 'loading'}
      />

      {/* Focusable as a landmark, not as a control: "Edit journey or profile"
          lands here, the heading is announced, and the next Tab reaches the
          search box. */}
      <div
        className={styles.plan}
        ref={planRef}
        tabIndex={-1}
        role="region"
        aria-labelledby="route-planner-heading"
        data-testid="plan-journey"
      >
        <h2 className={styles.planHeading} id="route-planner-heading">
          Plan your own journey
        </h2>

        <PlaceSearch
          apiBaseUrl={apiBaseUrl}
          region={region}
          onSelect={onSelectPlace}
          {...(fetchImpl ? { fetchImpl } : {})}
        />

        <PointFields points={points} onClear={onClearPoints} onSwap={onSwapPoints} />

        <ProfileChooser selected={profileKey} onChange={onProfileChange} />
      </div>

      {intro}
    </section>
  );
}

/**
 * The five profiles, as a row of chips and one line of rules.
 *
 * Every profile stays offered and keyboard operation is the browser's own —
 * a real radiogroup, so arrow keys move between them and one Tab stop covers
 * the set. What changed is that only the *chosen* profile explains itself:
 * five permanently expanded cards, each with its own rule summary, pushed the
 * answer off the first screen of a floating panel, and four of those summaries
 * describe a journey the viewer is not taking.
 *
 * The rule line is not hidden behind anything. Which constraints are being
 * applied is the difference between two routes, and a viewer who cannot see it
 * cannot read the comparison — and these constraints are engineering judgement,
 * not measurements of how people with these aids actually travel, so they have
 * to be inspectable.
 */
function ProfileChooser({
  selected,
  onChange,
}: {
  readonly selected: ProfileKey;
  readonly onChange: (key: ProfileKey) => void;
}) {
  const chosen = PROFILE_OPTIONS.find((option) => option.key === selected);

  return (
    <fieldset className={styles.fieldset}>
      <legend className={styles.legend}>How do you travel?</legend>
      <div className={styles.profiles} role="radiogroup" aria-label="Mobility profile">
        {PROFILE_OPTIONS.map((option) => (
          <label
            key={option.key}
            className={styles.profileOption}
            data-selected={option.key === selected}
          >
            <input
              type="radio"
              name="mobility-profile"
              value={option.key}
              checked={option.key === selected}
              onChange={() => onChange(option.key)}
              className={styles.profileInput}
            />
            <span className={styles.profileLabel}>{option.label}</span>
          </label>
        ))}
      </div>
      {chosen ? (
        <p className={styles.profileRule} data-testid="profile-rule">
          {chosen.hint}
        </p>
      ) : null}
    </fieldset>
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
