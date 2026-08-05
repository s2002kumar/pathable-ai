import { render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AppHeader } from './AppHeader';
import { ConfigurationError } from './ConfigurationError';
import { PilotPanel } from './PilotPanel';

const READY_BODY = {
  status: 'ready',
  service: 'pathable-api',
  version: '0.1.0',
  checks: {
    database: { status: 'ok', detail: 'connected', latency_ms: 4.2 },
    postgis: { status: 'ok', detail: 'postgis 3.5.0', latency_ms: 1.1 },
  },
};

const NOT_READY_BODY = {
  status: 'not_ready',
  service: 'pathable-api',
  version: '0.1.0',
  checks: {
    database: { status: 'unavailable', detail: 'database unreachable', latency_ms: null },
    postgis: { status: 'unavailable', detail: 'not probed', latency_ms: null },
  },
};

function stubFetch(handler: () => Promise<Response>) {
  vi.stubGlobal('fetch', vi.fn(handler));
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderHeader() {
  return render(
    <AppHeader
      apiBaseUrl="http://api.test"
      pilotRegionName="Waterloo, Ontario"
      statusPollIntervalMs={0}
    />,
  );
}

describe('AppHeader', () => {
  it('renders the product identity', () => {
    stubFetch(async () => jsonResponse(READY_BODY));

    renderHeader();

    expect(screen.getByText('PathAble AI')).toBeInTheDocument();
    expect(screen.getByText('Accessibility-aware pedestrian routing')).toBeInTheDocument();
  });

  it('shows the configured pilot region', () => {
    stubFetch(async () => jsonResponse(READY_BODY));

    renderHeader();

    expect(screen.getByTestId('pilot-region')).toHaveTextContent('Waterloo, Ontario');
  });

  it('starts in a checking state before the probe resolves', () => {
    stubFetch(async () => jsonResponse(READY_BODY));

    renderHeader();

    expect(screen.getByTestId('system-status')).toHaveAttribute('data-status', 'checking');
  });

  it('reports a healthy API', async () => {
    stubFetch(async () => jsonResponse(READY_BODY));

    renderHeader();

    await waitFor(() =>
      expect(screen.getByTestId('system-status')).toHaveAttribute('data-status', 'ready'),
    );
    expect(screen.getByTestId('system-status')).toHaveTextContent('API online');
    expect(screen.getByTestId('system-status')).toHaveTextContent('pathable-api v0.1.0');
  });

  it('reports an unavailable API', async () => {
    stubFetch(async () => {
      throw new TypeError('Failed to fetch');
    });

    renderHeader();

    await waitFor(() =>
      expect(screen.getByTestId('system-status')).toHaveAttribute('data-status', 'unreachable'),
    );
    expect(screen.getByTestId('system-status')).toHaveTextContent('API offline');
  });

  it('distinguishes a degraded backend from an offline one', async () => {
    stubFetch(async () => jsonResponse(NOT_READY_BODY, 503));

    renderHeader();

    await waitFor(() =>
      expect(screen.getByTestId('system-status')).toHaveAttribute('data-status', 'degraded'),
    );
    expect(screen.getByTestId('system-status')).toHaveTextContent('API degraded');
    expect(screen.getByTestId('system-status')).toHaveTextContent('database and PostGIS');
  });

  it('announces status changes politely rather than interrupting', async () => {
    stubFetch(async () => jsonResponse(READY_BODY));

    renderHeader();

    const badge = screen.getByTestId('system-status');
    expect(badge).toHaveAttribute('role', 'status');
    expect(badge).toHaveAttribute('aria-live', 'polite');
  });

  it('states the status in words, not colour alone', async () => {
    stubFetch(async () => jsonResponse(NOT_READY_BODY, 503));

    renderHeader();

    // The dot is decorative; the text carries the meaning.
    await waitFor(() => expect(screen.getByText(/API degraded/)).toBeInTheDocument());
  });
});

describe('PilotPanel', () => {
  function renderPanel(regionName = 'Waterloo, Ontario') {
    return render(
      <PilotPanel
        regionName={regionName}
        centerLat={43.4668}
        centerLon={-80.5164}
        descriptionId="pilot-area-description"
      />,
    );
  }

  it('renders the pilot area heading', () => {
    renderPanel();

    expect(
      screen.getByRole('heading', { name: 'Waterloo, Ontario', level: 1 }),
    ).toBeInTheDocument();
  });

  it('describes the pilot area in text, not only on the map', () => {
    renderPanel();

    const description = screen.getByTestId('pilot-description');
    expect(description).toHaveTextContent(/uptown core/i);
    expect(description).toHaveTextContent(/University of Waterloo/i);
    expect(description).toHaveTextContent(/ION light-rail/i);
  });

  it('exposes the description under the id the map references', () => {
    renderPanel();

    expect(screen.getByTestId('pilot-description')).toHaveAttribute('id', 'pilot-area-description');
  });

  it('shows the configured centre coordinates', () => {
    renderPanel();

    expect(screen.getByText(/43\.4668° N/)).toBeInTheDocument();
    expect(screen.getByText(/80\.5164° W/)).toBeInTheDocument();
  });

  it('discloses that this is a Phase 0 build', () => {
    renderPanel();

    const notice = screen.getByTestId('development-notice');
    expect(notice).toHaveTextContent(/Phase 0/i);
    expect(notice).toHaveTextContent(/foundation only/i);
  });

  it('states plainly that routing and ML do not exist yet', () => {
    // This product could mislead someone into an unsafe journey. The disclosure
    // is a safety requirement, not a nicety.
    renderPanel();

    const notice = screen.getByTestId('development-notice');
    expect(notice).toHaveTextContent(/no routing/i);
    expect(notice).toHaveTextContent(/no machine learning/i);
    expect(notice).toHaveTextContent(/should be used to plan a journey/i);
  });

  it('shows visible data attribution', () => {
    renderPanel();

    const attribution = screen.getByTestId('attribution');
    expect(attribution).toHaveTextContent(/OpenStreetMap/);
    expect(within(attribution).getByRole('link', { name: /OpenStreetMap/ })).toHaveAttribute(
      'href',
      'https://www.openstreetmap.org/copyright',
    );
  });

  it('notes that the development tile provider is not production-approved', () => {
    renderPanel();

    expect(screen.getByTestId('attribution')).toHaveTextContent(
      /not been approved for production/i,
    );
  });

  it('labels the Phase 1 list as planned, not available', () => {
    renderPanel();

    expect(screen.getByText(/Planned for Phase 1/i)).toBeInTheDocument();
  });

  it('offers no interactive routing controls', () => {
    // A search box or "Find route" button that silently does nothing would be
    // worse than no control at all.
    renderPanel();

    expect(screen.queryAllByRole('button')).toHaveLength(0);
    expect(screen.queryAllByRole('textbox')).toHaveLength(0);
    expect(screen.queryAllByRole('combobox')).toHaveLength(0);
    expect(screen.queryAllByRole('searchbox')).toHaveLength(0);
    expect(screen.queryAllByRole('radio')).toHaveLength(0);
  });

  it('exposes only external reference links, never route actions', () => {
    renderPanel();

    for (const link of screen.getAllByRole('link')) {
      expect(link.getAttribute('href')).toMatch(/^https:\/\//);
    }
  });

  it('follows the configured region rather than hard-coding Waterloo', () => {
    renderPanel('Vancouver, British Columbia');

    expect(
      screen.getByRole('heading', { name: 'Vancouver, British Columbia', level: 1 }),
    ).toBeInTheDocument();
  });
});

describe('ConfigurationError', () => {
  it('lists every invalid variable', () => {
    render(
      <ConfigurationError
        issues={[
          { field: 'NEXT_PUBLIC_PILOT_ZOOM', message: 'must be between 0 and 22' },
          { field: 'NEXT_PUBLIC_API_BASE_URL', message: 'must be an absolute URL' },
        ]}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('NEXT_PUBLIC_PILOT_ZOOM');
    expect(screen.getByRole('alert')).toHaveTextContent('NEXT_PUBLIC_API_BASE_URL');
    expect(screen.getByText('2 environment variables have invalid values:')).toBeInTheDocument();
  });

  it('uses singular wording for a single problem', () => {
    render(
      <ConfigurationError
        issues={[{ field: 'NEXT_PUBLIC_PILOT_ZOOM', message: 'must be between 0 and 22' }]}
      />,
    );

    expect(screen.getByText('One environment variable has an invalid value:')).toBeInTheDocument();
  });

  it('tells the reader how to fix it', () => {
    render(<ConfigurationError issues={[{ field: 'X', message: 'bad' }]} />);

    expect(screen.getByRole('alert')).toHaveTextContent('.env.example');
    expect(screen.getByRole('alert')).toHaveTextContent(/rebuild is required/i);
  });
});
