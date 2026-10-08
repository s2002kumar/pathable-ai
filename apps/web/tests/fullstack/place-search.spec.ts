/**
 * Place search, end to end against the real containers and the real index.
 *
 * Nothing is stubbed. The browser searches the API, the API searches the
 * Waterloo place index built from the network's own OpenStreetMap extract, and
 * the place chosen becomes the start of a route the live engine computes. The
 * test then checks that the request carried exactly the coordinates the search
 * returned — so a field that only looked searchable would fail here.
 *
 * Run it the same way as the demo suite, against the production-smoke stack:
 *
 *   FULLSTACK_TARGET=compose FULLSTACK_WEB_URL=http://127.0.0.1:3001 \
 *   FULLSTACK_API_URL=http://127.0.0.1:8001 \
 *     pnpm --filter @pathable/web exec playwright test --config=playwright.fullstack.config.ts
 */
import { expect, test } from '@playwright/test';

const SEARCH_PATH = '/api/v1/geocode/search';
const COMPARE_PATH = '/api/v1/routes/compare';
const PLANNER = '/planner';

/** Matches playwright.fullstack.config.ts, including its Compose override. */
const API_BASE_URL = process.env.FULLSTACK_API_URL ?? 'http://127.0.0.1:8100';

/** Two places on the University of Waterloo campus, as people would type them. */
const START = 'Davis Centre';
const DESTINATION = 'Student Life Centre';

type Match = { label: string; longitude: number; latitude: number; category: string | null };
type SearchAnswer = { enabled: boolean; matches: Match[]; attribution: string | null };

/**
 * The index is built from a 970 MB extract, and CI has only the nine-node
 * synthetic network — so, like the demo suite, this skips there and says so.
 */
let indexed = false;

test.beforeAll(async ({ request }) => {
  const response = await request.post(`${API_BASE_URL}${SEARCH_PATH}`, {
    data: { region: 'waterloo', query: START },
    failOnStatusCode: false,
  });
  const body = response.ok() ? ((await response.json()) as SearchAnswer) : null;
  indexed = body !== null && body.enabled && body.matches.length > 0;
  if (!indexed) {
    console.warn(
      `[place-search] skipping: ${API_BASE_URL} has no Waterloo place index ` +
        `(POST ${SEARCH_PATH} answered ${response.status()}, ` +
        `enabled=${String(body?.enabled)}). Build it with \`pathable gazetteer build\`.`,
    );
  }
});

test.beforeEach(() => {
  test.skip(
    !indexed,
    'needs the real Waterloo place index; run against the production-smoke stack',
  );
});

test('a searched place becomes the start of a live route', async ({ page }) => {
  await page.goto(PLANNER);
  await expect(page.getByTestId('map-frame')).toHaveAttribute('data-map-state', 'ready');

  async function choose(field: string, button: string, query: string): Promise<Match> {
    const answered = page.waitForResponse(
      (response) => response.url().includes(SEARCH_PATH) && response.status() === 200,
    );
    await page.getByLabel(field).fill(query);
    await page.getByRole('button', { name: button }).click();
    const answer = (await (await answered).json()) as SearchAnswer;
    expect(answer.enabled).toBe(true);
    expect(answer.attribution).toMatch(/OpenStreetMap as of \d{4}-\d{2}-\d{2}/);
    const [first] = answer.matches;
    expect(first, `no match for ${query}`).toBeDefined();

    await expect(page.getByTestId('search-attribution')).toContainText('OpenStreetMap');
    await page
      .getByRole('button', {
        name: first!.category ? `${first!.label}, ${first!.category}` : first!.label,
      })
      .first()
      .click();
    return first!;
  }

  const start = await choose('Start location', 'Search for a start', START);
  await expect(page.getByTestId('endpoint-origin-value')).toContainText(start.label);
  const destination = await choose('Target endpoint', 'Search for a destination', DESTINATION);
  await expect(page.getByTestId('endpoint-destination-value')).toContainText(destination.label);

  const asked = page.waitForRequest(
    (request) => request.url().includes(COMPARE_PATH) && request.method() === 'POST',
  );
  await page.getByTestId('compare-routes').click();
  const sent = (await asked).postDataJSON() as {
    origin: { longitude: number; latitude: number };
    destination: { longitude: number; latitude: number };
  };

  expect(sent.origin).toEqual({ longitude: start.longitude, latitude: start.latitude });
  expect(sent.destination).toEqual({
    longitude: destination.longitude,
    latitude: destination.latitude,
  });
  await expect(page.getByTestId('route-status')).toHaveAttribute('data-route-state', 'success');
});
