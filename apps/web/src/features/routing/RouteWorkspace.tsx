'use client';

import { type ReactNode, useCallback, useMemo, useState } from 'react';
import type { ProfileKey } from '@pathable/contracts';
import { MapPanel } from '@/features/map/MapPanel';
import type { RouteFocus } from '@/features/map/route-layers';
import { RoutePlanner } from './RoutePlanner';
import { useRouteComparison } from './useRouteComparison';
import type { LngLat, PlannerPoints, ProfileSelection } from './types';
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
  /** Rendered at the top of the planner column: the page title. */
  readonly title?: ReactNode;
  /** Rendered after the result, before the planning controls: the purpose statement. */
  readonly intro?: ReactNode;
  /** Rendered at the bottom of the planner column: data attribution. */
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
  const profile = useMemo<ProfileSelection>(() => ({ key: profileKey }), [profileKey]);

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
  }, []);

  const handleSelectPoint = useCallback((position: LngLat) => {
    setFocusedRoute(null);
    setActiveExampleId(null);
    setPoints((current) => {
      if (current.origin === null) return { ...current, origin: position };
      if (current.destination === null) return { ...current, destination: position };
      // Both already set: start a new journey from here rather than making the
      // user press Clear first.
      return { origin: position, destination: null };
    });
  }, []);

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

  return (
    <div className={styles.workspace}>
      <div className={styles.mapArea}>
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
          onSelectPoint={handleSelectPoint}
        />
        <MapLegend focus={effectiveFocus} />
      </div>

      <aside className={styles.panelArea} aria-label="Route planner">
        <span className={styles.grip} aria-hidden="true" />
        <div className={styles.panelInner}>
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
