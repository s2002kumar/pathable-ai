'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Icon } from '@/components/Icon';
import type { MapInstance } from './useMapLibre';
import styles from './MapPanel.module.css';

/**
 * Which of PathAble's own overlays are drawn.
 *
 * These are the only "layers" the product has: the evidence pins, the
 * recorded-stairway overlay and the shortest route. There is no satellite,
 * terrain, elevation-contour or traffic layer to switch to, so none of the
 * design's buttons for those is drawn.
 */
export type MapLayers = {
  readonly evidence: boolean;
  readonly stairs: boolean;
  readonly shortest: boolean;
};

export const ALL_LAYERS: MapLayers = { evidence: true, stairs: true, shortest: true };

/** Each Golden Master state arranges the same real controls differently. */
export type ControlsLayout = 'plan' | 'compare' | 'evidence' | 'no-route' | 'phone';

export type MapControlsProps = {
  readonly map: MapInstance | null;
  readonly layout?: ControlsLayout;
  readonly layers: MapLayers;
  readonly onLayersChange: (layers: MapLayers) => void;
  /** Re-frame the routes, or the points before there are routes. */
  readonly onFit?: () => void;
  readonly fitLabel?: string;
};

const LAYER_COPY: ReadonlyArray<{ key: keyof MapLayers; label: string }> = [
  { key: 'evidence', label: 'Evidence labels' },
  { key: 'stairs', label: 'Recorded stairways' },
  { key: 'shortest', label: 'Shortest walking route' },
];

function LayersMenu({
  layers,
  onLayersChange,
  label,
  iconOnly = false,
  round = false,
}: {
  readonly layers: MapLayers;
  readonly onLayersChange: (layers: MapLayers) => void;
  readonly label: string;
  readonly iconOnly?: boolean;
  readonly round?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const wrapper = useRef<HTMLDivElement>(null);

  // Escape and a click elsewhere close the menu, as any disclosure menu does.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    const onPointer = (event: PointerEvent) => {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [open]);

  return (
    <div className={styles.layers} ref={wrapper}>
      <button
        type="button"
        className={round ? styles.hudRound : iconOnly ? styles.hudSquare : styles.hudButton}
        aria-expanded={open}
        aria-controls={menuId}
        aria-label={iconOnly ? label : undefined}
        title={iconOnly ? label : undefined}
        onClick={() => setOpen((value) => !value)}
        data-testid="map-layers"
      >
        <Icon name="layers" />
        {iconOnly ? null : label}
      </button>
      {open ? (
        <fieldset className={styles.layerMenu} id={menuId}>
          <legend>Show on map</legend>
          {LAYER_COPY.map(({ key, label: optionLabel }) => (
            <label className={styles.layerOption} key={key}>
              <input
                type="checkbox"
                checked={layers[key]}
                onChange={(event) => onLayersChange({ ...layers, [key]: event.target.checked })}
                data-testid={`layer-${key}`}
              />
              {optionLabel}
            </label>
          ))}
        </fieldset>
      ) : null}
    </div>
  );
}

/**
 * The map's own controls, arranged as each Golden Master state draws them:
 * Layers, an evidence-label toggle, zoom, fit and north. Fit replaces the
 * design's locate glyph — PathAble does not read the viewer's location — and
 * re-frames what the map is showing instead.
 *
 * Each group is marked `data-map-chrome`, which is how the map's labels know
 * to stay out from under it (MapMarkers).
 */
export function MapControls({
  map,
  layout = 'compare',
  layers,
  onLayersChange,
  onFit,
  fitLabel = 'Fit routes',
}: MapControlsProps) {
  const zoomIn = (
    <button
      type="button"
      className={styles.hudIcon}
      aria-label="Zoom in"
      title="Zoom in"
      disabled={map?.zoomIn === undefined}
      onClick={() => map?.zoomIn?.()}
      data-testid="zoom-in"
    >
      <Icon name="plus" />
    </button>
  );
  const zoomOut = (
    <button
      type="button"
      className={styles.hudIcon}
      aria-label="Zoom out"
      title="Zoom out"
      disabled={map?.zoomOut === undefined}
      onClick={() => map?.zoomOut?.()}
      data-testid="zoom-out"
    >
      <Icon name="minus" />
    </button>
  );
  const fit = (className: string | undefined) => (
    <button
      type="button"
      className={className}
      aria-label={fitLabel}
      title={fitLabel}
      disabled={onFit === undefined}
      onClick={onFit}
      data-testid="fit-routes"
    >
      <Icon name="target" />
    </button>
  );
  const north = (
    <button
      type="button"
      className={styles.hudIcon}
      aria-label="Reset the map to north"
      title="Reset to north"
      disabled={map?.resetNorth === undefined}
      onClick={() => map?.resetNorth?.()}
      data-testid="reset-north"
    >
      <Icon name="navigate" />
    </button>
  );
  const evidenceToggle = (label: string) => (
    <button
      type="button"
      className={styles.hudBarButton}
      aria-pressed={layers.evidence}
      onClick={() => onLayersChange({ ...layers, evidence: !layers.evidence })}
      data-testid="toggle-evidence-labels"
    >
      <Icon name="warning" />
      {label}
    </button>
  );

  if (layout === 'phone') {
    return (
      <div
        className={styles.hud}
        data-layout={layout}
        data-testid="map-controls"
        data-map-chrome=""
      >
        <LayersMenu layers={layers} onLayersChange={onLayersChange} label="Layers" iconOnly round />
        <button
          type="button"
          className={styles.hudRound}
          aria-pressed={layers.evidence}
          aria-label="Evidence labels"
          title="Evidence labels"
          onClick={() => onLayersChange({ ...layers, evidence: !layers.evidence })}
          data-testid="toggle-evidence-labels"
        >
          <Icon name="warning" size={16} />
        </button>
        {fit(styles.hudRound)}
      </div>
    );
  }

  if (layout === 'compare') {
    return (
      <div
        className={styles.hud}
        data-layout={layout}
        data-testid="map-controls"
        data-map-chrome=""
      >
        <LayersMenu layers={layers} onLayersChange={onLayersChange} label="Layers" />
        <div className={styles.hudGroup} role="group" aria-label="Map view">
          {zoomIn}
          {zoomOut}
          {fit(styles.hudIcon)}
        </div>
      </div>
    );
  }

  if (layout === 'evidence') {
    return (
      <>
        <div
          className={styles.hud}
          data-layout={layout}
          data-testid="map-controls"
          data-map-chrome=""
        >
          <p className={styles.hudLegend}>
            <span className="visually-hidden">Map key: </span>
            <span className={styles.hudLegendItem}>
              <span className={styles.hudLegendDot} data-kind="recorded" />
              Recorded
            </span>
            <span className={styles.hudLegendItem}>
              <span className={styles.hudLegendDot} data-kind="unknown" />
              Not recorded
            </span>
          </p>
          {fit(styles.hudSquare)}
          <LayersMenu layers={layers} onLayersChange={onLayersChange} label="Layers" iconOnly />
        </div>
        <div className={styles.hudStack} role="group" aria-label="Map view" data-map-chrome="">
          {zoomIn}
          {zoomOut}
        </div>
      </>
    );
  }

  // plan and no-route: a labelled bar top right, a stack bottom right.
  return (
    <>
      <div
        className={styles.hud}
        data-layout={layout}
        data-testid="map-controls"
        data-map-chrome=""
      >
        <div className={styles.hudBar}>
          {layout === 'plan' ? (
            <>
              <LayersMenu layers={layers} onLayersChange={onLayersChange} label="Map Layers" />
              {evidenceToggle('Route Evidence')}
            </>
          ) : (
            <>
              {evidenceToggle('Evidence Overlay')}
              <LayersMenu layers={layers} onLayersChange={onLayersChange} label="Map Layers" />
            </>
          )}
        </div>
      </div>
      <div className={styles.hudStack} role="group" aria-label="Map view" data-map-chrome="">
        {layout === 'no-route' ? fit(styles.hudIcon) : null}
        {zoomIn}
        {zoomOut}
        {layout === 'plan' ? (
          <>
            <span className={styles.hudDivider} aria-hidden="true" />
            {fit(styles.hudIcon)}
          </>
        ) : null}
        {north}
      </div>
    </>
  );
}
