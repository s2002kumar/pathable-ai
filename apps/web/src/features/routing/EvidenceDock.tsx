'use client';

import type { Route } from '@pathable/contracts';
import { Icon, type IconName } from '@/components/Icon';
import {
  type CategoryFact,
  EVIDENCE_LABELS,
  type EvidenceKind,
  type ProfileRules,
  categoryFacts,
} from './route-facts';
import styles from './Planner.module.css';

const LEGEND: readonly EvidenceKind[] = ['recorded', 'derived', 'not_recorded', 'profile_rule'];

/** The column's primary evidence label; a gap beside it is stated in the detail line. */
function Tags({ fact }: { readonly fact: CategoryFact }) {
  return (
    <span className={styles.factTags}>
      {fact.tags.slice(0, 1).map((kind) => (
        <span
          key={kind}
          className={styles.tag}
          data-kind={kind}
          data-tone={kind === 'recorded' && fact.valueTone === 'good' ? 'good' : undefined}
        >
          {EVIDENCE_LABELS[kind]}
        </span>
      ))}
    </span>
  );
}

function Detail({ fact }: { readonly fact: CategoryFact }) {
  if (fact.detail === null) return null;
  const { lead, emphasis, emphasisTone, tail } = fact.detail;
  return (
    <p className={styles.factDetail}>
      {lead}
      {emphasis ? <span data-tone={emphasisTone}>{emphasis}</span> : null}
      {tail}
    </p>
  );
}

/**
 * "Why this route is different" (Golden Master 9:2177): the four categories
 * side by side, each with its own evidence label and its own comparison with
 * the shortest route.
 */
export function EvidenceDock({
  route,
  other,
  rules,
  profileName,
  onRouteDetails,
  onViewEvidence,
}: {
  readonly route: Route;
  readonly other: Route;
  readonly rules: ProfileRules;
  readonly profileName: string;
  readonly onRouteDetails: () => void;
  readonly onViewEvidence: () => void;
}) {
  const facts = categoryFacts(route, other, rules);
  return (
    <section
      className={`${styles.dock} ${styles.enter}`}
      aria-labelledby="dock-heading"
      data-testid="evidence-dock"
    >
      <div className={styles.dockIntro}>
        <div>
          <h2 className={styles.dockTitle} id="dock-heading">
            <Icon name="why-different" />
            Why this route is different
          </h2>
          <p className={styles.dockLead}>
            Comparing the {profileName.toLowerCase()} route with the shortest pedestrian route using
            recorded and derived accessibility evidence.
          </p>
        </div>
        <div className={styles.legend}>
          <p className={styles.legendTitle}>Evidence legend</p>
          <p className={styles.legendTags}>
            {LEGEND.map((kind) => (
              <span key={kind} className={styles.tag}>
                {EVIDENCE_LABELS[kind]}
              </span>
            ))}
          </p>
        </div>
      </div>

      <ul className={styles.facts} aria-label="Evidence by category">
        {facts.map((fact) => (
          <li key={fact.key} className={styles.fact} data-testid={`dock-${fact.key}`}>
            <div>
              <div className={styles.factHead}>
                <span className={styles.factLabel}>{fact.label}</span>
                <Tags fact={fact} />
              </div>
              <p className={styles.factFigure}>
                <span className={styles.factValue} data-tone={fact.valueTone}>
                  {fact.value}
                </span>
                <span className={styles.factUnit}>{fact.unit}</span>
              </p>
              <Detail fact={fact} />
            </div>
            {fact.footer ? (
              <p className={styles.factFooter} data-tone={fact.footer.tone}>
                <Icon name={fact.footer.icon} size={16} />
                {fact.footer.text}
              </p>
            ) : null}
          </li>
        ))}
      </ul>

      <div className={styles.dockActions}>
        <button
          type="button"
          className={`${styles.primaryButton} ${styles.dockPrimary}`}
          onClick={onRouteDetails}
          data-testid="open-route-details"
        >
          <Icon name="fork" />
          Route Details
        </button>
        <button
          type="button"
          className={`${styles.secondaryButton} ${styles.dockSecondary}`}
          onClick={onViewEvidence}
          data-testid="view-evidence"
        >
          <Icon name="eye" />
          View Evidence
        </button>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// The data-gap dock (17:3901)
// ---------------------------------------------------------------------------

const GAP_ICONS: Readonly<Record<CategoryFact['key'], IconName>> = {
  stairs: 'stairs',
  grade: 'trending-up',
  crossings: 'accessible',
  surface: 'stack',
};

/** The headline and the line under it, for a category seen as a record. */
function gapCopy(fact: CategoryFact, route: Route): { title: string; body: string } {
  switch (fact.key) {
    case 'stairs':
      return {
        title: `${fact.value} ${fact.unit}`,
        body:
          route.stairway_count === 0
            ? 'OSM records no stairways on this route'
            : 'Each is a stairway OSM records on this route',
      };
    case 'grade':
      return fact.tags[0] === 'derived'
        ? {
            title: 'Grade derived from HRDEM',
            body: `Deterministic elevation-derived grade · peak ${fact.value}`,
          }
        : fact.tags[0] === 'recorded'
          ? { title: 'Grade recorded in OpenStreetMap', body: `Steepest climb ${fact.value}.` }
          : {
              title: 'No gradient on record',
              body: 'Neither OpenStreetMap nor the elevation model gives one.',
            };
    case 'crossings':
      return fact.tags.includes('not_recorded')
        ? {
            title: 'Kerb information not recorded at some crossings',
            body: 'Missing kerb tags remain unknown; PathAble does not infer a ramp.',
          }
        : route.crossing_count === 0
          ? {
              title: 'No mapped crossings',
              body: 'OSM maps no crossing on this route; an unmapped one is not counted.',
            }
          : {
              title: 'Kerb recorded at every crossing',
              body: 'The kerb type is on record at each.',
            };
    case 'surface':
      // Not reported first: a response with no surface record says nothing
      // about the segments, so "some have no surface tag" would be invented.
      return fact.value === '—'
        ? { title: 'Surface not reported', body: 'The response carries no surface record.' }
        : fact.tags.includes('not_recorded')
          ? {
              title: 'Surface evidence is incomplete',
              body: `Some route segments have no surface tag in OpenStreetMap (${fact.value} recorded).`,
            }
          : { title: 'Surface recorded along the route', body: 'Every segment has a surface tag.' };
  }
}

export function GapDock({
  route,
  rules,
  onViewEvidence,
}: {
  readonly route: Route;
  readonly rules: ProfileRules;
  readonly onViewEvidence: () => void;
}) {
  const facts = categoryFacts(route, null, rules);
  return (
    <section
      className={`${styles.gapDock} ${styles.enter}`}
      aria-labelledby="gap-dock-heading"
      data-testid="gap-dock"
    >
      <div className={styles.gapDockHead}>
        <div className={styles.gapDockTitle}>
          <div>
            <h2 className={styles.gapDockHeading} id="gap-dock-heading">
              Category-Specific Evidence &amp; Data Gaps
            </h2>
            <p className={styles.gapDockSub}>
              Category-specific evidence only — no aggregate confidence score
            </p>
          </div>
        </div>
        <button
          type="button"
          className={`${styles.secondaryButton} ${styles.gapDockButton}`}
          onClick={onViewEvidence}
          data-testid="view-evidence"
        >
          <Icon name="book" />
          View Evidence
        </button>
      </div>

      <ul className={styles.gapCards} aria-label="Evidence by category">
        {facts.map((fact) => {
          const gap = fact.tags.includes('not_recorded');
          const copy = gapCopy(fact, route);
          // A limit is reported as met or exceeded (gradeFact), never as a
          // tick: the route on show may be the shortest one, above the limit.
          const footer =
            fact.key === 'stairs' && rules.excludesSteps
              ? { icon: 'check-circle' as const, text: EVIDENCE_LABELS.profile_rule, tone: 'good' }
              : gap
                ? {
                    icon: 'question' as const,
                    text:
                      fact.key === 'crossings'
                        ? EVIDENCE_LABELS.not_recorded
                        : 'Missing stays unknown',
                    tone: 'unknown',
                  }
                : fact.footer
                  ? { icon: fact.footer.icon, text: fact.footer.text, tone: fact.footer.tone }
                  : null;
          return (
            <li
              key={fact.key}
              className={styles.gapCard}
              data-gap={gap}
              data-testid={`gap-${fact.key}`}
            >
              <div className={styles.gapCardHead}>
                <span className={styles.gapCardName}>
                  <Icon name={GAP_ICONS[fact.key]} size={18} />
                  {fact.key === 'grade' ? 'Grade' : fact.label}
                </span>
                <span className={styles.factTags}>
                  {fact.tags.map((kind) => (
                    <span key={kind} className={styles.tag} data-kind={kind}>
                      {EVIDENCE_LABELS[kind]}
                    </span>
                  ))}
                </span>
              </div>
              <div>
                <p className={styles.gapCardTitle}>{copy.title}</p>
                <p className={styles.gapCardBody}>{copy.body}</p>
              </div>
              {footer ? (
                <p className={styles.gapCardFooter} data-tone={footer.tone}>
                  <Icon name={footer.icon} size={18} />
                  {footer.text}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>

      <p className={styles.philosophy}>
        <Icon name="info" />
        <span>
          <strong>Evidence Philosophy:</strong> Open data gaps are highlighted, not smoothed over.
          PathAble presents what is recorded in OSM and derived from NRCan elevation, leaving
          unknown conditions explicit.
        </span>
      </p>
    </section>
  );
}
