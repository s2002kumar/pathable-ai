import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MapCanvas } from './MapCanvas';
import { MapStatusOverlay } from './MapStatusOverlay';
import { INITIAL_MAP_STATUS, isTerminal, needsFallback, type MapStatus } from './map-state';
import { detectWebGl } from './webgl';

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

describe('map state helpers', () => {
  it.each([
    ['initialising', false],
    ['ready', true],
    ['error', true],
    ['unsupported', true],
  ] as const)('isTerminal(%s) === %s', (state, expected) => {
    expect(isTerminal({ state, message: null })).toBe(expected);
  });

  it.each([
    ['initialising', false],
    ['ready', false],
    ['error', true],
    ['unsupported', true],
  ] as const)('needsFallback(%s) === %s', (state, expected) => {
    expect(needsFallback({ state, message: null })).toBe(expected);
  });

  it('starts in the initialising state with no message', () => {
    expect(INITIAL_MAP_STATUS).toEqual({ state: 'initialising', message: null });
  });
});

describe('detectWebGl', () => {
  it('reports unsupported when the browser returns no WebGL 2 context', () => {
    // jsdom has no WebGL; this is the real code path for a locked-down browser.
    expect(detectWebGl()).toMatchObject({ supported: false });
  });

  it('reports supported when a context is produced', () => {
    const loseContext = { loseContext: vi.fn() };
    const fakeDocument = {
      createElement: () => ({
        getContext: () => ({ getExtension: () => loseContext }),
      }),
    } as unknown as Document;

    expect(detectWebGl(fakeDocument)).toEqual({ supported: true });
    // The probe context must be released, or MapLibre may hit the browser's cap.
    expect(loseContext.loseContext).toHaveBeenCalledOnce();
  });

  it('treats a thrown getContext as unsupported rather than crashing', () => {
    const fakeDocument = {
      createElement: () => ({
        getContext: () => {
          throw new Error('blocked');
        },
      }),
    } as unknown as Document;

    expect(detectWebGl(fakeDocument)).toMatchObject({ supported: false });
  });
});

describe('MapStatusOverlay', () => {
  it('shows a loading message while initialising', () => {
    render(<MapStatusOverlay status={INITIAL_MAP_STATUS} />);

    expect(screen.getByRole('status')).toHaveTextContent('Loading the map');
  });

  it('points at the written description while loading', () => {
    render(<MapStatusOverlay status={INITIAL_MAP_STATUS} />);

    expect(screen.getByRole('status')).toHaveTextContent('written description');
  });

  it('renders nothing once the map is ready', () => {
    const { container } = render(<MapStatusOverlay status={{ state: 'ready', message: null }} />);

    expect(container).toBeEmptyDOMElement();
  });

  it('announces a failure assertively with its explanation', () => {
    const status: MapStatus = { state: 'error', message: 'The map could not be loaded.' };

    render(<MapStatusOverlay status={status} />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('The map is unavailable');
    expect(alert).toHaveTextContent('The map could not be loaded.');
  });

  it('explains the WebGL fallback in browser terms, not technical ones', () => {
    const status: MapStatus = {
      state: 'unsupported',
      message: 'Hardware acceleration may be disabled.',
    };

    render(<MapStatusOverlay status={status} />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('This browser cannot display the map');
    expect(alert).toHaveTextContent('Hardware acceleration may be disabled.');
  });
});

describe('MapCanvas', () => {
  const props = {
    styleUrl: '/map-styles/offline-test-style.json',
    centerLat: 43.4668,
    centerLon: -80.5164,
    zoom: 14,
    regionName: 'Waterloo, Ontario',
    attribution: '© OpenStreetMap contributors',
  };

  it('exposes the map as a named region', () => {
    // Without an accessible name the map is an anonymous div: unreachable by
    // landmark navigation and unannounced by a screen reader.
    render(<MapCanvas {...props} />);

    expect(
      screen.getByRole('region', { name: /interactive map of waterloo, ontario/i }),
    ).toBeInTheDocument();
  });

  it('names the region after the configured pilot area', () => {
    render(<MapCanvas {...props} regionName="Vancouver, British Columbia" />);

    expect(
      screen.getByRole('region', { name: /interactive map of vancouver/i }),
    ).toBeInTheDocument();
  });

  it('links the map to its written description', () => {
    render(<MapCanvas {...props} describedById="pilot-area-description" />);

    expect(screen.getByRole('region', { name: /interactive map/i })).toHaveAttribute(
      'aria-describedby',
      'pilot-area-description',
    );
  });

  it('publishes its lifecycle state for deterministic browser tests', () => {
    render(<MapCanvas {...props} />);

    // jsdom provides no WebGL, so this is genuinely the unsupported path.
    expect(screen.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'unsupported');
  });

  it('renders the fallback explanation when WebGL is unavailable', () => {
    render(<MapCanvas {...props} />);

    expect(screen.getByRole('alert')).toHaveTextContent('This browser cannot display the map');
  });
});
