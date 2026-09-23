'use client';

import { type RefObject, useCallback, useEffect, useState } from 'react';
import {
  FIT_PADDING,
  NO_PANEL_INSET,
  type Padding,
  type PanelInset,
  type Rect,
  paddingForPanel,
  panelInset,
} from './route-layers';

export type PanelFit = {
  /** Room to leave around a fitted route, for `fitBounds`. Clamped to fit. */
  readonly padding: Padding;
  /**
   * Where the panel actually is, unclamped, for placing the map's own chrome
   * clear of it. Deliberately not derived from `padding`: squeezing the
   * camera's allowance to fit a small window would drag the ODbL credit back
   * under the panel with it, which a 320 px browser test caught.
   */
  readonly inset: PanelInset;
};

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
  const [fit, setFit] = useState<PanelFit>({
    padding: { ...FIT_PADDING },
    inset: NO_PANEL_INSET,
  });

  const measure = useCallback(() => {
    const map = rectOf(mapRef.current);
    const panel = rectOf(panelRef.current);
    const next = {
      padding: paddingForPanel(map, panel),
      inset: panelInset(map, panel),
    };
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
