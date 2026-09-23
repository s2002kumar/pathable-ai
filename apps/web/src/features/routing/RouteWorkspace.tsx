'use client';

import { type CSSProperties, type ReactNode, useCallback, useMemo, useRef, useState } from 'react';
import type { ProfileKey } from '@pathable/contracts';
import { MapPanel } from '@/features/map/MapPanel';
import type { RouteFocus } from '@/features/map/route-layers';
import { usePanelFit } from '@/features/map/usePanelFit';
import { RoutePlanner } from './RoutePlanner';
import { useRouteComparison } from './useRouteComparison';
import {
  type LngLat,
  type PlannerPoints,
  type ProfileSelection,
  type RouteRequestState,
  formatDistance,
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
 * Owns the planning state shared by the map and the panel.
 *
 * The routes have to be drawn *and* described, so neither the map nor the panel
 * can own them without reaching into the other. This component holds the two
 * endpoints, the chosen profile, the request, and which route (if any) the
 * viewer has brought forward, and hands both children exactly what they need.
 *
 * Layout: the map is the product, so it fills the workspace and everything else
 * floats over it — a planning surface against one edge, a map key against
 * another. What the panel covers is measured rather than assumed, because a
 * route framed underneath the panel is the same failure as a route drawn
 * off-screen.
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
    initialExample
      ? { origin: initialExample.origin, destination: initialExample.destination }
      : EMPTY_POINTS,
  );
  const [profileKey, setProfileKey] = useState<ProfileKey>('wheelchair');
  const [activeExampleId, setActiveExampleId] = useState<string | null>(initialExample?.id ?? null);
  const [focusedRoute, setFocusedRoute] = useState<RouteFocus>(null);
  // Only meaningful where the panel is a bottom sheet; the side layout ignores
  // it in CSS. Open by default, because the answer is the reason to be here.
  const [sheetOpen, setSheetOpen] = useState(true);
  const profile = useMemo<ProfileSelection>(() => ({ key: profileKey }), [profileKey]);

  const mapRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const fit = usePanelFit(mapRef, panelRef);

  const { state, retry } = useRouteComparison({
    apiBaseUrl,
    region,
    points,
    profile,
    ...(fetchImpl ? { fetchImpl } : {}),
  });

  const handleRunExample = useCallback((example: VerifiedExample) => {
    // Inputs only. Both endpoints and the profile land together, which is all
    // the comparison hook needs to issue the real request.
    setFocusedRoute(null);
    setPoints({ origin: example.origin, destination: example.destination });
    setProfileKey('wheelchair');
    setActiveExampleId(example.id);
    setSheetOpen(true);
  }, []);

  const handleSelectPoint = useCallback(
    (position: LngLat) => {
      setFocusedRoute(null);
      setActiveExampleId(null);

      if (points.origin === null) {
        setPoints({ ...points, origin: position });
        return;
      }
      if (points.destination === null) {
        // This click completes the pair, so a request follows it. A shut sheet
        // has its contents removed from the page, live region and all, so an
        // answer arriving into one would be announced to nobody — open it now,
        // while there is still only a "comparing routes" message to show.
        // Setting the first point deliberately does not: somebody who pulled
        // the sheet down to see more map is still placing points on it.
        setPoints({ ...points, destination: position });
        setSheetOpen(true);
        return;
      }
      // Both already set: start a new journey from here rather than making the
      // user press Clear first.
      setPoints({ origin: position, destination: null });
    },
    [points],
  );

  const handleClear = useCallback(() => {
    setFocusedRoute(null);
    setActiveExampleId(null);
    setPoints(EMPTY_POINTS);
  }, []);

  const handleSwap = useCallback(() => {
    setFocusedRoute(null);
    setPoints((current) => ({ origin: current.destination, destination: current.origin }));
  }, []);

  const handleProfileChange = useCallback((key: ProfileKey) => {
    setFocusedRoute(null);
    setProfileKey(key);
  }, []);

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

  // CSS places the map key and MapLibre's own credit clear of the panel from
  // the first paint; this replaces that estimate with the measurement. Only the
  // side actually covered is written, so the other keeps its CSS default.
  const insetStyle = useMemo<CSSProperties>(() => {
    const { side, amount } = fit.inset;
    if (amount <= 0 || (side !== 'bottom' && side !== 'left')) return {};
    const property = side === 'bottom' ? '--map-inset-bottom' : '--map-inset-left';
    return { [property]: `${Math.round(amount)}px` } as CSSProperties;
  }, [fit.inset]);

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
          origin={points.origin}
          destination={points.destination}
          focusedRoute={effectiveFocus}
          fitPadding={fit.padding}
          onSelectPoint={handleSelectPoint}
        />
      </div>

      <MapLegend focus={effectiveFocus} />

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
          {title}
          <RoutePlanner
            intro={intro}
            points={points}
            profileKey={profileKey}
            state={state}
            apiBaseUrl={apiBaseUrl}
            region={region}
            example={CAMPUS_EXAMPLE}
            exampleActive={activeExampleId === CAMPUS_EXAMPLE.id}
            focusedRoute={effectiveFocus}
            onFocusRoute={setFocusedRoute}
            onRunExample={handleRunExample}
            onProfileChange={handleProfileChange}
            onClearPoints={handleClear}
            onSwapPoints={handleSwap}
            onRetry={retry}
            onSelectPlace={handleSelectPoint}
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
 * explanation of what the two lines mean. When one route is brought forward it
 * says so in words, because a faded line is not a label.
 */
function MapLegend({ focus }: { readonly focus: RouteFocus }) {
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
      </ul>
    </div>
  );
}
