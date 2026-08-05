import { act, render, screen, waitFor } from '@testing-library/react';
import { useRef } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useMapLibre } from './useMapLibre';
import type { WebGlSupport } from './webgl';

type Handler = (event: { error?: { message?: string } }) => void;

/** Captures every fake map created during a test so lifecycle can be asserted. */
const created: FakeMap[] = [];

class FakeMap {
  readonly handlers = new Map<string, Handler[]>();
  readonly controls: unknown[] = [];
  removed = 0;

  constructor() {
    created.push(this);
  }

  on(event: string, handler: Handler): void {
    const existing = this.handlers.get(event) ?? [];
    existing.push(handler);
    this.handlers.set(event, existing);
  }

  addControl(control: unknown): void {
    this.controls.push(control);
  }

  remove(): void {
    this.removed += 1;
  }

  emit(event: string, payload: { error?: { message?: string } } = {}): void {
    for (const handler of this.handlers.get(event) ?? []) handler(payload);
  }
}

vi.mock('maplibre-gl', () => ({
  Map: FakeMap,
  NavigationControl: class NavigationControl {},
  ScaleControl: class ScaleControl {},
  AttributionControl: class AttributionControl {},
}));

const SUPPORTED: WebGlSupport = { supported: true };
const UNSUPPORTED: WebGlSupport = { supported: false, reason: 'no webgl here' };

function Harness({
  detect,
  initTimeoutMs,
  styleUrl = '/style.json',
}: {
  detect: () => WebGlSupport;
  initTimeoutMs?: number;
  styleUrl?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const status = useMapLibre({
    containerRef: ref,
    styleUrl,
    center: [-80.5164, 43.4668],
    zoom: 14,
    attribution: '© test',
    detect,
    ...(initTimeoutMs !== undefined ? { initTimeoutMs } : {}),
  });

  return (
    <div>
      <div ref={ref} data-testid="container" />
      <span data-testid="state">{status.state}</span>
      <span data-testid="message">{status.message ?? ''}</span>
    </div>
  );
}

const lastMap = () => created.at(-1);

beforeEach(() => {
  created.length = 0;
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

describe('useMapLibre', () => {
  describe('WebGL unavailable', () => {
    it('reports unsupported immediately, without a loading flash', () => {
      render(<Harness detect={() => UNSUPPORTED} />);

      expect(screen.getByTestId('state')).toHaveTextContent('unsupported');
    });

    it('surfaces the detector explanation', () => {
      render(<Harness detect={() => UNSUPPORTED} />);

      expect(screen.getByTestId('message')).toHaveTextContent('no webgl here');
    });

    it('never constructs a map', () => {
      render(<Harness detect={() => UNSUPPORTED} />);

      expect(created).toHaveLength(0);
    });
  });

  describe('WebGL available', () => {
    it('starts in the initialising state', () => {
      render(<Harness detect={() => SUPPORTED} />);

      expect(screen.getByTestId('state')).toHaveTextContent('initialising');
    });

    it('becomes ready once MapLibre finishes loading', async () => {
      render(<Harness detect={() => SUPPORTED} />);

      await waitFor(() => expect(lastMap()).toBeDefined());
      act(() => lastMap()?.emit('load'));

      await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('ready'));
    });

    it('registers navigation, scale and attribution controls', async () => {
      render(<Harness detect={() => SUPPORTED} />);

      await waitFor(() => expect(lastMap()?.controls).toHaveLength(3));
    });

    it('fails safely when MapLibre reports an initialisation error', async () => {
      render(<Harness detect={() => SUPPORTED} />);

      await waitFor(() => expect(lastMap()).toBeDefined());
      act(() => lastMap()?.emit('error', { error: { message: 'style not found' } }));

      await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('error'));
      expect(screen.getByTestId('message')).toHaveTextContent('could not be loaded');
    });

    it('does not downgrade an already-loaded map when a later tile fails', async () => {
      // A missing tile is a degraded map, not a broken one. Replacing a usable map
      // with an error screen would be a worse outcome than the missing tile.
      render(<Harness detect={() => SUPPORTED} />);

      await waitFor(() => expect(lastMap()).toBeDefined());
      act(() => lastMap()?.emit('load'));
      await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('ready'));

      act(() => lastMap()?.emit('error', { error: { message: 'tile 404' } }));

      expect(screen.getByTestId('state')).toHaveTextContent('ready');
    });

    it('gives up after the initialisation timeout', async () => {
      vi.useFakeTimers();
      try {
        render(<Harness detect={() => SUPPORTED} initTimeoutMs={50} />);
        await vi.waitFor(() => expect(lastMap()).toBeDefined());

        await act(async () => {
          await vi.advanceTimersByTimeAsync(60);
        });

        expect(screen.getByTestId('state')).toHaveTextContent('error');
        expect(screen.getByTestId('message')).toHaveTextContent('longer than expected');
      } finally {
        vi.useRealTimers();
      }
    });

    it('does not fire the timeout once the map is ready', async () => {
      vi.useFakeTimers();
      try {
        render(<Harness detect={() => SUPPORTED} initTimeoutMs={50} />);
        await vi.waitFor(() => expect(lastMap()).toBeDefined());
        act(() => lastMap()?.emit('load'));

        await act(async () => {
          await vi.advanceTimersByTimeAsync(500);
        });

        expect(screen.getByTestId('state')).toHaveTextContent('ready');
      } finally {
        vi.useRealTimers();
      }
    });

    it('removes the map on unmount', async () => {
      const view = render(<Harness detect={() => SUPPORTED} />);
      await waitFor(() => expect(lastMap()).toBeDefined());
      const map = lastMap();

      view.unmount();

      expect(map?.removed).toBe(1);
    });

    it('leaves no orphaned instance when unmounted mid-initialisation', async () => {
      // StrictMode's double effect plus an async import is exactly how an
      // orphaned map ends up attached to a detached container.
      const view = render(<Harness detect={() => SUPPORTED} />);
      view.unmount();

      await waitFor(() => {
        for (const map of created) expect(map.removed).toBeGreaterThanOrEqual(1);
      });
    });
  });
});
