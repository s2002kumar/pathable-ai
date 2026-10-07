/**
 * The Golden Master's four evidence categories — Stairs, Grade, Crossings,
 * Surface — read from a comparison.
 *
 * Every figure here is either a field of the response or a deterministic
 * reduction of its segments. Where the response does not carry something the
 * design drew (a place name for a stairway, a "1.5 km of asphalt"), the fact is
 * left out rather than written in; where it carries a gap, the gap is the fact.
 *
 * The four stay separate on purpose. There is no total, no score and no
 * confidence: a surface record and a kerb record are different things, and
 * one number across them would mean nothing.
 */

import type { Route, RouteCompareResponse, RouteSegment } from '@pathable/contracts';
import { coverageRows, exclusionsOf, formatShare, gradeBasis } from './route-evidence';

/** The four production evidence labels, exactly as DESIGN.md names them. */
export type EvidenceKind = 'recorded' | 'derived' | 'not_recorded' | 'profile_rule';

export const EVIDENCE_LABELS: Readonly<Record<EvidenceKind, string>> = {
  recorded: 'Recorded · OSM',
  derived: 'Derived · HRDEM',
  not_recorded: 'Not recorded',
  profile_rule: 'Your profile rule',
};

/**
 * What the profile on screen declares, as far as the frontend knows it.
 *
 * `excludesSteps` comes from `/routes/profiles`; `uphillLimit` is the limit the
 * traveller typed; `prefersUnder` is the preset's gradient preference, which
 * costs a climb and never rules one out. Any of them may be unknown — the
 * profiles request can fail — and an unknown rule is simply not stated.
 */
export type ProfileRules = {
  readonly excludesSteps: boolean | null;
  readonly uphillLimit: number | null;
  readonly prefersUnder: number | null;
};

export const NO_RULES: ProfileRules = {
  excludesSteps: null,
  uphillLimit: null,
  prefersUnder: null,
};

export type Tone = 'good' | 'derived' | 'unknown' | 'barrier' | 'neutral';

export type FactFooter = {
  readonly icon: 'double-check' | 'arrow-down' | 'question' | 'stack' | 'stairs';
  readonly text: string;
  readonly tone: Tone;
};

export type CategoryKey = 'stairs' | 'grade' | 'crossings' | 'surface';

export type CategoryFact = {
  readonly key: CategoryKey;
  readonly label: string;
  readonly tags: readonly EvidenceKind[];
  /** The headline figure, or an em dash when there is none. */
  readonly value: string;
  readonly valueTone: Tone;
  readonly unit: string;
  /** "vs. <emphasis> <tail>", or a plain sentence when `emphasis` is empty. */
  readonly detail: {
    readonly lead: string;
    readonly emphasis: string;
    readonly emphasisTone: Tone;
    readonly tail: string;
  } | null;
  readonly footer: FactFooter | null;
};

/** A declared limit, repeated as it was typed: 5 reads "5", 4.5 reads "4.5". */
export function plainPercent(value: number): string {
  return `${Number.isInteger(value) ? value : String(value)}%`;
}

function plural(count: number, one: string, many: string): string {
  return count === 1 ? one : many;
}

function stairsPhrase(count: number): string {
  return `${count} recorded ${plural(count, 'stairway', 'stairways')}`;
}

/** Stairways on a route whose step count nobody recorded. */
export function uncountedStairways(route: Route): number {
  return route.segments.filter((segment) => segment.steps === 'yes' && segment.step_count == null)
    .length;
}

// ---------------------------------------------------------------------------
// Stairs
// ---------------------------------------------------------------------------

export function stairsFact(route: Route, other: Route | null, rules: ProfileRules): CategoryFact {
  const count = route.stairway_count;
  const stepsRow = coverageRows(route).find((row) => row.key === 'steps');
  const unknownShare = stepsRow?.parts.find((part) => part.kind === 'unknown')?.share ?? 0;
  const ruledOut = other !== null && exclusionsOf(other).some((item) => item.reason === 'steps');

  let detail: CategoryFact['detail'] = null;
  if (other !== null) {
    // "Recorded": the total is a floor, since a stairway may carry no count.
    const steps = other.step_count > 0 ? ` (${other.step_count} recorded steps)` : '';
    detail = {
      lead: 'vs. ',
      emphasis: stairsPhrase(other.stairway_count),
      emphasisTone: ruledOut ? 'barrier' : 'neutral',
      tail: ` on shortest path${steps}.`,
    };
  } else if (unknownShare > 0) {
    detail = {
      lead: `Step state not recorded on ${formatShare(unknownShare)} of this route.`,
      emphasis: '',
      emphasisTone: 'neutral',
      tail: '',
    };
  }

  let footer: FactFooter | null = null;
  if (rules.excludesSteps === true) {
    footer = { icon: 'double-check', text: EVIDENCE_LABELS.profile_rule, tone: 'good' };
  } else if (rules.excludesSteps === false && count > 0) {
    footer = { icon: 'stairs', text: 'Stairs cost extra; not ruled out', tone: 'neutral' };
  }

  return {
    key: 'stairs',
    label: 'Stairs',
    tags: unknownShare > 0 ? ['recorded', 'not_recorded'] : ['recorded'],
    value: String(count),
    valueTone: count === 0 ? 'good' : 'neutral',
    unit: `recorded ${plural(count, 'stairway', 'stairways')}`,
    detail,
    footer,
  };
}

// ---------------------------------------------------------------------------
// Grade
// ---------------------------------------------------------------------------

export function gradeFact(route: Route, other: Route | null, rules: ProfileRules): CategoryFact {
  const climb = route.gradient.steepest_uphill;
  const otherClimb = other?.gradient.steepest_uphill ?? null;

  const detail: CategoryFact['detail'] =
    other === null
      ? null
      : {
          lead: 'vs. ',
          emphasis:
            otherClimb === null ? 'no climb on record' : `${otherClimb.percent.toFixed(1)}%`,
          emphasisTone: 'unknown',
          tail: ' on shortest path.',
        };

  let footer: FactFooter | null = null;
  if (rules.uphillLimit !== null && climb !== null) {
    footer =
      climb.percent <= rules.uphillLimit
        ? {
            icon: 'arrow-down',
            text: `Within your ${plainPercent(rules.uphillLimit)} limit`,
            tone: 'derived',
          }
        : {
            icon: 'arrow-down',
            text: `Above your ${plainPercent(rules.uphillLimit)} limit`,
            tone: 'barrier',
          };
  } else if (rules.prefersUnder !== null) {
    footer = {
      icon: 'arrow-down',
      text: `Profile prefers climbs under ${plainPercent(rules.prefersUnder)}`,
      tone: 'derived',
    };
  }

  if (climb === null) {
    return {
      key: 'grade',
      label: 'Maximum grade',
      tags: ['not_recorded'],
      value: '—',
      valueTone: 'unknown',
      unit: 'No climb on record',
      detail,
      footer,
    };
  }

  const basis = gradeBasis(climb);
  return {
    key: 'grade',
    label: 'Maximum grade',
    tags: [basis === 'recorded' ? 'recorded' : 'derived'],
    value: `${climb.percent.toFixed(1)}%`,
    valueTone: basis === 'recorded' ? 'neutral' : 'derived',
    unit: 'Peak climb',
    detail,
    footer,
  };
}

// ---------------------------------------------------------------------------
// Crossings
// ---------------------------------------------------------------------------

function raisedKerbs(route: Route): number {
  return route.segments.filter((segment) => segment.is_crossing && segment.kerb === 'raised')
    .length;
}

export function crossingsFact(route: Route, other: Route | null): CategoryFact {
  const crossings = Math.max(0, route.crossing_count);
  const unknown = Math.min(crossings, Math.max(0, route.unknown_kerb_crossing_count));

  if (crossings === 0) {
    return {
      key: 'crossings',
      label: 'Crossings',
      tags: ['recorded'],
      value: '0',
      valueTone: 'neutral',
      unit: 'mapped crossings',
      detail:
        other === null
          ? null
          : {
              lead: 'vs. ',
              emphasis: `${other.crossing_count}`,
              emphasisTone: 'neutral',
              tail: ' mapped on shortest path.',
            },
      footer: { icon: 'question', text: 'Unmapped crossings not counted', tone: 'unknown' },
    };
  }

  if (unknown > 0) {
    return {
      key: 'crossings',
      label: 'Crossings',
      tags: ['not_recorded'],
      value: String(unknown),
      valueTone: 'unknown',
      unit: `${plural(unknown, 'crossing has', 'crossings have')} no kerb record`,
      detail: {
        lead: `${crossings - unknown} of ${crossings} ${plural(crossings, 'crossing', 'crossings')} on this route ${plural(crossings - unknown, 'has', 'have')} a recorded kerb.`,
        emphasis: '',
        emphasisTone: 'neutral',
        tail: '',
      },
      footer: { icon: 'question', text: 'Missing stays unknown', tone: 'unknown' },
    };
  }

  const raised = raisedKerbs(route);
  return {
    key: 'crossings',
    label: 'Crossings',
    tags: ['recorded'],
    value: String(crossings),
    valueTone: raised > 0 ? 'barrier' : 'neutral',
    unit: `${plural(crossings, 'crossing', 'crossings')}, kerb recorded`,
    detail:
      raised > 0
        ? {
            lead: '',
            emphasis: `${raised} with a raised kerb`,
            emphasisTone: 'barrier',
            tail: ', as recorded.',
          }
        : null,
    footer: { icon: 'double-check', text: 'Kerb type recorded at each', tone: 'neutral' },
  };
}

// ---------------------------------------------------------------------------
// Surface
// ---------------------------------------------------------------------------

const SURFACE_NAMES: Readonly<Record<Exclude<RouteSegment['surface_class'], 'unknown'>, string>> = {
  paved: 'paved',
  compacted: 'compacted',
  rough: 'rough',
};

/** The surface class covering most of the route's recorded length, if any. */
export function dominantSurface(route: Route): { name: string; share: number } | null {
  const lengths = new Map<string, number>();
  let recorded = 0;
  for (const segment of route.segments) {
    if (segment.surface_class === 'unknown') continue;
    recorded += segment.length_m;
    lengths.set(
      segment.surface_class,
      (lengths.get(segment.surface_class) ?? 0) + segment.length_m,
    );
  }
  if (recorded <= 0) return null;
  const [name, length] = [...lengths.entries()].sort(([, a], [, b]) => b - a)[0]!;
  return { name: SURFACE_NAMES[name as keyof typeof SURFACE_NAMES], share: length / recorded };
}

export function surfaceFact(route: Route): CategoryFact {
  const missing = route.evidence_coverage?.['surface'];
  if (typeof missing !== 'number') {
    return {
      key: 'surface',
      label: 'Surface',
      tags: ['not_recorded'],
      value: '—',
      valueTone: 'unknown',
      unit: 'Not reported',
      detail: {
        lead: 'The response carries no surface record for this route.',
        emphasis: '',
        emphasisTone: 'neutral',
        tail: '',
      },
      footer: { icon: 'question', text: 'Missing stays unknown', tone: 'unknown' },
    };
  }
  const gap = Math.min(1, Math.max(0, missing));
  const recorded = 1 - gap;
  const dominant = dominantSurface(route);
  const footer: FactFooter | null =
    dominant === null
      ? { icon: 'question', text: 'Missing stays unknown', tone: 'unknown' }
      : dominant.share >= 0.5
        ? { icon: 'stack', text: `Mostly ${dominant.name} where recorded`, tone: 'neutral' }
        : { icon: 'stack', text: 'Mixed surfaces where recorded', tone: 'neutral' };

  return {
    key: 'surface',
    label: 'Surface',
    tags: gap > 0 ? ['recorded', 'not_recorded'] : ['recorded'],
    value: formatShare(recorded),
    valueTone: 'neutral',
    unit: 'Recorded',
    detail: {
      lead:
        gap > 0
          ? `Surface recorded on ${formatShare(recorded)} of this route; ${formatShare(gap)} not recorded.`
          : 'Surface recorded along the whole route.',
      emphasis: '',
      emphasisTone: 'neutral',
      tail: '',
    },
    footer,
  };
}

/** All four, in the order the design reads them. */
export function categoryFacts(
  route: Route,
  other: Route | null,
  rules: ProfileRules,
): CategoryFact[] {
  return [
    stairsFact(route, other, rules),
    gradeFact(route, other, rules),
    crossingsFact(route, other),
    surfaceFact(route),
  ];
}

// ---------------------------------------------------------------------------
// Where the evidence came from
// ---------------------------------------------------------------------------

/**
 * "Evaluated with OpenStreetMap & NRCan HRDEM": the sources this answer
 * actually rests on. Elevation is named only when a route's gradient was
 * derived from it.
 */
export function evaluatedWith(comparison: RouteCompareResponse): string {
  const network =
    comparison.dataset.source_type === 'osm' ? 'OpenStreetMap' : comparison.dataset.source_name;
  const routes = [comparison.standard_route, comparison.accessible_route].filter(
    (route): route is Route => route !== null && route !== undefined,
  );
  const usedElevation = routes.some(
    (route) =>
      route.gradient_source === 'derived_elevation' ||
      route.gradient.estimated_fraction > 0 ||
      route.gradient.steepest_uphill?.source === 'derived_elevation',
  );
  return usedElevation ? `Evaluated with ${network} & NRCan HRDEM` : `Evaluated with ${network}`;
}

/** How old the map data is, by its publication date, or null when unreported. */
export function mapAge(comparison: RouteCompareResponse): string | null {
  const days = comparison.dataset.evidence_age_days;
  if (days === null || days === undefined) return null;
  if (days === 0) return 'Map data from today';
  return `Map data ${days} ${days === 1 ? 'day' : 'days'} old`;
}
