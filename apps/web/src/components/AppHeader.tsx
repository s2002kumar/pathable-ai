'use client';

import Link from 'next/link';
import { Icon } from '@/components/Icon';
import type { SystemStatus } from '@/features/system-status/types';
import { shortRegionName } from '@/lib/region';
import styles from './AppHeader.module.css';

export type AppHeaderProps = {
  readonly pilotRegionName: string;
  /** The API's state: the dot's colour, and a word whenever it is not ready. */
  readonly status: SystemStatus;
  /** Where the search button sends focus: the planner's start field. */
  readonly searchTargetId?: string;
};

/**
 * The planner's bar: identity, the region it plans in, and two shortcuts.
 *
 * One row, 64 px, as the Golden Master draws it. The dot beside the region is
 * the API's state as a colour, and the pill says it in a word as well — the
 * design draws only the ready state, where the word stays for assistive
 * technology alone. The idle strip and the panel's errors say it in full.
 */
const STATE_WORDS: Readonly<Record<SystemStatus['state'], string>> = {
  ready: 'Ready',
  checking: 'Checking',
  preparing: 'Preparing',
  degraded: 'Degraded',
  unreachable: 'Offline',
};

export function AppHeader({ pilotRegionName, status, searchTargetId }: AppHeaderProps) {
  const word = STATE_WORDS[status.state];
  return (
    <header className={styles.header}>
      <div className={styles.identity}>
        <Link href="/" className={styles.brand} aria-label="PathAble home">
          <span className={styles.mark} aria-hidden="true">
            <Icon name="brand" />
          </span>
          <span className={styles.productName}>PathAble</span>
        </Link>
        <p className={styles.region} data-testid="pilot-region" data-status={status.state}>
          <span className={styles.regionDot} aria-hidden="true" />
          <span className={styles.regionFull}>{shortRegionName(pilotRegionName)}</span>
          <span className={styles.regionShort} aria-hidden="true">
            {pilotRegionName.split(',')[0]}
          </span>
          <span
            className={status.state === 'ready' ? 'visually-hidden' : styles.regionState}
            data-testid="header-status"
          >
            <span className="visually-hidden">Routing service: </span>
            {word}
          </span>
        </p>
      </div>

      <nav className={styles.actions} aria-label="Planner shortcuts">
        {searchTargetId ? (
          <button
            type="button"
            className={styles.iconButton}
            aria-label="Search for a place"
            title="Search for a place"
            onClick={() => document.getElementById(searchTargetId)?.focus()}
            data-testid="header-search"
          >
            <Icon name="search" />
          </button>
        ) : null}
        <Link
          href="/#how-it-works"
          className={styles.iconButton}
          aria-label="About PathAble, its open data and methodology"
          title="About the data and methodology"
        >
          <Icon name="info" />
        </Link>
      </nav>
    </header>
  );
}
