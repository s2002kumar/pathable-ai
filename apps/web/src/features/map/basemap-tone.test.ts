import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { BASEMAP_LAYOUT, BASEMAP_PAINT, applyBasemapTone } from './basemap-tone';
import {
  ACCESSIBLE_COLOUR,
  CAMERA_DURATION_MS,
  DESTINATION_COLOUR,
  ORIGIN_COLOUR,
  STANDARD_COLOUR,
  UNFOCUSED_OPACITY,
  cameraDuration,
  lineOpacity,
  prefersReducedMotion,
} from './route-layers';

/** A map that has exactly the layers it is told it has, and records what it was asked. */
function fakeMap(layerIds: readonly string[]) {
  const paint: Array<[string, string, unknown]> = [];
  const layout: Array<[string, string, unknown]> = [];
  return {
    paint,
    layout,
    getLayer: (id: string) => (layerIds.includes(id) ? { id } : undefined),
    setPaintProperty: (layer: string, name: string, value: unknown) => {
      if (!layerIds.includes(layer)) throw new Error(`no layer ${layer}`);
      paint.push([layer, name, value]);
    },
    setLayoutProperty: (layer: string, name: string, value: unknown) => {
      if (!layerIds.includes(layer)) throw new Error(`no layer ${layer}`);
      layout.push([layer, name, value]);
    },
  };
}

describe('basemap tone', () => {
  it('is a no-op on a style with none of the named layers', () => {
    // The deterministic test style has one background layer named `background`,
    // which is toned; the source-less e2e style is otherwise untouched, and a
    // style with unrelated layer IDs must never be asked to paint a layer it
    // does not have — MapLibre throws on that.
    const map = fakeMap(['some-other-layer']);

    expect(applyBasemapTone(map)).toBe(0);
    expect(map.paint).toEqual([]);
    expect(map.layout).toEqual([]);
  });

  it('applies only the overrides whose layers exist', () => {
    const map = fakeMap(['background', 'park', 'building', 'building-3d']);

    const applied = applyBasemapTone(map);

    expect(applied).toBe(map.paint.length + map.layout.length);
    expect(map.paint.map(([layer]) => layer)).toEqual([
      'background',
      'park',
      'building',
      'building',
    ]);
    expect(map.layout).toEqual([['building-3d', 'visibility', 'none']]);
  });

  it('switches the decorative 3D buildings off rather than recolouring them', () => {
    const extrusion = BASEMAP_LAYOUT.find((override) => override.layer === 'building-3d');

    expect(extrusion).toEqual({ layer: 'building-3d', property: 'visibility', value: 'none' });
    expect(BASEMAP_PAINT.some((override) => override.layer === 'building-3d')).toBe(false);
  });

  it('leaves labels, attribution and one-way arrows to the style', () => {
    // Pedestrian detail is what a route is read against. Recolouring a label
    // is fine; hiding one is not, and nothing here touches visibility except
    // the extrusion.
    const hidden = BASEMAP_LAYOUT.filter((override) => override.property === 'visibility');
    expect(hidden.map((override) => override.layer)).toEqual(['building-3d']);

    const properties = new Set(BASEMAP_PAINT.map((override) => override.property));
    expect([...properties].sort()).toEqual([
      'background-color',
      'fill-color',
      'fill-outline-color',
      'line-color',
      'text-color',
    ]);
  });
});

describe('route focus', () => {
  it('draws both routes in full when nothing is focused', () => {
    expect(lineOpacity('standard', null)).toBe(1);
    expect(lineOpacity('accessible', null)).toBe(1);
  });

  it('dims the other route without removing it', () => {
    expect(lineOpacity('accessible', 'accessible')).toBe(1);
    expect(lineOpacity('standard', 'accessible')).toBe(UNFOCUSED_OPACITY);
    expect(lineOpacity('standard', 'standard')).toBe(1);
    expect(lineOpacity('accessible', 'standard')).toBe(UNFOCUSED_OPACITY);
    // Faded, never gone: a comparison with one line is not a comparison.
    expect(UNFOCUSED_OPACITY).toBeGreaterThan(0);
  });
});

describe('camera motion', () => {
  it('caps the camera at the documented duration', () => {
    expect(CAMERA_DURATION_MS).toBeLessThanOrEqual(600);
    expect(cameraDuration(false)).toBe(CAMERA_DURATION_MS);
  });

  it('jumps instead of flying when the viewer prefers reduced motion', () => {
    expect(cameraDuration(true)).toBe(0);
  });

  it('reads the reduced-motion preference from the media query', () => {
    expect(
      prefersReducedMotion((query) => ({ matches: query === '(prefers-reduced-motion: reduce)' })),
    ).toBe(true);
    expect(prefersReducedMotion(() => ({ matches: false }))).toBe(false);
  });

  it('assumes full motion where there is no media query to ask', () => {
    expect(prefersReducedMotion(undefined)).toBe(false);
    expect(
      prefersReducedMotion(() => {
        throw new Error('not implemented');
      }),
    ).toBe(false);
  });
});

describe('route colours', () => {
  /**
   * The legend is CSS and the lines are WebGL, so the same colour has to be
   * written down twice. This is the test that keeps the two copies honest.
   */
  it('match the tokens the legend swatches use', () => {
    // Vitest runs from apps/web, and the tokens file is the one the app ships.
    const tokens = readFileSync(path.resolve(process.cwd(), 'src/styles/tokens.css'), 'utf8');
    const token = (name: string): string => {
      const match = new RegExp(`--${name}:\\s*(#[0-9a-f]{6});`, 'i').exec(tokens);
      if (match?.[1] === undefined) throw new Error(`token --${name} not found`);
      return match[1].toLowerCase();
    };

    expect(token('color-route-accessible')).toBe(ACCESSIBLE_COLOUR);
    expect(token('color-route-standard')).toBe(STANDARD_COLOUR);
    expect(token('color-marker-origin')).toBe(ORIGIN_COLOUR);
    expect(token('color-marker-destination')).toBe(DESTINATION_COLOUR);
  });
});
