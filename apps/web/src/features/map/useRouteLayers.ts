'use client';

import { useEffect, useRef } from 'react';
import type { Route } from '@pathable/contracts';
import type { MapInstance } from './useMapLibre';
import {
  ACCESSIBLE_CASING_LAYER_ID,
  ACCESSIBLE_LAYER_ID,
  ACCESSIBLE_SOURCE_ID,
  EMPTY_LINES,
  EMPTY_POINTS,
  FIT_PADDING,
  type Padding,
  POINTS_HALO_LAYER_ID,
  POINTS_LABEL_LAYER_ID,
  POINTS_LAYER_ID,
  POINTS_SOURCE_ID,
  type RouteFocus,
  STANDARD_CASING_LAYER_ID,
  STANDARD_LAYER_ID,
  STANDARD_SOURCE_ID,
  accessibleCasingLayer,
  accessibleLineLayer,
  boundsOf,
  cameraDuration,
  lineOpacity,
  pointCircleLayer,
  pointHaloLayer,
  pointLabelLayer,
  pointsToGeoJson,
  prefersReducedMotion,
  routeToGeoJson,
  standardCasingLayer,
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
  /** Which route to bring forward; the other fades but stays. */
  readonly focus?: RouteFocus;
  /**
   * Room to leave around a fitted route, measured from the floating panel by
   * the workspace. Deliberately not a dependency of the fitting effect: a
   * viewer who resizes the window, or opens a disclosure that makes the panel
   * taller, has not asked for the camera to move.
   */
  readonly fitPadding?: Padding;
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
  focus = null,
  fitPadding,
}: UseRouteLayersOptions): void {
  // The last bounds we fitted to. Refitting on every render would fight the user
  // for control of the viewport; refitting only when the route actually changes
  // keeps their pan and zoom.
  const lastFitted = useRef<string | null>(null);

  // Read at fit time rather than depended on, for the reason above. Synced in
  // an effect rather than during render, and declared before the effect that
  // reads it so a commit that changes both has the new padding by the time the
  // camera moves.
  const padding = useRef<Padding>({ ...FIT_PADDING });
  useEffect(() => {
    padding.current = fitPadding ?? { ...FIT_PADDING };
  }, [fitPadding]);

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
      padding: padding.current,
      maxZoom: 17,
      // Capped, and nothing at all for a viewer who asked for less motion.
      duration: cameraDuration(prefersReducedMotion()),
    });
  }, [map, standardRoute, accessibleRoute, origin, destination, showStandardRoute]);

  // Focus is paint only. It never touches the sources and never moves the
  // camera, so bringing one route forward cannot undo a viewer's pan or zoom.
  useEffect(() => {
    if (map === null) return;
    ensureLayers(map);

    const standardOpacity = lineOpacity('standard', focus);
    const accessibleOpacity = lineOpacity('accessible', focus);
    map.setPaintProperty(STANDARD_LAYER_ID, 'line-opacity', standardOpacity);
    map.setPaintProperty(STANDARD_CASING_LAYER_ID, 'line-opacity', standardOpacity * 0.9);
    map.setPaintProperty(ACCESSIBLE_LAYER_ID, 'line-opacity', accessibleOpacity);
    map.setPaintProperty(ACCESSIBLE_CASING_LAYER_ID, 'line-opacity', accessibleOpacity * 0.9);
  }, [map, focus]);

  // Layers belong to the map, and the map is torn down with its container — so
  // there is deliberately no removal here. Removing them on unmount would race
  // MapLibre's own teardown and throw on an already-destroyed style.
}

function ensureLayers(map: MapInstance): void {
  addEmptySource(map, STANDARD_SOURCE_ID, EMPTY_LINES);
  addEmptySource(map, ACCESSIBLE_SOURCE_ID, EMPTY_LINES);
  addEmptySource(map, POINTS_SOURCE_ID, EMPTY_POINTS);

  // Order matters: the standard route is a reference line and must sit beneath
  // the route the user is actually being offered, and each casing sits directly
  // under its own line.
  addLayerOnce(map, STANDARD_CASING_LAYER_ID, standardCasingLayer());
  addLayerOnce(map, STANDARD_LAYER_ID, standardLineLayer());
  addLayerOnce(map, ACCESSIBLE_CASING_LAYER_ID, accessibleCasingLayer());
  addLayerOnce(map, ACCESSIBLE_LAYER_ID, accessibleLineLayer());
  addLayerOnce(map, POINTS_HALO_LAYER_ID, pointHaloLayer());
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
