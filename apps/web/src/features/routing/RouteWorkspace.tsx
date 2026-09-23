'use client';

import { type CSSProperties, type ReactNode, useCallback, useMemo, useRef, useState } from 'react';
import type { ProfileKey } from '@pathable/contracts';
import { MapPanel } from '@/features/map/MapPanel';
import { type RouteFocus, recordedStairs } from '@/features/map/route-layers';
import { usePanelFit } from '@/features/map/usePanelFit';
import { MAP_POINT_LABEL } from './EndpointField';
import { RoutePlanner } from './RoutePlanner';
import { useRouteComparison } from './useRouteComparison';
import {
  type Endpoint,
  type Journey,
  type LngLat,
  type PlannerPoints,
  type PointRole,
  type RouteRequestState,
  type StairsTarget,
  formatDistance,
  hasPendingEndpointEdits,
  journeyOf,
} from './types';
import { CAMPUS_EXAMPLE, type VerifiedExample } from './verified-example';
import styles from './RouteWorkspace.module.css';

export type RouteWorkspaceProps = {
  readonly apiBaseUrl: string;
  readonly region: string;
  readonly mapStyleUrl: string;
  readonly centerLat: number;
  readonly centerLon: number;
  readonly zoom: number;
  readonly regionName: string;
  readonly attribution: string;
  readonly describedById?: string;
  /** Injectable so tests never touch the network. */
  readonly fetchImpl?: typeof fetch;
  /**
   * Preselect an example. Resolved from the query string by the page, which is
   * a server component and can read it without an effect — so a deep link is
   * server-rendered like everything else rather than appearing a frame late.
   */
  readonly initialExample?: VerifiedExample | null;
  /** Rendered at the top of the planner: the page title. */
  readonly title?: ReactNode;
  /** Rendered near the foot of the planner: the purpose line and what it means. */
  readonly intro?: ReactNode;
  /** Rendered at the bottom of the planner: data attribution. */
  readonly footer?: ReactNode;
};

const EMPTY_POINTS: PlannerPoints = { origin: null, destination: null };

/**
 * The example's endpoints, carrying the corpus's own names for the places.
 *
 * Typed non-null so the journey built from it needs no assertion: the preset
 * always has both ends, which is the whole reason it is one press.
 */
function exampleEndpoints(example: VerifiedExample): {
  readonly origin: Endpoint;
  readonly destination: Endpoint;
} {
  return {
    origin: { position: example.origin, label: example.originLabel, source: 'example' },
    destination: {
      position: example.destination,
      label: example.destinationLabel,
      source: 'example',
    },
  };
}

/**
 * Owns the planning state shared by the map and the panel.
 *
 * The routes have to be drawn *and* described, so neither the map nor the panel
 * can own them without reaching into the other.
 *
 * Two pieces of state, not one. `points` is the draft the viewer is assembling;
 * `submitted` is the journey they asked to compare. Keeping them apart is what
 * lets an answer stay truthfully attributed to the journey that produced it
 * while a different one is being typed above it — and it is why a half-finished
 * destination no longer fires a request.
 *
 * Layout: the map is the product, so it fills the workspace and everything else
 * floats over it. What the panel covers is measured rather than assumed,
 * because a route framed underneath the panel is the same failure as a route
 * drawn off-screen.
 */
export function RouteWorkspace({
  apiBaseUrl,
  region,
  mapStyleUrl,
  centerLat,
  centerLon,
  zoom,
  regionName,
  attribution,
  describedById,
  fetchImpl,
  initialExample,
  title,
  intro,
  footer,
}: RouteWorkspaceProps) {
  const [points, setPoints] = useState<PlannerPoints>(
    initialExample ? exampleEndpoints(initialExample) : EMPTY_POINTS,
  );
  // A deep-linked example is submitted from the first render, not pressed by a
  // simulated click in an effect: the page already knows the journey, so the
  // request goes out with everything else rather than a frame later.
  const [submitted, setSubmitted] = useState<Journey | null>(
    initialExample
      ? { ...exampleEndpoints(initialExample), profileKey: 'wheelchair' as ProfileKey }
      : null,
  );
  const [profileKey, setProfileKey] = useState<ProfileKey>('wheelchair');
  const [activeExampleId, setActiveExampleId] = useState<string | null>(initialExample?.id ?? null);
  const [focusedRoute, setFocusedRoute] = useState<RouteFocus>(null);
  const [stairsTarget, setStairsTarget] = useState<StairsTarget>(null);
  const [pickTarget, setPickTarget] = useState<PointRole | null>(null);
  // Only meaningful where the panel is a bottom sheet; the side layout ignores
  // it in CSS. Open by default, because the answer is the reason to be here.
  const [sheetOpen, setSheetOpen] = useState(true);

  const mapRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const fit = usePanelFit(mapRef, panelRef);

  const { state, retry } = useRouteComparison({
    apiBaseUrl,
    region,
    journey: submitted,
    ...(fetchImpl ? { fetchImpl } : {}),
  });

  /** Commit a journey, and drop anything that described the previous one. */
  const commit = useCallback((journey: Journey) => {
    setSubmitted(journey);
    setFocusedRoute(null);
    setStairsTarget(null);
    setPickTarget(null);
    setSheetOpen(true);
  }, []);

  const handleRunExample = useCallback(
    (example: VerifiedExample) => {
      // One press: the endpoints, the profile and the request all land in the
      // same interaction. The journey is built here rather than read back from
      // state, because these setStates have not been applied yet.
      const endpoints = exampleEndpoints(example);
      setPoints(endpoints);
      setProfileKey('wheelchair');
      setActiveExampleId(example.id);
      commit({ ...endpoints, profileKey: 'wheelchair' });
    },
    [commit],
  );

  const handleSelectPlace = useCallback((role: PointRole, position: LngLat, label: string) => {
    const endpoint: Endpoint = { position, label, source: 'search' };
    setActiveExampleId(null);
    setPickTarget(null);
    setPoints((current) => ({ ...current, [role]: endpoint }));
  }, []);

  const handlePickOnMap = useCallback((role: PointRole) => {
    setPickTarget((current) => (current === role ? null : role));
  }, []);

  const handleSelectPoint = useCallback(
    (position: LngLat) => {
      const endpoint: Endpoint = { position, label: MAP_POINT_LABEL, source: 'map' };
      setActiveExampleId(null);

      if (pickTarget !== null) {
        const role = pickTarget;
        setPickTarget(null);
        setPoints((current) => ({ ...current, [role]: endpoint }));
        return;
      }

      // No field asked for this click, so fall back to filling the first empty
      // one. Convenient, and unambiguous only because every field also has an
      // explicit "Set on map" that says where a click will land.
      setPoints((current) => {
        if (current.origin === null) return { ...current, origin: endpoint };
        if (current.destination === null) return { ...current, destination: endpoint };
        return { origin: endpoint, destination: null };
      });
    },
    [pickTarget],
  );

  const handleClearPoint = useCallback((role: PointRole) => {
    setActiveExampleId(null);
    setPoints((current) => ({ ...current, [role]: null }));
  }, []);

  const handleClearAll = useCallback(() => {
    // Clearing has to clear the *request* too. Dropping the points alone would
    // leave the previous answer drawn on the map with nothing naming it.
    setPoints(EMPTY_POINTS);
    setSubmitted(null);
    setActiveExampleId(null);
    setFocusedRoute(null);
    setStairsTarget(null);
    setPickTarget(null);
  }, []);

  const handleSwap = useCallback(() => {
    // Labels travel with their coordinates; swapping one without the other
    // would route to a place under another place's name.
    setPoints((current) => ({ origin: current.destination, destination: current.origin }));
  }, []);

  const pendingEdits = hasPendingEndpointEdits(points, submitted);

  const handleProfileChange = useCallback(
    (key: ProfileKey) => {
      setProfileKey(key);
      setFocusedRoute(null);
      setStairsTarget(null);
      // Re-run for the journey already on screen, but only while the endpoints
      // still match it. With an endpoint half-edited, re-running would answer a
      // question that is a mixture of two — so that case waits for Compare.
      if (submitted !== null && !hasPendingEndpointEdits(points, submitted)) {
        setSubmitted({ ...submitted, profileKey: key });
      }
    },
    [points, submitted],
  );

  const handleCompare = useCallback(() => {
    const journey = journeyOf(points, profileKey);
    if (journey === null) return;
    commit(journey);
  }, [points, profileKey, commit]);

  const comparison = state.status === 'success' ? state.comparison : null;

  // A focus only means something while the route it names is on the map. The
  // stored value is left alone — it is reset by every action that changes the
  // request — but what the map and the legend are told is the effective one.
  const effectiveFocus: RouteFocus =
    focusedRoute === 'standard' && comparison?.standard_route
      ? 'standard'
      : focusedRoute === 'accessible' && comparison?.accessible_route
        ? 'accessible'
        : null;

  const stairs = useMemo(() => {
    if (comparison === null || stairsTarget === null) return null;
    const route =
      stairsTarget === 'standard' ? comparison.standard_route : comparison.accessible_route;
    return recordedStairs(route);
  }, [comparison, stairsTarget]);

  // CSS places the map key and MapLibre's own credit clear of the panel from
  // the first paint; this replaces that estimate with the measurement. Only the
  // side actually covered is written, so the other keeps its CSS default.
  //
  // Rounded up, never to nearest. A panel edge lands on a fractional pixel all
  // the time, and rounding down leaves the ODbL credit a fraction of a pixel
  // underneath it — which is still covered, and still a licence term.
  const insetStyle = useMemo<CSSProperties>(() => {
    const { side, amount } = fit.inset;
    if (amount <= 0 || (side !== 'bottom' && side !== 'left')) return {};
    const property = side === 'bottom' ? '--map-inset-bottom' : '--map-inset-left';
    return { [property]: `${Math.ceil(amount)}px` } as CSSProperties;
  }, [fit.inset]);

  const submittedSummary =
    submitted === null ? null : `${submitted.origin.label} to ${submitted.destination.label}`;

  return (
    <div className={styles.workspace} style={insetStyle} data-testid="route-workspace">
      <div className={styles.mapArea} ref={mapRef}>
        <MapPanel
          styleUrl={mapStyleUrl}
          centerLat={centerLat}
          centerLon={centerLon}
          zoom={zoom}
          regionName={regionName}
          attribution={attribution}
          {...(describedById !== undefined ? { describedById } : {})}
          standardRoute={comparison?.standard_route ?? null}
          accessibleRoute={comparison?.accessible_route ?? null}
          origin={points.origin?.position ?? null}
          destination={points.destination?.position ?? null}
          focusedRoute={effectiveFocus}
          fitPadding={fit.padding}
          stairs={stairs}
          onSelectPoint={handleSelectPoint}
        />
      </div>

      <MapLegend
        focus={effectiveFocus}
        stairs={stairsTarget !== null}
        hasRoutes={comparison !== null}
      />

      <aside
        className={styles.panelArea}
        ref={panelRef}
        aria-label="Route planner"
        data-sheet-open={sheetOpen}
      >
        {/* A real control, not an ornament. The previous layout drew a grip
            that looked draggable and was not; this one says what it does and
            does it. CSS shows it only where the panel is a bottom sheet. */}
        <div className={styles.sheetBar}>
          <p className={styles.sheetSummary} aria-hidden="true">
            {sheetSummary(state)}
          </p>
          <button
            type="button"
            className={styles.sheetToggle}
            onClick={() => setSheetOpen((open) => !open)}
            aria-expanded={sheetOpen}
            aria-controls="route-planner-panel"
            data-testid="sheet-toggle"
          >
            {sheetOpen ? 'Collapse' : 'Expand'}
          </button>
        </div>

        <div className={styles.panelInner} id="route-planner-panel">
          <div className={styles.panelTitle}>{title}</div>
          <RoutePlanner
            intro={intro}
            points={points}
            profileKey={profileKey}
            state={state}
            apiBaseUrl={apiBaseUrl}
            region={region}
            example={CAMPUS_EXAMPLE}
            exampleActive={activeExampleId === CAMPUS_EXAMPLE.id}
            canCompare={points.origin !== null && points.destination !== null}
            pendingEdits={pendingEdits}
            pickTarget={pickTarget}
            submittedSummary={submittedSummary}
            stairsTarget={stairsTarget}
            focusedRoute={effectiveFocus}
            onFocusRoute={setFocusedRoute}
            onShowStairs={setStairsTarget}
            onRunExample={handleRunExample}
            onProfileChange={handleProfileChange}
            onCompare={handleCompare}
            onClearPoint={handleClearPoint}
            onClearAll={handleClearAll}
            onSwapPoints={handleSwap}
            onRetry={retry}
            onSelectPlace={handleSelectPlace}
            onPickOnMap={handlePickOnMap}
            {...(fetchImpl ? { fetchImpl } : {})}
          />
          {footer}
        </div>
      </aside>
    </div>
  );
}

/**
 * What the collapsed sheet says it is holding.
 *
 * Hidden from assistive technology: the panel it summarises stays in the
 * accessibility tree behind the toggle, and repeating the headline here would
 * announce the same figure twice. It is a visual label for a collapsed drawer,
 * so it never states a difference or a caution — those belong in the panel,
 * beside the evidence for them.
 */
function sheetSummary(state: RouteRequestState): string {
  switch (state.status) {
    case 'loading':
      return 'Comparing routes…';
    case 'error':
      return 'Could not compare these points';
    case 'success': {
      const route = state.comparison.accessible_route;
      return route
        ? `${state.comparison.profile_display_name} · ${formatDistance(route.distance_m)}`
        : state.comparison.profile_display_name;
    }
    default:
      return 'Plan a walking route';
  }
}

/**
 * The map legend.
 *
 * Outside the canvas so it is real text: a legend painted into WebGL is
 * invisible to a screen reader and unselectable, and this one carries the only
 * explanation of what the lines mean. When one route is brought forward it says
 * so in words, because a faded line is not a label.
 *
 * Hidden until there is something on the map to explain. A key to two routes
 * that do not exist yet is furniture, and on a phone it is furniture sitting on
 * the map.
 */
function MapLegend({
  focus,
  stairs,
  hasRoutes,
}: {
  readonly focus: RouteFocus;
  readonly stairs: boolean;
  readonly hasRoutes: boolean;
}) {
  if (!hasRoutes) return null;

  return (
    <div className={styles.legend} data-testid="map-legend">
      <h2 className={styles.legendHeading}>Map key</h2>
      <ul className={styles.legendList}>
        <li
          className={styles.legendItem}
          data-dimmed={focus !== null && focus !== 'accessible'}
          data-testid="legend-accessible"
        >
          <span className={styles.legendSwatch} data-variant="accessible" aria-hidden="true" />
          <span>
            Route for your profile
            {focus === 'accessible' ? (
              <span className={styles.legendNote}> · highlighted</span>
            ) : null}
          </span>
        </li>
        <li
          className={styles.legendItem}
          data-dimmed={focus !== null && focus !== 'standard'}
          data-testid="legend-standard"
        >
          <span className={styles.legendSwatch} data-variant="standard" aria-hidden="true" />
          <span>
            Shortest walking route
            {focus === 'standard' ? (
              <span className={styles.legendNote}> · highlighted</span>
            ) : null}
          </span>
        </li>
        {stairs ? (
          <li className={styles.legendItem} data-testid="legend-stairs">
            <span className={styles.legendSwatch} data-variant="stairs" aria-hidden="true" />
            <span>Stairway recorded in OpenStreetMap</span>
          </li>
        ) : null}
      </ul>
    </div>
  );
}
