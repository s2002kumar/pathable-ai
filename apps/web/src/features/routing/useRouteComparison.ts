'use client';

import { useCallback, useEffect, useState } from 'react';
import { compareRoutes } from './compare-routes';
import type { CustomProfileOptions, Journey, RouteRequestState } from './types';

export type UseRouteComparisonOptions = {
  readonly apiBaseUrl: string;
  readonly region: string;
  /**
   * The journey that has been submitted for comparison, or null for none.
   *
   * A *submitted* journey, not the panel's draft: the request fires when the
   * viewer commits one, not while they are still assembling it.
   */
  readonly journey: Journey | null;
  /** Custom profile options, when a caller supplies them. No UI sets these today. */
  readonly custom?: CustomProfileOptions;
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
 * Requests a comparison for the journey that has been submitted.
 *
 * It used to fire the moment two endpoints existed. That was fine while a
 * point was only ever a map click, and wrong once endpoints are named things
 * a person types: a half-finished destination would be routed to, and editing
 * either end would fire a request nobody asked for. The panel now commits a
 * journey and this hook answers it.
 *
 * The visible state is *derived* from the request key rather than assigned in
 * an effect. That does two things: it removes a synchronous setState from the
 * effect body, and it means a result can never be shown against the wrong
 * request — committing a new journey shows "comparing…" on the very same
 * render that commits it, not one render later. Keeping that property is why
 * the key is still computed during render rather than stored when submitting.
 */
export function useRouteComparison({
  apiBaseUrl,
  region,
  journey,
  custom,
  fetchImpl,
}: UseRouteComparisonOptions): UseRouteComparisonResult {
  const [settled, setSettled] = useState<Settled | null>(null);
  const [attempt, setAttempt] = useState(0);

  const origin = journey?.origin.position ?? null;
  const destination = journey?.destination.position ?? null;
  const profileKey = journey?.profileKey ?? null;
  const customSignature = custom ? JSON.stringify(custom) : '';

  const requestKey =
    journey === null || origin === null || destination === null || profileKey === null
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
    if (requestKey === null || origin === null || destination === null || profileKey === null) {
      return;
    }

    const controller = new AbortController();

    void compareRoutes({
      apiBaseUrl,
      region,
      origin,
      destination,
      profile: { key: profileKey, ...(customSignature && custom ? { custom } : {}) },
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
    // The journey is compared through the serialised key rather than by
    // identity: a parent re-render creates a new object every time, which
    // would otherwise re-request on every unrelated state change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey, fetchImpl]);

  const retry = useCallback(() => {
    setAttempt((value) => value + 1);
  }, []);

  const state = requestKey === null ? IDLE : settled?.key === requestKey ? settled.state : LOADING;

  return { state, retry };
}
