import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import HomePage from './page';

vi.mock('maplibre-gl', () => ({
  Map: class {
    on() {}
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

describe('HomePage', () => {
  it('renders the product shell', () => {
    setEnv(VALID_ENV);

    render(<HomePage />);

    expect(screen.getByText('PathAble AI')).toBeInTheDocument();
    expect(screen.getByRole('main')).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: 'Waterloo, Ontario', level: 1 }),
    ).toBeInTheDocument();
  });

  it('renders the map surface', async () => {
    setEnv(VALID_ENV);

    render(<HomePage />);

    await waitFor(() => expect(screen.getByTestId('map-frame')).toBeInTheDocument());
  });

  it('renders the pilot description and the development disclosure together', () => {
    setEnv(VALID_ENV);

    render(<HomePage />);

    expect(screen.getByTestId('pilot-description')).toBeInTheDocument();
    expect(screen.getByTestId('development-notice')).toHaveTextContent(/no routing/i);
  });

  it('shows backend status in the shell', async () => {
    setEnv(VALID_ENV);

    render(<HomePage />);

    await waitFor(() =>
      expect(screen.getByTestId('system-status')).toHaveAttribute('data-status', 'ready'),
    );
  });

  it('presents no routing controls anywhere in the shell', () => {
    setEnv(VALID_ENV);

    render(<HomePage />);

    expect(screen.queryAllByRole('textbox')).toHaveLength(0);
    expect(screen.queryAllByRole('searchbox')).toHaveLength(0);
    expect(screen.queryAllByRole('combobox')).toHaveLength(0);
  });

  it('renders the configuration error page instead of a broken shell', () => {
    setEnv({ ...VALID_ENV, NEXT_PUBLIC_PILOT_ZOOM: '99' });

    render(<HomePage />);

    expect(screen.getByTestId('configuration-error')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('NEXT_PUBLIC_PILOT_ZOOM');
    expect(screen.queryByText('PathAble AI')).not.toBeInTheDocument();
  });

  it('reports every configuration problem at once', () => {
    setEnv({
      ...VALID_ENV,
      NEXT_PUBLIC_PILOT_ZOOM: '99',
      NEXT_PUBLIC_API_BASE_URL: 'not-a-url',
    });

    render(<HomePage />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('NEXT_PUBLIC_PILOT_ZOOM');
    expect(alert).toHaveTextContent('NEXT_PUBLIC_API_BASE_URL');
  });
});
