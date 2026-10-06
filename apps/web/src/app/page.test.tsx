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

    const visual = screen.getByTestId('hero-visual');
    expect(visual).toHaveTextContent(
      `The wheelchair route is ${VERIFIED_ROUTE.extraDistanceM.toFixed(1)} m longer`,
    );
    expect(visual).toHaveTextContent(`avoids all ${VERIFIED_ROUTE.standard.stairways} stairways`);
    expect(visual).toHaveTextContent('Missing accessibility data remains unknown.');
    expect(visual).toHaveTextContent(
      `Recorded from the routing API on ${VERIFIED_ROUTE.recordedOn}`,
    );
    expect(visual).toHaveTextContent(`dataset ${VERIFIED_ROUTE.datasetChecksum.slice(0, 8)}`);
    // And a way to compute it live rather than take the record's word for it.
    expect(within(visual).getByRole('link', { name: /\/planner\?example=/ })).toHaveAttribute(
      'href',
      '/planner?example=campus-library-to-student-life',
    );
  });

  it('records a response in which no model took part', () => {
    expect(VERIFIED_ROUTE.mlPredictionsUsed).toBe(false);
  });

  it('makes no safety, compliance or machine-learning claim', async () => {
    render(await homePage());

    const text = document.body.textContent ?? '';
    expect(text).not.toMatch(/barrier-free|AODA|\bAI\b|artificial intelligence/i);
    expect(text).not.toMatch(/guaranteed (safe|accessible)|certified accessible/i);
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
