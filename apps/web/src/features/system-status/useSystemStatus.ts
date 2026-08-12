'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchSystemStatus } from './fetch-system-status';
import type { SystemStatus } from './types';

export type UseSystemStatusOptions = {
  readonly apiBaseUrl: string;
  /** Re-probe interval. 0 disables polling — used by tests and by the e2e suite. */
  readonly pollIntervalMs?: number;
};

export type UseSystemStatusResult = {
  readonly status: SystemStatus;
  readonly refresh: () => void;
};

export const DEFAULT_POLL_INTERVAL_MS = 30_000;

export function useSystemStatus({
  apiBaseUrl,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
}: UseSystemStatusOptions): UseSystemStatusResult {
  const [status, setStatus] = useState<SystemStatus>({ state: 'checking' });
  const abortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  const probe = useCallback(async () => {
    // Supersede any in-flight probe so a slow response cannot overwrite a newer one.
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const result = await fetchSystemStatus({ apiBaseUrl, signal: controller.signal });
    if (mountedRef.current && !controller.signal.aborted) {
      setStatus(result);
    }
  }, [apiBaseUrl]);

  const refresh = useCallback(() => {
    void probe();
  }, [probe]);

  useEffect(() => {
    mountedRef.current = true;
    void probe();

    const timer = pollIntervalMs > 0 ? setInterval(() => void probe(), pollIntervalMs) : undefined;

    return () => {
      mountedRef.current = false;
      if (timer !== undefined) clearInterval(timer);
      abortRef.current?.abort();
    };
  }, [probe, pollIntervalMs]);

  return { status, refresh };
}
