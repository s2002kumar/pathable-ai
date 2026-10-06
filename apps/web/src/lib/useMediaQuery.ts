'use client';

import { useSyncExternalStore } from 'react';

/**
 * Whether a media query matches, kept in step with the viewport.
 *
 * Server renders and the first client render report `false` (the desktop
 * composition); the real answer arrives on the first subscription. Used only
 * where the two compositions differ in content, not just in layout — CSS
 * handles everything that is only layout.
 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (notify) => {
      if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
        return () => {};
      }
      const list = window.matchMedia(query);
      list.addEventListener('change', notify);
      return () => list.removeEventListener('change', notify);
    },
    () =>
      typeof window !== 'undefined' && typeof window.matchMedia === 'function'
        ? window.matchMedia(query).matches
        : false,
    () => false,
  );
}

/** The Golden Master's phone composition (17:2865) applies below 720 px. */
export const PHONE_QUERY = '(max-width: 719px)';
