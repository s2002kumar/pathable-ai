/**
 * The profile rules the panel shows are the routing service's own.
 *
 * What is tested here is that the browser takes them as given, refuses what it
 * cannot read, and never substitutes a rule of its own when the service is
 * silent.
 */
import { describe, expect, it, vi } from 'vitest';
import type { MobilityProfile } from '@pathable/contracts';
import { fetchMobilityProfiles, profileRuleLines } from './mobility-profiles';

const WHEELCHAIR: MobilityProfile = {
  key: 'wheelchair',
  display_name: 'Wheelchair',
  description: 'Avoids steps entirely.',
  excludes_steps: true,
  max_incline_percent: null,
  min_width_m: null,
  prefers_gradient_under_percent: 8,
  prefers_width_over_m: 0.9,
  hard_requirements: ['cannot use steps'],
};

function respond(body: unknown, status = 200) {
  return vi.fn(
    async () => new Response(JSON.stringify(body), { status }),
  ) as unknown as typeof fetch;
}

describe('fetchMobilityProfiles', () => {
  it('reads the list from the profiles route', async () => {
    const fetchImpl = respond({ profiles: [WHEELCHAIR] });
    const profiles = await fetchMobilityProfiles({ apiBaseUrl: 'http://api.test', fetchImpl });

    expect(profiles).toEqual([WHEELCHAIR]);
    expect(fetchImpl).toHaveBeenCalledWith(
      'http://api.test/api/v1/routes/profiles',
      expect.objectContaining({ headers: { Accept: 'application/json' } }),
    );
  });

  it('has nothing to offer when the service answers with an error', async () => {
    expect(
      await fetchMobilityProfiles({ apiBaseUrl: 'x', fetchImpl: respond({ profiles: [] }, 503) }),
    ).toBeNull();
  });

  it('refuses a list it cannot read rather than showing part of it', async () => {
    const malformed = { profiles: [WHEELCHAIR, { key: 'walker', hard_requirements: 'none' }] };
    expect(
      await fetchMobilityProfiles({ apiBaseUrl: 'x', fetchImpl: respond(malformed) }),
    ).toBeNull();
    expect(await fetchMobilityProfiles({ apiBaseUrl: 'x', fetchImpl: respond({}) })).toBeNull();
  });

  it('never rejects when the network fails', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }) as unknown as typeof fetch;
    expect(await fetchMobilityProfiles({ apiBaseUrl: 'x', fetchImpl })).toBeNull();
  });
});

describe('profileRuleLines', () => {
  it('repeats limits as the service states them, without rounding', () => {
    expect(
      profileRuleLines({
        ...WHEELCHAIR,
        hard_requirements: ['cannot use steps', 'cannot manage uphill gradients above 4.5%'],
        prefers_gradient_under_percent: 8.0,
        prefers_width_over_m: 0.75,
      }),
    ).toEqual({
      hard: 'Hard limits: cannot use steps; cannot manage uphill gradients above 4.5%.',
      preferences: 'Prefers climbs under 8% and paths wider than 0.75 m.',
    });
  });

  it('says there are no hard limits, and no preferences, when there are none', () => {
    expect(
      profileRuleLines({
        ...WHEELCHAIR,
        hard_requirements: [],
        prefers_gradient_under_percent: null,
        prefers_width_over_m: null,
      }),
    ).toEqual({ hard: 'No hard limits.', preferences: null });
  });
});
