'use client';

import type { ProfileKey, Route, RouteCompareResponse } from '@pathable/contracts';
import { Icon } from '@/components/Icon';
import { shortRegionName } from '@/lib/region';
import { EndpointField } from './EndpointField';
import { MobileComparison } from './MobileComparison';
import { PROFILE_OPTIONS, ProfileChooser } from './ProfileChooser';
import { RouteCards } from './RouteCards';
import { UphillLimitControl, limitText } from './UphillLimitControl';
import type { ProfilesState } from './mobility-profiles';
import {
  type RouteExclusion,
  type RouteVariant,
  exclusionLabel,
  exclusionsOf,
  gradeBasis,
} from './route-evidence';
import { EVIDENCE_LABELS, type ProfileRules, evaluatedWith, mapAge } from './route-facts';
import { routesSharePath } from './route-identity';
import type { VerifiedExample } from './verified-example';
import {
  type LngLat,
  NO_UPHILL_LIMIT,
  type PlannerPoints,
  type PointRole,
  type RouteRequestState,
  type UphillLimit,
} from './types';
import styles from './Planner.module.css';

/**
 * Which of the Golden Master's panels is showing.
 *
 * `plan` is the planning form (17:3555); `compare` the comparison (9:1905);
 * `evidence` one route's record and its gaps (17:3789); `no-route` a journey
 * the profile's hard requirements leave without a route (17:4041).
 */
export type PlannerLayout = 'plan' | 'compare' | 'evidence' | 'no-route';

/**
 * Presentational: every piece of state lives in the workspace above it. The
 * routes have to be drawn on the map *and* described here, so the request
 * cannot live inside this component without the map reaching into it.
 */
export type RoutePlannerProps = {
  readonly layout: PlannerLayout;
  readonly points: PlannerPoints;
  readonly profileKey: ProfileKey;
  readonly state: RouteRequestState;
  readonly apiBaseUrl: string;
  readonly region: string;
  readonly regionName: string;
  /** The answer's profile, named as the traveller chose it; null before one. */
  readonly profileName?: string | null;
  readonly example: VerifiedExample;
  readonly exampleActive: boolean;
  /** True once both endpoints are set and a comparison can be asked for. */
  readonly canCompare: boolean;
  /** True when the draft has moved away from the journey on screen. */
  readonly pendingEdits: boolean;
  /** Which endpoint the next map click fills, if the viewer asked for one. */
  readonly pickTarget: PointRole | null;
  /** Which route the map brings forward. */
  readonly selectedRoute?: RouteVariant;
  readonly onSelectRoute?: (variant: RouteVariant) => void;
  /** The profiles' rules, as the routing service states them. */
  readonly profiles?: ProfilesState;
  readonly rules: ProfileRules;
  /** The traveller's own uphill limit; off unless they turn it on. */
  readonly uphillLimit?: UphillLimit;
  readonly onUphillLimitChange?: (limit: UphillLimit) => void;
  readonly onUphillLimitCommit?: () => void;
  readonly onRunExample: (example: VerifiedExample) => void;
  readonly onProfileChange: (key: ProfileKey) => void;
  readonly onCompare: () => void;
  readonly onClearAll: () => void;
  readonly onSwapPoints: () => void;
  readonly onRetry: () => void;
  readonly onSelectPlace: (role: PointRole, position: LngLat, label: string) => void;
  readonly onPickOnMap: (role: PointRole) => void;
  readonly onRouteDetails?: () => void;
  /** Opens the full record at its evidence section (the phone's second action). */
  readonly onOpenEvidence?: () => void;
  /** The phone composition (17:2865): the answer as a sheet under the map. */
  readonly phone?: boolean;
  /**
   * A desktop window shorter than the frames: the comparison's answer comes
   * before the profile controls rather than after them.
   */
  readonly answerFirst?: boolean;
  /**
   * Whether the phone's "Edit journey or profile" is open. Held above the
   * sheet, which re-mounts while a changed profile re-runs; held inside it,
   * the controls the traveller was using would snap shut under them.
   */
  readonly editorOpen?: boolean;
  readonly onEditorToggle?: (open: boolean) => void;
  /** Switch between the comparison and one route's evidence. */
  readonly onShowLayout?: (layout: 'compare' | 'evidence') => void;
  /** From the no-route panel: go back to the controls, focused where asked. */
  readonly onEditJourney?: (target: 'profile' | 'destination') => void;
  readonly fetchImpl?: typeof fetch;
};

/** The design's glyph for a profile, solid, as the no-route tag draws it. */
function profileIcon(key: ProfileKey) {
  return (
    PROFILE_OPTIONS.find((option) => option.key === key)?.listIcon ?? 'profile-wheelchair-solid'
  );
}

/** What the status region says before there is an answer to show. */
function idleHint(points: PlannerPoints): string {
  if (points.origin !== null && points.destination !== null) {
    return 'Both ends are set — compare the routes.';
  }
  if (points.origin !== null) return 'Start set. Now choose a destination.';
  if (points.destination !== null) return 'Destination set. Now choose a start.';
  return 'Name both ends to begin, or click the map.';
}

export function RoutePlanner(props: RoutePlannerProps) {
  switch (props.layout) {
    case 'compare': {
      const comparison = props.state.status === 'success' ? props.state.comparison : null;
      if (props.phone && comparison?.standard_route && comparison.accessible_route) {
        return (
          <StatusRegion state={props.state} points={props.points} onRetry={props.onRetry}>
            <MobileComparison
              comparison={comparison}
              profileKey={props.profileKey}
              profileName={props.profileName ?? comparison.profile_display_name}
              rules={props.rules}
              origin={props.points.origin}
              destination={props.points.destination}
              selectedRoute={props.selectedRoute ?? 'accessible'}
              onSelectRoute={props.onSelectRoute ?? (() => {})}
              onRouteDetails={props.onRouteDetails ?? (() => {})}
              onViewEvidence={props.onOpenEvidence ?? (() => {})}
              editorOpen={props.editorOpen ?? false}
              onEditorToggle={props.onEditorToggle ?? (() => {})}
              editor={
                <>
                  <CompareControls {...props} />
                  <ClearJourney onClearAll={props.onClearAll} />
                </>
              }
            />
          </StatusRegion>
        );
      }
      return <ComparePanel {...props} />;
    }
    case 'evidence':
      return <EvidencePanel {...props} />;
    case 'no-route':
      return <NoRoutePanel {...props} />;
    default:
      return <PlanPanel {...props} />;
  }
}

// ---------------------------------------------------------------------------
// The status region
// ---------------------------------------------------------------------------

/**
 * The live region every layout keeps. Results replace one another in place,
 * so the region announces itself rather than relying on focus moving.
 */
function StatusRegion({
  state,
  points,
  onRetry,
  children,
  hideIdle = false,
}: {
  readonly state: RouteRequestState;
  readonly points: PlannerPoints;
  readonly onRetry: () => void;
  readonly children?: React.ReactNode;
  readonly hideIdle?: boolean;
}) {
  return (
    <div
      className={styles.status}
      aria-live="polite"
      aria-busy={state.status === 'loading'}
      data-route-state={state.status}
      data-testid="route-status"
    >
      {state.status === 'idle' ? (
        <p className={hideIdle ? 'visually-hidden' : styles.hint}>{idleHint(points)}</p>
      ) : null}
      {state.status === 'loading' ? (
        <p className={styles.loadingCard}>
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
      {state.status === 'success' ? children : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Plan (17:3555)
// ---------------------------------------------------------------------------

function PlanPanel({
  points,
  profileKey,
  state,
  apiBaseUrl,
  region,
  regionName,
  example,
  exampleActive,
  canCompare,
  pickTarget,
  profiles = { status: 'loading' },
  rules,
  uphillLimit = NO_UPHILL_LIMIT,
  onUphillLimitChange = () => {},
  onUphillLimitCommit = () => {},
  onRunExample,
  onProfileChange,
  onCompare,
  onClearAll,
  onSwapPoints,
  onRetry,
  onSelectPlace,
  onPickOnMap,
  fetchImpl,
}: RoutePlannerProps) {
  const hasPoints = points.origin !== null || points.destination !== null;
  const busy = state.status === 'loading';

  return (
    <section
      className={`${styles.panel} ${styles.panelPlan}`}
      aria-labelledby="route-planner-heading"
      data-testid="plan-journey"
      data-layout="plan"
    >
      <header className={styles.planHead}>
        <div>
          <p className={styles.eyebrow}>
            <span className={styles.dot} aria-hidden="true" />
            Routing engine
          </p>
          <h1 className={styles.planTitle} id="route-planner-heading">
            Route Planner
          </h1>
          <p className={styles.planSubtitle}>{shortRegionName(regionName)} Pedestrian Network</p>
        </div>
        {hasPoints ? (
          <button
            type="button"
            className={styles.textButton}
            onClick={onClearAll}
            data-testid="clear-journey"
          >
            Clear
          </button>
        ) : null}
      </header>

      <div className={styles.waypointWell}>
        <EndpointField
          role="origin"
          endpoint={points.origin}
          apiBaseUrl={apiBaseUrl}
          region={region}
          picking={pickTarget === 'origin'}
          onSelectPlace={onSelectPlace}
          onPickOnMap={onPickOnMap}
          extra={
            <button
              type="button"
              className={styles.fieldButton}
              onClick={onSwapPoints}
              disabled={!hasPoints}
              aria-label="Swap ends"
              title="Swap ends"
              data-testid="swap-points"
            >
              <Icon name="swap" />
            </button>
          }
          {...(fetchImpl ? { fetchImpl } : {})}
        />
        <p className={styles.stem} aria-hidden="true">
          <span className={styles.stemLabel}>NRCan 1 m elevation · derived grade</span>
        </p>
        <EndpointField
          role="destination"
          endpoint={points.destination}
          apiBaseUrl={apiBaseUrl}
          region={region}
          picking={pickTarget === 'destination'}
          onSelectPlace={onSelectPlace}
          onPickOnMap={onPickOnMap}
          {...(fetchImpl ? { fetchImpl } : {})}
        />
      </div>

      <ProfileChooser
        variant="list"
        selected={profileKey}
        onChange={onProfileChange}
        profiles={profiles}
      />

      <UphillLimitControl
        variant="card"
        limit={uphillLimit}
        onChange={onUphillLimitChange}
        onCommit={onUphillLimitCommit}
        prefersUnder={rules.prefersUnder}
      />

      <div className={styles.compareBlock}>
        <button
          type="button"
          className={`${styles.primaryButton} ${styles.compareButton}`}
          onClick={onCompare}
          disabled={!canCompare || busy}
          data-testid="compare-routes"
        >
          <Icon name="fork" />
          {busy ? 'Comparing…' : 'Compare Routes'}
        </button>
        <p className={styles.compareCaption}>
          Uses the PathAble routing API with the selected profile rules
        </p>
        <div className={styles.exampleRow} data-testid="verified-example">
          <button
            type="button"
            className={styles.textButton}
            onClick={() => onRunExample(example)}
            disabled={busy}
            aria-pressed={exampleActive}
            data-testid="run-verified-example"
          >
            Or run the verified Waterloo example →
          </button>
        </div>
        <p className={styles.exampleNote}>
          {example.originLabel} to {example.destinationLabel}. {example.provenance}
        </p>
      </div>

      <StatusRegion state={state} points={points} onRetry={onRetry} hideIdle />
    </section>
  );
}

// ---------------------------------------------------------------------------
// Compare (9:1905)
// ---------------------------------------------------------------------------

/**
 * The journey and profile controls beside a result (9:2044–9:2101): the two
 * endpoints, a pending-edit notice with its Compare button, the profile grid
 * and the uphill slider. Shared by the desktop panel and the phone's
 * "Edit journey or profile" disclosure.
 */
export function CompareControls(props: RoutePlannerProps) {
  return (
    <>
      <JourneyFields {...props} />
      <ProfileControls {...props} />
    </>
  );
}

/** The two endpoints, and — once they have moved — the notice and Compare. */
function JourneyFields({
  points,
  state,
  apiBaseUrl,
  region,
  pendingEdits,
  canCompare,
  pickTarget,
  onCompare,
  onSwapPoints,
  onSelectPlace,
  onPickOnMap,
  fetchImpl,
}: RoutePlannerProps) {
  const hasPoints = points.origin !== null || points.destination !== null;
  return (
    <>
      <div className={styles.waypoints}>
        <EndpointField
          role="origin"
          variant="compact"
          endpoint={points.origin}
          apiBaseUrl={apiBaseUrl}
          region={region}
          picking={pickTarget === 'origin'}
          onSelectPlace={onSelectPlace}
          onPickOnMap={onPickOnMap}
          {...(fetchImpl ? { fetchImpl } : {})}
        />
        <EndpointField
          role="destination"
          variant="compact"
          endpoint={points.destination}
          apiBaseUrl={apiBaseUrl}
          region={region}
          picking={pickTarget === 'destination'}
          onSelectPlace={onSelectPlace}
          onPickOnMap={onPickOnMap}
          {...(fetchImpl ? { fetchImpl } : {})}
        />
        <button
          type="button"
          className={styles.swapFloat}
          onClick={onSwapPoints}
          disabled={!hasPoints}
          aria-label="Swap ends"
          title="Swap ends"
          data-testid="swap-points"
        >
          <Icon name="swap" />
        </button>
      </div>

      {pendingEdits ? (
        <>
          <p className={styles.staleNote} role="status" data-testid="stale-result">
            You have changed the journey. The routes below are still for the previous one.
          </p>
          <button
            type="button"
            className={`${styles.primaryButton} ${styles.updateButton}`}
            onClick={onCompare}
            disabled={!canCompare || state.status === 'loading'}
            data-testid="compare-routes"
          >
            {state.status === 'loading' ? 'Comparing…' : 'Compare routes'}
          </button>
        </>
      ) : null}
    </>
  );
}

/** The profile grid and the uphill slider, which re-run the journey on change. */
function ProfileControls({
  profileKey,
  state,
  profiles = { status: 'loading' },
  uphillLimit = NO_UPHILL_LIMIT,
  onUphillLimitChange = () => {},
  onUphillLimitCommit = () => {},
  onProfileChange,
}: RoutePlannerProps) {
  const comparison = state.status === 'success' ? state.comparison : null;
  const accessible = comparison?.accessible_route ?? null;
  return (
    <>
      <div className={styles.compareSection}>
        <ProfileChooser
          variant="grid"
          selected={profileKey}
          onChange={onProfileChange}
          profiles={profiles}
          selectedNote={
            accessible === null
              ? null
              : `${accessible.stairway_count} recorded ${accessible.stairway_count === 1 ? 'stairway' : 'stairways'}`
          }
        />
      </div>

      <UphillLimitControl
        variant="slider"
        limit={uphillLimit}
        onChange={onUphillLimitChange}
        onCommit={onUphillLimitCommit}
      />
    </>
  );
}

function ComparePanel(props: RoutePlannerProps) {
  const {
    points,
    profileName = null,
    state,
    regionName,
    selectedRoute = 'accessible',
    onSelectRoute = () => {},
    onRetry,
    answerFirst = false,
  } = props;
  const comparison = state.status === 'success' ? state.comparison : null;
  const age = comparison ? mapAge(comparison) : null;

  const answer = (
    <>
      <StatusRegion state={state} points={points} onRetry={onRetry}>
        {comparison === null ? null : comparison.standard_route && comparison.accessible_route ? (
          <RouteCards
            comparison={comparison}
            profileName={profileName ?? comparison.profile_display_name}
            selectedRoute={selectedRoute}
            onSelectRoute={onSelectRoute}
          />
        ) : (
          <SingleRouteNote comparison={comparison} profileName={profileName} />
        )}
      </StatusRegion>

      {comparison ? (
        <p className={styles.statusLine}>
          <span className={styles.statusLead}>
            <span className={styles.dot} aria-hidden="true" />
            {evaluatedWith(comparison)}
          </span>
          {age ? <span className={styles.statusTrail}>{age}</span> : null}
        </p>
      ) : null}
    </>
  );

  return (
    <section
      className={`${styles.panel} ${styles.panelCompare}`}
      aria-labelledby="route-planner-heading"
      data-testid="plan-journey"
      data-layout="compare"
    >
      <header className={styles.compareHead}>
        <h1 className={styles.compareTitle} id="route-planner-heading">
          <span className={styles.titleMark} aria-hidden="true">
            <Icon name="planner-route" />
          </span>
          Route Planner
        </h1>
        <span className={styles.compareHeadEnd}>
          <span className={styles.compareRegion}>{shortRegionName(regionName)}</span>
          <ClearJourney onClearAll={props.onClearAll} />
        </span>
      </header>

      <JourneyFields {...props} />
      {answerFirst ? (
        // A window shorter than the frame: the answer before the controls
        // that change it, so both routes are on screen without scrolling.
        <>
          {answer}
          <ProfileControls {...props} />
        </>
      ) : (
        <>
          <ProfileControls {...props} />
          {answer}
        </>
      )}
    </section>
  );
}

/**
 * Start again: both ends, the answer and the map's lines go together. The
 * design's comparison has no such control; without one, the only way back to
 * the planning form from a result was reloading the page.
 */
function ClearJourney({ onClearAll }: { readonly onClearAll: () => void }) {
  return (
    <button
      type="button"
      className={styles.textButton}
      onClick={onClearAll}
      aria-label="Clear the journey and start again"
      data-testid="clear-journey"
    >
      Clear
    </button>
  );
}

/** When the response carries one route, say which and why there is no pair. */
function SingleRouteNote({
  comparison,
  profileName,
}: {
  readonly comparison: RouteCompareResponse;
  readonly profileName: string | null;
}) {
  const profile = (profileName ?? comparison.profile_display_name).toLowerCase();
  if (!comparison.accessible_route) {
    return (
      <p className={styles.error} role="status" data-testid="no-accessible-route">
        No route meets the {profile} profile between these points. PathAble does not loosen your
        profile’s limits to find one.
      </p>
    );
  }
  return (
    <p className={styles.loadingCard} role="status">
      A {profile} route was found; the response returned no shortest walking route to compare it
      with.
    </p>
  );
}

// ---------------------------------------------------------------------------
// Evidence (17:3789)
// ---------------------------------------------------------------------------

function shownRouteOf(comparison: RouteCompareResponse, selected: RouteVariant): Route | null {
  if (selected === 'standard' && comparison.standard_route) return comparison.standard_route;
  return comparison.accessible_route ?? comparison.standard_route ?? null;
}

/** True when the record behind a route has at least one gap the API reports. */
export function hasEvidenceGaps(route: Route): boolean {
  const coverage = route.evidence_coverage ?? {};
  return (
    route.unknown_data_fraction > 0 ||
    route.unknown_kerb_crossing_count > 0 ||
    Object.values(coverage).some((share) => share > 0)
  );
}

function EvidencePanel({
  points,
  profileName = null,
  state,
  selectedRoute = 'accessible',
  rules,
  uphillLimit = NO_UPHILL_LIMIT,
  onRouteDetails = () => {},
  onShowLayout = () => {},
  onRetry,
}: RoutePlannerProps) {
  const comparison = state.status === 'success' ? state.comparison : null;
  const route = comparison ? shownRouteOf(comparison, selectedRoute) : null;
  const isShortest = comparison !== null && route !== null && route === comparison.standard_route;
  const routeName = comparison
    ? isShortest
      ? 'Shortest walking route'
      : `${profileName ?? comparison.profile_display_name} route`
    : 'Route';
  const gaps = route ? hasEvidenceGaps(route) : false;
  const canCompare = Boolean(
    comparison?.standard_route &&
      comparison.accessible_route &&
      !routesSharePath(comparison.standard_route, comparison.accessible_route),
  );

  return (
    <section
      className={`${styles.panel} ${styles.panelEvidence}`}
      aria-labelledby="route-planner-heading"
      data-testid="plan-journey"
      data-layout="evidence"
    >
      <div className={styles.journeyCard}>
        <header className={styles.journeyHead}>
          <h1 className={styles.journeyName} id="route-planner-heading">
            <Icon name="route" />
            {routeName}
          </h1>
          <span className={styles.journeyMode}>Evidence gaps shown</span>
        </header>
        <div className={styles.journeyPoints}>
          {(['origin', 'destination'] as const).map((role) => (
            <div className={styles.journeyPoint} key={role}>
              <span className={styles.pointDot} data-role={role} aria-hidden="true" />
              <span className={styles.journeyPointText}>
                <span className={styles.journeyPointLabel}>
                  {role === 'origin' ? 'Origin' : 'Destination'}
                </span>
                <span className={styles.journeyPointName} data-testid={`journey-${role}`}>
                  {points[role]?.label ?? 'Not set'}
                </span>
              </span>
            </div>
          ))}
        </div>
        {comparison ? (
          <p className={styles.pills}>
            <span className={styles.pill}>{profileName ?? comparison.profile_display_name}</span>
            {uphillLimit.enabled && rules.uphillLimit !== null ? (
              <span className={styles.pill}>
                Custom uphill limit · {limitText(rules.uphillLimit)}
              </span>
            ) : null}
            {rules.excludesSteps ? (
              <span className={styles.pill}>Avoid recorded stairways</span>
            ) : null}
          </p>
        ) : null}
      </div>

      <StatusRegion state={state} points={points} onRetry={onRetry}>
        {route ? (
          <div className={styles.gapBanner} data-complete={!gaps} data-testid="gap-banner">
            {/* The design's own two-tone warning glyph, used as drawn. */}
            {gaps ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src="/icons/warning-box.svg" width={30} height={33} alt="" />
            ) : (
              <Icon name="check-circle" />
            )}
            <div>
              <p className={styles.gapBannerTitle}>
                {gaps
                  ? 'Route found with accessibility data gaps'
                  : 'Route found; no gaps reported in its record'}
              </p>
              <p className={styles.gapBannerBody}>
                {gaps
                  ? 'Missing stays unknown; this is not an accessibility guarantee.'
                  : 'A statement about the record, not a certification that the route is passable.'}
              </p>
            </div>
          </div>
        ) : null}
      </StatusRegion>

      <div className={styles.actionRow}>
        <button
          type="button"
          className={styles.primaryButton}
          onClick={onRouteDetails}
          data-testid="open-route-details"
        >
          Route Details
        </button>
        <button
          type="button"
          className={`${styles.secondaryButton} ${styles.eyeButton}`}
          onClick={() => onShowLayout('compare')}
          aria-label={canCompare ? 'Back to the route comparison' : 'Edit journey or profile'}
          title={canCompare ? 'Back to the route comparison' : 'Edit journey or profile'}
          aria-pressed
          data-testid="toggle-evidence"
        >
          <Icon name="eye" />
        </button>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// No route (17:4041)
// ---------------------------------------------------------------------------

type Requirement = {
  readonly key: string;
  readonly icon: 'stairs' | 'trending-up' | 'block';
  readonly title: string;
  readonly tag: string;
  readonly statement: string;
  readonly verdict: React.ReactNode;
};

/**
 * What the response says the shortest walking route breaks, one card per
 * reason. Only what the API reports: these are facts about the shortest route
 * the engine did return, never a diagnosis of every path it searched.
 */
function requirementsOf(
  comparison: RouteCompareResponse,
  rules: ProfileRules,
): readonly Requirement[] {
  const standard = comparison.standard_route ?? null;
  if (standard === null) return [];
  return exclusionsOf(standard).map((exclusion: RouteExclusion) => {
    const count = exclusion.segmentIndexes.length;
    if (exclusion.reason === 'steps') {
      return {
        key: exclusion.reason,
        icon: 'stairs',
        title: 'Recorded stairway evidence',
        tag: EVIDENCE_LABELS.recorded,
        statement: `The shortest walking route uses ${count} recorded ${count === 1 ? 'stairway' : 'stairways'}; your profile rules out stairs.`,
        verdict: (
          <>
            Violates: <strong>0 recorded stairways</strong> [Your profile rule]
          </>
        ),
      };
    }
    if (exclusion.reason === 'too_steep') {
      const segments = exclusion.segmentIndexes.map((index) => standard.segments[index]);
      const recorded = segments.some((segment) => segment?.incline_percent != null);
      const derived = segments.some(
        (segment) => segment?.incline_percent == null && segment?.derived_grade_percent != null,
      );
      const basis = recorded && derived ? 'mixed' : recorded ? 'recorded' : 'estimated';
      return {
        key: exclusion.reason,
        icon: 'trending-up',
        title:
          basis === 'recorded'
            ? 'Recorded grade evidence'
            : basis === 'mixed'
              ? 'Recorded and derived grade evidence'
              : 'Derived grade evidence',
        tag:
          basis === 'recorded'
            ? EVIDENCE_LABELS.recorded
            : basis === 'mixed'
              ? `${EVIDENCE_LABELS.recorded} + ${EVIDENCE_LABELS.derived}`
              : EVIDENCE_LABELS.derived,
        statement: `${count} ${count === 1 ? 'segment' : 'segments'} of the shortest walking route ${count === 1 ? 'climbs' : 'climb'} more than your limit.`,
        verdict:
          rules.uphillLimit !== null ? (
            <>
              Exceeds your custom uphill limit of <strong>{limitText(rules.uphillLimit)}</strong>{' '}
              [Your profile rule]
            </>
          ) : (
            <>Exceeds your uphill limit [Your profile rule]</>
          ),
      };
    }
    return {
      key: exclusion.reason,
      icon: 'block',
      title: 'Recorded map evidence',
      tag: EVIDENCE_LABELS.recorded,
      statement: `The shortest walking route has ${exclusionLabel(exclusion)}.`,
      verdict: <>Ruled out by your profile [Your profile rule]</>,
    };
  });
}

function NoRoutePanel({
  points,
  profileName = null,
  profileKey,
  state,
  apiBaseUrl,
  region,
  pickTarget,
  rules,
  onSwapPoints,
  onSelectPlace,
  onPickOnMap,
  onRetry,
  onEditJourney = () => {},
  fetchImpl,
}: RoutePlannerProps) {
  const comparison = state.status === 'success' ? state.comparison : null;
  const requirements = comparison ? requirementsOf(comparison, rules) : [];
  const failure = comparison?.accessible_failure ?? null;
  const steepest = comparison?.standard_route?.gradient.steepest_uphill ?? null;

  return (
    <section
      className={`${styles.panel} ${styles.panelNoRoute}`}
      aria-labelledby="route-planner-heading"
      data-testid="plan-journey"
      data-layout="no-route"
    >
      <div className={styles.noRouteHead}>
        <div className={styles.modeRow}>
          <h1 className={styles.modeTag} id="route-planner-heading">
            <Icon name={profileIcon(profileKey)} size={16} />
            {profileName ?? comparison?.profile_display_name ?? 'Your'} profile
          </h1>
          <span className={styles.modeNote}>Hard requirements preserved</span>
        </div>
        <div className={styles.waypoints}>
          <EndpointField
            role="origin"
            variant="route"
            endpoint={points.origin}
            apiBaseUrl={apiBaseUrl}
            region={region}
            picking={pickTarget === 'origin'}
            onSelectPlace={onSelectPlace}
            onPickOnMap={onPickOnMap}
            {...(fetchImpl ? { fetchImpl } : {})}
          />
          <EndpointField
            role="destination"
            variant="route"
            endpoint={points.destination}
            apiBaseUrl={apiBaseUrl}
            region={region}
            picking={pickTarget === 'destination'}
            onSelectPlace={onSelectPlace}
            onPickOnMap={onPickOnMap}
            {...(fetchImpl ? { fetchImpl } : {})}
          />
          <button
            type="button"
            className={styles.swapFloat}
            onClick={onSwapPoints}
            aria-label="Swap ends"
            title="Swap ends"
            data-testid="swap-points"
          >
            <Icon name="swap" />
          </button>
        </div>
        <p className={styles.ruleChips}>
          {rules.excludesSteps ? (
            <span className={styles.ruleChip}>
              Rule: <strong>0 Recorded Stairs</strong>
            </span>
          ) : null}
          {rules.uphillLimit !== null ? (
            <span className={styles.ruleChip}>
              Rule: <strong>Max {limitText(rules.uphillLimit)} Uphill</strong>
            </span>
          ) : null}
          <span className={styles.ruleChip}>Rule: No automatic relaxation</span>
        </p>
      </div>

      {/* It scrolls on short windows, so it takes focus itself: a keyboard
          user can scroll it even though nothing inside it is a control. */}
      <div
        className={styles.noRouteBody}
        role="region"
        aria-label="Why there is no route"
        tabIndex={0}
      >
        <StatusRegion state={state} points={points} onRetry={onRetry}>
          <div className={styles.noRouteBanner} role="status" data-testid="no-accessible-route">
            <span className={styles.noRouteIcon} aria-hidden="true">
              <Icon name="block" />
            </span>
            <div>
              <h2 className={styles.noRouteTitle}>No route satisfies your profile requirements</h2>
              <p className={styles.noRouteText}>
                PathAble did not find a route satisfying every hard requirement in the current
                pedestrian graph. It will not silently relax them.
              </p>
              {failure ? <p className={styles.noRouteText}>{failure}</p> : null}
            </div>
          </div>
        </StatusRegion>

        {requirements.length > 0 ? (
          <section className={styles.compareSection} aria-labelledby="requirements-heading">
            <div className={styles.requirementsHead}>
              <h3 className={styles.caps} id="requirements-heading">
                Hard requirements
              </h3>
              <span className={styles.requirementsFlag}>No route returned</span>
            </div>
            {requirements.map((requirement) => (
              <article
                key={requirement.key}
                className={styles.requirement}
                data-testid={`requirement-${requirement.key}`}
              >
                <div className={styles.requirementHead}>
                  <span className={styles.requirementName}>
                    <Icon name={requirement.icon} size={18} />
                    {requirement.title}
                  </span>
                  <span className={styles.requirementTag}>{requirement.tag}</span>
                </div>
                <p className={styles.requirementStatement}>{requirement.statement}</p>
                <p className={styles.requirementVerdict}>
                  <Icon name="cancel" />
                  <span>{requirement.verdict}</span>
                </p>
              </article>
            ))}
            {steepest !== null && !requirements.some((item) => item.key === 'too_steep') ? (
              <p className={styles.hint}>
                Steepest climb on the shortest walking route: {steepest.percent.toFixed(1)}% (
                {gradeBasis(steepest) === 'recorded'
                  ? EVIDENCE_LABELS.recorded
                  : EVIDENCE_LABELS.derived}
                ).
              </p>
            ) : null}
          </section>
        ) : null}

        <div className={styles.preserved}>
          <Icon name="shield-check" />
          <div>
            <p className={styles.preservedTitle}>Hard requirements preserved</p>
            <p className={styles.preservedText}>
              PathAble will not relax explicit hard requirements just to return a route.
            </p>
          </div>
        </div>
      </div>

      <div className={styles.noRouteFoot}>
        <button
          type="button"
          className={styles.primaryButton}
          onClick={() => onEditJourney('profile')}
          data-testid="edit-profile"
        >
          <Icon name="tune" />
          Edit Profile
        </button>
        <button
          type="button"
          className={styles.secondaryButton}
          onClick={() => onEditJourney('destination')}
          data-testid="change-destination"
        >
          <Icon name="add-location" />
          Change Destination
        </button>
      </div>
    </section>
  );
}
