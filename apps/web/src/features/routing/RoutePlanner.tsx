'use client';

import { type ReactNode, useCallback, useId, useRef } from 'react';
import type { ProfileKey } from '@pathable/contracts';
import { prefersReducedMotion } from '@/features/map/route-layers';
import { EndpointField } from './EndpointField';
import { RouteComparisonView } from './RouteComparisonView';
import { VerifiedExampleCard } from './VerifiedExample';
import { type ProfilesState, profileRuleLines } from './mobility-profiles';
import type { RouteVariant } from './route-evidence';
import type { VerifiedExample } from './verified-example';
import {
  type LngLat,
  NO_UPHILL_LIMIT,
  type PlannerPoints,
  type PointRole,
  type RouteRequestState,
  type UphillLimit,
  parseUphillLimit,
} from './types';
import styles from './RoutePlanner.module.css';

/**
 * The five profiles, by key and chip label.
 *
 * Labels only. What each profile rules out and prefers is routing policy, and
 * it is read from `/routes/profiles` — the same definitions that choose the
 * route — rather than restated here. The labels are held locally so the
 * control renders at once and stays usable while the service is waking up;
 * the API still validates the key, and the answer is headed with the API's
 * own full name for the profile.
 *
 * Short, and in this order, so the five chips sit on two lines in the
 * narrowest panel: "Walker or rollator" alone pushed them onto a third, and
 * with it Compare and the one-press example below a 700 px window.
 */
const PROFILE_OPTIONS: ReadonlyArray<{ key: Exclude<ProfileKey, 'custom'>; label: string }> = [
  { key: 'wheelchair', label: 'Wheelchair' },
  { key: 'walker', label: 'Walker' },
  { key: 'stroller', label: 'Stroller' },
  { key: 'crutches', label: 'Crutches or cane' },
  { key: 'reduced_mobility', label: 'Reduced mobility' },
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
  /** Which route the map brings forward; optional for callers without a map. */
  readonly selectedRoute?: RouteVariant;
  readonly onSelectRoute?: (variant: RouteVariant) => void;
  /** The profiles' rules, as the routing service states them. */
  readonly profiles?: ProfilesState;
  /** The traveller's own uphill limit; off unless they turn it on. */
  readonly uphillLimit?: UphillLimit;
  readonly onUphillLimitChange?: (limit: UphillLimit) => void;
  /** Apply the typed limit to the journey on screen. */
  readonly onUphillLimitCommit?: () => void;
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

/** What the status line says before there is an answer to show. */
function idleHint(points: PlannerPoints): string {
  if (points.origin !== null && points.destination !== null) {
    return 'Both ends are set — compare the routes.';
  }
  if (points.origin !== null) return 'Start set. Now choose a destination.';
  if (points.destination !== null) return 'Destination set. Now choose a start.';
  return 'Name both ends to begin, or click the map.';
}

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
  selectedRoute,
  onSelectRoute = () => {},
  profiles = { status: 'loading' },
  uphillLimit = NO_UPHILL_LIMIT,
  onUphillLimitChange = () => {},
  onUphillLimitCommit = () => {},
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
        {state.status === 'idle' ? <p className={styles.hint}>{idleHint(points)}</p> : null}

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
            {...(selectedRoute ? { selectedRoute } : {})}
            onSelectRoute={onSelectRoute}
            onEditJourney={handleEditJourney}
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

        {/* In the gutter between A and B, where map apps put it, rather than
            on a row of its own: the row cost 44 px of the first screen. */}
        <div className={styles.swapRow}>
          <button
            type="button"
            className={styles.swapButton}
            onClick={onSwapPoints}
            disabled={points.origin === null && points.destination === null}
            aria-label="Swap ends"
            title="Swap ends"
            data-testid="swap-points"
          >
            <span aria-hidden="true">⇅</span>
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

        <ProfileChooser
          selected={profileKey}
          onChange={onProfileChange}
          profiles={profiles}
          uphillLimit={uphillLimit}
          onUphillLimitChange={onUphillLimitChange}
          onUphillLimitCommit={onUphillLimitCommit}
        />

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
 * The five profiles as one row of chips, with the chosen one's rules beneath.
 *
 * Native radio buttons styled as chips: the arrow keys, the group's single tab
 * stop and the announcement are the platform's own. The rule lines are never
 * hidden — which limits are in force is the whole difference between the two
 * routes — and they come from the routing service, so they cannot disagree
 * with the rules that actually chose the route.
 */
function ProfileChooser({
  selected,
  onChange,
  profiles,
  uphillLimit,
  onUphillLimitChange,
  onUphillLimitCommit,
}: {
  readonly selected: ProfileKey;
  readonly onChange: (key: ProfileKey) => void;
  readonly profiles: ProfilesState;
  readonly uphillLimit: UphillLimit;
  readonly onUphillLimitChange: (limit: UphillLimit) => void;
  readonly onUphillLimitCommit: () => void;
}) {
  const profile = profiles.status === 'ready' ? profiles.profiles.get(selected) : undefined;
  const rules = profile ? profileRuleLines(profile) : null;

  return (
    <fieldset className={styles.fieldset} data-testid="mobility-profile">
      <legend className={styles.legend}>How do you travel?</legend>
      <div className={styles.profiles}>
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
              className={styles.chipInput}
              checked={option.key === selected}
              onChange={() => onChange(option.key)}
            />
            <span className={styles.profileLabel}>{option.label}</span>
          </label>
        ))}
      </div>
      <div className={styles.profileRule} data-testid="profile-rule">
        {rules ? (
          <p>
            {rules.hard}
            {rules.preferences ? ` ${rules.preferences}` : ''}
          </p>
        ) : profiles.status === 'unavailable' ? (
          <p>This profile’s rules could not be loaded. The routing service still applies them.</p>
        ) : (
          <p>Loading this profile’s rules…</p>
        )}
      </div>
      <UphillLimitControl
        limit={uphillLimit}
        onChange={onUphillLimitChange}
        onCommit={onUphillLimitCommit}
      />
    </fieldset>
  );
}

/**
 * "The steepest climb I can manage", off until the traveller turns it on.
 *
 * Off is not a default number: with no limit set, no gradient rules a path out
 * and the profile's preference only makes steep climbs cost more. On, the
 * number is sent exactly as typed and becomes a hard limit — applied to the
 * gradient OpenStreetMap records where it has one and to the elevation
 * estimate otherwise — and the answer says which of the two each exclusion
 * rested on.
 */
function UphillLimitControl({
  limit,
  onChange,
  onCommit,
}: {
  readonly limit: UphillLimit;
  readonly onChange: (limit: UphillLimit) => void;
  readonly onCommit: () => void;
}) {
  const inputId = useId();
  const messageId = useId();
  const parsed = parseUphillLimit(limit);

  return (
    <div className={styles.uphill} data-testid="uphill-limit">
      <label className={styles.uphillToggle}>
        <input
          type="checkbox"
          className={styles.profileInput}
          checked={limit.enabled}
          onChange={(event) => onChange({ ...limit, enabled: event.target.checked })}
          data-testid="uphill-limit-toggle"
        />
        <span>Set my own uphill limit</span>
      </label>
      {limit.enabled ? (
        <div className={styles.uphillField}>
          <label htmlFor={inputId} className={styles.uphillLabel}>
            Steepest climb I can manage (%)
          </label>
          <input
            id={inputId}
            type="text"
            inputMode="decimal"
            autoComplete="off"
            className={styles.uphillInput}
            value={limit.text}
            onChange={(event) => onChange({ ...limit, text: event.target.value })}
            onBlur={onCommit}
            onKeyDown={(event) => {
              if (event.key === 'Enter') onCommit();
            }}
            aria-invalid={!parsed.ok}
            aria-describedby={messageId}
            data-testid="uphill-limit-input"
          />
          <p
            className={parsed.ok ? styles.uphillNote : styles.uphillError}
            id={messageId}
            data-testid="uphill-limit-note"
          >
            {parsed.ok
              ? `Climbs steeper than ${limit.text.trim()}% are ruled out, whether recorded or estimated.`
              : parsed.message}
          </p>
        </div>
      ) : null}
    </div>
  );
}
