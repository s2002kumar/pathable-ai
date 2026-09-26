import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AppHeader } from './AppHeader';
import { ConfigurationError } from './ConfigurationError';

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

    expect(screen.getByText('PathAble')).toBeInTheDocument();
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
