'use client';

import { useEffect, useRef } from 'react';
import type { Route } from '@pathable/contracts';
import type { MapInstance } from './useMapLibre';
import {
  ACCESSIBLE_LAYER_ID,
  ACCESSIBLE_SOURCE_ID,
  EMPTY_LINES,
  EMPTY_POINTS,
  POINTS_LABEL_LAYER_ID,
  POINTS_LAYER_ID,
  POINTS_SOURCE_ID,
  STANDARD_LAYER_ID,
  STANDARD_SOURCE_ID,
  accessibleLineLayer,
  boundsOf,
  pointCircleLayer,
  pointLabelLayer,
  pointsToGeoJson,
  routeToGeoJson,
  standardLineLayer,
} from './route-layers';

type GeoJsonSource = { setData: (data: unknown) => void };

export type UseRouteLayersOptions = {
  readonly map: MapInstance | null;
  readonly standardRoute: Route | null;
  readonly accessibleRoute: Route | null;
  readonly origin: { longitude: number; latitude: number } | null;
  readonly destination: { longitude: number; latitude: number } | null;
  /** Whether the standard route is drawn at all. */
  readonly showStandardRoute?: boolean;
};

/**
 * Keeps the map's route layers in step with the current comparison.
 *
 * Sources and layers are created once and then updated with `setData`, rather
 * than being removed and re-added on every change. Re-adding causes a visible
 * flicker and forces MapLibre to re-parse the style, and route updates happen on
 * every profile change.
 */
export function useRouteLayers({
  map,
  standardRoute,
  accessibleRoute,
  origin,
  destination,
  showStandardRoute = true,
}: UseRouteLayersOptions): void {
  // The last bounds we fitted to. Refitting on every render would fight the user
  // for control of the viewport; refitting only when the route actually changes
  // keeps their pan and zoom.
  const lastFitted = useRef<string | null>(null);

  useEffect(() => {
    if (map === null) return;

    ensureLayers(map);

    const standard = showStandardRoute ? routeToGeoJson(standardRoute) : EMPTY_LINES;
    const accessible = routeToGeoJson(accessibleRoute);
    const points = pointsToGeoJson(origin, destination);

    setData(map, STANDARD_SOURCE_ID, standard);
    setData(map, ACCESSIBLE_SOURCE_ID, accessible);
    setData(map, POINTS_SOURCE_ID, points);

    const bounds = boundsOf(standard, accessible, points);
    if (bounds === null) {
      lastFitted.current = null;
      return;
    }

    const signature = JSON.stringify(bounds);
    if (signature === lastFitted.current) return;
    lastFitted.current = signature;

    map.fitBounds(bounds, {
      // Enough room that the route is not tucked under the panel or the
      // attribution control.
      padding: { top: 60, bottom: 80, left: 60, right: 60 },
      maxZoom: 17,
      duration: 500,
    });
  }, [map, standardRoute, accessibleRoute, origin, destination, showStandardRoute]);

  // Layers belong to the map, and the map is torn down with its container — so
  // there is deliberately no removal here. Removing them on unmount would race
  // MapLibre's own teardown and throw on an already-destroyed style.
}

function ensureLayers(map: MapInstance): void {
  addEmptySource(map, STANDARD_SOURCE_ID, EMPTY_LINES);
  addEmptySource(map, ACCESSIBLE_SOURCE_ID, EMPTY_LINES);
  addEmptySource(map, POINTS_SOURCE_ID, EMPTY_POINTS);

  // Order matters: the standard route is a reference line and must sit beneath
  // the route the user is actually being offered.
  addLayerOnce(map, STANDARD_LAYER_ID, standardLineLayer());
  addLayerOnce(map, ACCESSIBLE_LAYER_ID, accessibleLineLayer());
  addLayerOnce(map, POINTS_LAYER_ID, pointCircleLayer());
  addLayerOnce(map, POINTS_LABEL_LAYER_ID, pointLabelLayer());
}

function addEmptySource(map: MapInstance, id: string, data: unknown): void {
  if (map.getSource(id)) return;
  map.addSource(id, { type: 'geojson', data });
}

function addLayerOnce(map: MapInstance, id: string, layer: unknown): void {
  if (map.getLayer(id)) return;
  map.addLayer(layer);
}

function setData(map: MapInstance, id: string, data: unknown): void {
  const source = map.getSource(id) as GeoJsonSource | undefined;
  source?.setData(data);
}
