import { readFileSync } from 'node:fs';
import path from 'node:path';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { VERIFIED_ROUTE } from '@/features/landing/verified-route';
import { legacyPlannerUrl } from '@/features/routing/legacy-url';
import HomePage from './page';

// `redirect` ends a server render by throwing; the test only needs to see
// where it was sent.
vi.mock('next/navigation', () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`redirect:${url}`);
  }),
}));

/** `HomePage` is an async server component; await it rather than render the promise. */
function homePage(searchParams: Record<string, string | string[] | undefined> = {}) {
  return HomePage({ searchParams: Promise.resolve(searchParams) });
}

describe('the landing page', () => {
  it('says what the product does, and sends the reader to the planner', async () => {
    render(await homePage());

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      /Routes that account for what you can actually traverse/,
    );
    expect(screen.getByTestId('hero-explore')).toHaveAttribute('href', '/planner');
    expect(screen.getByTestId('header-explore')).toHaveAttribute('href', '/planner');
  });

  it('shows the verified example as the routing API recorded it, and says when', async () => {
    // The landing page is static and cannot ask the API, so every figure on it
    // comes from one recorded response — dated, with the dataset it ran on.
    render(await homePage());

    const readout = screen.getByTestId('hero-readout');
    expect(readout).toHaveTextContent('Shortest walking route287.4 m4 recorded stairways');
    expect(readout).toHaveTextContent('Wheelchair profile route354.1 m0 recorded stairways');
    expect(readout).toHaveTextContent(
      `The wheelchair route is ${VERIFIED_ROUTE.extraDistanceM.toFixed(1)} m longer`,
    );
    expect(readout).toHaveTextContent(`avoids all ${VERIFIED_ROUTE.standard.stairways} stairways`);
    expect(readout).toHaveTextContent('Missing accessibility data remains unknown.');
    expect(readout).toHaveTextContent(
      `Recorded from the routing API on ${VERIFIED_ROUTE.recordedOn}`,
    );
    expect(readout).toHaveTextContent(`dataset ${VERIFIED_ROUTE.datasetChecksum.slice(0, 8)}`);
    // And a way to compute it live rather than take the record's word for it.
    expect(
      within(readout).getByRole('link', { name: 'Compute this journey live' }),
    ).toHaveAttribute('href', '/planner?example=campus-library-to-student-life');
  });

  it('draws the journey as one labelled image, not a second unreadable copy', async () => {
    // Everything on the stage is also in the text; to assistive technology it
    // is one picture with a description, not dozens of loose map labels.
    render(await homePage());

    const stage = screen.getByRole('img', { name: /Drawing of the verified journey/ });
    expect(stage).toHaveAccessibleName(/takes 4 recorded stairways/);
    expect(stage).toHaveAccessibleName(/66\.7 m longer/);
    expect(stage).toHaveAttribute('data-testid', 'hero-visual');
    // The backdrop is the generated network file, not a third-party tile.
    expect(stage.querySelector('image')).toHaveAttribute('href', '/landing/campus-paths.svg');
  });

  it('tells the story in four steps, every figure from the record', async () => {
    render(await homePage());

    const story = screen.getByRole('region', { name: 'One journey, taken apart.' });
    const steps = within(story).getAllByRole('heading', { level: 3 });
    expect(steps.map((step) => step.textContent)).toEqual([
      'Both routes leave the library together.',
      'The shortest route takes 4 recorded stairways.',
      'The wheelchair profile rules every one of them out.',
      'What nobody recorded stays unknown.',
    ]);
    expect(story).toHaveTextContent('16 steps across 2 of them');
    expect(story).toHaveTextContent('no recorded step count — unknown, not zero');
    expect(story).toHaveTextContent('never relaxes a hard limit');
    expect(story).toHaveTextContent('No surface is recorded on 65 m of the wheelchair route');
    expect(story).toHaveTextContent('a missing tag is never read as a clear path');
    // The stage starts on the whole answer, so nothing depends on a script.
    expect(document.querySelector('[data-story-root]')).toHaveAttribute('data-step', 'overview');
  });

  it('offers four evidence lenses as a real radio group, each with its own figures', async () => {
    render(await homePage());

    const group = screen.getByRole('group', { name: 'Choose a lens' });
    const radios = within(group).getAllByRole('radio');
    expect(radios.map((radio) => radio.getAttribute('value'))).toEqual([
      'stairs',
      'gradient',
      'surface',
      'width',
    ]);
    expect(radios[0]).toBeChecked();

    const panel = (lens: string) =>
      document.querySelector<HTMLElement>(`[data-lens-panel="${lens}"]`) as HTMLElement;
    expect(panel('stairs')).toHaveTextContent(
      '4 recorded stairways · 16 steps across 2, no step count on 2',
    );
    expect(panel('gradient')).toHaveTextContent('Estimated on 61% · steepest 3.4% up · 4.6% down');
    expect(panel('gradient')).toHaveTextContent('never flat');
    expect(panel('surface')).toHaveTextContent('Recorded on 82% · not recorded on 65 m');
    expect(panel('surface')).toHaveTextContent('Recorded on 71% · not recorded on 84 m');
    expect(panel('width')).toHaveTextContent('Neither recorded on any segment');

    // The strips draw one cell per recorded segment, coloured from the record.
    const cells = (route: string, attribute: string, value: string) =>
      document.querySelectorAll(`[data-route="${route}"] [data-${attribute}="${value}"]`).length;
    expect(cells('standard', 'stairs', 'yes')).toBe(VERIFIED_ROUTE.standard.stairways);
    expect(cells('accessible', 'stairs', 'yes')).toBe(0);
    expect(document.querySelectorAll('[data-route="accessible"] > span')).toHaveLength(
      VERIFIED_ROUTE.accessible.segments.length,
    );
    expect(cells('accessible', 'surface', 'missing')).toBe(
      VERIFIED_ROUTE.accessible.segments.filter((segment) => segment.surface === null).length,
    );
  });

  it('quotes no engineering figure the claims ledger does not hold', async () => {
    // The landing page's measurements are the ledger's, with its conditions.
    // A number added here that the ledger does not contain is a claim nobody
    // has checked, so this fails until the ledger has it too.
    render(await homePage());

    const ledger = readFileSync(path.resolve(process.cwd(), '../../docs/CLAIMS_LEDGER.md'), 'utf8');
    const section = screen.getByRole('region', { name: 'Measured, with the conditions attached.' });
    const figures = (section.textContent ?? '').match(/\d+(?:,\d{3})*(?:\.\d+)?/g) ?? [];
    expect(figures.length).toBeGreaterThan(15);
    const missing = [...new Set(figures)].filter((figure) => !ledger.includes(figure));
    expect(missing).toEqual([]);
    expect(section).toHaveTextContent('one laptop');
    expect(section).toHaveTextContent('A* is not faster here');
  });

  it('records a response in which no model took part', () => {
    expect(VERIFIED_ROUTE.mlPredictionsUsed).toBe(false);
  });

  it('makes no safety, compliance or machine-learning claim', async () => {
    render(await homePage());

    const text = document.body.textContent ?? '';
    expect(text).not.toMatch(/barrier-free|AODA|\bAI\b|artificial intelligence/i);
    expect(text).not.toMatch(/guaranteed (safe|accessible)|certified accessible/i);
    // Nothing is deployed, and the page neither says nor implies otherwise.
    expect(text).toContain('Local demo · Not deployed');
    expect(text).not.toMatch(/live demo|deployment pending|try it (live|here)/i);
    // Machine learning is named only to say that none affects a route.
    for (const match of text.matchAll(/machine-learning|machine learning/gi)) {
      const around = text.slice(Math.max(0, (match.index ?? 0) - 40), (match.index ?? 0) + 60);
      expect(around).toMatch(/\bNo machine-learning prediction currently affects\b/);
    }
  });

  it('credits OpenStreetMap and the elevation licence', async () => {
    render(await homePage());

    const footer = screen.getByTestId('landing-footer');
    expect(footer).toHaveTextContent('OpenStreetMap contributors');
    expect(footer).toHaveTextContent('ODbL 1.0');
    expect(footer).toHaveTextContent('Open Government Licence – Canada');
    // Source-visible, all rights reserved — never "open source".
    expect(footer).toHaveTextContent('All rights reserved.');
    expect(footer).not.toHaveTextContent(/open[- ]source/i);
  });
});

describe('the planner’s old address', () => {
  it('sends a recorded `/?example=` link on to the planner, query intact', async () => {
    await expect(
      homePage({ example: 'campus-library-to-student-life', utm_source: 'readme' }),
    ).rejects.toThrow('redirect:/planner?example=campus-library-to-student-life&utm_source=readme');
  });

  it('serves the landing page to every other request for /', async () => {
    render(await homePage({ utm_source: 'readme' }));

    expect(screen.getByTestId('hero-explore')).toBeInTheDocument();
  });

  it('keeps repeated parameters and drops none', () => {
    expect(legacyPlannerUrl({ example: 'x', tag: ['a', 'b'], empty: undefined })).toBe(
      '/planner?example=x&tag=a&tag=b',
    );
    expect(legacyPlannerUrl(undefined)).toBeNull();
    expect(legacyPlannerUrl({})).toBeNull();
  });
});
