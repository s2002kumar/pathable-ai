'use client';

import { useEffect, useRef } from 'react';
import { Icon, type IconName } from '@/components/Icon';
import type { MapInstance } from './useMapLibre';
import styles from './MapPanel.module.css';

/**
 * A short label pinned to a place on the map.
 *
 * `tone` is what kind of mark it is, never how safe anything is: `barrier` is
 * something the chosen profile rules out, `gradient` is a figure about a
 * climb, `unknown` is something nobody recorded.
 */
export type MapMarker = {
  readonly id: string;
  readonly position: readonly [number, number];
  /** The first line: what the mark is. */
  readonly label: string;
  readonly tone: 'barrier' | 'gradient' | 'unknown' | 'origin' | 'destination';
  /**
   * `pin`: the comparison's evidence pins (9:1964). `callout`: the evidence
   * view's gap callouts (17:3808). `endpoint`: a place name beside A or B
   * (17:3576). Defaults to `pin`.
   */
  readonly variant?: 'pin' | 'callout' | 'endpoint' | 'badge';
  /** Where the fact came from: "Recorded · OSM", "Derived · HRDEM", "Not recorded". */
  readonly tag?: string;
  /** The second line: which route, and why it matters. */
  readonly detail?: string;
  readonly icon?: IconName;
  /** Measurements read in the mono face, as the design sets them. */
  readonly mono?: boolean;
};

/** How far above its point a pin sits, matching `.markerPill` in the CSS. */
const PILL_LIFT_PX = 14;
/** Space kept clear around a pin before another counts as overlapping it. */
const PILL_MARGIN_PX = 4;
/** How far right of A or B its name starts, matching `.endpointLabel`. */
const ENDPOINT_OFFSET_PX = 18;

type Box = { left: number; right: number; top: number; bottom: number };

function overlaps(a: Box, b: Box): boolean {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}

const DEFAULT_ICONS: Readonly<Record<MapMarker['tone'], IconName>> = {
  barrier: 'pin-stairs',
  gradient: 'pin-check',
  unknown: 'pin-question',
  origin: 'pin-location',
  destination: 'pin-location',
};

/** Where a label sits relative to its point, as a box for collision tests. */
function boxFor(
  variant: MapMarker['variant'],
  x: number,
  y: number,
  width: number,
  height: number,
): Box {
  if (variant === 'endpoint') {
    return {
      left: x + ENDPOINT_OFFSET_PX - PILL_MARGIN_PX,
      right: x + ENDPOINT_OFFSET_PX + width + PILL_MARGIN_PX,
      top: y - height / 2 - PILL_MARGIN_PX,
      bottom: y + height / 2 + PILL_MARGIN_PX,
    };
  }
  return {
    left: x - width / 2 - PILL_MARGIN_PX,
    right: x + width / 2 + PILL_MARGIN_PX,
    top: y - PILL_LIFT_PX - height - PILL_MARGIN_PX,
    bottom: y - PILL_LIFT_PX + PILL_MARGIN_PX,
  };
}

/**
 * Evidence labels over the map, as ordinary DOM.
 *
 * Not a MapLibre symbol layer: text in the canvas needs the basemap's glyph
 * server, is invisible to the test style, and cannot be read or selected. These
 * are positioned with the map's own projection and moved on every camera
 * change — by writing the transform directly, not through React state, so a
 * pan does not re-render the panel sixty times a second.
 *
 * Hidden from assistive technology on purpose. Every label repeats a statement
 * the panel makes in full, next to its evidence; announcing both would say it
 * twice, the second time without the context.
 */
export function MapMarkers({
  map,
  markers,
}: {
  readonly map: MapInstance | null;
  readonly markers: readonly MapMarker[];
}) {
  const elements = useRef(new Map<string, HTMLDivElement>());

  useEffect(() => {
    const project = map?.project;
    if (map === null || project === undefined || markers.length === 0) return;

    const place = () => {
      // In the order given, which is the order of importance: a label whose
      // pin would cover one already placed is hidden rather than stacked on
      // it. Zoomed out, a barrier and a climb a few metres apart would
      // otherwise cover each other and neither could be read. Measured from
      // the pins themselves, because their width is their text.
      const placed: Box[] = [];
      for (const marker of markers) {
        const element = elements.current.get(marker.id);
        if (!element) continue;
        const { x, y } = project.call(map, [marker.position[0], marker.position[1]]);
        element.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
        const pill = element.querySelector<HTMLElement>('[data-pin]');
        const box = boxFor(marker.variant, x, y, pill?.offsetWidth ?? 0, pill?.offsetHeight ?? 0);
        const collides = placed.some((other) => overlaps(box, other));
        element.style.visibility = collides ? 'hidden' : 'visible';
        if (!collides) placed.push(box);
      }
    };

    place();
    map.on('move', place);
    map.on('resize', place);
    return () => {
      map.off('move', place);
      map.off('resize', place);
    };
  }, [map, markers]);

  if (map === null || map.project === undefined || markers.length === 0) return null;

  return (
    <div className={styles.markers} aria-hidden="true" data-testid="map-evidence">
      {markers.map((marker) => (
        <div
          key={marker.id}
          ref={(element) => {
            if (element) elements.current.set(marker.id, element);
            else elements.current.delete(marker.id);
          }}
          className={styles.marker}
          data-tone={marker.tone}
          data-variant={marker.variant ?? 'pin'}
          // Placed by the effect once the map can project; until then it would
          // sit in the corner.
          style={{ visibility: 'hidden' }}
        >
          {marker.variant === 'endpoint' ? null : <span className={styles.markerPoint} />}
          {marker.variant === 'endpoint' ? (
            <span
              className={styles.endpointLabel}
              data-pin=""
              data-testid={`map-marker-${marker.id}`}
            >
              <span className={styles.endpointLabelDot} />
              <span className={styles.endpointLabelName}>{marker.label}</span>
              {marker.tag ? <span className={styles.endpointLabelRole}>{marker.tag}</span> : null}
            </span>
          ) : marker.variant === 'badge' ? (
            <span className={styles.badge} data-pin="" data-testid={`map-marker-${marker.id}`}>
              <Icon name={marker.icon ?? DEFAULT_ICONS[marker.tone]} size={11} />
              {marker.label}
            </span>
          ) : marker.variant === 'callout' ? (
            <span className={styles.callout} data-pin="" data-testid={`map-marker-${marker.id}`}>
              <span className={styles.calloutDot} />
              <span className={styles.markerText}>
                <span className={styles.calloutTitle}>{marker.label}</span>
                {marker.detail ? (
                  <span className={styles.calloutDetail}>{marker.detail}</span>
                ) : null}
              </span>
              <span className={styles.calloutIcon}>
                <Icon name={marker.icon ?? 'warning'} />
              </span>
            </span>
          ) : (
            <span className={styles.markerPill} data-pin="" data-testid={`map-marker-${marker.id}`}>
              <span className={styles.markerIcon}>
                <Icon name={marker.icon ?? DEFAULT_ICONS[marker.tone]} size={16} />
              </span>
              <span className={styles.markerText}>
                <span className={styles.markerHead}>
                  <span className={marker.mono ? styles.markerTitleMono : styles.markerTitle}>
                    {marker.label}
                  </span>
                  {marker.tag ? <span className={styles.markerTag}>{marker.tag}</span> : null}
                </span>
                {marker.detail ? (
                  <span className={styles.markerDetail}>{marker.detail}</span>
                ) : null}
              </span>
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
