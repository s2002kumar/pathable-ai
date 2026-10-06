/**
 * The surfaces around the panel: the phone's comparison sheet (17:2865), the
 * desktop evidence dock (9:2177), the data-gap dock (17:3901) and the details
 * sheet. Each states the response's facts with their evidence labels, keeps
 * gaps as gaps, and claims nothing the response does not.
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { Route } from '@pathable/contracts';
import { comparison, route, segment, shortestSegments } from '@/test/route-fixtures';
import { EvidenceDock, GapDock } from './EvidenceDock';
import { RouteDetails } from './RouteDetails';
import { RoutePlanner, type RoutePlannerProps } from './RoutePlanner';
import { NO_RULES, type ProfileRules } from './route-facts';
import { CAMPUS_EXAMPLE } from './verified-example';

const ORIGIN = {
  position: { longitude: -80.54, latitude: 43.47 },
  label: 'Davis Centre library',
  source: 'search' as const,
};
const DESTINATION = {
  position: { longitude: -80.534, latitude: 43.47 },
  label: 'Student Life Centre',
  source: 'search' as const,
};
const STEP_FREE: ProfileRules = { excludesSteps: true, uphillLimit: null, prefersUnder: 8 };

const pair = comparison();
const accessible = pair.accessible_route as Route;
const shortest = pair.standard_route as Route;

function renderPhone(overrides: Partial<RoutePlannerProps> = {}) {
  const props: RoutePlannerProps = {
    layout: 'compare',
    phone: true,
    points: { origin: ORIGIN, destination: DESTINATION },
    profileKey: 'wheelchair',
    state: { status: 'success', comparison: pair },
    apiBaseUrl: 'http://api.test',
    region: 'waterloo',
    regionName: 'Waterloo, Ontario',
    example: CAMPUS_EXAMPLE,
    exampleActive: false,
    canCompare: true,
    pendingEdits: false,
    pickTarget: null,
    rules: STEP_FREE,
    selectedRoute: 'accessible',
    onSelectRoute: vi.fn(),
    onRouteDetails: vi.fn(),
    onOpenEvidence: vi.fn(),
    onRunExample: vi.fn(),
    onProfileChange: vi.fn(),
    onCompare: vi.fn(),
    onClearAll: vi.fn(),
    onSwapPoints: vi.fn(),
    onRetry: vi.fn(),
    onSelectPlace: vi.fn(),
    onPickOnMap: vi.fn(),
    fetchImpl: vi.fn() as unknown as typeof fetch,
    ...overrides,
  };
  return { ...render(<RoutePlanner {...props} />), props };
}

describe('the phone’s comparison sheet', () => {
  it('names the journey and the profile, and both routes as one radio group', () => {
    renderPhone();

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Wheelchair profile');
    const group = screen.getByRole('radiogroup', { name: /route drawn in front/i });
    const [mine, theirs] = within(group).getAllByRole('radio');
    expect(mine).toHaveAccessibleName('Wheelchair route');
    expect(mine).toHaveAttribute('aria-checked', 'true');
    expect(theirs).toHaveAccessibleName('Shortest pedestrian route');
    expect(theirs).toHaveAttribute('tabindex', '-1');
    expect(screen.getByText('Davis Centre library')).toBeInTheDocument();
    expect(screen.getByText('Student Life Centre')).toBeInTheDocument();
  });

  it('states the detour to a tenth of a metre, from the response', () => {
    renderPhone();

    // 709 m against 483 m in the fixture: +226.0 m, +47%.
    expect(screen.getByTestId('difference-extra')).toHaveTextContent(
      '+226.0 m • (+47%) vs shortest route',
    );
  });

  it('says the shortest route breaks the profile, with its steps as a floor', () => {
    renderPhone();

    const blocked = screen.getByTestId('route-blocked');
    expect(blocked).toHaveTextContent('1 recorded stairway');
    expect(blocked).toHaveTextContent('14 recorded steps');
    expect(screen.getByTestId('difference-shortest')).toHaveTextContent(
      'Incompatible with Wheelchair profile',
    );
  });

  it('never prints "0 steps" for stairways nobody counted', () => {
    const uncounted = route(
      shortestSegments().map((item) =>
        item.steps === 'yes' ? { ...item, step_count: null } : item,
      ),
      { profile: 'standard' },
    );
    renderPhone({
      state: { status: 'success', comparison: comparison({ standard_route: uncounted }) },
    });

    const blocked = screen.getByTestId('route-blocked');
    expect(blocked).toHaveTextContent('Step count not recorded');
    expect(blocked).not.toHaveTextContent(/\b0 (recorded )?steps\b/);
  });

  it('labels every category with where it came from, gaps as not recorded', () => {
    renderPhone({ rules: { ...STEP_FREE, uphillLimit: 5 } });

    expect(screen.getByTestId('mobile-stairs')).toHaveTextContent('Recorded · OSM');
    expect(screen.getByTestId('mobile-stairs')).toHaveTextContent('Your profile rule');
    expect(screen.getByTestId('mobile-grade')).toHaveTextContent('Recorded · OSM');
    expect(screen.getByTestId('mobile-grade')).toHaveTextContent('≤ 5.0% limit');
    expect(screen.getByTestId('mobile-grade')).toHaveTextContent('Peak 4.0%');
    expect(screen.getByTestId('mobile-grade')).toHaveTextContent('1.2% on shortest');
    // Every surface on the profile's route is recorded in the fixture.
    expect(screen.getByTestId('mobile-surface')).toHaveTextContent('100% recorded');
    expect(screen.getByTestId('mobile-surface')).not.toHaveTextContent('Not recorded');
  });

  it('marks a surface the response did not report as not recorded, not as recorded', () => {
    renderPhone({
      state: {
        status: 'success',
        comparison: comparison({
          accessible_route: { ...accessible, evidence_coverage: undefined } as unknown as Route,
        }),
      },
    });

    const surface = screen.getByTestId('mobile-surface');
    expect(surface).toHaveTextContent('Not reported');
    expect(surface).toHaveTextContent('Not recorded');
    expect(surface).not.toHaveTextContent('Recorded · OSM');
  });

  it('says a route with no climb on record has none, rather than "none" as a value', () => {
    renderPhone({
      state: {
        status: 'success',
        comparison: comparison({
          accessible_route: {
            ...accessible,
            gradient: {
              steepest_uphill: null,
              steepest_downhill: null,
              recorded_fraction: 0,
              estimated_fraction: 0,
              unknown_fraction: 1,
            },
          },
        }),
      },
    });

    expect(screen.getByTestId('mobile-grade')).toHaveTextContent('No climb on record');
    expect(screen.getByTestId('difference-accessible')).toHaveTextContent(
      /Not recorded\s*Grade source/,
    );
  });

  it('moves the choice with the arrow keys, and opens the record two ways', async () => {
    const user = userEvent.setup();
    const { props } = renderPhone();

    fireEvent.keyDown(screen.getByTestId('difference-accessible'), { key: 'ArrowRight' });
    expect(props.onSelectRoute).toHaveBeenCalledWith('standard');
    expect(screen.getByTestId('difference-shortest')).toHaveFocus();
    fireEvent.keyDown(screen.getByTestId('difference-shortest'), { key: 'Tab' });
    expect(props.onSelectRoute).toHaveBeenCalledTimes(1);

    await user.click(screen.getByTestId('open-route-details'));
    expect(props.onRouteDetails).toHaveBeenCalledOnce();
    await user.click(screen.getByTestId('view-evidence'));
    expect(props.onOpenEvidence).toHaveBeenCalledOnce();
  });

  it('keeps the journey and profile controls behind one disclosure, with a way to start again', async () => {
    const user = userEvent.setup();
    const onEditorToggle = vi.fn();
    const { props, rerender } = renderPhone({ onEditorToggle });

    const editor = screen.getByTestId('mobile-edit');
    expect(editor).not.toHaveAttribute('open');
    await user.click(within(editor).getByText('Edit journey or profile'));
    expect(editor).toHaveAttribute('open');
    // Reported upward, because the sheet re-mounts while a change re-runs.
    expect(onEditorToggle).toHaveBeenLastCalledWith(true);
    expect(within(editor).getByLabelText('Origin')).toHaveValue('Davis Centre library');

    await user.click(within(editor).getByTestId('clear-journey'));
    expect(props.onClearAll).toHaveBeenCalledOnce();

    // Whatever was open when the sheet re-mounts opens again.
    rerender(<RoutePlanner {...props} editorOpen />);
    expect(screen.getByTestId('mobile-edit')).toHaveAttribute('open');
  });

  it('draws the glyph of the profile the answer was asked with', () => {
    const { container } = renderPhone({ profileKey: 'stroller', profileName: 'Stroller or pram' });

    const glyph = container.querySelector('h1 .icon') as HTMLElement;
    expect(glyph.style.maskImage).toContain('profile-stroller');
  });
});

describe('the evidence dock', () => {
  it('compares the four categories with the shortest route, each with its label', async () => {
    const user = userEvent.setup();
    const onRouteDetails = vi.fn();
    const onViewEvidence = vi.fn();
    render(
      <EvidenceDock
        route={accessible}
        other={shortest}
        rules={STEP_FREE}
        profileName="Wheelchair"
        onRouteDetails={onRouteDetails}
        onViewEvidence={onViewEvidence}
      />,
    );

    expect(screen.getByTestId('evidence-dock')).toHaveTextContent(
      'Comparing the wheelchair route with the shortest pedestrian route',
    );
    expect(screen.getByTestId('dock-stairs')).toHaveTextContent('0recorded stairways');
    expect(screen.getByTestId('dock-stairs')).toHaveTextContent('Your profile rule');
    expect(screen.getByTestId('dock-grade')).toHaveTextContent('Recorded · OSM');
    expect(screen.getByTestId('dock-grade')).toHaveTextContent('vs. 1.2% on shortest path.');
    expect(screen.getByTestId('dock-crossings')).toHaveTextContent('Kerb type recorded at each');
    // The legend names the four kinds of evidence, and nothing scores them.
    expect(screen.getByTestId('evidence-dock')).toHaveTextContent(
      /Recorded · OSM.*Derived · HRDEM.*Not recorded.*Your profile rule/,
    );
    expect(screen.getByTestId('evidence-dock')).not.toHaveTextContent(/confidence|score/i);

    await user.click(screen.getByTestId('open-route-details'));
    await user.click(screen.getByTestId('view-evidence'));
    expect(onRouteDetails).toHaveBeenCalledOnce();
    expect(onViewEvidence).toHaveBeenCalledOnce();
  });
});

describe('the data-gap dock', () => {
  const gappy = route(
    [
      segment({ edge_identity: 'a', is_crossing: true, kerb: 'unknown' }),
      segment({ edge_identity: 'b', surface: null, surface_class: 'unknown' }),
      segment({ edge_identity: 'c' }),
    ],
    { evidence_coverage: { surface: 0.33, smoothness: 1, gradient: 0, width: 1, kerb: 1 } },
  );

  it('states each gap as a gap, and never infers what is missing', () => {
    render(<GapDock route={gappy} rules={STEP_FREE} onViewEvidence={() => {}} />);

    expect(screen.getByTestId('gap-crossings')).toHaveAttribute('data-gap', 'true');
    expect(screen.getByTestId('gap-crossings')).toHaveTextContent(
      'PathAble does not infer a ramp.',
    );
    expect(screen.getByTestId('gap-surface')).toHaveTextContent('Surface evidence is incomplete');
    expect(screen.getByTestId('gap-surface')).toHaveTextContent('Missing stays unknown');
    expect(screen.getByTestId('gap-stairs')).toHaveTextContent('OSM records no stairways');
    expect(screen.getByTestId('gap-stairs')).toHaveTextContent('Your profile rule');
    expect(screen.getByTestId('gap-dock')).toHaveTextContent('no aggregate confidence score');
  });

  it('reports a climb above the traveller’s limit as above it, never with a tick', () => {
    render(
      <GapDock
        route={accessible}
        rules={{ ...NO_RULES, uphillLimit: 3.5 }}
        onViewEvidence={() => {}}
      />,
    );

    const grade = screen.getByTestId('gap-grade');
    expect(grade).toHaveTextContent('Grade recorded in OpenStreetMap');
    expect(grade).toHaveTextContent('Above your 3.5% limit');
    expect(grade.querySelector('[data-tone="barrier"]')).not.toBeNull();
  });

  it('names a derived grade as derived, and a missing one as missing', () => {
    const { unmount } = render(
      <GapDock route={shortest} rules={NO_RULES} onViewEvidence={() => {}} />,
    );
    expect(screen.getByTestId('gap-grade')).toHaveTextContent('Grade derived from HRDEM');
    expect(screen.getByTestId('gap-crossings')).toHaveTextContent('No mapped crossings');
    unmount();

    const none = route([segment()], {
      gradient: {
        steepest_uphill: null,
        steepest_downhill: null,
        recorded_fraction: 0,
        estimated_fraction: 0,
        unknown_fraction: 1,
      },
      evidence_coverage: undefined,
    } as never);
    render(<GapDock route={none} rules={NO_RULES} onViewEvidence={() => {}} />);
    expect(screen.getByTestId('gap-grade')).toHaveTextContent('No gradient on record');
    expect(screen.getByTestId('gap-surface')).toHaveTextContent('Surface not reported');
  });

  it('says a complete record is complete without calling the route passable', () => {
    render(<GapDock route={accessible} rules={NO_RULES} onViewEvidence={() => {}} />);

    expect(screen.getByTestId('gap-crossings')).toHaveTextContent(
      'Kerb recorded at every crossing',
    );
    expect(screen.getByTestId('gap-surface')).toHaveTextContent('Surface recorded along the route');
    expect(screen.getByTestId('gap-dock')).not.toHaveTextContent(/passable|safe|accessible route/i);
  });
});

describe('the details sheet', () => {
  function renderSheet(overrides: Partial<Parameters<typeof RouteDetails>[0]> = {}) {
    const onClose = vi.fn();
    const onSelectRoute = vi.fn();
    const result = render(
      <>
        <button type="button">Opener</button>
        <RouteDetails
          open
          section="details"
          comparison={pair}
          selectedRoute="accessible"
          onSelectRoute={onSelectRoute}
          journeySummary="Davis Centre library to Student Life Centre"
          profileName={null}
          uphillLimit={null}
          onClose={onClose}
          {...overrides}
        />
      </>,
    );
    return { ...result, onClose, onSelectRoute };
  }

  it('renders nothing while closed or before there is an answer', () => {
    const { container, rerender } = render(
      <RouteDetails
        open={false}
        section="details"
        comparison={pair}
        selectedRoute="accessible"
        onSelectRoute={() => {}}
        journeySummary={null}
        profileName={null}
        uphillLimit={null}
        onClose={() => {}}
      />,
    );
    expect(container).toBeEmptyDOMElement();

    rerender(
      <RouteDetails
        open
        section="details"
        comparison={null}
        selectedRoute="accessible"
        onSelectRoute={() => {}}
        journeySummary={null}
        profileName={null}
        uphillLimit={null}
        onClose={() => {}}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('is a modal dialog that takes focus and states both routes itself', () => {
    renderSheet();

    const dialog = screen.getByRole('dialog', { name: 'Route details' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByTestId('close-route-details')).toHaveFocus();
    // Modal, so the panel's cards are out of reach: the sheet has its own.
    expect(within(dialog).getByTestId('difference-accessible')).toBeInTheDocument();
    expect(within(dialog).getByTestId('difference-shortest')).toBeInTheDocument();
    expect(within(dialog).getByTestId('journey-summary')).toHaveTextContent(
      'Davis Centre library to Student Life Centre',
    );
  });

  it('chooses a route on the map from inside the sheet', async () => {
    const user = userEvent.setup();
    const { onSelectRoute } = renderSheet();

    await user.click(within(screen.getByRole('dialog')).getByTestId('difference-shortest'));
    expect(onSelectRoute).toHaveBeenCalledWith('standard');
  });

  it('names a custom-limit answer by its preset, with the limit beside it', () => {
    renderSheet({
      comparison: comparison({ profile: 'custom', profile_display_name: 'Custom' }),
      profileName: 'Wheelchair',
      uphillLimit: 4.5,
    });

    const summary = screen.getByTestId('journey-summary');
    expect(summary).toHaveTextContent('Wheelchair');
    expect(summary).toHaveTextContent('Custom uphill limit · 4.5%');
    expect(screen.getByRole('dialog')).not.toHaveTextContent(/custom route/i);
  });

  it('closes on Escape, on the backdrop, and not on a click inside', async () => {
    const user = userEvent.setup();
    const { onClose } = renderSheet();

    await user.click(screen.getByRole('dialog'));
    expect(onClose).not.toHaveBeenCalled();
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
    await user.click(screen.getByTestId('route-details-backdrop'));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('keeps Tab inside the sheet while it is open', () => {
    renderSheet();

    const dialog = screen.getByRole('dialog');
    const focusable = dialog.querySelectorAll<HTMLElement>(
      'button, [href], summary, input, [tabindex]:not([tabindex="-1"])',
    );
    const first = focusable[0]!;
    const last = focusable[focusable.length - 1]!;

    last.focus();
    fireEvent.keyDown(dialog, { key: 'Tab' });
    expect(first).toHaveFocus();
    fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true });
    expect(last).toHaveFocus();
  });

  it('opens at the evidence when asked for it, and gives focus back on close', () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    const opener = () => screen.getByRole('button', { name: 'Opener' });
    const props = {
      section: 'evidence' as const,
      comparison: pair,
      selectedRoute: 'accessible' as const,
      onSelectRoute: () => {},
      journeySummary: null,
      profileName: null,
      uphillLimit: null,
      onClose: () => {},
    };
    const { rerender } = render(
      <>
        <button type="button">Opener</button>
        <RouteDetails open={false} {...props} />
      </>,
    );
    opener().focus();

    rerender(
      <>
        <button type="button">Opener</button>
        <RouteDetails open {...props} />
      </>,
    );
    expect(screen.getByRole('dialog', { name: 'Route evidence' })).toBeInTheDocument();
    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'start' });

    rerender(
      <>
        <button type="button">Opener</button>
        <RouteDetails open={false} {...props} />
      </>,
    );
    expect(opener()).toHaveFocus();
  });
});
