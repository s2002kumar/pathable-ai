/**
 * The map's routing behaviour, against a fake MapLibre.
 *
 * jsdom has no WebGL, so the real library cannot run here. The fake implements
 * exactly the surface `useRouteLayers` and `useMapClick` use and records what
 * they did, which is enough to answer the questions that matter: are the layers
 * added once and then updated, is the accessible route drawn on top, and does a
 * click reach the planner.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { act } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RouteWorkspace } from '@/features/routing/RouteWorkspace';
import {
  ACCESSIBLE_CASING_LAYER_ID,
  ACCESSIBLE_LAYER_ID,
  ACCESSIBLE_SOURCE_ID,
  POINTS_SOURCE_ID,
  POINTS_HALO_LAYER_ID,
  POINTS_LAYER_ID,
  STANDARD_CASING_LAYER_ID,
  STANDARD_LAYER_ID,
  STANDARD_SOURCE_ID,
} from './route-layers';

type Listener = (payload: unknown) => void;

class FakeMap {
  static instances: FakeMap[] = [];

  listeners = new Map<string, Set<Listener>>();
  sources = new Map<string, { type: string; data: unknown }>();
  layerIds: string[] = [];
  fitted: Array<[[number, number], [number, number]]> = [];
  paint: Array<{ layer: string; name: string; value: unknown }> = [];
  layout: Array<{ layer: string; name: string; value: unknown }> = [];
  removed = false;

  constructor() {
    FakeMap.instances.push(this);
  }

  on(event: string, listener: Listener) {
    const set = this.listeners.get(event) ?? new Set();
    set.add(listener);
    this.listeners.set(event, set);
    if (event === 'load') {
      // The real map fires `load` asynchronously once its style is parsed.
      queueMicrotask(() => listener(undefined));
    }
  }

  off(event: string, listener: Listener) {
    this.listeners.get(event)?.delete(listener);
  }

  emit(event: string, payload: unknown) {
    for (const listener of this.listeners.get(event) ?? []) listener(payload);
  }

  addControl() {}
  remove() {
    this.removed = true;
  }

  addSource(id: string, source: { type: string; data: unknown }) {
    if (this.sources.has(id)) throw new Error(`source ${id} already exists`);
    this.sources.set(id, { ...source, data: source.data });
  }

  getSource(id: string) {
    const source = this.sources.get(id);
    if (!source) return undefined;
    return {
      setData: (data: unknown) => {
        source.data = data;
      },
    };
  }

  removeSource(id: string) {
    this.sources.delete(id);
  }

  addLayer(layer: { id: string }) {
    if (this.layerIds.includes(layer.id)) throw new Error(`layer ${layer.id} already exists`);
    this.layerIds.push(layer.id);
  }

  getLayer(id: string) {
    return this.layerIds.includes(id) ? { id } : undefined;
  }

  removeLayer(id: string) {
    this.layerIds = this.layerIds.filter((existing) => existing !== id);
  }

  setPaintProperty(layer: string, name: string, value: unknown) {
    if (!this.layerIds.includes(layer)) throw new Error(`layer ${layer} does not exist`);
    this.paint.push({ layer, name, value });
  }

  setLayoutProperty(layer: string, name: string, value: unknown) {
    if (!this.layerIds.includes(layer)) throw new Error(`layer ${layer} does not exist`);
    this.layout.push({ layer, name, value });
  }

  fitBounds(bounds: [[number, number], [number, number]]) {
    this.fitted.push(bounds);
  }

  dataOf(id: string): { features: unknown[] } {
    return this.sources.get(id)?.data as { features: unknown[] };
  }
}

vi.mock('maplibre-gl', () => ({
  setWorkerUrl: () => {},
  getWorkerUrl: () => '',
  Map: FakeMap,
  NavigationControl: class {},
  ScaleControl: class {},
  AttributionControl: class {},
}));

// Bypass the `next/dynamic` boundary only. MapPanel exists to keep MapLibre out
// of the server bundle, which is a bundling concern with nothing to test here —
// and under jsdom the lazy chunk never resolves, so the real canvas would never
// mount. Everything below it, including the hooks under test, is the real thing.
vi.mock('@/features/map/MapPanel', async () => {
  const { MapCanvas } = await import('./MapCanvas');
  return { MapPanel: MapCanvas };
});

const COMPARISON = {
  profile: 'wheelchair',
  profile_display_name: 'Wheelchair',
  profile_description: 'Avoids steps.',
  standard_route: {
    profile: 'standard',
    profile_display_name: 'Standard walking',
    distance_m: 483,
    effective_distance_m: 483,
    estimated_duration_seconds: 380,
    coordinates: [
      [-80.54, 43.47],
      [-80.536, 43.47],
    ],
    segments: [],
    origin: { longitude: -80.54, latitude: 43.47, distance_m: 1 },
    destination: { longitude: -80.536, latitude: 43.47, distance_m: 1 },
    stairway_count: 1,
    step_count: 14,
    crossing_count: 1,
    unknown_kerb_crossing_count: 1,
    steepest_incline_percent: null,
    unknown_data_fraction: 0.1,
    computation_ms: 3,
  },
  accessible_route: {
    profile: 'wheelchair',
    profile_display_name: 'Wheelchair',
    distance_m: 709,
    effective_distance_m: 980,
    estimated_duration_seconds: 746,
    coordinates: [
      [-80.54, 43.47],
      [-80.538, 43.469],
      [-80.536, 43.47],
    ],
    segments: [],
    origin: { longitude: -80.54, latitude: 43.47, distance_m: 1 },
    destination: { longitude: -80.536, latitude: 43.47, distance_m: 1 },
    stairway_count: 0,
    step_count: 0,
    crossing_count: 1,
    unknown_kerb_crossing_count: 0,
    steepest_incline_percent: 4,
    unknown_data_fraction: 0.2,
    computation_ms: 5,
  },
  standard_failure: null,
  accessible_failure: null,
  extra_distance_m: 226,
  extra_distance_fraction: 0.468,
  explanations: [{ code: 'avoids_stairs', summary: 'Avoids 1 stairway.', evidence: {} }],
  cautions: [],
  dataset: {
    dataset_id: 'd',
    region: 'waterloo',
    checksum: 'abcdef0123456789',
    source_type: 'osm',
    source_name: 'openstreetmap:waterloo',
    acquired_at: '2026-08-12T00:00:00+00:00',
    attribution: '© OpenStreetMap contributors, ODbL 1.0',
  },
  ml_predictions_used: false,
};

const CONFIG = {
  apiBaseUrl: 'http://api.test',
  region: 'waterloo',
  mapStyleUrl: '/map-styles/offline-test-style.json',
  centerLat: 43.4668,
  centerLon: -80.5164,
  zoom: 14,
  regionName: 'Waterloo, Ontario',
  attribution: '© test',
};

function respondWithComparison() {
  return vi.fn(
    async () =>
      new Response(JSON.stringify(COMPARISON), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
  ) as unknown as typeof fetch;
}

async function clickMap(map: FakeMap, lng: number, lat: number) {
  await act(async () => {
    map.emit('click', { lngLat: { lng, lat } });
  });
}

/**
 * Ask for the comparison.
 *
 * Placing two points is now a draft, not a request: the planner commits a
 * journey when the viewer presses Compare. These tests exercise the map's
 * click handling, so they still click — and then say so.
 */
async function compare() {
  await act(async () => {
    screen.getByTestId('compare-routes').click();
  });
}

beforeEach(() => {
  FakeMap.instances.length = 0;
  // jsdom has no WebGL, so the real capability check would report "unsupported"
  // and the map would never be constructed. Stubbing the probe is what lets the
  // routing hooks above MapLibre be exercised at all here; the detection logic
  // itself is covered separately in map.test.tsx.
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    getExtension: () => null,
  } as unknown as RenderingContext);
});

describe('route layers', () => {
  it('creates its sources and layers once the map has loaded', async () => {
    render(<RouteWorkspace {...CONFIG} fetchImpl={respondWithComparison()} />);

    await waitFor(() => expect(FakeMap.instances[0]?.layerIds.length).toBeGreaterThan(0));

    const map = FakeMap.instances[0]!;
    expect([...map.sources.keys()]).toEqual(
      expect.arrayContaining([STANDARD_SOURCE_ID, ACCESSIBLE_SOURCE_ID, POINTS_SOURCE_ID]),
    );
  });

  it('draws the accessible route above the shortest route', () => {
    // The accessible route is the answer; the shortest route is the comparison.
    // Layer order is what decides which one is visible where they overlap.
    return waitFor(async () => {
      render(<RouteWorkspace {...CONFIG} fetchImpl={respondWithComparison()} />);
      await waitFor(() => expect(FakeMap.instances[0]?.layerIds.length).toBeGreaterThan(0));

      const { layerIds } = FakeMap.instances[0]!;
      expect(layerIds.indexOf(ACCESSIBLE_LAYER_ID)).toBeGreaterThan(
        layerIds.indexOf(STANDARD_LAYER_ID),
      );
    });
  });

  it('updates existing sources instead of re-adding them', async () => {
    // Re-adding a source flickers and forces MapLibre to re-parse the style, and
    // this happens on every profile change.
    render(<RouteWorkspace {...CONFIG} fetchImpl={respondWithComparison()} />);
    await waitFor(() => expect(FakeMap.instances[0]?.layerIds.length).toBeGreaterThan(0));

    const map = FakeMap.instances[0]!;
    await clickMap(map, -80.54, 43.47);
    await clickMap(map, -80.536, 43.47);
    await compare();

    // FakeMap.addSource throws on a duplicate, so reaching here proves it.
    await waitFor(() => expect(map.dataOf(POINTS_SOURCE_ID).features).toHaveLength(2));
  });

  it('draws both routes once a comparison arrives', async () => {
    render(<RouteWorkspace {...CONFIG} fetchImpl={respondWithComparison()} />);
    await waitFor(() => expect(FakeMap.instances[0]?.layerIds.length).toBeGreaterThan(0));

    const map = FakeMap.instances[0]!;
    await clickMap(map, -80.54, 43.47);
    await clickMap(map, -80.536, 43.47);
    await compare();

    await waitFor(() => {
      expect(map.dataOf(ACCESSIBLE_SOURCE_ID).features).toHaveLength(1);
      expect(map.dataOf(STANDARD_SOURCE_ID).features).toHaveLength(1);
    });
  });

  it('fits the viewport to the route rather than leaving it elsewhere', async () => {
    render(<RouteWorkspace {...CONFIG} fetchImpl={respondWithComparison()} />);
    await waitFor(() => expect(FakeMap.instances[0]?.layerIds.length).toBeGreaterThan(0));

    const map = FakeMap.instances[0]!;
    await clickMap(map, -80.54, 43.47);

    await waitFor(() => expect(map.fitted.length).toBeGreaterThan(0));
  });

  it('cases each line directly beneath it, and halos the markers', async () => {
    // A casing above its own line would hide it; a casing under the *other*
    // route would draw a pale stripe through it. Each sits immediately below
    // the line it belongs to, and the marker halo below the marker.
    render(<RouteWorkspace {...CONFIG} fetchImpl={respondWithComparison()} />);
    await waitFor(() => expect(FakeMap.instances[0]?.layerIds.length).toBeGreaterThan(0));

    const { layerIds } = FakeMap.instances[0]!;
    expect(layerIds.indexOf(STANDARD_LAYER_ID)).toBe(
      layerIds.indexOf(STANDARD_CASING_LAYER_ID) + 1,
    );
    expect(layerIds.indexOf(ACCESSIBLE_LAYER_ID)).toBe(
      layerIds.indexOf(ACCESSIBLE_CASING_LAYER_ID) + 1,
    );
    expect(layerIds.indexOf(POINTS_LAYER_ID)).toBe(layerIds.indexOf(POINTS_HALO_LAYER_ID) + 1);
  });

  it('highlights a route by paint alone, without moving the camera', async () => {
    const user = userEvent.setup();
    render(<RouteWorkspace {...CONFIG} fetchImpl={respondWithComparison()} />);
    await waitFor(() => expect(FakeMap.instances[0]?.layerIds.length).toBeGreaterThan(0));

    const map = FakeMap.instances[0]!;
    await clickMap(map, -80.54, 43.47);
    await clickMap(map, -80.536, 43.47);
    await compare();
    await waitFor(() =>
      expect(screen.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success'),
    );
    const fitsBefore = map.fitted.length;
    const paintsBefore = map.paint.length;

    await user.click(screen.getByTestId('focus-accessible'));

    await waitFor(() => expect(map.paint.length).toBeGreaterThan(paintsBefore));
    const latest = Object.fromEntries(
      map.paint.slice(paintsBefore).map(({ layer, value }) => [layer, value]),
    );
    expect(latest[ACCESSIBLE_LAYER_ID]).toBe(1);
    expect(latest[STANDARD_LAYER_ID]).toBeLessThan(1);
    expect(latest[STANDARD_LAYER_ID]).toBeGreaterThan(0);
    // No refit and no new map: a highlight must not undo the viewer's pan.
    expect(map.fitted.length).toBe(fitsBefore);
    expect(FakeMap.instances).toHaveLength(1);
  });

  it('keeps one map instance across form and result updates', async () => {
    // Remounting the canvas on a profile change would flash the loading
    // overlay, drop the viewer's viewport and re-download the style.
    const user = userEvent.setup();
    render(<RouteWorkspace {...CONFIG} fetchImpl={respondWithComparison()} />);
    await waitFor(() => expect(FakeMap.instances[0]?.layerIds.length).toBeGreaterThan(0));

    const map = FakeMap.instances[0]!;
    await clickMap(map, -80.54, 43.47);
    await clickMap(map, -80.536, 43.47);
    await compare();
    await waitFor(() =>
      expect(screen.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success'),
    );

    await user.click(screen.getByRole('radio', { name: /Crutches or cane/ }));
    await waitFor(() =>
      expect(screen.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success'),
    );
    await user.click(screen.getByTestId('swap-points'));

    expect(FakeMap.instances).toHaveLength(1);
    expect(map.removed).toBe(false);
  });
});

describe('choosing points on the map', () => {
  it('sets the start on the first click and the end on the second', async () => {
    render(<RouteWorkspace {...CONFIG} fetchImpl={respondWithComparison()} />);
    await waitFor(() => expect(FakeMap.instances[0]?.layerIds.length).toBeGreaterThan(0));

    const map = FakeMap.instances[0]!;
    await clickMap(map, -80.54, 43.47);
    expect(screen.getByTestId('endpoint-origin-value')).toHaveTextContent('Selected map point');
    expect(screen.getByTestId('endpoint-origin-value')).toHaveTextContent('43.47000, -80.54000');
    expect(screen.getByTestId('endpoint-destination-value')).toHaveTextContent(/not set/i);

    await clickMap(map, -80.536, 43.471);
    expect(screen.getByTestId('endpoint-destination-value')).toHaveTextContent(
      'Selected map point',
    );
    expect(screen.getByTestId('endpoint-destination-value')).toHaveTextContent(
      '43.47100, -80.53600',
    );
  });

  it('asks for nothing until the viewer presses Compare', async () => {
    // Placing points is drafting, not asking. It used to fire the moment two
    // existed, which was fine while a point was only ever a map click and
    // wrong once an endpoint is a named thing somebody is still typing.
    const fetchImpl = respondWithComparison();
    render(<RouteWorkspace {...CONFIG} fetchImpl={fetchImpl} />);
    await waitFor(() => expect(FakeMap.instances[0]?.layerIds.length).toBeGreaterThan(0));

    const map = FakeMap.instances[0]!;
    await clickMap(map, -80.54, 43.47);
    expect(fetchImpl).not.toHaveBeenCalled();

    await clickMap(map, -80.536, 43.47);
    expect(fetchImpl).not.toHaveBeenCalled();

    await compare();
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledOnce());
  });

  it('sends exactly one request for one Compare press', async () => {
    const fetchImpl = respondWithComparison();
    render(<RouteWorkspace {...CONFIG} fetchImpl={fetchImpl} />);
    await waitFor(() => expect(FakeMap.instances[0]?.layerIds.length).toBeGreaterThan(0));

    const map = FakeMap.instances[0]!;
    await clickMap(map, -80.54, 43.47);
    await clickMap(map, -80.536, 43.47);
    await compare();

    await waitFor(() => expect(fetchImpl).toHaveBeenCalledOnce());
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('shows the comparison the API returned', async () => {
    render(<RouteWorkspace {...CONFIG} fetchImpl={respondWithComparison()} />);
    await waitFor(() => expect(FakeMap.instances[0]?.layerIds.length).toBeGreaterThan(0));

    const map = FakeMap.instances[0]!;
    await clickMap(map, -80.54, 43.47);
    await clickMap(map, -80.536, 43.47);
    await compare();

    await waitFor(() =>
      expect(screen.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success'),
    );
    expect(screen.getByTestId('difference-accessible')).toHaveTextContent('709 m');
  });

  it('a third click starts a new journey instead of doing nothing', async () => {
    render(<RouteWorkspace {...CONFIG} fetchImpl={respondWithComparison()} />);
    await waitFor(() => expect(FakeMap.instances[0]?.layerIds.length).toBeGreaterThan(0));

    const map = FakeMap.instances[0]!;
    await clickMap(map, -80.54, 43.47);
    await clickMap(map, -80.536, 43.47);
    await clickMap(map, -80.53, 43.475);

    expect(screen.getByTestId('endpoint-origin-value')).toHaveTextContent('43.47500, -80.53000');
    expect(screen.getByTestId('endpoint-destination-value')).toHaveTextContent(/not set/i);
  });

  it('re-requests when the mobility profile changes', async () => {
    const fetchImpl = respondWithComparison();
    render(<RouteWorkspace {...CONFIG} fetchImpl={fetchImpl} />);
    await waitFor(() => expect(FakeMap.instances[0]?.layerIds.length).toBeGreaterThan(0));

    const map = FakeMap.instances[0]!;
    await clickMap(map, -80.54, 43.47);
    await clickMap(map, -80.536, 43.47);
    await compare();
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledOnce());

    const radio = screen.getByRole('radio', { name: /Crutches or cane/ }) as HTMLInputElement;
    await act(async () => {
      radio.click();
    });

    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(2));
    const [, init] = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[1] as [
      string,
      RequestInit,
    ];
    expect(JSON.parse(String(init.body)).profile).toBe('crutches');
  });

  it('clears both points and the drawn routes', async () => {
    render(<RouteWorkspace {...CONFIG} fetchImpl={respondWithComparison()} />);
    await waitFor(() => expect(FakeMap.instances[0]?.layerIds.length).toBeGreaterThan(0));

    const map = FakeMap.instances[0]!;
    await clickMap(map, -80.54, 43.47);
    await clickMap(map, -80.536, 43.47);
    await compare();
    await waitFor(() => expect(map.dataOf(ACCESSIBLE_SOURCE_ID).features).toHaveLength(1));

    await act(async () => {
      screen.getByTestId('clear-journey').click();
    });

    expect(screen.getByTestId('endpoint-origin-value')).toHaveTextContent(/not set/i);
    await waitFor(() => expect(map.dataOf(POINTS_SOURCE_ID).features).toHaveLength(0));
    expect(map.dataOf(ACCESSIBLE_SOURCE_ID).features).toHaveLength(0);
  });

  it('swaps the endpoints', async () => {
    render(<RouteWorkspace {...CONFIG} fetchImpl={respondWithComparison()} />);
    await waitFor(() => expect(FakeMap.instances[0]?.layerIds.length).toBeGreaterThan(0));

    const map = FakeMap.instances[0]!;
    await clickMap(map, -80.54, 43.47);
    await clickMap(map, -80.536, 43.471);
    await compare();

    await act(async () => {
      screen.getByTestId('swap-points').click();
    });

    expect(screen.getByTestId('endpoint-origin-value')).toHaveTextContent('43.47100, -80.53600');
    expect(screen.getByTestId('endpoint-destination-value')).toHaveTextContent(
      '43.47000, -80.54000',
    );
  });

  it('surfaces a failed request without losing the chosen points', async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify({ code: 'no_route', message: 'No route was found.' }), {
          status: 422,
        }),
    ) as unknown as typeof fetch;

    render(<RouteWorkspace {...CONFIG} fetchImpl={fetchImpl} />);
    await waitFor(() => expect(FakeMap.instances[0]?.layerIds.length).toBeGreaterThan(0));

    const map = FakeMap.instances[0]!;
    await clickMap(map, -80.54, 43.47);
    await clickMap(map, -80.536, 43.47);
    await compare();

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('No route was found.'));
    expect(screen.getByTestId('endpoint-origin-value')).toHaveTextContent('Selected map point');
    expect(screen.getByTestId('endpoint-origin-value')).toHaveTextContent('43.47000, -80.54000');
  });
});
