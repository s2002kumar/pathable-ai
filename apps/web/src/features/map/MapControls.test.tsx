/**
 * The map's own controls. Every one does something real — zoom, re-frame,
 * north, or switch one of PathAble's three overlays — and the design's buttons
 * for layers the product does not have are simply not drawn.
 */
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ALL_LAYERS, type ControlsLayout, MapControls } from './MapControls';
import type { MapInstance } from './useMapLibre';

function fakeMap() {
  return {
    zoomIn: vi.fn(),
    zoomOut: vi.fn(),
    resetNorth: vi.fn(),
  } as unknown as MapInstance & {
    zoomIn: ReturnType<typeof vi.fn>;
    zoomOut: ReturnType<typeof vi.fn>;
    resetNorth: ReturnType<typeof vi.fn>;
  };
}

function renderControls(layout: ControlsLayout, overrides: Record<string, unknown> = {}) {
  const map = fakeMap();
  const onLayersChange = vi.fn();
  const onFit = vi.fn();
  render(
    <MapControls
      map={map}
      layout={layout}
      layers={ALL_LAYERS}
      onLayersChange={onLayersChange}
      onFit={onFit}
      {...overrides}
    />,
  );
  return { map, onLayersChange, onFit };
}

describe('map controls', () => {
  it('zooms, re-frames and turns north on the map itself', async () => {
    const user = userEvent.setup();
    const { map, onFit } = renderControls('plan');

    await user.click(screen.getByTestId('zoom-in'));
    await user.click(screen.getByTestId('zoom-out'));
    await user.click(screen.getByTestId('reset-north'));
    await user.click(screen.getByTestId('fit-routes'));

    expect(map.zoomIn).toHaveBeenCalledOnce();
    expect(map.zoomOut).toHaveBeenCalledOnce();
    expect(map.resetNorth).toHaveBeenCalledOnce();
    expect(onFit).toHaveBeenCalledOnce();
  });

  it('offers nothing it cannot do before the map exists', () => {
    render(
      <MapControls map={null} layout="no-route" layers={ALL_LAYERS} onLayersChange={() => {}} />,
    );

    for (const id of ['zoom-in', 'zoom-out', 'reset-north', 'fit-routes']) {
      expect(screen.getByTestId(id)).toBeDisabled();
    }
  });

  it('switches only PathAble’s own overlays, from a menu that closes like one', async () => {
    const user = userEvent.setup();
    const { onLayersChange } = renderControls('compare');

    const toggle = screen.getByTestId('map-layers');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    const menu = screen.getByRole('group', { name: 'Show on map' });
    expect(
      within(menu)
        .getAllByRole('checkbox')
        .map((box) => box.parentElement?.textContent),
    ).toEqual(['Evidence labels', 'Recorded stairways', 'Shortest walking route']);
    // No satellite, terrain or traffic: the product has none of them.
    expect(menu).not.toHaveTextContent(/satellite|terrain|traffic|elevation/i);

    await user.click(screen.getByTestId('layer-shortest'));
    expect(onLayersChange).toHaveBeenCalledWith({ ...ALL_LAYERS, shortest: false });

    await user.keyboard('{Escape}');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await user.click(toggle);
    await user.click(document.body);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  it('turns the evidence labels off and on as a pressed button', async () => {
    const user = userEvent.setup();
    const { onLayersChange } = renderControls('plan');

    const labels = screen.getByTestId('toggle-evidence-labels');
    expect(labels).toHaveAttribute('aria-pressed', 'true');
    expect(labels).toHaveTextContent('Route Evidence');
    await user.click(labels);
    expect(onLayersChange).toHaveBeenCalledWith({ ...ALL_LAYERS, evidence: false });
  });

  it('arranges the same controls for each state of the design', () => {
    const { unmount } = render(
      <MapControls
        map={fakeMap()}
        layout="no-route"
        layers={ALL_LAYERS}
        onLayersChange={() => {}}
      />,
    );
    expect(screen.getByTestId('toggle-evidence-labels')).toHaveTextContent('Evidence Overlay');
    unmount();

    const evidence = render(
      <MapControls
        map={fakeMap()}
        layout="evidence"
        layers={ALL_LAYERS}
        onLayersChange={() => {}}
      />,
    );
    // The evidence view keys its two line styles in words.
    expect(screen.getByTestId('map-controls')).toHaveTextContent(
      /Map key: Recorded\s*Not recorded/,
    );
    expect(screen.getByTestId('map-layers')).toHaveAccessibleName('Layers');
    evidence.unmount();

    render(
      <MapControls map={fakeMap()} layout="phone" layers={ALL_LAYERS} onLayersChange={() => {}} />,
    );
    expect(screen.getByTestId('toggle-evidence-labels')).toHaveAccessibleName('Evidence labels');
    expect(screen.queryByTestId('zoom-in')).not.toBeInTheDocument();
  });
});
