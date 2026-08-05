'use client';

import { type RefObject, useEffect, useState } from 'react';
import {
  INITIAL_MAP_STATUS,
  MAP_ERROR_MESSAGE,
  MAP_INIT_TIMEOUT_MS,
  MAP_TIMEOUT_MESSAGE,
  type MapStatus,
} from './map-state';
import { type WebGlSupport, detectWebGl } from './webgl';

export type UseMapLibreOptions = {
  readonly containerRef: RefObject<HTMLDivElement | null>;
  readonly styleUrl: string;
  readonly center: readonly [longitude: number, latitude: number];
  readonly zoom: number;
  readonly attribution: string;
  readonly initTimeoutMs?: number;
  /** Injectable for tests; defaults to real WebGL detection. */
  readonly detect?: () => WebGlSupport;
};

/**
 * Owns one MapLibre instance for the lifetime of the container element.
 *
 * MapLibre is imported dynamically inside the effect for three reasons: it keeps
 * ~800 kB out of the initial bundle, it guarantees the library never evaluates
 * during server rendering, and it leaves this module importable under jsdom so
 * the lifecycle can be tested without a GPU.
 *
 * Note on re-initialisation: the effect does not reset state when `styleUrl`
 * changes, because a synchronous setState in an effect body causes cascading
 * renders. Callers that need to swap styles should remount instead — MapPanel
 * keys the canvas on the style URL for exactly this reason.
 */
export function useMapLibre({
  containerRef,
  styleUrl,
  center,
  zoom,
  attribution,
  initTimeoutMs = MAP_INIT_TIMEOUT_MS,
  detect = detectWebGl,
}: UseMapLibreOptions): MapStatus {
  // Capability, not state: resolved once on first render rather than in an
  // effect, so an unsupported browser renders its explanation immediately
  // instead of flashing a loading spinner it will never resolve.
  const [support] = useState<WebGlSupport>(detect);
  const [mapStatus, setMapStatus] = useState<MapStatus>(INITIAL_MAP_STATUS);
  const [longitude, latitude] = center;

  useEffect(() => {
    if (!support.supported) return;

    const container = containerRef.current;
    if (container === null) return;

    // Guards the async gap: React 19 StrictMode runs this effect twice in
    // development, and without this the first run's import could finish after the
    // second run's cleanup and leave an orphaned map attached to the container.
    let cancelled = false;
    let ready = false;
    let map: { remove: () => void } | null = null;

    const timer = setTimeout(() => {
      if (!cancelled && !ready) {
        setMapStatus({ state: 'error', message: MAP_TIMEOUT_MESSAGE });
      }
    }, initTimeoutMs);

    void (async () => {
      try {
        const maplibre = await import('maplibre-gl');
        if (cancelled) return;

        const instance = new maplibre.Map({
          container,
          style: styleUrl,
          center: [longitude, latitude],
          zoom,
          // Replaced below with a non-compact control so attribution is visible
          // rather than hidden behind an "i" button.
          attributionControl: false,
          // Keeps the canvas sized to its container without a manual listener.
          trackResize: true,
        });

        if (cancelled) {
          instance.remove();
          return;
        }
        map = instance;

        instance.addControl(
          new maplibre.AttributionControl({ compact: false, customAttribution: attribution }),
          'bottom-right',
        );
        instance.addControl(
          new maplibre.NavigationControl({ showCompass: false, visualizePitch: false }),
          'top-right',
        );
        instance.addControl(new maplibre.ScaleControl({ unit: 'metric' }), 'bottom-left');

        instance.on('load', () => {
          if (cancelled) return;
          ready = true;
          clearTimeout(timer);
          setMapStatus({ state: 'ready', message: null });
        });

        instance.on('error', (event: { error?: { message?: string } }) => {
          // A tile that fails after the map is up is a degraded map, not a broken
          // one; flipping an already-usable map to an error screen would be worse
          // than the missing tile.
          if (cancelled || ready) return;
          clearTimeout(timer);
          console.error('MapLibre initialisation failed', event.error);
          setMapStatus({ state: 'error', message: MAP_ERROR_MESSAGE });
        });
      } catch (error) {
        if (cancelled) return;
        clearTimeout(timer);
        console.error('MapLibre could not be loaded', error);
        setMapStatus({ state: 'error', message: MAP_ERROR_MESSAGE });
      }
    })();

    return () => {
      cancelled = true;
      clearTimeout(timer);
      map?.remove();
    };
  }, [support, containerRef, styleUrl, longitude, latitude, zoom, attribution, initTimeoutMs]);

  return support.supported ? mapStatus : { state: 'unsupported', message: support.reason };
}
