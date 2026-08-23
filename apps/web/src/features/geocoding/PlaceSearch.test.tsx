import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { PlaceSearch } from './PlaceSearch';

const MATCHES = [
  {
    label: 'Waterloo Public Square, King Street South, Waterloo, Ontario',
    longitude: -80.523,
    latitude: 43.4658,
    category: 'square',
  },
  {
    label: 'Waterloo Park, Waterloo, Ontario',
    longitude: -80.533,
    latitude: 43.469,
    category: 'park',
  },
];

function jsonFetch(body: unknown, status = 200) {
  return vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
  ) as unknown as typeof fetch;
}

function renderSearch(fetchImpl: typeof fetch, onSelect = vi.fn()) {
  render(
    <PlaceSearch
      apiBaseUrl="http://api.test"
      region="waterloo"
      onSelect={onSelect}
      fetchImpl={fetchImpl}
    />,
  );
  return { onSelect };
}

describe('PlaceSearch', () => {
  it('does not search while the user is typing', async () => {
    // Per-keystroke geocoding is forbidden by the provider's usage policy, and
    // the backend's one-per-second throttle would make it useless anyway.
    const user = userEvent.setup();
    const fetchImpl = jsonFetch({ provider: 'nominatim', enabled: true, matches: MATCHES });
    renderSearch(fetchImpl);

    await user.type(screen.getByRole('searchbox'), 'Waterloo Park');

    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('searches when the form is submitted', async () => {
    const user = userEvent.setup();
    const fetchImpl = jsonFetch({ provider: 'nominatim', enabled: true, matches: MATCHES });
    renderSearch(fetchImpl);

    await user.type(screen.getByRole('searchbox'), 'Waterloo Park');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(fetchImpl).toHaveBeenCalledOnce());
    const [url, init] = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe('http://api.test/api/v1/geocode/search');
    expect(init.method).toBe('POST');
    // The query is a statement about a person's plans; it does not go in a URL.
    expect(url).not.toContain('Waterloo');
  });

  it('offers each match as a choosable button', async () => {
    const user = userEvent.setup();
    const fetchImpl = jsonFetch({ provider: 'nominatim', enabled: true, matches: MATCHES });
    const { onSelect } = renderSearch(fetchImpl);

    await user.type(screen.getByRole('searchbox'), 'Waterloo');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    const match = await screen.findByRole('button', { name: /Waterloo Park/ });
    await user.click(match);

    expect(onSelect).toHaveBeenCalledWith(
      { longitude: -80.533, latitude: 43.469 },
      'Waterloo Park, Waterloo, Ontario',
    );
  });

  it('distinguishes "search is off" from "nothing matched"', async () => {
    // Telling somebody their query found nothing, when it was never sent, sends
    // them off rephrasing a search that cannot work.
    const user = userEvent.setup();
    const fetchImpl = jsonFetch({ provider: 'disabled', enabled: false, matches: [] });
    renderSearch(fetchImpl);

    await user.type(screen.getByRole('searchbox'), 'Waterloo');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    expect(await screen.findByText(/not enabled on this deployment/i)).toBeInTheDocument();
  });

  it('says so when nothing matched inside the region', async () => {
    const user = userEvent.setup();
    const fetchImpl = jsonFetch({ provider: 'nominatim', enabled: true, matches: [] });
    renderSearch(fetchImpl);

    await user.type(screen.getByRole('searchbox'), 'Atlantis');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    expect(await screen.findByText(/nothing matched that inside this area/i)).toBeInTheDocument();
  });

  it('passes a provider failure through and points at the map instead', async () => {
    const user = userEvent.setup();
    const fetchImpl = jsonFetch(
      { code: 'geocoding_unavailable', message: 'The geocoding service is rate-limiting us.' },
      503,
    );
    renderSearch(fetchImpl);

    await user.type(screen.getByRole('searchbox'), 'Waterloo');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/rate-limiting/);
  });

  it('recovers from a network failure without breaking the page', async () => {
    const user = userEvent.setup();
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }) as unknown as typeof fetch;
    renderSearch(fetchImpl);

    await user.type(screen.getByRole('searchbox'), 'Waterloo');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/click the map instead/i);
  });

  it('will not submit an empty query', async () => {
    const fetchImpl = jsonFetch({ provider: 'nominatim', enabled: true, matches: [] });
    renderSearch(fetchImpl);

    expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('labels its input for assistive technology', async () => {
    renderSearch(jsonFetch({ provider: 'disabled', enabled: false, matches: [] }));

    expect(screen.getByLabelText('Search for a place')).toBeInTheDocument();
  });

  it('announces results politely', () => {
    renderSearch(jsonFetch({ provider: 'disabled', enabled: false, matches: [] }));

    const region = screen.getByTestId('place-search').querySelector('[aria-live="polite"]');
    expect(region).not.toBeNull();
  });
});
