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
  /**
   * Whether the detail is a diagnostic rather than something a visitor needs.
   * A build version is one: it stays in the badge for a screen reader and for
   * anyone debugging their own setup, but it is not part of the visual
   * hierarchy of a page whose subject is a route.
   */
  readonly diagnostic: boolean;
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
      return { label: 'Checking API', detail: null, diagnostic: false, className: styles.checking };
    case 'ready':
      return {
        label: 'API online',
        detail: `${status.service} v${status.version}`,
        diagnostic: true,
        className: styles.ready,
      };
    case 'preparing':
      return {
        label: 'Preparing routes',
        detail: 'loading the Waterloo routing graph',
        diagnostic: false,
        className: styles.preparing,
      };
    case 'degraded':
      return {
        label: 'API degraded',
        detail:
          status.failing.length > 0
            ? `${status.failing.join(' and ')} unavailable`
            : 'a dependency is unavailable',
        diagnostic: false,
        className: styles.degraded,
      };
    case 'unreachable':
      return {
        label: 'API offline',
        detail: status.reason,
        diagnostic: false,
        className: styles.unreachable,
      };
  }
}

export function SystemStatusBadge({ status }: SystemStatusBadgeProps) {
  const { label, detail, diagnostic, className } = describeStatus(status);

  return (
    <p
      className={cx(styles.badge, className)}
      // Polite, not assertive: a backend recovering mid-session should not
      // interrupt whatever the user is reading.
      role="status"
      aria-live="polite"
      data-testid="system-status"
      data-status={status.state}
      {...(diagnostic && detail !== null ? { title: detail } : {})}
    >
      <span className={styles.dot} aria-hidden="true" />
      <span>{label}</span>
      {detail !== null && (
        <span className={diagnostic ? 'visually-hidden' : styles.detail}>· {detail}</span>
      )}
    </p>
  );
}
