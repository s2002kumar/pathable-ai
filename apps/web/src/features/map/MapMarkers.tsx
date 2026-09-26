'use client';

import { useEffect, useRef } from 'react';
import type { MapInstance } from './useMapLibre';
import styles from './MapPanel.module.css';

/**
 * A short label pinned to a place on the map.
 *
 * `tone` is what kind of mark it is, never how safe anything is: `barrier` is
 * something the chosen profile rules out, `gradient` is a figure about a climb.
 */
export type MapMarker = {
  readonly id: string;
  readonly position: readonly [number, number];
  readonly label: string;
  readonly tone: 'barrier' | 'gradient';
};

/** How far above its point a pill sits, matching `.markerPill` in the CSS. */
const PILL_LIFT_PX = 10;
/** Space kept clear around a pill before another counts as overlapping it. */
const PILL_MARGIN_PX = 4;

type Box = { left: number; right: number; top: number; bottom: number };

function overlaps(a: Box, b: Box): boolean {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
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
      // pill would cover one already placed is hidden rather than stacked on
      // it. Zoomed out, a barrier and a climb a few metres apart would
      // otherwise cover each other and neither could be read. Measured from
      // the pills themselves, because their width is their text.
      const placed: Box[] = [];
      for (const marker of markers) {
        const element = elements.current.get(marker.id);
        if (!element) continue;
        const { x, y } = project.call(map, [marker.position[0], marker.position[1]]);
        element.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
        const pill = element.firstElementChild as HTMLElement | null;
        const halfWidth = (pill?.offsetWidth ?? 0) / 2;
        const height = pill?.offsetHeight ?? 0;
        const box: Box = {
          left: x - halfWidth - PILL_MARGIN_PX,
          right: x + halfWidth + PILL_MARGIN_PX,
          top: y - PILL_LIFT_PX - height - PILL_MARGIN_PX,
          bottom: y - PILL_LIFT_PX + PILL_MARGIN_PX,
        };
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
          // Placed by the effect once the map can project; until then it would
          // sit in the corner.
          style={{ visibility: 'hidden' }}
        >
          <span className={styles.markerPill} data-testid={`map-marker-${marker.id}`}>
            <span className={styles.markerDot} />
            {marker.label}
          </span>
        </div>
      ))}
    </div>
  );
}
