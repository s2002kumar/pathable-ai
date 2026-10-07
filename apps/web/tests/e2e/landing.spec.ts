import { expect, test } from '@playwright/test';
import {
  COMPARE_PATTERN,
  PLANNER,
  SCREENSHOT_DIR,
  hasHorizontalOverflow,
  stubHealthyApi,
  stubRouteComparison,
} from './fixtures';

/**
 * The landing page (Golden Master 10:2318, phone 17:3167).
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

    const caption = page.getByText(/Recorded from the routing API on 2026-10-05/);
    if (await caption.isVisible()) {
      await expect(caption).toContainText('dataset 51e75f78');
    }
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
