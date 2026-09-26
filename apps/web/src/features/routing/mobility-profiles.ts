'use client';

import { useEffect, useState } from 'react';
import { API_ROUTES, type MobilityProfile } from '@pathable/contracts';

/**
 * What each mobility profile rules out and prefers, as the routing service
 * states it.
 *
 * Read from `/routes/profiles` rather than written down here. The limits are
 * the routing policy — "cannot use steps", "prefers climbs under 8%" — and a
 * second copy in the browser would be a second policy that drifts from the
 * one that actually chooses the route. The panel shows the labels at once and
 * the rules when they arrive; until then it says it is waiting, not a guess.
 */

export type ProfilesState =
  | { readonly status: 'loading' }
  | { readonly status: 'ready'; readonly profiles: ReadonlyMap<string, MobilityProfile> }
  | { readonly status: 'unavailable' };

const PROFILES_TIMEOUT_MS = 10_000;

function isProfile(value: unknown): value is MobilityProfile {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<MobilityProfile>;
  return (
    typeof candidate.key === 'string' &&
    typeof candidate.display_name === 'string' &&
    typeof candidate.excludes_steps === 'boolean' &&
    (candidate.hard_requirements === undefined ||
      (Array.isArray(candidate.hard_requirements) &&
        candidate.hard_requirements.every((rule) => typeof rule === 'string')))
  );
}

/** The profiles, or null when the service cannot supply them. Never rejects. */
export async function fetchMobilityProfiles({
  apiBaseUrl,
  fetchImpl,
  signal,
}: {
  readonly apiBaseUrl: string;
  readonly fetchImpl?: typeof fetch;
  readonly signal?: AbortSignal;
}): Promise<MobilityProfile[] | null> {
  const doFetch = fetchImpl ?? globalThis.fetch;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROFILES_TIMEOUT_MS);
  const onAbort = () => controller.abort();
  signal?.addEventListener('abort', onAbort);
  try {
    const response = await doFetch(`${apiBaseUrl}${API_ROUTES.mobilityProfiles}`, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    });
    if (!response.ok) return null;
    const body: unknown = await response.json().catch(() => null);
    const profiles = (body as { profiles?: unknown } | null)?.profiles;
    if (!Array.isArray(profiles) || !profiles.every(isProfile)) return null;
    return profiles;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}

export function useMobilityProfiles({
  apiBaseUrl,
  fetchImpl,
}: {
  readonly apiBaseUrl: string;
  readonly fetchImpl?: typeof fetch;
}): ProfilesState {
  const [state, setState] = useState<ProfilesState>({ status: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    void fetchMobilityProfiles({
      apiBaseUrl,
      signal: controller.signal,
      ...(fetchImpl ? { fetchImpl } : {}),
    }).then((profiles) => {
      if (controller.signal.aborted) return;
      setState(
        profiles === null
          ? { status: 'unavailable' }
          : {
              status: 'ready',
              profiles: new Map(profiles.map((profile) => [profile.key, profile])),
            },
      );
    });
    return () => controller.abort();
  }, [apiBaseUrl, fetchImpl]);

  return state;
}

/** A limit as it was declared: `8.0` reads 8, `0.9` stays 0.9. */
function plainNumber(value: number): string {
  return String(Number(value.toFixed(4)));
}

/**
 * The rules one profile applies, in two short lines.
 *
 * Hard limits and preferences are kept apart on purpose. A hard limit removes
 * a path from consideration; a preference only makes it cost more. Reading
 * "prefers climbs under 8%" as "cannot climb over 8%" would tell somebody who
 * manages an 11% ramp that their journey is impossible.
 */
export function profileRuleLines(profile: MobilityProfile): {
  readonly hard: string;
  readonly preferences: string | null;
} {
  const requirements = profile.hard_requirements ?? [];
  const hard =
    requirements.length === 0
      ? 'No hard limits.'
      : `Hard ${requirements.length === 1 ? 'limit' : 'limits'}: ${requirements.join('; ')}.`;

  const preferred: string[] = [];
  if (typeof profile.prefers_gradient_under_percent === 'number') {
    preferred.push(`climbs under ${plainNumber(profile.prefers_gradient_under_percent)}%`);
  }
  if (typeof profile.prefers_width_over_m === 'number') {
    preferred.push(`paths wider than ${plainNumber(profile.prefers_width_over_m)} m`);
  }
  return {
    hard,
    preferences: preferred.length === 0 ? null : `Prefers ${preferred.join(' and ')}.`,
  };
}
