'use client';

import { type ReactNode, useCallback, useRef } from 'react';
import type { ProfileKey } from '@pathable/contracts';
import { type RouteFocus, prefersReducedMotion } from '@/features/map/route-layers';
import { EndpointField } from './EndpointField';
import { RouteComparisonView } from './RouteComparisonView';
import { VerifiedExampleCard } from './VerifiedExample';
import type { VerifiedExample } from './verified-example';
import type { LngLat, PlannerPoints, PointRole, RouteRequestState, StairsTarget } from './types';
import styles from './RoutePlanner.module.css';

/**
 * The profiles offered in the UI.
 *
 * Held here rather than fetched from `/routes/profiles` so the panel renders
 * immediately and stays usable when the backend is down — the profile list is
 * part of the contract, and a network round trip to learn five stable labels
 * would trade a real cost for no benefit. The API still validates the key.
 *
 * The hints are deliberately client-side: the API's `description` is a full
 * sentence rather than a one-line rule summary, and there is no short-hint
 * field to read. They describe what the profile does to the route, and they
 * are engineering judgement rather than a measurement of how anybody travels.
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
  /** True once both endpoints are set and a comparison can be asked for. */
  readonly canCompare: boolean;
  /** True when the draft has moved away from the journey on screen. */
  readonly pendingEdits: boolean;
  /** Which endpoint the next map click fills, if the viewer asked for one. */
  readonly pickTarget: PointRole | null;
  /** The journey the result on screen belongs to, for labelling it. */
  readonly submittedSummary: string | null;
  /** Which route's recorded stairs are highlighted, if any. */
  readonly stairsTarget: StairsTarget;
  /** Which route is brought forward on the map; optional for callers without a map. */
  readonly focusedRoute?: RouteFocus;
  readonly onFocusRoute?: (focus: RouteFocus) => void;
  readonly onShowStairs?: (target: StairsTarget) => void;
  readonly onRunExample: (example: VerifiedExample) => void;
  readonly onProfileChange: (key: ProfileKey) => void;
  readonly onCompare: () => void;
  readonly onClearPoint: (role: PointRole) => void;
  readonly onClearAll: () => void;
  readonly onSwapPoints: () => void;
  readonly onRetry: () => void;
  readonly onSelectPlace: (role: PointRole, position: LngLat, label: string) => void;
  readonly onPickOnMap: (role: PointRole) => void;
  readonly fetchImpl?: typeof fetch;
  /** The page's purpose statement, placed after the controls. */
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
  canCompare,
  pendingEdits,
  pickTarget,
  submittedSummary,
  stairsTarget,
  focusedRoute = null,
  onFocusRoute = () => {},
  onShowStairs = () => {},
  onRunExample,
  onProfileChange,
  onCompare,
  onClearPoint,
  onClearAll,
  onSwapPoints,
  onRetry,
  onSelectPlace,
  onPickOnMap,
  fetchImpl,
  intro,
}: RoutePlannerProps) {
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
          Before there is one this is a single line of instruction, and the
          controls below it are what the viewer came for. The region is always
          rendered and never empty: an aria-live container has to exist before
          anything is put into it, and an empty box is not something a viewer
          can see. */}
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
            {canCompare
              ? 'Both ends are set. Compare routes to see the difference.'
              : 'Name a start and a destination, or set them on the map.'}
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
            stairsTarget={stairsTarget}
            onShowStairs={onShowStairs}
            {...(submittedSummary ? { journeySummary: submittedSummary } : {})}
            pendingEdits={pendingEdits}
          />
        ) : null}
      </div>

      {/* Focusable as a landmark, not as a control: "Edit journey or profile"
          lands here, the heading is announced, and the next Tab reaches the
          start field. */}
      <div
        className={styles.plan}
        ref={planRef}
        tabIndex={-1}
        role="region"
        aria-labelledby="route-planner-heading"
        data-testid="plan-journey"
      >
        <h2 className={styles.planHeading} id="route-planner-heading">
          Plan a journey
        </h2>

        <EndpointField
          role="origin"
          endpoint={points.origin}
          apiBaseUrl={apiBaseUrl}
          region={region}
          picking={pickTarget === 'origin'}
          onSelectPlace={onSelectPlace}
          onPickOnMap={onPickOnMap}
          onClear={onClearPoint}
          {...(fetchImpl ? { fetchImpl } : {})}
        />

        <div className={styles.swapRow}>
          <button
            type="button"
            className={styles.quietButton}
            onClick={onSwapPoints}
            disabled={points.origin === null && points.destination === null}
            data-testid="swap-points"
          >
            Swap start and destination
          </button>
        </div>

        <EndpointField
          role="destination"
          endpoint={points.destination}
          apiBaseUrl={apiBaseUrl}
          region={region}
          picking={pickTarget === 'destination'}
          onSelectPlace={onSelectPlace}
          onPickOnMap={onPickOnMap}
          onClear={onClearPoint}
          {...(fetchImpl ? { fetchImpl } : {})}
        />

        <ProfileChooser selected={profileKey} onChange={onProfileChange} />

        <div className={styles.submitRow}>
          <button
            type="button"
            className={styles.primaryButton}
            onClick={onCompare}
            disabled={!canCompare}
            data-testid="compare-routes"
          >
            {state.status === 'loading' ? 'Comparing…' : 'Compare routes'}
          </button>
          <button
            type="button"
            className={styles.quietButton}
            onClick={onClearAll}
            disabled={points.origin === null && points.destination === null}
            data-testid="clear-journey"
          >
            Clear
          </button>
        </div>

        <VerifiedExampleCard
          example={example}
          onRun={onRunExample}
          active={exampleActive}
          journeyStarted={points.origin !== null || points.destination !== null}
          busy={state.status === 'loading'}
        />
      </div>

      {intro}
    </section>
  );
}

/**
 * The five profiles, as a row of chips and one line of rules.
 *
 * Every profile stays offered and keyboard operation is the browser's own — a
 * real radiogroup, so arrow keys move between them and one Tab stop covers the
 * set. Only the *chosen* profile explains itself: five permanently expanded
 * rule summaries pushed the controls off the first screen, and four of them
 * describe a journey the viewer is not taking.
 *
 * The rule line is not hidden behind anything. Which constraints are applied
 * is the difference between the two routes, and they are engineering judgement
 * rather than measurements of how people with these aids travel — so they have
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
