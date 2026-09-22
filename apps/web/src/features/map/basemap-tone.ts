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
 * The intent is a navigation instrument rather than a postcard: warm ivory
 * ground, parks and buildings pushed back to a murmur, water desaturated, roads
 * kept white with softer casings, and the route lines the only saturated marks
 * on the page. Labels, one-way arrows, transit icons and attribution are left
 * exactly as the style draws them — pedestrian detail is what a route is read
 * against, and none of it is decoration.
 *
 * The 3D building extrusion Liberty draws at high zoom is switched off. It is
 * decorative, it is expensive on the software renderer the browser suite uses,
 * and at the zoom a campus route is viewed at it hides the paths behind it.
 */

export type PaintOverride = {
  readonly layer: string;
  readonly property: string;
  readonly value: string;
};

export type LayoutOverride = {
  readonly layer: string;
  readonly property: string;
  readonly value: string;
};

const IVORY = '#f4efe6';
const GREEN_MUTED = '#e2e7d4';
const GREEN_SOFT = '#e8ebdc';
const WATER = '#cddbe4';
const BUILDING = '#e8e1d4';
const BUILDING_EDGE = '#dad1c1';
const CASING_MINOR = '#dcd4c6';
const CASING_MAJOR = '#d9c8a8';
const ROAD_MAJOR = '#f7f0dd';
const ROAD_MOTORWAY = '#f2dfc0';
const RAIL = '#c9c2b6';
const LABEL_ROAD = '#5c554a';
const LABEL_POI = '#6a6358';

export const BASEMAP_PAINT: readonly PaintOverride[] = [
  { layer: 'background', property: 'background-color', value: IVORY },

  { layer: 'park', property: 'fill-color', value: GREEN_MUTED },
  { layer: 'park_outline', property: 'line-color', value: '#d5dcc4' },
  { layer: 'landcover_wood', property: 'fill-color', value: 'rgba(215, 224, 200, 0.7)' },
  { layer: 'landcover_grass', property: 'fill-color', value: GREEN_MUTED },
  { layer: 'landcover_sand', property: 'fill-color', value: '#efe8d3' },
  { layer: 'landuse_pitch', property: 'fill-color', value: GREEN_SOFT },
  { layer: 'landuse_track', property: 'fill-color', value: GREEN_SOFT },
  { layer: 'landuse_cemetery', property: 'fill-color', value: GREEN_SOFT },
  { layer: 'landuse_hospital', property: 'fill-color', value: '#f1e7e2' },
  { layer: 'landuse_school', property: 'fill-color', value: '#efeadc' },
  { layer: 'landuse_residential', property: 'fill-color', value: '#efe9de' },

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
  { layer: 'bridge_path_pedestrian_casing', property: 'line-color', value: CASING_MINOR },

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

  { layer: 'road_major_rail', property: 'line-color', value: RAIL },
  { layer: 'road_major_rail_hatching', property: 'line-color', value: RAIL },
  { layer: 'road_transit_rail', property: 'line-color', value: RAIL },
  { layer: 'road_transit_rail_hatching', property: 'line-color', value: RAIL },

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
