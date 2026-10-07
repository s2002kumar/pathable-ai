'use client';

import { useId, useRef } from 'react';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { Route } from '@pathable/contracts';
import { MapControls, type MapControlsProps } from './MapControls';
import { type MapMarker, MapMarkers } from './MapMarkers';
import { MapStatusOverlay } from './MapStatusOverlay';
import type { LineFeatureCollection, Padding, RecordedStairs, RouteFocus } from './route-layers';
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
  /** Which route to bring forward on the map, if the viewer asked for one. */
  readonly focusedRoute?: RouteFocus;
  /** Room to leave around a fitted route, so the panel floating over the map
   *  never sits on top of the answer; a function is measured as the camera
   *  moves. */
  readonly fitPadding?: Padding | (() => Padding);
  /** Recorded stairways to draw over the route, or null for none. */
  readonly stairs?: RecordedStairs | null;
  /** Unrecorded stretches of the shown route, for the evidence view. */
  readonly gaps?: LineFeatureCollection | null;
  /** Labels pinned to the map: what the profile rules out, the steepest climb. */
  readonly markers?: readonly MapMarker[];
  /** Incremented to re-frame the routes on request. */
  readonly fitRequest?: number;
  /** The view the routes are framed for; a new one re-frames them. */
  readonly fitScope?: string;
  /**
   * Called with the clicked position. Absent when the map is decorative, which
   * is what keeps this component usable outside the planner.
   */
  readonly onSelectPoint?: (position: MapPoint) => void;
  /**
   * Quiets the basemap behind an idle planner, as the Golden Master's idle
   * frame does. Drawn under the pins, so A and its name stay bright.
   */
  readonly veil?: boolean;
  /** The map's own controls; absent where the map is decorative. */
  readonly controls?: Omit<MapControlsProps, 'map'>;
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
  focusedRoute = null,
  fitPadding,
  stairs = null,
  gaps = null,
  markers = NO_MARKERS,
  fitRequest = 0,
  fitScope,
  onSelectPoint,
  controls,
  veil = false,
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

  useRouteLayers({
    map,
    standardRoute,
    accessibleRoute,
    origin,
    destination,
    showStandardRoute,
    focus: focusedRoute,
    ...(fitPadding ? { fitPadding } : {}),
    stairs,
    fitRequest,
    ...(fitScope !== undefined ? { fitScope } : {}),
    gaps,
  });
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
      {veil ? <div className={styles.veil} aria-hidden="true" /> : null}
      <MapMarkers map={map} markers={markers} />
      {controls ? <MapControls map={map} {...controls} /> : null}
      <MapStatusOverlay status={status} />
    </div>
  );
}

const NO_MARKERS: readonly MapMarker[] = [];

function noop(): void {
  // The map is still clickable when no handler is supplied; it just does nothing.
}

export default MapCanvas;
