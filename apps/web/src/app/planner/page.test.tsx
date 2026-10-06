import { render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import PlannerPage from './page';

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

const READY = {
  status: 'ready',
  service: 'pathable-api',
  version: '0.1.0',
  checks: {
    database: { status: 'ok', detail: 'connected', latency_ms: 3 },
    postgis: { status: 'ok', detail: 'postgis 3.5.0', latency_ms: 1 },
  },
};

const NOT_READY = {
  status: 'not_ready',
  service: 'pathable-api',
  version: '0.1.0',
  checks: {
    database: { status: 'unavailable', detail: 'database unreachable', latency_ms: null },
    postgis: { status: 'unavailable', detail: 'not probed', latency_ms: null },
  },
};

function setEnv(values: Record<string, string>) {
  for (const [key, value] of Object.entries(values)) vi.stubEnv(key, value);
}

/** The readiness probe answers with `health`; the profile rules are not served. */
function stubApi(health: () => Promise<Response>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      String(url).includes('/health') ? health() : new Response('{}', { status: 503 }),
    ),
  );
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  stubApi(async () => json(READY));
});

/** An async server component: await it rather than render the promise. */
function plannerPage(searchParams: Record<string, string | string[] | undefined> = {}) {
  return PlannerPage({ searchParams: Promise.resolve(searchParams) });
}

describe('the planner page', () => {
  it('renders the product shell', async () => {
    setEnv(VALID_ENV);

    render(await plannerPage());

    expect(screen.getByText('PathAble')).toBeInTheDocument();
    expect(screen.getByRole('main')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Route Planner', level: 1 })).toBeInTheDocument();
    expect(screen.getByTestId('pilot-region')).toHaveTextContent('Waterloo, ON');
  });

  it('renders the map surface', async () => {
    setEnv(VALID_ENV);

    render(await plannerPage());

    await waitFor(() => expect(screen.getByTestId('map-frame')).toBeInTheDocument());
  });

  it('describes what the page does in text, not only on the map', async () => {
    setEnv(VALID_ENV);

    render(await plannerPage());

    const description = screen.getByTestId('pilot-description');
    expect(description).toHaveAttribute('id', 'pilot-area-description');
    expect(description).toHaveTextContent(/compares the shortest walking route/i);
  });

  it('states that missing data is not evidence of a clear path', async () => {
    // The product's central safety claim. If this sentence disappears, somebody
    // can read an unsurveyed route as a checked one.
    setEnv(VALID_ENV);

    render(await plannerPage());

    expect(screen.getByTestId('pilot-description')).toHaveTextContent(
      /missing information is never treated as a clear path/i,
    );
  });

  it('never promises that a route is passable', async () => {
    setEnv(VALID_ENV);

    render(await plannerPage());

    expect(screen.getByTestId('pilot-description')).toHaveTextContent(
      /no route here is a guarantee/i,
    );
  });

  it('offers all five mobility profiles as one labelled group of radio buttons', async () => {
    // Real radio buttons, drawn as cards: every profile on show at once, one
    // tab stop for the group and the arrow keys within it, as the platform
    // does it. The wheelchair profile is chosen first.
    setEnv(VALID_ENV);

    render(await plannerPage());

    const group = screen.getByRole('group', { name: /mobility profile/i });
    const radios = within(group).getAllByRole('radio');
    expect(radios.map((radio) => radio.getAttribute('value'))).toEqual([
      'wheelchair',
      'walker',
      'crutches',
      'stroller',
      'reduced_mobility',
    ]);
    expect(within(group).getByRole('radio', { name: /^Wheelchair/ })).toBeChecked();
    expect(radios.filter((radio) => (radio as HTMLInputElement).checked)).toHaveLength(1);
  });

  it('explains how to begin before any point is chosen', async () => {
    setEnv(VALID_ENV);

    render(await plannerPage());

    expect(screen.getByTestId('route-status')).toHaveAttribute('data-route-state', 'idle');
    // Two ways in: a journey they can run immediately, and the fields and map.
    expect(screen.getByTestId('run-verified-example')).toBeInTheDocument();
    expect(screen.getByTestId('route-status')).toHaveTextContent(/name both ends to begin/i);
  });

  it('opens with the verified example already chosen when the link asks for it', async () => {
    setEnv(VALID_ENV);

    render(await plannerPage({ example: 'campus-library-to-student-life' }));

    expect(screen.getByLabelText('Start location')).toHaveValue('Davis Centre library');
    expect(screen.getByLabelText('Target endpoint')).toHaveValue('Student Life Centre');
  });

  it('shows visible OpenStreetMap and elevation attribution', async () => {
    setEnv(VALID_ENV);

    render(await plannerPage());

    const attribution = screen.getByTestId('attribution');
    expect(attribution).toHaveTextContent(/OpenStreetMap/);
    expect(attribution).toHaveTextContent(/ODbL/);
    // The panel shows HRDEM grades on its first screen, so the licence's
    // statement cannot wait behind "Route Details".
    expect(screen.getByTestId('elevation-licence')).toHaveTextContent(
      'contains information licensed under the Open Government Licence – Canada.',
    );
  });

  it('notes that the development tile provider is not production-approved', async () => {
    setEnv(VALID_ENV);

    render(await plannerPage());

    expect(screen.getByTestId('attribution')).toHaveTextContent(
      /OpenFreeMap, which has not been approved for production/i,
    );
  });

  it('renders the configuration error page instead of a broken shell', async () => {
    setEnv({ ...VALID_ENV, NEXT_PUBLIC_PILOT_ZOOM: '99' });

    render(await plannerPage());

    expect(screen.getByTestId('configuration-error')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('NEXT_PUBLIC_PILOT_ZOOM');
    expect(screen.queryByText('PathAble')).not.toBeInTheDocument();
  });

  it('reports every configuration problem at once', async () => {
    setEnv({
      ...VALID_ENV,
      NEXT_PUBLIC_PILOT_ZOOM: '99',
      NEXT_PUBLIC_API_BASE_URL: 'not-a-url',
    });

    render(await plannerPage());

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('NEXT_PUBLIC_PILOT_ZOOM');
    expect(alert).toHaveTextContent('NEXT_PUBLIC_API_BASE_URL');
  });

  it('rejects a region slug the API could not accept', async () => {
    setEnv({ ...VALID_ENV, NEXT_PUBLIC_PILOT_REGION_SLUG: 'Waterloo Ontario!' });

    render(await plannerPage());

    expect(screen.getByRole('alert')).toHaveTextContent('NEXT_PUBLIC_PILOT_REGION_SLUG');
  });
});

/**
 * The routing service's state, probed once for the page: a word in the bar's
 * region pill, and the full sentence in the idle strip.
 */
describe('the routing service’s state', () => {
  it('starts in a checking state before the probe resolves', async () => {
    setEnv(VALID_ENV);
    stubApi(() => new Promise<Response>(() => {}));

    render(await plannerPage());

    expect(screen.getByTestId('system-status')).toHaveAttribute('data-status', 'checking');
    expect(screen.getByTestId('header-status')).toHaveTextContent('Checking');
  });

  it('reports a healthy API, with its version kept off the strip’s face', async () => {
    setEnv(VALID_ENV);

    render(await plannerPage());

    await waitFor(() =>
      expect(screen.getByTestId('system-status')).toHaveAttribute('data-status', 'ready'),
    );
    expect(screen.getByTestId('system-status')).toHaveTextContent('Ready to route');
    expect(screen.getByTestId('system-status')).toHaveAttribute('title', 'pathable-api v0.1.0');
    // Ready is the design's state: the word is there for assistive technology.
    expect(screen.getByTestId('header-status')).toHaveClass('visually-hidden');
    expect(screen.getByTestId('header-status')).toHaveTextContent('Routing service: Ready');
  });

  it('reports an unavailable API in words, not colour alone', async () => {
    setEnv(VALID_ENV);
    stubApi(async () => {
      throw new TypeError('Failed to fetch');
    });

    render(await plannerPage());

    await waitFor(() =>
      expect(screen.getByTestId('system-status')).toHaveAttribute('data-status', 'unreachable'),
    );
    expect(screen.getByTestId('system-status')).toHaveTextContent('Routing service offline');
    const word = screen.getByTestId('header-status');
    expect(word).toHaveTextContent('Offline');
    expect(word).not.toHaveClass('visually-hidden');
  });

  it('distinguishes a degraded backend from an offline one', async () => {
    setEnv(VALID_ENV);
    stubApi(async () => json(NOT_READY, 503));

    render(await plannerPage());

    await waitFor(() =>
      expect(screen.getByTestId('system-status')).toHaveAttribute('data-status', 'degraded'),
    );
    expect(screen.getByTestId('system-status')).toHaveTextContent('Routing service degraded');
    expect(screen.getByTestId('system-status')).toHaveTextContent('database and PostGIS');
    expect(screen.getByTestId('header-status')).toHaveTextContent('Degraded');
  });

  it('announces status changes politely rather than interrupting', async () => {
    setEnv(VALID_ENV);

    render(await plannerPage());

    const strip = screen.getByTestId('system-status');
    expect(strip).toHaveAttribute('role', 'status');
    expect(strip).toHaveAttribute('aria-live', 'polite');
  });
});
