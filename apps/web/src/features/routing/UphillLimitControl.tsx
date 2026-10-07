'use client';

import { type CSSProperties, useId } from 'react';
import { Icon } from '@/components/Icon';
import { type UphillLimit, parseUphillLimit } from './types';
import styles from './Planner.module.css';

/** The slider's span. Any other limit can still be typed in the planning form. */
export const SLIDER_MIN = 1;
export const SLIDER_MAX = 12;
const SLIDER_STEP = 0.5;

/** A limit at the precision it was given: 5 reads "5.0%", 4.25 stays "4.25%". */
export function limitText(percent: number): string {
  return Number.isInteger(percent * 10) ? `${percent.toFixed(1)}%` : `${percent}%`;
}

export type UphillLimitControlProps = {
  readonly limit: UphillLimit;
  readonly onChange: (limit: UphillLimit) => void;
  /** Apply the current value to the journey on screen. */
  readonly onCommit: () => void;
  /** `card`: the planning form (17:3689). `slider`: beside a result (9:2101). */
  readonly variant: 'card' | 'slider';
  /** The chosen preset's gradient preference, to say what "off" means. */
  readonly prefersUnder?: number | null;
};

/**
 * "The steepest climb I can manage", off until the traveller turns it on.
 *
 * Off is not a default number: with no limit set, no gradient rules a path out
 * and the profile's preference only makes steep climbs cost more. On, the
 * number is sent exactly as given and becomes a hard limit — applied to the
 * gradient OpenStreetMap records where it has one and to the elevation
 * estimate otherwise.
 */
export function UphillLimitControl({
  limit,
  onChange,
  onCommit,
  variant,
  prefersUnder = null,
}: UphillLimitControlProps) {
  return variant === 'card' ? (
    <UphillCard limit={limit} onChange={onChange} onCommit={onCommit} prefersUnder={prefersUnder} />
  ) : (
    <UphillSlider limit={limit} onChange={onChange} onCommit={onCommit} />
  );
}

function offExplanation(prefersUnder: number | null): string {
  return prefersUnder === null
    ? 'Leave off and no climb is ruled out, or set a limit of your own.'
    : `Leave off to use the profile’s preference (climbs under ${prefersUnder}% cost less), or set a hard limit of your own.`;
}

function UphillCard({
  limit,
  onChange,
  onCommit,
  prefersUnder,
}: {
  readonly limit: UphillLimit;
  readonly onChange: (limit: UphillLimit) => void;
  readonly onCommit: () => void;
  readonly prefersUnder: number | null;
}) {
  const switchId = useId();
  const inputId = useId();
  const messageId = useId();
  const parsed = parseUphillLimit(limit);

  return (
    <div className={styles.uphillCard} data-testid="uphill-limit">
      <div className={styles.uphillHead}>
        <label className={styles.uphillTitle} htmlFor={switchId}>
          <Icon name="elevation" />
          Custom uphill limit
        </label>
        <input
          id={switchId}
          type="checkbox"
          role="switch"
          className={styles.switch}
          checked={limit.enabled}
          onChange={(event) => onChange({ ...limit, enabled: event.target.checked })}
          data-testid="uphill-limit-toggle"
        />
      </div>
      {limit.enabled ? (
        <div className={styles.uphillField}>
          <label htmlFor={inputId} className={styles.uphillLabel}>
            Steepest climb I can manage (%)
          </label>
          <input
            id={inputId}
            type="text"
            inputMode="decimal"
            autoComplete="off"
            className={styles.uphillInput}
            value={limit.text}
            onChange={(event) => onChange({ ...limit, text: event.target.value })}
            onBlur={onCommit}
            onKeyDown={(event) => {
              if (event.key === 'Enter') onCommit();
            }}
            aria-invalid={!parsed.ok}
            aria-describedby={messageId}
            data-testid="uphill-limit-input"
          />
          <p
            className={parsed.ok ? styles.uphillNote : styles.uphillError}
            id={messageId}
            data-testid="uphill-limit-note"
          >
            {parsed.ok
              ? `Climbs steeper than ${limit.text.trim()}% are ruled out, whether recorded or estimated.`
              : parsed.message}
          </p>
        </div>
      ) : (
        <p className={styles.uphillHelp}>{offExplanation(prefersUnder)}</p>
      )}
    </div>
  );
}

function UphillSlider({
  limit,
  onChange,
  onCommit,
}: {
  readonly limit: UphillLimit;
  readonly onChange: (limit: UphillLimit) => void;
  readonly onCommit: () => void;
}) {
  const rangeId = useId();
  const parsed = parseUphillLimit(limit);
  const percent = limit.enabled && parsed.ok && parsed.percent !== null ? parsed.percent : null;
  const position = Math.min(SLIDER_MAX, Math.max(SLIDER_MIN, percent ?? 5));
  const fill = limit.enabled ? ((position - SLIDER_MIN) / (SLIDER_MAX - SLIDER_MIN)) * 100 : 0;
  const mid = (SLIDER_MIN + SLIDER_MAX) / 2;

  return (
    <div className={styles.slider} data-testid="uphill-limit">
      <div className={styles.sliderHead}>
        <label className={styles.caps} htmlFor={rangeId}>
          Custom uphill limit · {percent === null ? 'off' : limitText(percent)}
        </label>
        <button
          type="button"
          role="switch"
          aria-checked={limit.enabled}
          aria-label="Custom uphill limit"
          className={styles.sliderState}
          onClick={() =>
            onChange({
              enabled: !limit.enabled,
              text: limit.text.trim() === '' ? String(position) : limit.text,
            })
          }
          data-testid="uphill-limit-toggle"
        >
          {limit.enabled ? 'Enabled' : 'Off'}
        </button>
      </div>
      <input
        id={rangeId}
        type="range"
        className={styles.range}
        min={SLIDER_MIN}
        max={SLIDER_MAX}
        step={SLIDER_STEP}
        value={position}
        disabled={!limit.enabled}
        style={{ '--fill': `${fill}%` } as CSSProperties}
        aria-valuetext={percent === null ? 'Off' : `${limitText(percent)} uphill`}
        onChange={(event) => onChange({ enabled: true, text: event.target.value })}
        // A drag is many changes and one decision: the journey re-runs when
        // the thumb is let go, not at every half percent on the way.
        onPointerUp={onCommit}
        onKeyUp={onCommit}
        onBlur={onCommit}
        data-testid="uphill-limit-range"
      />
      <div className={styles.ticks} aria-hidden="true">
        <span>{limitText(SLIDER_MIN)}</span>
        <span>{limitText(mid)}</span>
        <span>{limitText(SLIDER_MAX)}</span>
      </div>
    </div>
  );
}
