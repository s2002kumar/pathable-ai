/**
 * Evidence labels pinned to the map, against a fake projection.
 *
 * What matters is where a label goes, that it follows the camera, and that a
 * less important label gives way rather than covering a more important one.
 */
import { act, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { type MapMarker, MapMarkers } from './MapMarkers';
import type { MapInstance } from './useMapLibre';

type Handler = () => void;

function fakeMap(offset = { x: 0, y: 0 }) {
  const handlers = new Map<string, Set<Handler>>();
  const state = { offset };
  const map = {
    project: ([lng, lat]: [number, number]) => ({
      x: lng * 10 + state.offset.x,
      y: lat * 10 + state.offset.y,
    }),
    on: (event: string, handler: Handler) => {
      const set = handlers.get(event) ?? new Set();
      set.add(handler);
      handlers.set(event, set);
    },
    off: (event: string, handler: Handler) => handlers.get(event)?.delete(handler),
  } as unknown as MapInstance;
  const emit = (event: string) => handlers.get(event)?.forEach((handler) => handler());
  return { map, state, emit, handlers };
}

const BARRIER: MapMarker = {
  id: 'barrier-steps',
  position: [10, 20],
  label: 'Ruled out: 1 stairway',
  tone: 'barrier',
};
const CLIMB: MapMarker = {
  id: 'gradient-accessible',
  position: [10, 20],
  label: 'Steepest climb 4.0% · recorded',
  tone: 'gradient',
};

function anchorOf(testId: string): HTMLElement {
  return screen.getByTestId(testId).parentElement as HTMLElement;
}

describe('evidence labels on the map', () => {
  it('pins each label to its own point and follows the camera', () => {
    const { map, state, emit } = fakeMap();
    render(<MapMarkers map={map} markers={[BARRIER]} />);

    expect(anchorOf('map-marker-barrier-steps').style.transform).toBe('translate(100px, 200px)');

    state.offset = { x: -30, y: 5 };
    act(() => emit('move'));
    expect(anchorOf('map-marker-barrier-steps').style.transform).toBe('translate(70px, 205px)');
  });

  it('hides the less important of two labels that would cover each other', () => {
    const { map } = fakeMap();
    render(<MapMarkers map={map} markers={[BARRIER, CLIMB]} />);

    expect(anchorOf('map-marker-barrier-steps')).toHaveStyle({ visibility: 'visible' });
    expect(anchorOf('map-marker-gradient-accessible')).toHaveStyle({ visibility: 'hidden' });
  });

  it('shows both when they are apart', () => {
    const { map } = fakeMap();
    render(<MapMarkers map={map} markers={[BARRIER, { ...CLIMB, position: [40, 20] }]} />);

    expect(anchorOf('map-marker-gradient-accessible')).toHaveStyle({ visibility: 'visible' });
  });

  it('stops following the camera once it is gone', () => {
    const { map, handlers } = fakeMap();
    const { unmount } = render(<MapMarkers map={map} markers={[BARRIER]} />);
    expect(handlers.get('move')?.size).toBe(1);

    unmount();
    expect(handlers.get('move')?.size).toBe(0);
  });

  it('draws nothing without a map, a projection or anything to mark', () => {
    const { container, rerender } = render(<MapMarkers map={null} markers={[BARRIER]} />);
    expect(container).toBeEmptyDOMElement();

    rerender(<MapMarkers map={fakeMap().map} markers={[]} />);
    expect(container).toBeEmptyDOMElement();

    rerender(<MapMarkers map={{} as MapInstance} markers={[BARRIER]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('is hidden from assistive technology, which hears it in the panel', () => {
    render(<MapMarkers map={fakeMap().map} markers={[BARRIER]} />);
    expect(screen.getByTestId('map-evidence')).toHaveAttribute('aria-hidden', 'true');
  });
});
