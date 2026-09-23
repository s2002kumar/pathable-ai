import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import HomePage from './page';

vi.mock('maplibre-gl', () => ({
  // Required since the KI-1 fix: the hook configures the worker URL before
  // constructing a Map. A mock without it throws.
  setWorkerUrl: () => {},
  getWorkerUrl: () => '',
  Map: class {
    on() {}
    off() {}
    addControl() {}
    remove() {}
  },
  NavigationControl: class {},
  ScaleControl: class {},
  AttributionControl: class {},
}));

const VALID_ENV = {
  NEXT_PUBLIC_API_BASE_URL: 'http://api.test',
  NEXT_PUBLIC_MAP_STYLE_URL: '/map-styles/offline-test-style.json',
  NEXT_PUBLIC_PILOT_CENTER_LAT: '43.4668',
  NEXT_PUBLIC_PILOT_CENTER_LON: '-80.5164',
  NEXT_PUBLIC_PILOT_ZOOM: '14',
  NEXT_PUBLIC_PILOT_REGION_NAME: 'Waterloo, Ontario',
  NEXT_PUBLIC_PILOT_REGION_SLUG: 'waterloo',
};

function setEnv(values: Record<string, string>) {
  for (const [key, value] of Object.entries(values)) vi.stubEnv(key, value);
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            status: 'ready',
            service: 'pathable-api',
            version: '0.1.0',
            checks: {
              database: { status: 'ok', detail: 'connected', latency_ms: 3 },
              postgis: { status: 'ok', detail: 'postgis 3.5.0', latency_ms: 1 },
            },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
    ),
  );
});

/**
 * `HomePage` is an async server component — it resolves the `?example=` deep
 * link before rendering — so a test has to await it rather than render the
 * promise it returns.
 */
function homePage(searchParams: Record<string, string | string[] | undefined> = {}) {
  return HomePage({ searchParams: Promise.resolve(searchParams) });
}

describe('HomePage', () => {
  it('renders the product shell', async () => {
    setEnv(VALID_ENV);

    render(await homePage());

    expect(screen.getByText('PathAble AI')).toBeInTheDocument();
    expect(screen.getByRole('main')).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: /Waterloo, Ontario/, level: 1 }),
    ).toBeInTheDocument();
  });

  it('renders the map surface', async () => {
    setEnv(VALID_ENV);

    render(await homePage());

    await waitFor(() => expect(screen.getByTestId('map-frame')).toBeInTheDocument());
  });

  it('describes what the page does in text, not only on the map', async () => {
    setEnv(VALID_ENV);

    render(await homePage());

    const description = screen.getByTestId('pilot-description');
    expect(description).toHaveAttribute('id', 'pilot-area-description');
    expect(description).toHaveTextContent(/compares the shortest walking route/i);
  });

  it('states that missing data is not evidence of a clear path', async () => {
    // The product's central safety claim. If this sentence disappears, somebody
    // can read an unsurveyed route as a checked one.
    setEnv(VALID_ENV);

    render(await homePage());

    expect(screen.getByTestId('pilot-description')).toHaveTextContent(
      /missing information is never treated as a clear path/i,
    );
  });

  it('never promises that a route is passable', async () => {
    setEnv(VALID_ENV);

    render(await homePage());

    expect(screen.getByTestId('pilot-description')).toHaveTextContent(
      /no route here is a guarantee/i,
    );
  });

  it('offers the mobility profiles as a labelled radio group', async () => {
    setEnv(VALID_ENV);

    render(await homePage());

    const group = screen.getByRole('radiogroup', { name: /mobility profile/i });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Wheelchair/ })).toBeChecked();
    expect(screen.getAllByRole('radio')).toHaveLength(5);
  });

  it('explains how to begin before any point is chosen', async () => {
    setEnv(VALID_ENV);

    render(await homePage());

    expect(screen.getByTestId('route-status')).toHaveAttribute('data-route-state', 'idle');

    // Two ways in, in the order a first-time viewer should meet them: a journey
    // they can run immediately, and the map they can use instead.
    expect(screen.getByTestId('run-verified-example')).toBeInTheDocument();
    expect(screen.getByTestId('route-status')).toHaveTextContent(/click the map to set a start/i);
  });

  it('shows a map key explaining the two route lines', async () => {
    // The legend is real text outside the canvas: one painted into WebGL would
    // be invisible to a screen reader and unselectable.
    setEnv(VALID_ENV);

    render(await homePage());

    const legend = screen.getByTestId('map-legend');
    expect(legend).toHaveTextContent(/Route for your profile/i);
    expect(legend).toHaveTextContent(/Shortest walking route/i);
  });

  it('shows backend status in the shell', async () => {
    setEnv(VALID_ENV);

    render(await homePage());

    await waitFor(() =>
      expect(screen.getByTestId('system-status')).toHaveAttribute('data-status', 'ready'),
    );
  });

  it('shows visible OpenStreetMap attribution', async () => {
    setEnv(VALID_ENV);

    render(await homePage());

    const attribution = screen.getByTestId('attribution');
    expect(attribution).toHaveTextContent(/OpenStreetMap/);
    expect(attribution).toHaveTextContent(/ODbL/);
  });

  it('notes that the development tile provider is not production-approved', async () => {
    setEnv(VALID_ENV);

    render(await homePage());

    expect(screen.getByTestId('attribution')).toHaveTextContent(
      /not been approved for production/i,
    );
  });

  it('renders the configuration error page instead of a broken shell', async () => {
    setEnv({ ...VALID_ENV, NEXT_PUBLIC_PILOT_ZOOM: '99' });

    render(await homePage());

    expect(screen.getByTestId('configuration-error')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('NEXT_PUBLIC_PILOT_ZOOM');
    expect(screen.queryByText('PathAble AI')).not.toBeInTheDocument();
  });

  it('reports every configuration problem at once', async () => {
    setEnv({
      ...VALID_ENV,
      NEXT_PUBLIC_PILOT_ZOOM: '99',
      NEXT_PUBLIC_API_BASE_URL: 'not-a-url',
    });

    render(await homePage());

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('NEXT_PUBLIC_PILOT_ZOOM');
    expect(alert).toHaveTextContent('NEXT_PUBLIC_API_BASE_URL');
  });

  it('rejects a region slug the API could not accept', async () => {
    setEnv({ ...VALID_ENV, NEXT_PUBLIC_PILOT_REGION_SLUG: 'Waterloo Ontario!' });

    render(await homePage());

    expect(screen.getByRole('alert')).toHaveTextContent('NEXT_PUBLIC_PILOT_REGION_SLUG');
  });
});
