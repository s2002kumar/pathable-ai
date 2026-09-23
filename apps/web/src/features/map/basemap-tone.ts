/**
 * Quiet cartography: paint overrides applied to the basemap after it loads.
 *
 * PathAble does not own the basemap style — it is OpenFreeMap's "Liberty", an
 * OpenMapTiles style served from their CDN — and copying it into the repository
 * would mean redistributing something this project has no licence to. So the
 * style is left where it is and toned at runtime: a short list of paint
 * properties, keyed by the layer IDs Liberty publishes, applied only where a
 * layer with that ID actually exists. On any other style, including the
 * source-less one the browser tests use, this is a no-op.
 *
 * The intent is a navigation instrument rather than a postcard: a crisp neutral
 * ground, parks and water present but quiet, buildings given just enough edge to
 * read as blocks, roads kept pale with softer casings, and the route lines the
 * only saturated marks on the page. Labels, one-way arrows, transit icons and
 * attribution are left exactly as the style draws them — pedestrian detail is
 * what a route is read against, and none of it is decoration.
 *
 * Pedestrian paths are the exception to "quieter". Liberty draws footways as a
 * thin white dash, which disappears against a white road on a pale ground — on
 * a pedestrian router that is the single most important class of line on the
 * map. They are given their own tint and a wider stroke, so the network a route
 * is drawn over is visible as a network. This changes how paths are *drawn*,
 * never which ones exist: no path is added, removed or reclassified, and a
 * drawn path is not a claim that it is in PathAble's routing graph.
 *
 * The 3D building extrusion Liberty draws at high zoom is switched off. It is
 * decorative, it is expensive on the software renderer the browser suite uses,
 * and at the zoom a campus route is viewed at it hides the paths behind it.
 */

export type PaintOverride = {
  readonly layer: string;
  readonly property: string;
  /**
   * A colour, or a MapLibre style expression. Widths are zoom ramps, so this
   * cannot be narrowed to `string` — but nothing here may set a visibility or
   * an opacity that would remove a feature, which `basemap-tone.test.ts`
   * asserts against the list rather than trusting the type.
   */
  readonly value: unknown;
};

export type LayoutOverride = {
  readonly layer: string;
  readonly property: string;
  readonly value: string;
};

const GROUND = '#eef0f2';
const GREEN_MUTED = '#dde7da';
const GREEN_SOFT = '#e4ebe2';
const WATER = '#c3d6e3';
const BUILDING = '#e0e4e8';
const BUILDING_EDGE = '#ccd2d8';
const CASING_MINOR = '#dbdfe3';
const CASING_MAJOR = '#ccd3d9';
const ROAD_MAJOR = '#f8fafb';
const ROAD_MOTORWAY = '#eef2f5';
const RAIL = '#c2c8cd';
const LABEL_ROAD = '#4c545b';
const LABEL_POI = '#525a61';

/**
 * The pedestrian network: a cool grey-blue, darker than any road, so a footway
 * crossing a white service road is still a footway. Deliberately unsaturated —
 * it has to stay clearly subordinate to the two route lines drawn over it.
 */
const PATH = '#9aa7b2';
const PATH_CASING = '#e7eaee';
const LABEL_PATH = '#5a636b';

/** Wider than Liberty draws them, on the same exponential ramp it uses. */
const PATH_WIDTH = [
  'interpolate',
  ['exponential', 1.2],
  ['zoom'],
  14,
  1.6,
  17,
  3.2,
  20,
  11,
] as const;

const PATH_CASING_WIDTH = [
  'interpolate',
  ['exponential', 1.2],
  ['zoom'],
  14,
  2.6,
  17,
  5,
  20,
  15,
] as const;

export const BASEMAP_PAINT: readonly PaintOverride[] = [
  { layer: 'background', property: 'background-color', value: GROUND },

  { layer: 'park', property: 'fill-color', value: GREEN_MUTED },
  { layer: 'park_outline', property: 'line-color', value: '#cfdccb' },
  { layer: 'landcover_wood', property: 'fill-color', value: 'rgba(210, 225, 208, 0.7)' },
  { layer: 'landcover_grass', property: 'fill-color', value: GREEN_MUTED },
  { layer: 'landcover_sand', property: 'fill-color', value: '#ecebe0' },
  { layer: 'landuse_pitch', property: 'fill-color', value: GREEN_SOFT },
  { layer: 'landuse_track', property: 'fill-color', value: GREEN_SOFT },
  { layer: 'landuse_cemetery', property: 'fill-color', value: GREEN_SOFT },
  { layer: 'landuse_hospital', property: 'fill-color', value: '#eee4e4' },
  { layer: 'landuse_school', property: 'fill-color', value: '#e9ebe4' },
  { layer: 'landuse_residential', property: 'fill-color', value: '#eaedef' },

  { layer: 'water', property: 'fill-color', value: WATER },
  { layer: 'waterway_river', property: 'line-color', value: WATER },
  { layer: 'waterway_other', property: 'line-color', value: WATER },
  { layer: 'waterway_tunnel', property: 'line-color', value: WATER },

  { layer: 'building', property: 'fill-color', value: BUILDING },
  { layer: 'building', property: 'fill-outline-color', value: BUILDING_EDGE },

  { layer: 'road_minor_casing', property: 'line-color', value: CASING_MINOR },
  { layer: 'road_service_track_casing', property: 'line-color', value: CASING_MINOR },
  { layer: 'tunnel_street_casing', property: 'line-color', value: CASING_MINOR },
  { layer: 'tunnel_service_track_casing', property: 'line-color', value: CASING_MINOR },
  { layer: 'bridge_street_casing', property: 'line-color', value: CASING_MINOR },
  { layer: 'bridge_service_track_casing', property: 'line-color', value: CASING_MINOR },

  { layer: 'road_secondary_tertiary_casing', property: 'line-color', value: CASING_MAJOR },
  { layer: 'road_trunk_primary_casing', property: 'line-color', value: CASING_MAJOR },
  { layer: 'road_link_casing', property: 'line-color', value: CASING_MAJOR },
  { layer: 'road_motorway_casing', property: 'line-color', value: CASING_MAJOR },
  { layer: 'road_motorway_link_casing', property: 'line-color', value: CASING_MAJOR },
  { layer: 'tunnel_secondary_tertiary_casing', property: 'line-color', value: CASING_MAJOR },
  { layer: 'tunnel_trunk_primary_casing', property: 'line-color', value: CASING_MAJOR },
  { layer: 'tunnel_link_casing', property: 'line-color', value: CASING_MAJOR },
  { layer: 'tunnel_motorway_casing', property: 'line-color', value: CASING_MAJOR },
  { layer: 'tunnel_motorway_link_casing', property: 'line-color', value: CASING_MAJOR },
  { layer: 'bridge_secondary_tertiary_casing', property: 'line-color', value: CASING_MAJOR },
  { layer: 'bridge_trunk_primary_casing', property: 'line-color', value: CASING_MAJOR },
  { layer: 'bridge_link_casing', property: 'line-color', value: CASING_MAJOR },
  { layer: 'bridge_motorway_casing', property: 'line-color', value: CASING_MAJOR },
  { layer: 'bridge_motorway_link_casing', property: 'line-color', value: CASING_MAJOR },

  { layer: 'road_secondary_tertiary', property: 'line-color', value: ROAD_MAJOR },
  { layer: 'road_trunk_primary', property: 'line-color', value: ROAD_MAJOR },
  { layer: 'road_link', property: 'line-color', value: ROAD_MAJOR },
  { layer: 'road_motorway', property: 'line-color', value: ROAD_MOTORWAY },
  { layer: 'road_motorway_link', property: 'line-color', value: ROAD_MOTORWAY },
  { layer: 'tunnel_secondary_tertiary', property: 'line-color', value: ROAD_MAJOR },
  { layer: 'tunnel_trunk_primary', property: 'line-color', value: ROAD_MAJOR },
  { layer: 'tunnel_link', property: 'line-color', value: ROAD_MAJOR },
  { layer: 'tunnel_motorway', property: 'line-color', value: ROAD_MOTORWAY },
  { layer: 'tunnel_motorway_link', property: 'line-color', value: ROAD_MOTORWAY },
  { layer: 'bridge_secondary_tertiary', property: 'line-color', value: ROAD_MAJOR },
  { layer: 'bridge_trunk_primary', property: 'line-color', value: ROAD_MAJOR },
  { layer: 'bridge_link', property: 'line-color', value: ROAD_MAJOR },
  { layer: 'bridge_motorway', property: 'line-color', value: ROAD_MOTORWAY },
  { layer: 'bridge_motorway_link', property: 'line-color', value: ROAD_MOTORWAY },

  // --- The pedestrian network -------------------------------------------
  // Drawn up, not down: this is a pedestrian router, and Liberty's thin white
  // dash vanishes against a white road. Colour and width only — the filters,
  // the dash patterns and which features appear are the style's.
  { layer: 'road_path_pedestrian', property: 'line-color', value: PATH },
  { layer: 'road_path_pedestrian', property: 'line-width', value: PATH_WIDTH },
  { layer: 'bridge_path_pedestrian', property: 'line-color', value: PATH },
  { layer: 'bridge_path_pedestrian', property: 'line-width', value: PATH_WIDTH },
  { layer: 'bridge_path_pedestrian_casing', property: 'line-color', value: PATH_CASING },
  { layer: 'bridge_path_pedestrian_casing', property: 'line-width', value: PATH_CASING_WIDTH },
  { layer: 'tunnel_path_pedestrian', property: 'line-color', value: PATH },
  { layer: 'tunnel_path_pedestrian', property: 'line-width', value: PATH_WIDTH },

  { layer: 'road_major_rail', property: 'line-color', value: RAIL },
  { layer: 'road_major_rail_hatching', property: 'line-color', value: RAIL },
  { layer: 'road_transit_rail', property: 'line-color', value: RAIL },
  { layer: 'road_transit_rail_hatching', property: 'line-color', value: RAIL },

  { layer: 'highway-name-path', property: 'text-color', value: LABEL_PATH },
  { layer: 'highway-name-minor', property: 'text-color', value: LABEL_ROAD },
  { layer: 'highway-name-major', property: 'text-color', value: LABEL_ROAD },
  { layer: 'poi_r20', property: 'text-color', value: LABEL_POI },
  { layer: 'poi_r7', property: 'text-color', value: LABEL_POI },
  { layer: 'poi_r1', property: 'text-color', value: LABEL_POI },
];

export const BASEMAP_LAYOUT: readonly LayoutOverride[] = [
  { layer: 'building-3d', property: 'visibility', value: 'none' },
];

/** The slice of a map this module needs: enough to ask and to set, no more. */
export type TonableMap = {
  readonly getLayer: (id: string) => unknown;
  readonly setPaintProperty: (layer: string, name: string, value: unknown) => void;
  readonly setLayoutProperty: (layer: string, name: string, value: unknown) => void;
};

/**
 * Apply the overrides to whichever of the named layers exist.
 *
 * Returns how many were applied, so a caller (or a test) can tell a toned
 * basemap from one that had none of these layers to begin with.
 */
export function applyBasemapTone(map: TonableMap): number {
  let applied = 0;
  for (const override of BASEMAP_PAINT) {
    if (!map.getLayer(override.layer)) continue;
    map.setPaintProperty(override.layer, override.property, override.value);
    applied += 1;
  }
  for (const override of BASEMAP_LAYOUT) {
    if (!map.getLayer(override.layer)) continue;
    map.setLayoutProperty(override.layer, override.property, override.value);
    applied += 1;
  }
  return applied;
}
