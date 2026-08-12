'use client';

import { cx } from '@/lib/cx';
import type { SystemStatus } from './types';
import styles from './SystemStatusBadge.module.css';

export type SystemStatusBadgeProps = {
  readonly status: SystemStatus;
};

type Presentation = {
  readonly label: string;
  readonly detail: string | null;
  /** Undefined when the CSS module has no matching class; `cx` drops it. */
  readonly className: string | undefined;
};

/**
 * Colour is a secondary cue only — the label always states the status in words,
 * so the badge is meaningful to a colour-blind or screen-reader user.
 */
export function describeStatus(status: SystemStatus): Presentation {
  switch (status.state) {
    case 'checking':
      return { label: 'Checking API', detail: null, className: styles.checking };
    case 'ready':
      return {
        label: 'API online',
        detail: `${status.service} v${status.version}`,
        className: styles.ready,
      };
    case 'degraded':
      return {
        label: 'API degraded',
        detail:
          status.failing.length > 0
            ? `${status.failing.join(' and ')} unavailable`
            : 'a dependency is unavailable',
        className: styles.degraded,
      };
    case 'unreachable':
      return { label: 'API offline', detail: status.reason, className: styles.unreachable };
  }
}

export function SystemStatusBadge({ status }: SystemStatusBadgeProps) {
  const { label, detail, className } = describeStatus(status);

  return (
    <p
      className={cx(styles.badge, className)}
      // Polite, not assertive: a backend recovering mid-session should not
      // interrupt whatever the user is reading.
      role="status"
      aria-live="polite"
      data-testid="system-status"
      data-status={status.state}
    >
      <span className={styles.dot} aria-hidden="true" />
      <span>{label}</span>
      {detail !== null && <span className={styles.detail}>· {detail}</span>}
    </p>
  );
}
