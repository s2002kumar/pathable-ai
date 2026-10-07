'use client';

import { type RefObject, useCallback, useEffect, useMemo, useState } from 'react';
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
  /**
   * Where the panel actually is, unclamped, for placing the map's own chrome
   * clear of it. Deliberately not derived from the camera's padding: squeezing
   * the camera's allowance to fit a small window would drag the ODbL credit
   * back under the panel with it, which a 320 px browser test caught.
   */
  readonly inset: PanelInset;
  /**
   * How far a docked surface along the bottom of the map reaches up into it,
   * or 0 with none. The evidence dock is drawn across the foot of the map on a
   * desktop, so the route is framed above it and the map's credit lifted clear
   * of it.
   */
  readonly dockInset: number;
  /**
   * Room to leave around a fitted route, for `fitBounds`, measured from the
   * page as it is laid out when called. Clamped to fit.
   *
   * A function, not a value, because the camera moves in the same commit that
   * draws a new layout: the map's effect runs before this hook's, so a value
   * handed down is still the previous layout's. The comparison's slim dock
   * framed one route's evidence under the far taller gap dock that way, on a
   * 1280 × 800 window.
   */
  readonly measurePadding: () => Padding;
};

type Measured = Pick<PanelFit, 'inset' | 'dockInset'> & { readonly padding: Padding };

function rectOf(element: Element | null): Rect | null {
  if (element === null) return null;
  const { left, top, right, bottom, width, height } = element.getBoundingClientRect();
  return { left, top, right, bottom, width, height };
}

function measureOf(map: Rect | null, panel: Rect | null, dock: Rect | null): Measured {
  const dockInset =
    map !== null && dock !== null && dock.top < map.bottom && dock.bottom > map.top
      ? Math.max(0, map.bottom - dock.top)
      : 0;
  return {
    padding: paddingForPanel(map, panel, {
      ...FIT_PADDING,
      bottom: FIT_PADDING.bottom + dockInset,
    }),
    inset: panelInset(map, panel),
    dockInset,
  };
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
 * Reports no inset until both elements exist, which is also what a renderer
 * without `ResizeObserver` gets: the route is still framed, just without the
 * allowance.
 */
export function usePanelFit(
  mapRef: RefObject<HTMLElement | null>,
  panelRef: RefObject<HTMLElement | null>,
  dockRef?: RefObject<HTMLElement | null>,
  /** Changes whenever the dock appears, disappears or changes shape. */
  dockKey?: string,
): PanelFit {
  const [placement, setPlacement] = useState<Pick<PanelFit, 'inset' | 'dockInset'>>({
    inset: NO_PANEL_INSET,
    dockInset: 0,
  });

  // Both read the refs themselves, rather than through a shared callback, so
  // the lint rule can see that the state set in an effect is a measurement.
  const measure = useCallback(() => {
    const { inset, dockInset } = measureOf(
      rectOf(mapRef.current),
      rectOf(panelRef.current),
      rectOf(dockRef?.current ?? null),
    );
    setPlacement((current) =>
      current.inset.side === inset.side &&
      current.inset.amount === inset.amount &&
      current.dockInset === dockInset
        ? current
        : { inset, dockInset },
    );
  }, [mapRef, panelRef, dockRef]);

  const measurePadding = useCallback(
    () =>
      measureOf(rectOf(mapRef.current), rectOf(panelRef.current), rectOf(dockRef?.current ?? null))
        .padding,
    [mapRef, panelRef, dockRef],
  );

  useEffect(() => {
    measure();

    const map = mapRef.current;
    const panel = panelRef.current;
    const dock = dockRef?.current ?? null;
    if (typeof ResizeObserver !== 'function') return;

    const observer = new ResizeObserver(() => measure());
    if (map !== null) observer.observe(map);
    if (panel !== null) observer.observe(panel);
    if (dock !== null) observer.observe(dock);
    return () => observer.disconnect();
  }, [measure, mapRef, panelRef, dockRef, dockKey]);

  return useMemo(() => ({ ...placement, measurePadding }), [placement, measurePadding]);
}
