'use client';

import type { MapStatus } from './map-state';
import styles from './MapPanel.module.css';

export type MapStatusOverlayProps = {
  readonly status: MapStatus;
};

/**
 * Renders the map's loading, failure and unsupported states.
 *
 * Returns null once the map is ready so the canvas is unobstructed.
 */
export function MapStatusOverlay({ status }: MapStatusOverlayProps) {
  if (status.state === 'ready') return null;

  const isLoading = status.state === 'initialising';

  return (
    <div
      className={styles.overlay}
      data-testid="map-overlay"
      // Loading is announced politely; a failure is announced assertively because
      // the user is otherwise left waiting on something that will never arrive.
      role={isLoading ? 'status' : 'alert'}
      aria-live={isLoading ? 'polite' : 'assertive'}
    >
      <div className={styles.overlayInner}>
        {isLoading ? (
          <>
            <span className={styles.spinner} aria-hidden="true" />
            <p className={styles.overlayTitle}>Loading the map…</p>
            <p className={styles.overlayBody}>
              Preparing the pilot area. A written description is available below.
            </p>
          </>
        ) : (
          <>
            <span className={styles.icon} aria-hidden="true">
              !
            </span>
            <p className={styles.overlayTitle}>
              {status.state === 'unsupported'
                ? 'This browser cannot display the map'
                : 'The map is unavailable'}
            </p>
            <p className={styles.overlayBody}>{status.message}</p>
          </>
        )}
      </div>
    </div>
  );
}
