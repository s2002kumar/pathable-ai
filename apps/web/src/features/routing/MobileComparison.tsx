'use client';

import { type KeyboardEvent, type ReactNode, useId } from 'react';
import type { ProfileKey, Route, RouteCompareResponse } from '@pathable/contracts';
import { Icon } from '@/components/Icon';
import { PROFILE_OPTIONS } from './ProfileChooser';
import { limitText } from './UphillLimitControl';
import { type RouteVariant, exclusionsOf, formatShare, gradeBasis } from './route-evidence';
import {
  EVIDENCE_LABELS,
  type ProfileRules,
  crossingsFact,
  uncountedStairways,
} from './route-facts';
import { type Endpoint, formatDistance } from './types';
import styles from './MobileComparison.module.css';

/** A distance difference to a tenth of a metre, as the verified example reads it. */
function preciseDistance(metres: number): string {
  return metres >= 1000 ? `${(metres / 1000).toFixed(2)} km` : `${metres.toFixed(1)} m`;
}

/** Recorded length of a route by surface: paved, other recorded, not recorded. */
function surfaceShares(route: Route): { paved: number; other: number; unknown: number } {
  const total = route.segments.reduce((sum, segment) => sum + segment.length_m, 0);
  if (total <= 0) return { paved: 0, other: 0, unknown: 1 };
  let paved = 0;
  let other = 0;
  for (const segment of route.segments) {
    if (segment.surface_class === 'paved') paved += segment.length_m;
    else if (segment.surface_class !== 'unknown') other += segment.length_m;
  }
  return { paved: paved / total, other: other / total, unknown: 1 - (paved + other) / total };
}

/**
 * The phone's answer (Golden Master 17:2865): a sheet under the map with the
 * journey, the two routes as options, the four categories side by side with
 * the shortest route, and the two ways into the full record.
 *
 * Same facts as the desktop panel and dock, the same functions underneath;
 * only the arrangement is the phone's.
 */
export function MobileComparison({
  comparison,
  profileKey,
  profileName,
  rules,
  origin,
  destination,
  selectedRoute,
  onSelectRoute,
  onRouteDetails,
  onViewEvidence,
  editor,
  editorOpen,
  onEditorToggle,
}: {
  readonly comparison: RouteCompareResponse;
  /** The preset the answer was asked with, for its glyph. */
  readonly profileKey: ProfileKey;
  readonly profileName: string;
  readonly rules: ProfileRules;
  readonly origin: Endpoint | null;
  readonly destination: Endpoint | null;
  readonly selectedRoute: RouteVariant;
  readonly onSelectRoute: (variant: RouteVariant) => void;
  readonly onRouteDetails: () => void;
  readonly onViewEvidence: () => void;
  /** The journey and profile controls, behind a disclosure. */
  readonly editor: ReactNode;
  readonly editorOpen: boolean;
  readonly onEditorToggle: (open: boolean) => void;
}) {
  const { standard_route: standard, accessible_route: accessible } = comparison;
  if (!standard || !accessible) return null;

  const usesElevation = [standard, accessible].some(
    (route) => route.gradient_source === 'derived_elevation',
  );
  const extra = comparison.extra_distance_m;
  const fraction = comparison.extra_distance_fraction;
  const exclusions = exclusionsOf(standard);
  const stairsRuledOut = exclusions.some((item) => item.reason === 'steps');
  const climb = accessible.gradient.steepest_uphill;
  const otherClimb = standard.gradient.steepest_uphill;
  const crossing = crossingsFact(accessible, standard);
  const surfaceGap = accessible.evidence_coverage?.['surface'];
  const shares = surfaceShares(accessible);
  const uncounted = uncountedStairways(standard);
  const profileIcon =
    PROFILE_OPTIONS.find((option) => option.key === profileKey)?.icon ?? 'profile-walking';

  const move = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    const next: RouteVariant = selectedRoute === 'accessible' ? 'standard' : 'accessible';
    onSelectRoute(next);
    event.currentTarget
      .closest('[role="radiogroup"]')
      ?.querySelector<HTMLButtonElement>(`[role="radio"][data-variant="${next}"]`)
      ?.focus();
  };

  return (
    <section
      className={styles.sheet}
      aria-labelledby="route-planner-heading"
      data-testid="plan-journey"
      data-layout="compare"
    >
      <span className={styles.handle} aria-hidden="true" />

      <div className={styles.journey}>
        <div className={styles.journeyHead}>
          <h1 className={styles.profileChip} id="route-planner-heading">
            <Icon name={profileIcon} size={11} />
            {profileName} profile
          </h1>
          <span className={styles.journeyNote}>
            {accessible.stairway_count} recorded{' '}
            {accessible.stairway_count === 1 ? 'stairway' : 'stairways'}
          </span>
          <span className={styles.sources}>{usesElevation ? 'OSM · HRDEM' : 'OSM'}</span>
        </div>
        <ol className={styles.points}>
          {(
            [
              ['origin', 'Origin', origin],
              ['destination', 'Destination', destination],
            ] as const
          ).map(([role, label, endpoint]) => (
            <li key={role} className={styles.point}>
              <span className={styles.pointRing} data-role={role} aria-hidden="true">
                <span />
              </span>
              <span className={styles.pointText}>
                <span className={styles.pointLabel}>{label}</span>
                <span className={styles.pointName}>{endpoint?.label ?? 'Not set'}</span>
              </span>
            </li>
          ))}
        </ol>
      </div>

      <details
        className={styles.editor}
        open={editorOpen}
        onToggle={(event) => onEditorToggle(event.currentTarget.open)}
        data-testid="mobile-edit"
      >
        <summary>Edit journey or profile</summary>
        <div className={styles.editorBody}>{editor}</div>
      </details>

      <div className={styles.optionsHead}>
        <h2 className={styles.optionsTitle}>Available options</h2>
        <span className={styles.optionsNote}>Route comparison</span>
      </div>
      <div
        className={styles.options}
        role="radiogroup"
        aria-label="Route drawn in front on the map"
        data-testid="route-difference"
      >
        <RouteOption
          variant="accessible"
          checked={selectedRoute === 'accessible'}
          onSelect={onSelectRoute}
          onKeyDown={move}
          testId="difference-accessible"
          title={`${profileName} route`}
        >
          <span className={styles.optionHead}>
            <span className={styles.optionFigures}>
              <span className={styles.optionLine}>
                <span className={styles.distance}>{formatDistance(accessible.distance_m)}</span>
                {selectedRoute === 'accessible' ? (
                  <span className={styles.activePill}>Active Selection</span>
                ) : null}
              </span>
              <span className={styles.optionMeta} data-testid="difference-extra">
                {typeof extra === 'number' && extra >= 0.5 ? (
                  <>
                    +{preciseDistance(extra)}
                    <span aria-hidden="true"> • </span>
                    <span className={styles.metaWarm}>
                      {typeof fraction === 'number' ? `(+${Math.round(fraction * 100)}%) ` : ''}vs
                      shortest route
                    </span>
                  </>
                ) : typeof extra === 'number' && extra <= -0.5 ? (
                  `${preciseDistance(-extra)} shorter than the shortest route`
                ) : (
                  'Same length as the shortest route'
                )}
              </span>
            </span>
            <span className={styles.optionBadge} data-tone="good" aria-hidden="true">
              <Icon name="check-circle-outline" />
            </span>
          </span>
          <span className={styles.tiles}>
            <span className={styles.tile}>
              <span
                className={styles.tileValue}
                data-tone={accessible.stairway_count === 0 ? 'good' : undefined}
              >
                {accessible.stairway_count}
              </span>
              <span className={styles.tileLabel}>Recorded Stairs</span>
            </span>
            <span className={styles.tile}>
              <span className={styles.tileValue}>
                {climb === null
                  ? EVIDENCE_LABELS.not_recorded
                  : gradeBasis(climb) === 'recorded'
                    ? 'OSM'
                    : 'HRDEM'}
              </span>
              <span className={styles.tileLabel}>Grade source</span>
            </span>
            <span className={styles.tile}>
              <span className={styles.tileValue} data-tone="derived">
                Explicit
              </span>
              <span className={styles.tileLabel}>Unknowns shown</span>
            </span>
          </span>
        </RouteOption>

        <RouteOption
          variant="standard"
          checked={selectedRoute === 'standard'}
          onSelect={onSelectRoute}
          onKeyDown={move}
          testId="difference-shortest"
          title="Shortest pedestrian route"
        >
          <span className={styles.optionHead}>
            <span className={styles.optionFigures}>
              <span className={styles.optionLine}>
                <span className={styles.distance}>{formatDistance(standard.distance_m)}</span>
                {typeof extra === 'number' && extra >= 0.5 ? (
                  <span className={styles.plainPill}>{formatDistance(extra)} shorter</span>
                ) : null}
              </span>
              <span className={styles.optionMeta}>
                {standard.stairway_count} {standard.stairway_count === 1 ? 'stairway' : 'stairways'}
                {exclusions.length > 0 ? (
                  <>
                    <span aria-hidden="true"> • </span>
                    <span className={styles.metaBarrier}>
                      Incompatible with {profileName} profile
                    </span>
                  </>
                ) : null}
              </span>
            </span>
            {exclusions.length > 0 ? (
              <span className={styles.optionBadge} data-tone="barrier" aria-hidden="true">
                <Icon name="warning" size={18} />
              </span>
            ) : null}
          </span>
          {standard.stairway_count > 0 ? (
            <span className={styles.chips} data-testid="route-blocked">
              <span className={styles.chip} data-tone={stairsRuledOut ? 'barrier' : 'neutral'}>
                <Icon name="stairs" size={10} />
                {standard.stairway_count} recorded{' '}
                {standard.stairway_count === 1 ? 'stairway' : 'stairways'}
              </span>
              <span className={styles.chip} data-tone="unknown">
                <Icon name="trending-up" size={11} />
                {/* "Recorded": the total is a floor, since a stairway may carry no count. */}
                {standard.step_count > 0
                  ? `${standard.step_count} recorded steps`
                  : 'Step count not recorded'}
                {standard.step_count > 0 && uncounted > 0
                  ? ` · ${uncounted} ${uncounted === 1 ? 'count' : 'counts'} missing`
                  : ''}
              </span>
            </span>
          ) : null}
        </RouteOption>
      </div>

      <section className={styles.why} aria-labelledby="mobile-why-heading">
        <div className={styles.whyHead}>
          <h2 className={styles.whyTitle} id="mobile-why-heading">
            <Icon name="fact-check" />
            Why this route is different
          </h2>
          <span className={styles.whyNote}>Evidence base</span>
        </div>
        <ul className={styles.rows}>
          <li className={styles.row} data-testid="mobile-stairs">
            <div className={styles.rowHead}>
              <span className={styles.rowName}>
                <Icon name="stairs" size={12} />
                Stairs
              </span>
              <span className={styles.tags}>
                <span className={styles.tag}>{EVIDENCE_LABELS.recorded}</span>
                {rules.excludesSteps ? (
                  <span className={styles.tag} data-tone="good">
                    {EVIDENCE_LABELS.profile_rule}
                  </span>
                ) : null}
              </span>
            </div>
            <p className={styles.versus}>
              <span data-tone="good">
                {accessible.stairway_count} recorded{' '}
                {accessible.stairway_count === 1 ? 'stairway' : 'stairways'}
              </span>
              <span>vs</span>
              <span data-tone={stairsRuledOut ? 'barrier' : undefined}>
                {standard.stairway_count} on shortest
              </span>
            </p>
          </li>
          <li className={styles.row} data-testid="mobile-grade">
            <div className={styles.rowHead}>
              <span className={styles.rowName}>
                <Icon name="trending-up" size={13} />
                Grade
              </span>
              <span className={styles.tags}>
                <span className={styles.tag}>
                  {climb === null
                    ? EVIDENCE_LABELS.not_recorded
                    : gradeBasis(climb) === 'recorded'
                      ? EVIDENCE_LABELS.recorded
                      : EVIDENCE_LABELS.derived}
                </span>
                {rules.uphillLimit !== null ? (
                  <span className={styles.tag} data-tone="good">
                    ≤ {limitText(rules.uphillLimit)} limit
                  </span>
                ) : null}
              </span>
            </div>
            <p className={styles.versus}>
              <span data-tone="good">
                {climb === null ? 'No climb on record' : `Peak ${climb.percent.toFixed(1)}%`}
              </span>
              <span>vs</span>
              <span data-tone="unknown">
                {otherClimb === null
                  ? 'none on shortest'
                  : `${otherClimb.percent.toFixed(1)}% on shortest`}
              </span>
            </p>
          </li>
          <li className={styles.row} data-testid="mobile-crossings">
            <div className={styles.rowHead}>
              <span className={styles.rowName}>
                <Icon name="fork" size={13} />
                Crossings
              </span>
              <span className={styles.tags}>
                <span className={styles.tag}>
                  {EVIDENCE_LABELS[crossing.tags[0] ?? 'recorded']}
                </span>
              </span>
            </div>
            <p className={styles.rowText}>
              {crossing.value === '0'
                ? 'No crossing is mapped on this route; an unmapped one is not counted.'
                : crossing.tags.includes('not_recorded')
                  ? `${crossing.value} ${crossing.unit}. Missing kerb information stays unknown.`
                  : `${crossing.value} ${crossing.unit}.`}
            </p>
          </li>
          <li className={styles.row} data-testid="mobile-surface">
            <div className={styles.rowHead}>
              <span className={styles.rowName}>
                <Icon name="surface-pattern" size={12} />
                Surface
              </span>
              <span className={styles.tags}>
                {typeof surfaceGap === 'number' && surfaceGap < 1 ? (
                  <span className={styles.tag}>{EVIDENCE_LABELS.recorded}</span>
                ) : null}
                {typeof surfaceGap !== 'number' || surfaceGap > 0 ? (
                  <span className={styles.tag} data-tone="unknown">
                    {EVIDENCE_LABELS.not_recorded}
                  </span>
                ) : null}
              </span>
            </div>
            <p className={styles.versus}>
              <span className={styles.plain}>
                {typeof surfaceGap === 'number'
                  ? `${formatShare(1 - surfaceGap)} recorded`
                  : 'Not reported'}
              </span>
              <span className={styles.mono}>
                {typeof surfaceGap === 'number' ? `${formatShare(surfaceGap)} unknown` : ''}
              </span>
            </p>
            <span className={styles.bar} aria-hidden="true">
              <span data-kind="paved" style={{ width: `${shares.paved * 100}%` }} />
              <span data-kind="other" style={{ width: `${shares.other * 100}%` }} />
              <span data-kind="unknown" style={{ width: `${shares.unknown * 100}%` }} />
            </span>
            <p className={styles.rowFoot}>No inference</p>
          </li>
        </ul>
      </section>

      <div className={styles.actions}>
        <button
          type="button"
          className={styles.primary}
          onClick={onRouteDetails}
          data-testid="open-route-details"
        >
          Route Details
          <Icon name="arrow-forward" />
        </button>
        <button
          type="button"
          className={styles.secondary}
          onClick={onViewEvidence}
          data-testid="view-evidence"
        >
          <Icon name="book" size={17} />
          View Evidence &amp; Source Data
        </button>
      </div>
    </section>
  );
}

function RouteOption({
  variant,
  checked,
  onSelect,
  onKeyDown,
  testId,
  title,
  children,
}: {
  readonly variant: RouteVariant;
  readonly checked: boolean;
  readonly onSelect: (variant: RouteVariant) => void;
  readonly onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
  readonly testId: string;
  readonly title: string;
  readonly children: ReactNode;
}) {
  const titleId = useId();
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      tabIndex={checked ? 0 : -1}
      aria-labelledby={titleId}
      className={styles.option}
      data-variant={variant}
      data-testid={testId}
      onClick={() => onSelect(variant)}
      onKeyDown={onKeyDown}
    >
      <span className="visually-hidden" id={titleId}>
        {title}
      </span>
      {children}
    </button>
  );
}
