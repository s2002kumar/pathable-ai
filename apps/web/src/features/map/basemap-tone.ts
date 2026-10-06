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
 * The intent is the Golden Master's midnight navigation surface: a deep navy
 * ground, water and parks given their own dark tint because a map whose water
 * is indistinguishable from land is not a map, buildings with just enough edge
 * to read as blocks, roads a step lighter than the ground, and the two route
 * lines by far the brightest marks on the page. Labels are re-inked light on a
 * dark halo so they stay legible; one-way arrows, transit icons and
 * attribution are left exactly as the style draws them — pedestrian detail is
 * what a route is read against, and none of it is decoration.
 *
 * Pedestrian paths are the exception to "quieter". Liberty draws footways as a
 * thin dash that disappears against a road once the ground is re-toned — on
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

const GROUND = '#0a1224';
const GREEN_MUTED = '#0d2124';
const GREEN_SOFT = '#0f2328';
const WATER = '#0c2a40';
const BUILDING = '#131b2e';
const BUILDING_EDGE = '#222a3d';
const CASING_MINOR = '#0e1629';
const CASING_MAJOR = '#121a2e';
const ROAD_MAJOR = '#2a3449';
const ROAD_MINOR = '#1b2438';
const ROAD_MOTORWAY = '#31394d';
const RAIL = '#2d3a52';
const LABEL_ROAD = '#8b9bb4';
const LABEL_POI = '#849587';
const LABEL_PLACE = '#bacbbc';
const LABEL_HALO = '#060e20';

/**
 * The pedestrian network: a muted slate, lighter than the ground and distinct
 * from the roads, so a footway crossing a service road is still a footway.
 * Deliberately unsaturated — it has to stay clearly subordinate to the two
 * route lines drawn over it.
 */
const PATH = '#3d4c66';
const PATH_CASING = '#0a1224';
const LABEL_PATH = '#8b9bb4';

/**
 * Wider than Liberty draws them, on the same exponential ramp it uses.
 *
 * Tuned by zoom rather than flat. At a city overview a footway is context and
 * stays hairline; at the zoom a campus route is actually read at, it is the
 * thing being read and earns real width. The route lines are wider again at
 * every stop, so the network never competes with the answer drawn over it.
 */
const PATH_WIDTH = [
  'interpolate',
  ['exponential', 1.2],
  ['zoom'],
  13,
  1,
  15,
  1.9,
  17,
  3.4,
  20,
  11,
] as const;

const PATH_CASING_WIDTH = [
  'interpolate',
  ['exponential', 1.2],
  ['zoom'],
  13,
  1.8,
  15,
  3.1,
  17,
  5.2,
  20,
  15,
] as const;

export const BASEMAP_PAINT: readonly PaintOverride[] = [
  { layer: 'background', property: 'background-color', value: GROUND },

  { layer: 'park', property: 'fill-color', value: GREEN_MUTED },
  { layer: 'park_outline', property: 'line-color', value: '#12302f' },
  { layer: 'landcover_wood', property: 'fill-color', value: 'rgba(13, 38, 40, 0.75)' },
  { layer: 'landcover_grass', property: 'fill-color', value: GREEN_MUTED },
  { layer: 'landcover_sand', property: 'fill-color', value: '#1a1d24' },
  { layer: 'landuse_pitch', property: 'fill-color', value: GREEN_SOFT },
  { layer: 'landuse_track', property: 'fill-color', value: GREEN_SOFT },
  { layer: 'landuse_cemetery', property: 'fill-color', value: GREEN_SOFT },
  { layer: 'landuse_hospital', property: 'fill-color', value: '#1a1626' },
  { layer: 'landuse_school', property: 'fill-color', value: '#101a2a' },
  { layer: 'landuse_residential', property: 'fill-color', value: '#0c1528' },

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

  // Minor streets and service roads: one step above the ground, so the street
  // grid reads without competing with the two route lines.
  { layer: 'road_minor', property: 'line-color', value: ROAD_MINOR },
  { layer: 'road_service_track', property: 'line-color', value: ROAD_MINOR },
  { layer: 'tunnel_minor', property: 'line-color', value: ROAD_MINOR },
  { layer: 'tunnel_service_track', property: 'line-color', value: ROAD_MINOR },
  { layer: 'bridge_street', property: 'line-color', value: ROAD_MINOR },
  { layer: 'bridge_service_track', property: 'line-color', value: ROAD_MINOR },
  { layer: 'aeroway_fill', property: 'fill-color', value: BUILDING },
  { layer: 'aeroway_runway', property: 'line-color', value: ROAD_MINOR },
  { layer: 'aeroway_taxiway', property: 'line-color', value: ROAD_MINOR },
  { layer: 'landcover_ice', property: 'fill-color', value: GREEN_SOFT },
  { layer: 'boundary_3', property: 'line-color', value: RAIL },
  { layer: 'boundary_2', property: 'line-color', value: RAIL },
  { layer: 'tunnel_major_rail', property: 'line-color', value: RAIL },
  { layer: 'tunnel_major_rail_hatching', property: 'line-color', value: RAIL },
  { layer: 'tunnel_transit_rail', property: 'line-color', value: RAIL },
  { layer: 'tunnel_transit_rail_hatching', property: 'line-color', value: RAIL },
  { layer: 'bridge_major_rail', property: 'line-color', value: RAIL },
  { layer: 'bridge_major_rail_hatching', property: 'line-color', value: RAIL },
  { layer: 'bridge_transit_rail', property: 'line-color', value: RAIL },
  { layer: 'bridge_transit_rail_hatching', property: 'line-color', value: RAIL },
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

  // --- Label halos ---------------------------------------------------------
  // Liberty halos its dark labels in white; on a navy ground that is a glowing
  // box around every name. The halo becomes the ground and the ink goes light.
  ...[
    'highway-name-path',
    'highway-name-minor',
    'highway-name-major',
    'poi_r20',
    'poi_r7',
    'poi_r1',
    'label_other',
    'label_village',
    'label_town',
    'label_city',
    'water_name_point_label',
    'water_name_line_label',
    'waterway_line_label',
    'poi_transit',
    'airport',
    'label_state',
    'label_city_capital',
  ].map((layer) => ({ layer, property: 'text-halo-color', value: LABEL_HALO })),
  { layer: 'label_other', property: 'text-color', value: LABEL_PLACE },
  { layer: 'label_village', property: 'text-color', value: LABEL_PLACE },
  { layer: 'label_town', property: 'text-color', value: LABEL_PLACE },
  { layer: 'label_city', property: 'text-color', value: LABEL_PLACE },
  { layer: 'label_city_capital', property: 'text-color', value: LABEL_PLACE },
  { layer: 'label_state', property: 'text-color', value: LABEL_PLACE },
  { layer: 'waterway_line_label', property: 'text-color', value: '#7bd0ff' },
  { layer: 'poi_transit', property: 'text-color', value: LABEL_POI },
  { layer: 'airport', property: 'text-color', value: LABEL_POI },
  { layer: 'water_name_point_label', property: 'text-color', value: '#7bd0ff' },
  { layer: 'water_name_line_label', property: 'text-color', value: '#7bd0ff' },
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
