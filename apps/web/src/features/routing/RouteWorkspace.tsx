'use client';

import { useCallback, useMemo, useState } from 'react';
import type { ProfileKey } from '@pathable/contracts';
import { MapPanel } from '@/features/map/MapPanel';
import { RoutePlanner } from './RoutePlanner';
import { useRouteComparison } from './useRouteComparison';
import type { LngLat, PlannerPoints, ProfileSelection } from './types';
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
};

const EMPTY_POINTS: PlannerPoints = { origin: null, destination: null };

/**
 * Owns the planning state shared by the map and the panel.
 *
 * The routes have to be drawn *and* described, so neither the map nor the panel
 * can own them without reaching into the other. This component holds the two
 * endpoints, the chosen profile and the request, and hands both children exactly
 * what they need.
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
}: RouteWorkspaceProps) {
  const [points, setPoints] = useState<PlannerPoints>(EMPTY_POINTS);
  const [profileKey, setProfileKey] = useState<ProfileKey>('wheelchair');
  const profile = useMemo<ProfileSelection>(() => ({ key: profileKey }), [profileKey]);

  const { state, retry } = useRouteComparison({
    apiBaseUrl,
    region,
    points,
    profile,
    ...(fetchImpl ? { fetchImpl } : {}),
  });

  const handleSelectPoint = useCallback((position: LngLat) => {
    setPoints((current) => {
      if (current.origin === null) return { ...current, origin: position };
      if (current.destination === null) return { ...current, destination: position };
      // Both already set: start a new journey from here rather than making the
      // user press Clear first.
      return { origin: position, destination: null };
    });
  }, []);

  const handleClear = useCallback(() => {
    setPoints(EMPTY_POINTS);
  }, []);

  const handleSwap = useCallback(() => {
    setPoints((current) => ({ origin: current.destination, destination: current.origin }));
  }, []);

  const comparison = state.status === 'success' ? state.comparison : null;

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
          onSelectPoint={handleSelectPoint}
        />
        <MapLegend />
      </div>

      <div className={styles.panelArea}>
        <RoutePlanner
          points={points}
          profileKey={profileKey}
          state={state}
          apiBaseUrl={apiBaseUrl}
          region={region}
          onProfileChange={setProfileKey}
          onClearPoints={handleClear}
          onSwapPoints={handleSwap}
          onRetry={retry}
          onSelectPlace={handleSelectPoint}
          {...(fetchImpl ? { fetchImpl } : {})}
        />
      </div>
    </div>
  );
}

/**
 * The map legend.
 *
 * Outside the canvas so it is real text: a legend painted into WebGL is
 * invisible to a screen reader and unselectable, and this one carries the only
 * explanation of what the two lines mean.
 */
function MapLegend() {
  return (
    <div className={styles.legend} data-testid="map-legend">
      <h2 className={styles.legendHeading}>Map key</h2>
      <ul className={styles.legendList}>
        <li className={styles.legendItem}>
          <span className={styles.legendSwatch} data-variant="accessible" aria-hidden="true" />
          Route for your profile
        </li>
        <li className={styles.legendItem}>
          <span className={styles.legendSwatch} data-variant="standard" aria-hidden="true" />
          Shortest walking route
        </li>
      </ul>
    </div>
  );
}
