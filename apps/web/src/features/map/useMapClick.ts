'use client';

import { useEffect } from 'react';
import type { MapInstance } from './useMapLibre';

type MapClickEvent = { lngLat: { lng: number; lat: number } };

/**
 * Reports where the user clicked on the map, in WGS84.
 *
 * `onSelect` is a real dependency rather than being stashed in a ref, so the
 * subscription is always attached to the handler that is actually current.
 * Callers are expected to pass a stable callback — `RouteWorkspace` wraps its
 * handler in `useCallback` — which keeps this from detaching and reattaching the
 * MapLibre listener on every parent render.
 */
export function useMapClick(
  map: MapInstance | null,
  onSelect: (position: { longitude: number; latitude: number }) => void,
): void {
  useEffect(() => {
    if (map === null) return;

    const listener = (event: MapClickEvent) => {
      onSelect({ longitude: event.lngLat.lng, latitude: event.lngLat.lat });
    };

    map.on('click', listener as (payload: never) => void);
    return () => {
      map.off('click', listener as (payload: never) => void);
    };
  }, [map, onSelect]);
}
