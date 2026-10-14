import { expect, test, type Page } from '@playwright/test';
import {
  COMPARE_PATTERN,
  PLANNER,
  SCREENSHOT_DIR,
  hasHorizontalOverflow,
  stubHealthyApi,
  stubRouteComparison,
} from './fixtures';

const STORY_STEPS = ['together', 'stairs', 'rule', 'unknown'] as const;

/**
 * Wait until every time-based animation and transition has finished.
 *
 * Scroll-driven animations (the pipeline line) are excluded: one tied to the
 * scroll position reports itself as running for as long as it exists, so
 * waiting for it to stop would wait forever.
 */
async function settled(page: Page): Promise<void> {
  await page.waitForFunction(() =>
    document
      .getAnimations()
      .filter((animation) => animation.timeline === document.timeline)
      .every((animation) => animation.playState !== 'running'),
  );
}

/**
 * Scroll as a reader would until a story step's title crosses the band of the
 * viewport the page watches (LandingMotion.tsx), then let the stage settle.
 */
async function readStep(page: Page, step: string): Promise<void> {
  await page.evaluate((name) => {
    const element = document.querySelector(`[data-story-step="${name}"]`);
    if (!element) throw new Error(`no story step ${name}`);
    const wide = window.matchMedia('(min-width: 64rem) and (min-height: 40rem)').matches;
    const top = element.getBoundingClientRect().top + window.scrollY;
    window.scrollTo(0, top - window.innerHeight * (wide ? 0.42 : 0.6));
  }, step);
  await expect(page.locator('[data-story-root]')).toHaveAttribute('data-step', step);
  await settled(page);
}

/**
 * The landing page (PA-UX-05; first built from Golden Master 10:2318 and
 * phone 17:3167).
 *
 * It is static — it cannot ask the API — so what is under test is that it
 * says what the product does, shows the verified example as the API recorded
 * it and says when, claims nothing the system cannot back, and gets a reader
 * to the planner. The old planner address keeps working.
 */
test.describe('landing page', () => {
  test('names the product and sends the reader to the planner', async ({ page }) => {
    await page.goto('/');

    await expect(page).toHaveTitle(/^PathAble — /);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(
      /Routes that account for what you can actually traverse/,
    );
    await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);

    await page.getByTestId('hero-explore').click();
    await expect(page).toHaveURL(/\/planner$/);
    await expect(page.getByTestId('map-frame')).toBeVisible();
  });

  test('says where its figures came from, and when', async ({ page }) => {
    await page.goto('/');

    // One recorded response, dated, named as one journey rather than a typical one.
    const callout = page.getByText(/recorded from\s+the implemented routing API/);
    await callout.scrollIntoViewIfNeeded();
    await expect(callout).toBeVisible();
    await expect(callout).toContainText('One journey, not typical of all.');

    const source = page.getByTestId('hero-readout');
    await expect(source).toBeVisible();
    await expect(source).toContainText('Recorded from the routing API on 2026-10-13');
    await expect(source).toContainText('dataset 51e75f78');
  });

  test('the stage follows the story as it is read, by ordinary scrolling', async ({ page }) => {
    await page.goto('/');
    const root = page.locator('[data-story-root]');
    await expect(root).toHaveAttribute('data-step', 'overview');

    for (const step of STORY_STEPS) {
      await readStep(page, step);
    }
    // Back up to the hero and the whole answer returns.
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect(root).toHaveAttribute('data-step', 'overview');
  });

  test('every label the stage shows stays inside it, at every step', async ({ page }) => {
    // A label pushed off the drawing is cut mid-word — found on the phone
    // stage while building this page; held here at both sizes.
    await page.goto('/');
    await settled(page);

    for (const step of ['overview', ...STORY_STEPS]) {
      if (step !== 'overview') await readStep(page, step);
      const outside = await page.evaluate(() => {
        const stage = document
          .querySelector('[data-testid="hero-visual"]')!
          .getBoundingClientRect();
        return Array.from(
          document.querySelectorAll<HTMLElement>('[data-testid="hero-visual"] [data-show]'),
        )
          .filter((label) => Number(getComputedStyle(label).opacity) > 0.5)
          .filter((label) => getComputedStyle(label).display !== 'none')
          .map((label) => ({ text: label.textContent, box: label.getBoundingClientRect() }))
          .filter(
            ({ box }) =>
              box.left < stage.left - 1 ||
              box.right > stage.right + 1 ||
              box.top < stage.top - 1 ||
              box.bottom > stage.bottom + 1,
          )
          .map(({ text }) => text);
      });
      expect(outside, `labels outside the stage at "${step}"`).toEqual([]);
    }
  });

  test('reduced motion: the stage still follows the story, but the camera never moves', async ({
    page,
  }) => {
    // Regression: the reduced-motion override was less specific than each
    // step's camera rule, so with reduced motion on the stage still zoomed to
    // 1.18× on the stairs step. Found by this test while building PA-UX-05.
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');
    const camera = page.locator('[data-testid="hero-visual"] > div > div').first();
    const atRest = await camera.evaluate((element) => getComputedStyle(element).transform);

    for (const step of STORY_STEPS) {
      await readStep(page, step);
      expect(await camera.evaluate((element) => getComputedStyle(element).transform)).toBe(atRest);
    }
    // And nothing waits to be revealed.
    expect(await page.locator('html[data-reveal-armed]').count()).toBe(0);
  });

  test('evidence lenses work from the keyboard alone', async ({ page }) => {
    await page.goto('/');
    const stairs = page.getByRole('radio', { name: 'Stairs' });
    await stairs.focus();
    await page.keyboard.press('ArrowRight');

    await expect(page.getByRole('radio', { name: 'Gradient' })).toBeChecked();
    await expect(page.locator('[data-lens-panel="gradient"]')).toBeVisible();
    await expect(page.locator('[data-lens-panel="stairs"]')).toBeHidden();
    await expect(page.locator('[data-lens-panel="gradient"]')).toContainText('never flat');

    await page.keyboard.press('ArrowRight');
    await expect(page.locator('[data-lens-panel="surface"]')).toContainText('not recorded on 65 m');
  });

  test('“Compute this journey live” carries the reader into the planner, which routes it', async ({
    page,
  }) => {
    await stubHealthyApi(page);
    await stubRouteComparison(page);
    await page.goto('/');

    await page.getByRole('link', { name: 'Compute this journey live' }).click();
    await expect(page).toHaveURL(/\/planner\?example=campus-library-to-student-life$/);
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
  });

  test('a fast scroll to the bottom leaves nothing waiting to be revealed', async ({ page }) => {
    // Regression: under load, blocks in a section the browser skips
    // (content-visibility) went by too fast to be reported on screen and
    // stayed hidden above the reader. Whether a fade has finished off screen
    // is invisible by definition, so what is held is the state: nothing the
    // reader has passed is still waiting, and what is on screen is opaque.
    await page.goto('/');
    await page.evaluate(async () => {
      for (let y = 0; y < document.documentElement.scrollHeight; y += window.innerHeight / 2) {
        window.scrollTo(0, y);
        await new Promise((resolve) => setTimeout(resolve, 60));
      }
      window.scrollTo(0, document.documentElement.scrollHeight);
    });
    await settled(page);

    const waiting = await page.evaluate(() =>
      Array.from(document.querySelectorAll<HTMLElement>('[data-reveal="pending"]')).map(
        (element) => element.className,
      ),
    );
    expect(waiting).toEqual([]);
    const cta = page.locator('[data-reveal]').last();
    await expect(cta).toBeInViewport();
    expect(Number(await cta.evaluate((element) => getComputedStyle(element).opacity))).toBe(1);
  });

  test('makes no safety, compliance or machine-learning claim', async ({ page }) => {
    await page.goto('/');

    const text = (await page.locator('body').innerText()).replace(/\s+/g, ' ');
    expect(text).not.toMatch(/barrier-free|AODA|\bAI\b|artificial intelligence/i);
    expect(text).not.toMatch(/guaranteed (safe|accessible)|certified accessible/i);
    expect(text).not.toMatch(/open[- ]source/i);
  });

  test('credits the map data and the elevation licence', async ({ page }) => {
    await page.goto('/');

    const footer = page.getByTestId('landing-footer');
    await footer.scrollIntoViewIfNeeded();
    await expect(footer).toContainText('OpenStreetMap contributors');
    await expect(footer).toContainText('ODbL 1.0');
    await expect(footer).toContainText('Open Government Licence – Canada');
  });

  test('keeps a recorded `/?example=` link working, query intact', async ({ page }) => {
    // README links, the evidence pack and the earlier demo all use the
    // planner's old address. They must still open the planner on the example.
    await stubHealthyApi(page);
    await stubRouteComparison(page);
    const compare = page.waitForRequest(
      (request) => request.url().includes('/api/v1/routes/compare') && request.method() === 'POST',
    );

    await page.goto('/?example=campus-library-to-student-life');

    await expect(page).toHaveURL(/\/planner\?example=campus-library-to-student-life$/);
    const sent = (await compare).postDataJSON() as { origin: unknown };
    expect(sent.origin).toEqual({ longitude: -80.5424, latitude: 43.4728 });
    await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
  });

  test('asks the routing service nothing', async ({ page }) => {
    const calls: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/')) calls.push(request.url());
    });
    await page.route(COMPARE_PATTERN, (route) => route.abort());

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    expect(calls).toEqual([]);
  });

  test('skip link, focus and reflow', async ({ page }) => {
    await page.goto('/');
    await page.keyboard.press('Tab');

    const focused = page.locator(':focus-visible');
    await expect(focused).toContainText(/skip to main content/i);
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/#main-content$/);

    expect(await hasHorizontalOverflow(page)).toBe(false);
  });

  test('reduced motion leaves the hero still', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');

    const duration = await page
      .getByRole('heading', { level: 1 })
      .evaluate((heading) => getComputedStyle(heading.parentElement!).animationDuration);
    expect(Number.parseFloat(duration)).toBeLessThan(0.016);
  });

  test('the planner link in the header goes to the planner', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByTestId('header-explore')).toHaveAttribute('href', PLANNER);
  });

  test('captures the landing page for visual review', async ({ page }, testInfo) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');

    const path = `${SCREENSHOT_DIR}/${testInfo.project.name}-landing.png`;
    await page.screenshot({ path, fullPage: false });
    await testInfo.attach('landing', { path, contentType: 'image/png' });
  });
});

test.describe('landing page with JavaScript off', () => {
  test.use({ javaScriptEnabled: false });

  test('every word is there and the stage shows the whole answer', async ({ page }) => {
    await page.goto('/');

    await expect(page.locator('[data-story-root]')).toHaveAttribute('data-step', 'overview');
    await expect(page.locator('html[data-reveal-armed]')).toHaveCount(0);
    for (const heading of [
      'What nobody recorded stays unknown.',
      'PathAble shows what it knows — and what it doesn’t.',
      'Measured, with the conditions attached.',
    ]) {
      const element = page.getByRole('heading', { name: heading });
      await element.scrollIntoViewIfNeeded();
      await expect(element).toBeVisible();
    }
    // The lens is CSS, not script: it still switches.
    await page.locator('label[for="lens-surface"]').click();
    await expect(page.locator('[data-lens-panel="surface"]')).toBeVisible();
    await expect(page.locator('[data-lens-panel="stairs"]')).toBeHidden();
  });
});
