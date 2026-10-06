'use client';

import { useEffect, useRef } from 'react';
import type { RouteCompareResponse } from '@pathable/contracts';
import { Icon } from '@/components/Icon';
import { RouteComparisonView } from './RouteComparisonView';
import type { RouteVariant } from './route-evidence';
import { limitText } from './UphillLimitControl';
import styles from './RouteDetails.module.css';

export type DetailsSection = 'details' | 'evidence';

/**
 * "Route Details" and "View Evidence": the whole answer, in text.
 *
 * Everything the comparison panel summarises is here in full — every reason by
 * topic with its evidence label, the per-category record with its own
 * denominator, the cautions, the dataset and its age, the licences. A modal
 * side sheet over the map: the routes stay drawn behind it, focus moves into
 * it on open and back to the control that opened it on close.
 *
 * The sheet is modal, so assistive technology cannot reach the panel's route
 * cards while it is open. It states both routes itself for that reason, and
 * choosing one here chooses it on the map as the cards do.
 */
export function RouteDetails({
  open,
  section,
  comparison,
  selectedRoute,
  onSelectRoute,
  journeySummary,
  profileName,
  uphillLimit,
  onClose,
}: {
  readonly open: boolean;
  readonly section: DetailsSection;
  readonly comparison: RouteCompareResponse | null;
  readonly selectedRoute: RouteVariant;
  readonly onSelectRoute: (variant: RouteVariant) => void;
  readonly journeySummary: string | null;
  /**
   * The profile as the traveller chose it. A limit of their own makes the API
   * answer as "Custom"; the panel names it by its preset, and so does this.
   */
  readonly profileName: string | null;
  /** The traveller's own uphill limit on that answer, if they set one. */
  readonly uphillLimit: number | null;
  readonly onClose: () => void;
}) {
  const sheet = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButton.current?.focus();
    if (section === 'evidence') {
      sheet.current
        ?.querySelector<HTMLElement>('[data-testid="evidence-coverage"]')
        ?.scrollIntoView?.({ block: 'start' });
    }
    return () => {
      opener.current?.focus?.();
    };
  }, [open, section]);

  if (!open || comparison === null) return null;

  return (
    <div className={styles.backdrop} onClick={onClose} data-testid="route-details-backdrop">
      <div
        ref={sheet}
        className={styles.sheet}
        role="dialog"
        aria-modal="true"
        // Focusable itself, so a click on its text keeps focus inside the
        // dialog and Escape and the Tab trap keep working.
        tabIndex={-1}
        aria-labelledby="route-details-heading"
        data-testid="route-details"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.stopPropagation();
            onClose();
            return;
          }
          if (event.key !== 'Tab') return;
          // Keep focus inside the sheet while it is open.
          const focusable = sheet.current?.querySelectorAll<HTMLElement>(
            'button, [href], summary, input, [tabindex]:not([tabindex="-1"])',
          );
          if (!focusable || focusable.length === 0) return;
          const first = focusable[0]!;
          const last = focusable[focusable.length - 1]!;
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }}
      >
        <header className={styles.head}>
          <h2 className={styles.title} id="route-details-heading">
            <Icon name="fork" />
            {section === 'evidence' ? 'Route evidence' : 'Route details'}
          </h2>
          <button
            ref={closeButton}
            type="button"
            className={styles.close}
            onClick={onClose}
            aria-label="Close route details"
            data-testid="close-route-details"
          >
            ×
          </button>
        </header>
        <div className={styles.body}>
          <RouteComparisonView
            comparison={
              profileName === null
                ? comparison
                : { ...comparison, profile_display_name: profileName }
            }
            selectedRoute={selectedRoute}
            onSelectRoute={onSelectRoute}
            {...(journeySummary ? { journeySummary } : {})}
            {...(uphillLimit !== null
              ? { profileNote: `Custom uphill limit · ${limitText(uphillLimit)}` }
              : {})}
          />
        </div>
      </div>
    </div>
  );
}
