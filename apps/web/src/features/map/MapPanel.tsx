'use client';

import dynamic from 'next/dynamic';
import { MapStatusOverlay } from './MapStatusOverlay';
import { INITIAL_MAP_STATUS } from './map-state';
import styles from './MapPanel.module.css';
import type { MapCanvasProps } from './MapCanvas';

/**
 * Client-only boundary for the map.
 *
 * `ssr: false` is required: MapLibre constructs a WebGL context against `window`,
 * which does not exist during server rendering. The `loading` fallback renders the
 * same overlay the map itself uses while initialising, so there is no visual jump
 * between "chunk downloading" and "map initialising".
 */
const MapCanvas = dynamic(() => import('./MapCanvas').then((module) => module.MapCanvas), {
  ssr: false,
  loading: () => (
    <div className={styles.frame} data-map-state="initialising" data-testid="map-frame">
      <MapStatusOverlay status={INITIAL_MAP_STATUS} />
    </div>
  ),
});

export function MapPanel(props: MapCanvasProps) {
  // Keyed on the style URL: the map hook deliberately does not reset its own
  // state mid-life, so changing styles remounts a clean instance instead.
  return <MapCanvas key={props.styleUrl} {...props} />;
}
