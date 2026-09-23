'use client';

import { type RefObject, useCallback, useEffect, useState } from 'react';
import { FIT_PADDING, type Padding, type Rect, paddingForPanel } from './route-layers';

/** Which edge of the map the panel is covering, and by how many pixels. */
export type PanelInset = {
  readonly side: keyof Padding;
  readonly amount: number;
};

export type PanelFit = {
  /** Room to leave around a fitted route, for `fitBounds`. */
  readonly padding: Padding;
  /** The same measurement, for placing the map's own chrome clear of the panel. */
  readonly inset: PanelInset;
};

const NO_INSET: PanelInset = { side: 'left', amount: 0 };

function rectOf(element: Element | null): Rect | null {
  if (element === null) return null;
  const { left, top, right, bottom, width, height } = element.getBoundingClientRect();
  return { left, top, right, bottom, width, height };
}

function sameFit(a: PanelFit, b: PanelFit): boolean {
  return (
    a.inset.side === b.inset.side &&
    a.inset.amount === b.inset.amount &&
    a.padding.top === b.padding.top &&
    a.padding.bottom === b.padding.bottom &&
    a.padding.left === b.padding.left &&
    a.padding.right === b.padding.right
  );
}

/**
 * Measure how far the floating panel reaches into the map.
 *
 * The map fills the viewport and the planning surface floats over one edge of
 * it, so "fit the route to the map" and "fit the route to the part of the map
 * anybody can see" are no longer the same instruction. CSS knows where the
 * panel is; the camera needs it in pixels, and the panel's height changes with
 * its content — a result is taller than an empty planner — so this is measured
 * rather than assumed.
 *
 * Both elements are observed, not just the panel: rotating a phone or dragging
 * a window edge changes the map without changing the panel's own box.
 *
 * Returns the base padding until both elements exist, which is also what a
 * renderer without `ResizeObserver` gets: the route is still framed, just
 * without the allowance.
 */
export function usePanelFit(
  mapRef: RefObject<HTMLElement | null>,
  panelRef: RefObject<HTMLElement | null>,
): PanelFit {
  const [fit, setFit] = useState<PanelFit>({ padding: { ...FIT_PADDING }, inset: NO_INSET });

  const measure = useCallback(() => {
    const map = rectOf(mapRef.current);
    const panel = rectOf(panelRef.current);
    const padding = paddingForPanel(map, panel);

    // Which side grew, and by how much. Derived from the same function the
    // camera uses so the map key and the credit cannot drift from the fit.
    const base = FIT_PADDING;
    let inset: PanelInset = NO_INSET;
    for (const side of ['left', 'right', 'top', 'bottom'] as const) {
      const amount = padding[side] - base[side];
      if (amount > inset.amount) inset = { side, amount };
    }

    const next = { padding, inset };
    setFit((current) => (sameFit(current, next) ? current : next));
  }, [mapRef, panelRef]);

  useEffect(() => {
    measure();

    const map = mapRef.current;
    const panel = panelRef.current;
    if (typeof ResizeObserver !== 'function') return;

    const observer = new ResizeObserver(() => measure());
    if (map !== null) observer.observe(map);
    if (panel !== null) observer.observe(panel);
    return () => observer.disconnect();
  }, [measure, mapRef, panelRef]);

  return fit;
}
