/**
 * The map's observable lifecycle.
 *
 * Kept in its own module, free of React and of MapLibre, so the state machine can
 * be unit-tested directly and so the e2e suite has a stable contract to wait on
 * (`[data-map-state]`) instead of racing a canvas.
 */

export type MapState = 'initialising' | 'ready' | 'error' | 'unsupported';

export type MapStatus = {
  readonly state: MapState;
  /** Human-readable explanation. Always present for non-success states. */
  readonly message: string | null;
};

export const INITIAL_MAP_STATUS: MapStatus = { state: 'initialising', message: null };

export const MAP_INIT_TIMEOUT_MS = 15_000;

export const MAP_ERROR_MESSAGE =
  'The map could not be loaded. This is usually a network problem or an unreachable ' +
  'map style. The pilot area is described in text below.';

export const MAP_TIMEOUT_MESSAGE =
  'The map is taking longer than expected to load and may be unavailable. The pilot ' +
  'area is described in text below.';

/** True once the map has reached a state that will not change on its own. */
export function isTerminal(status: MapStatus): boolean {
  return status.state !== 'initialising';
}

/** True when the user should be offered the textual fallback instead of the map. */
export function needsFallback(status: MapStatus): boolean {
  return status.state === 'error' || status.state === 'unsupported';
}
