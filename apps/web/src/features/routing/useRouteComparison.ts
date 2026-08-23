'use client';

import { useCallback, useEffect, useState } from 'react';
import { compareRoutes } from './compare-routes';
import type { PlannerPoints, ProfileSelection, RouteRequestState } from './types';

export type UseRouteComparisonOptions = {
  readonly apiBaseUrl: string;
  readonly region: string;
  readonly points: PlannerPoints;
  readonly profile: ProfileSelection;
  readonly fetchImpl?: typeof fetch;
};

export type UseRouteComparisonResult = {
  readonly state: RouteRequestState;
  readonly retry: () => void;
};

const IDLE: RouteRequestState = { status: 'idle' };
const LOADING: RouteRequestState = { status: 'loading' };

type Settled = { readonly key: string; readonly state: RouteRequestState };

/**
 * Requests a comparison whenever both endpoints and the profile are settled.
 *
 * Automatic rather than behind a "find route" button: the user has already
 * expressed the whole request by placing two points and choosing a profile, and
 * making them confirm it again adds a step without adding information. Changing
 * the profile re-requests, which is the point — the comparison is what the
 * product is for.
 *
 * The visible state is *derived* from the request key rather than assigned in an
 * effect. That does two things: it removes a synchronous setState from the
 * effect body, and it means a result can never be shown against the wrong
 * request — changing the profile shows "comparing…" on the very same render that
 * changes it, not one render later.
 */
export function useRouteComparison({
  apiBaseUrl,
  region,
  points,
  profile,
  fetchImpl,
}: UseRouteComparisonOptions): UseRouteComparisonResult {
  const [settled, setSettled] = useState<Settled | null>(null);
  const [attempt, setAttempt] = useState(0);

  const { origin, destination } = points;
  const profileKey = profile.key;
  const customSignature = profile.custom ? JSON.stringify(profile.custom) : '';

  const requestKey =
    origin === null || destination === null
      ? null
      : [
          apiBaseUrl,
          region,
          origin.longitude,
          origin.latitude,
          destination.longitude,
          destination.latitude,
          profileKey,
          customSignature,
          attempt,
        ].join('|');

  useEffect(() => {
    if (requestKey === null || origin === null || destination === null) return;

    const controller = new AbortController();

    void compareRoutes({
      apiBaseUrl,
      region,
      origin,
      destination,
      profile: { key: profileKey, ...(customSignature ? { custom: profile.custom } : {}) },
      signal: controller.signal,
      ...(fetchImpl ? { fetchImpl } : {}),
    }).then((result) => {
      if (controller.signal.aborted) return;
      setSettled({
        key: requestKey,
        state: result.ok
          ? { status: 'success', comparison: result.data }
          : { status: 'error', message: result.message, code: result.code },
      });
    });

    return () => {
      // A superseded request must not overwrite a newer answer.
      controller.abort();
    };
    // `profile` is compared by key and serialised options rather than identity:
    // a parent re-render creates a new object every time, which would otherwise
    // re-request on every unrelated state change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey, fetchImpl]);

  const retry = useCallback(() => {
    setAttempt((value) => value + 1);
  }, []);

  const state = requestKey === null ? IDLE : settled?.key === requestKey ? settled.state : LOADING;

  return { state, retry };
}
