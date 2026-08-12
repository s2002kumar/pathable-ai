'use client';

import { useId, useRef } from 'react';
import 'maplibre-gl/dist/maplibre-gl.css';
import { MapStatusOverlay } from './MapStatusOverlay';
import { useMapLibre } from './useMapLibre';
import styles from './MapPanel.module.css';

export type MapCanvasProps = {
  readonly styleUrl: string;
  readonly centerLat: number;
  readonly centerLon: number;
  readonly zoom: number;
  readonly regionName: string;
  readonly attribution: string;
  /** Text alternative describing the area, referenced by the map region. */
  readonly describedById?: string;
};

/**
 * The MapLibre surface.
 *
 * Only ever rendered on the client (see MapPanel), because MapLibre touches
 * `window` and WebGL at construction time.
 */
export function MapCanvas({
  styleUrl,
  centerLat,
  centerLon,
  zoom,
  regionName,
  attribution,
  describedById,
}: MapCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const fallbackId = useId();

  const status = useMapLibre({
    containerRef,
    styleUrl,
    center: [centerLon, centerLat],
    zoom,
    attribution,
  });

  return (
    <div
      className={styles.frame}
      // The e2e suite waits on this instead of racing the canvas, which keeps
      // browser tests deterministic and free of tile-server dependence.
      data-map-state={status.state}
      data-testid="map-frame"
    >
      <div
        ref={containerRef}
        className={styles.canvas}
        // A named region, so the map is announced and reachable by rotor/landmark
        // navigation rather than being an anonymous div.
        role="region"
        aria-label={`Interactive map of ${regionName}`}
        {...(describedById !== undefined ? { 'aria-describedby': describedById } : {})}
        id={fallbackId}
      />
      <MapStatusOverlay status={status} />
    </div>
  );
}

export default MapCanvas;
