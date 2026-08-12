'use client';

import { useId, useRef } from 'react';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { Route } from '@pathable/contracts';
import { MapStatusOverlay } from './MapStatusOverlay';
import { useMapClick } from './useMapClick';
import { useMapLibre } from './useMapLibre';
import { useRouteLayers } from './useRouteLayers';
import styles from './MapPanel.module.css';

export type MapPoint = { readonly longitude: number; readonly latitude: number };

export type MapCanvasProps = {
  readonly styleUrl: string;
  readonly centerLat: number;
  readonly centerLon: number;
  readonly zoom: number;
  readonly regionName: string;
  readonly attribution: string;
  /** Text alternative describing the area, referenced by the map region. */
  readonly describedById?: string;

  // --- Routing -----------------------------------------------------------
  readonly standardRoute?: Route | null;
  readonly accessibleRoute?: Route | null;
  readonly origin?: MapPoint | null;
  readonly destination?: MapPoint | null;
  readonly showStandardRoute?: boolean;
  /**
   * Called with the clicked position. Absent when the map is decorative, which
   * is what keeps this component usable outside the planner.
   */
  readonly onSelectPoint?: (position: MapPoint) => void;
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
  standardRoute = null,
  accessibleRoute = null,
  origin = null,
  destination = null,
  showStandardRoute = true,
  onSelectPoint,
}: MapCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const fallbackId = useId();

  const { status, map } = useMapLibre({
    containerRef,
    styleUrl,
    center: [centerLon, centerLat],
    zoom,
    attribution,
  });

  useRouteLayers({ map, standardRoute, accessibleRoute, origin, destination, showStandardRoute });
  useMapClick(map, onSelectPoint ?? noop);

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

function noop(): void {
  // The map is still clickable when no handler is supplied; it just does nothing.
}

export default MapCanvas;
