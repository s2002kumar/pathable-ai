import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LandingMotion } from './LandingMotion';

type Callback = (entries: Partial<IntersectionObserverEntry>[]) => void;

/** An IntersectionObserver the test drives by hand. */
class ObserverDouble {
  static all: ObserverDouble[] = [];
  readonly observed = new Set<Element>();
  constructor(
    readonly callback: Callback,
    readonly options: IntersectionObserverInit = {},
  ) {
    ObserverDouble.all.push(this);
  }
  observe(element: Element) {
    this.observed.add(element);
  }
  unobserve(element: Element) {
    this.observed.delete(element);
  }
  disconnect() {
    this.observed.clear();
  }
  fire(element: Element, isIntersecting = true) {
    act(() => this.callback([{ target: element, isIntersecting }]));
  }
}

function matchMedia(matches: Record<string, boolean>) {
  return (query: string) => ({
    matches: matches[query] ?? false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  });
}

/** A story root with two steps, and two revealable blocks: one on screen, one below. */
function page() {
  document.body.innerHTML = `
    <div data-story-root data-step="overview">
      <section data-story-step="overview"></section>
      <li data-story-step="stairs"></li>
    </div>
    <div id="above" data-reveal=""></div>
    <div id="below" data-reveal=""></div>`;
}

beforeEach(() => {
  ObserverDouble.all = [];
  vi.stubGlobal('IntersectionObserver', ObserverDouble);
});

afterEach(() => {
  delete document.documentElement.dataset.revealArmed;
  document.body.innerHTML = '';
});

describe('LandingMotion', () => {
  it('tells the stage which story step is being read', () => {
    page();
    vi.stubGlobal('matchMedia', matchMedia({}));
    render(<LandingMotion />);

    const root = document.querySelector<HTMLElement>('[data-story-root]')!;
    const steps = ObserverDouble.all.find((o) => o.observed.has(document.querySelector('li')!))!;
    steps.fire(document.querySelector('li')!);
    expect(root.dataset.step).toBe('stairs');

    // Leaving a step without entering another keeps the last one.
    steps.fire(document.querySelector('li')!, false);
    expect(root.dataset.step).toBe('stairs');

    steps.fire(document.querySelector('section')!);
    expect(root.dataset.step).toBe('overview');
  });

  it('watches the middle of the screen beside the stage, and lower under it', () => {
    page();
    vi.stubGlobal('matchMedia', matchMedia({ '(min-width: 64rem) and (min-height: 40rem)': true }));
    render(<LandingMotion />);
    expect(ObserverDouble.all[0]?.options.rootMargin).toBe('-45% 0px -45% 0px');
  });

  it('never hides what is already on screen, and reveals the rest once', () => {
    page();
    vi.stubGlobal('matchMedia', matchMedia({}));
    const measure = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect');
    render(<LandingMotion />);

    const above = document.getElementById('above')!;
    const below = document.getElementById('below')!;
    const reveal = ObserverDouble.all.find((o) => o.observed.has(below))!;
    expect(document.documentElement.dataset.revealArmed).toBe('');
    // Nothing is hidden before the observer has said where it is.
    expect(above.dataset.reveal).toBe('');
    expect(below.dataset.reveal).toBe('');

    reveal.fire(above, true);
    reveal.fire(below, false);
    expect(above.dataset.reveal).toBe('shown');
    expect(below.dataset.reveal).toBe('pending');

    reveal.fire(below, true);
    expect(below.dataset.reveal).toBe('shown');
    expect(reveal.observed.has(below)).toBe(false);
    // And no element was asked for its position: that forces a layout of the
    // whole page, skipped sections included (found by tracing PA-UX-05).
    expect(measure).not.toHaveBeenCalled();
  });

  it('releases every waiting block in a section the reader has scrolled past', () => {
    // Found in the browser suite: blocks in a section the browser skips can
    // go by too fast to be reported on screen, and stayed hidden above the
    // reader. The section's own box is always reported, so passing it is
    // enough.
    document.body.innerHTML = `
      <section id="evidence">
        <div id="head" data-reveal=""></div>
        <div id="kinds" data-reveal=""></div>
      </section>`;
    vi.stubGlobal('matchMedia', matchMedia({}));
    render(<LandingMotion />);
    const section = document.getElementById('evidence')!;
    const head = document.getElementById('head')!;
    const kinds = document.getElementById('kinds')!;
    const reveal = ObserverDouble.all.find((o) => o.observed.has(section))!;

    reveal.fire(head, false);
    reveal.fire(kinds, false);
    expect(kinds.dataset.reveal).toBe('pending');

    // Still below the reader: nothing changes.
    act(() =>
      reveal.callback([
        {
          target: section,
          isIntersecting: false,
          boundingClientRect: { bottom: 2400 } as DOMRect,
          rootBounds: { top: 0 } as DOMRect,
        },
      ]),
    );
    expect(kinds.dataset.reveal).toBe('pending');

    // Above the reader: everything in it is shown.
    act(() =>
      reveal.callback([
        {
          target: section,
          isIntersecting: false,
          boundingClientRect: { bottom: -40 } as DOMRect,
          rootBounds: { top: 0 } as DOMRect,
        },
      ]),
    );
    expect(head.dataset.reveal).toBe('shown');
    expect(kinds.dataset.reveal).toBe('shown');
  });

  it('does not hide a block again once it has been shown', () => {
    page();
    vi.stubGlobal('matchMedia', matchMedia({}));
    render(<LandingMotion />);
    const above = document.getElementById('above')!;
    const reveal = ObserverDouble.all.find((o) => o.observed.has(above))!;

    reveal.fire(above, true);
    reveal.fire(above, false);
    expect(above.dataset.reveal).toBe('shown');
  });

  it('hides nothing at all when the reader asks for reduced motion', () => {
    page();
    vi.stubGlobal('matchMedia', matchMedia({ '(prefers-reduced-motion: reduce)': true }));
    render(<LandingMotion />);

    expect(document.documentElement.dataset.revealArmed).toBeUndefined();
    expect(document.getElementById('below')!.dataset.reveal).toBe('');
    // Only the story observer exists; nothing watches the blocks.
    expect(ObserverDouble.all).toHaveLength(1);
  });

  it('puts everything back when the page goes away', () => {
    page();
    vi.stubGlobal('matchMedia', matchMedia({}));
    const { unmount } = render(<LandingMotion />);
    const root = document.querySelector<HTMLElement>('[data-story-root]')!;
    ObserverDouble.all[0]!.fire(document.querySelector('li')!);

    unmount();
    expect(root.dataset.step).toBe('overview');
    expect(document.documentElement.dataset.revealArmed).toBeUndefined();
  });
});
