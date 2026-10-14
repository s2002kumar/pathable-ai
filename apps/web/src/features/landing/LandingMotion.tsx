'use client';

import { useEffect } from 'react';

/** The band of the viewport a story step must cross to become the current one. */
const STEP_BAND = {
  // Side by side: the middle tenth of the screen.
  wide: '-45% 0px -45% 0px',
  // Stacked under a sticky stage: the middle of what the stage leaves visible.
  stacked: '-62% 0px -28% 0px',
} as const;

/** Where the stage sits beside the story rather than above it (Landing.module.css). */
const SIDE_BY_SIDE = '(min-width: 64rem) and (min-height: 40rem)';

/**
 * The landing page's only script, and nothing on the page depends on it.
 *
 * It does two things. It tells the stage which story step is being read, by
 * setting `data-step` on the story root as each step crosses the middle of
 * the viewport — ordinary scrolling, never hijacked. And it arms the
 * once-only section reveals: content is visible by default and is hidden
 * only after this runs, and only once it is known to be off screen, so with
 * no script, or before hydration, nothing is ever invisible.
 *
 * Reduced motion turns the reveals off entirely; the stage still follows
 * the story, but its CSS makes every change instant.
 */
export function LandingMotion() {
  useEffect(() => {
    const cleanups: (() => void)[] = [];
    const root = document.querySelector<HTMLElement>('[data-story-root]');

    if (root) {
      const steps = Array.from(root.querySelectorAll<HTMLElement>('[data-story-step]'));
      const wide = window.matchMedia(SIDE_BY_SIDE);
      let observer: IntersectionObserver | undefined;

      const observe = () => {
        observer?.disconnect();
        observer = new IntersectionObserver(
          (entries) => {
            for (const entry of entries) {
              const step = (entry.target as HTMLElement).dataset.storyStep;
              if (entry.isIntersecting && step) root.dataset.step = step;
            }
          },
          { rootMargin: wide.matches ? STEP_BAND.wide : STEP_BAND.stacked },
        );
        steps.forEach((step) => observer?.observe(step));
      };

      observe();
      wide.addEventListener('change', observe);
      cleanups.push(() => {
        observer?.disconnect();
        wide.removeEventListener('change', observe);
        root.dataset.step = 'overview';
      });
    }

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!reduced) {
      const html = document.documentElement;
      // The observer's first report says what is on screen, without forcing a
      // layout: asking each block for its position here laid out the whole
      // page at once, sections the browser was deliberately skipping
      // included, in one long task during hydration. Something reported off
      // screen can be hidden without anyone seeing it go; something on screen
      // is never touched.
      const reveal = new IntersectionObserver((entries) => {
        for (const entry of entries) {
          const element = entry.target as HTMLElement;
          if (entry.isIntersecting) {
            element.dataset.reveal = 'shown';
            reveal.unobserve(element);
          } else if (element.dataset.reveal === '') {
            element.dataset.reveal = 'pending';
          }
        }
      });
      html.dataset.revealArmed = '';
      document
        .querySelectorAll<HTMLElement>('[data-reveal]')
        .forEach((element) => reveal.observe(element));
      cleanups.push(() => {
        reveal.disconnect();
        delete html.dataset.revealArmed;
      });
    }

    return () => cleanups.forEach((cleanup) => cleanup());
  }, []);

  return null;
}
