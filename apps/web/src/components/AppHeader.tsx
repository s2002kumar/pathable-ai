'use client';

import { SystemStatusBadge } from '@/features/system-status/SystemStatusBadge';
import { useSystemStatus } from '@/features/system-status/useSystemStatus';
import styles from './AppHeader.module.css';

export type AppHeaderProps = {
  readonly apiBaseUrl: string;
  readonly pilotRegionName: string;
  /** 0 disables polling. The e2e suite uses this for deterministic assertions. */
  readonly statusPollIntervalMs?: number;
};

function BrandMark() {
  return (
    <svg className={styles.mark} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        d="M6 20c0-5 3-7 6-8.5S18 8 18 4"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.25"
        strokeLinecap="round"
      />
      <circle cx="6" cy="20" r="2.5" fill="currentColor" />
      <circle cx="18" cy="4" r="2.5" fill="currentColor" />
    </svg>
  );
}

/**
 * A compact instrument bar: identity on the left, where the system is and how
 * it is doing on the right. It is deliberately one row high so the map and the
 * planner get the rest of the viewport.
 */
export function AppHeader({ apiBaseUrl, pilotRegionName, statusPollIntervalMs }: AppHeaderProps) {
  const { status } = useSystemStatus({
    apiBaseUrl,
    ...(statusPollIntervalMs !== undefined ? { pollIntervalMs: statusPollIntervalMs } : {}),
  });

  return (
    <header className={styles.header}>
      <div className={styles.brand}>
        <BrandMark />
        <div className={styles.names}>
          <p className={styles.productName}>PathAble AI</p>
          <p className={styles.mission}>Accessibility-aware pedestrian routing</p>
        </div>
      </div>

      <div className={styles.meta}>
        <p className={styles.pilot} data-testid="pilot-region">
          <span className={styles.pilotLabel}>Pilot</span>
          <span>{pilotRegionName}</span>
        </p>
        <SystemStatusBadge status={status} />
      </div>
    </header>
  );
}
