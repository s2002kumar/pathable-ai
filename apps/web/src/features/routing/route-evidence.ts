/**
 * What a comparison says, reduced to the few facts a person reads first.
 *
 * Every function here reads the response as data — segments, counts, fractions
 * and each explanation's `basis` — and never the wording of a summary. The
 * interface above it only arranges what these functions return, so the rules
 * that decide what somebody is told live in one place and are tested as rules.
 *
 * Three rules run through all of it:
 *
 * - **Missing is not clear.** A share with no record is drawn and labelled as
 *   unknown, never folded into "fine".
 * - **Recorded, estimated and profile rule stay apart.** A gradient a mapper
 *   wrote down and one an elevation model inferred are different facts.
 * - **Nothing is invented.** Where the response does not carry a figure, the
 *   answer is "not reported", not a default.
 */

import type {
  EvidenceBasis,
  GradeExtreme,
  Route,
  RouteCompareResponse,
  RouteExplanation,
  RouteSegment,
} from '@pathable/contracts';
import { differenceIsBelowDisplayPrecision, routesSharePath } from './route-identity';

export type RouteVariant = 'standard' | 'accessible';
export type ExclusionReason = NonNullable<RouteSegment['excluded_by_profile']>;

// ---------------------------------------------------------------------------
// Hard incompatibility
// ---------------------------------------------------------------------------

export type RouteExclusion = {
  readonly reason: ExclusionReason;
  /** Segments of the route the chosen profile rules out for this reason. */
  readonly segmentIndexes: readonly number[];
  /** Steps recorded on those segments; a floor, since some carry no count. */
  readonly recordedSteps: number;
};

const EXCLUSION_ORDER: readonly ExclusionReason[] = [
  'steps',
  'too_steep',
  'too_narrow',
  'surface_excluded',
  'smoothness_excluded',
  'foot_prohibited',
];

/**
 * The hard limits a route breaks for the chosen profile, grouped by reason.
 *
 * Read from each segment's `excluded_by_profile`, which the API sets on the
 * shortest route only. It is the single source for "this profile cannot use
 * this route": a route is never judged unusable from its stairway count or
 * from an explanation's text, because crutches allow stairs and a stairway is
 * then a cost, not a wall.
 */
export function exclusionsOf(route: Route | null | undefined): RouteExclusion[] {
  if (!route) return [];
  const byReason = new Map<ExclusionReason, { indexes: number[]; steps: number }>();
  route.segments.forEach((segment, index) => {
    const reason = segment.excluded_by_profile;
    if (reason === null || reason === undefined) return;
    const entry = byReason.get(reason) ?? { indexes: [], steps: 0 };
    entry.indexes.push(index);
    entry.steps += segment.step_count ?? 0;
    byReason.set(reason, entry);
  });
  return EXCLUSION_ORDER.filter((reason) => byReason.has(reason)).map((reason) => {
    const entry = byReason.get(reason)!;
    return { reason, segmentIndexes: entry.indexes, recordedSteps: entry.steps };
  });
}

/** How one group of excluded segments reads, singular or plural. */
export function exclusionLabel(exclusion: RouteExclusion): string {
  const count = exclusion.segmentIndexes.length;
  switch (exclusion.reason) {
    case 'steps':
      return `${count} ${count === 1 ? 'stairway' : 'stairways'}`;
    case 'too_steep':
      return `${count} ${count === 1 ? 'segment' : 'segments'} above your gradient limit`;
    case 'too_narrow':
      return `${count} ${count === 1 ? 'segment' : 'segments'} narrower than your limit`;
    case 'surface_excluded':
      return `${count} ${count === 1 ? 'segment' : 'segments'} of excluded surface`;
    case 'smoothness_excluded':
      return `${count} ${count === 1 ? 'segment' : 'segments'} in excluded condition`;
    case 'foot_prohibited':
      return `${count} ${count === 1 ? 'segment' : 'segments'} closed to pedestrians`;
  }
}

// ---------------------------------------------------------------------------
// Time
// ---------------------------------------------------------------------------

export type RouteTime =
  | { readonly kind: 'estimate'; readonly seconds: number }
  /** The chosen profile cannot use this route, so it has no time for them. */
  | { readonly kind: 'unavailable' }
  /** Timed at a different assumed pace from the route beside it. */
  | { readonly kind: 'not_comparable' };

/**
 * Whether a route gets a travel time, for the traveller who chose the profile.
 *
 * A route the profile cannot use gets none: "16 min" beside a flight of stairs
 * reads as a trip a wheelchair user could take. And two estimates only sit side
 * by side when they share an assumed pace, since otherwise part of the gap
 * between them is a difference in assumption, not in route.
 */
export function routeTime(route: Route, variant: RouteVariant, other: Route | null): RouteTime {
  if (variant === 'standard' && exclusionsOf(route).length > 0) return { kind: 'unavailable' };
  if (variant === 'standard' && other !== null && other.pace_profile !== route.pace_profile) {
    return { kind: 'not_comparable' };
  }
  return { kind: 'estimate', seconds: route.estimated_duration_seconds };
}

// ---------------------------------------------------------------------------
// The one-line answer
// ---------------------------------------------------------------------------

export type Verdict =
  | { readonly kind: 'detour'; readonly extraM: number; readonly fraction: number | null }
  | { readonly kind: 'shorter'; readonly savedM: number }
  | { readonly kind: 'same_length' }
  | { readonly kind: 'same_route' }
  | { readonly kind: 'no_accessible_route'; readonly failure: string | null }
  | { readonly kind: 'no_shortest_route' }
  | { readonly kind: 'difference_not_reported' };

export function verdictOf(comparison: RouteCompareResponse): Verdict {
  const { standard_route: standard, accessible_route: accessible } = comparison;
  if (!accessible) {
    return { kind: 'no_accessible_route', failure: comparison.accessible_failure ?? null };
  }
  if (!standard) return { kind: 'no_shortest_route' };
  const extra = comparison.extra_distance_m;
  // Identity from segments or geometry, never from distance: two routes can
  // measure the same and be different paths. And identity only when the
  // figures agree — identical segments beside a reported 40 m difference is a
  // response contradicting itself, and the figure is what gets reported.
  if (
    routesSharePath(standard, accessible) &&
    (typeof extra !== 'number' || differenceIsBelowDisplayPrecision(extra))
  ) {
    return { kind: 'same_route' };
  }
  if (typeof extra !== 'number') return { kind: 'difference_not_reported' };
  if (differenceIsBelowDisplayPrecision(extra)) return { kind: 'same_length' };
  if (extra < 0) return { kind: 'shorter', savedM: -extra };
  return { kind: 'detour', extraM: extra, fraction: comparison.extra_distance_fraction ?? null };
}

// ---------------------------------------------------------------------------
// Why the routes differ
// ---------------------------------------------------------------------------

export type ReasonCategory =
  | 'stairs'
  | 'crossings'
  | 'gradient'
  | 'surface'
  | 'width'
  | 'access'
  | 'missing'
  | 'other';

export const CATEGORY_LABELS: Readonly<Record<ReasonCategory, string>> = {
  stairs: 'Stairs',
  crossings: 'Crossings and kerbs',
  gradient: 'Gradient',
  surface: 'Surface',
  width: 'Width',
  access: 'Access',
  missing: 'Missing information',
  other: 'Other',
};

/**
 * Which topic a statement is about.
 *
 * A statement resting on data nobody recorded is filed under "missing
 * information" whatever it is about: "avoids a crossing with no recorded kerb"
 * is a statement about an absence, and filing it under kerbs would read as a
 * fact about a kerb.
 */
export function categoryOf(explanation: RouteExplanation): ReasonCategory {
  if (explanation.basis === 'not_recorded') return 'missing';
  const code = explanation.code;
  if (code === 'avoids_stairs' || code === 'avoids_steps') return 'stairs';
  if (code.includes('kerb') || code.includes('crossing')) return 'crossings';
  if (code.includes('gradient') || code === 'avoids_too_steep') return 'gradient';
  if (code.includes('surface') || code.includes('smoothness')) return 'surface';
  if (code.includes('narrow') || code.includes('width')) return 'width';
  if (code === 'avoids_foot_prohibited') return 'access';
  return 'other';
}

export type RankedReason = {
  readonly explanation: RouteExplanation;
  readonly category: ReasonCategory;
  /** True when the shortest route breaks a limit the profile cannot relax. */
  readonly hardLimit: boolean;
};

export type ReasonGroup = {
  readonly category: ReasonCategory;
  readonly label: string;
  readonly reasons: readonly RankedReason[];
  readonly hardLimit: boolean;
};

function costOf(explanation: RouteExplanation): number {
  const value = explanation.evidence?.['cost_difference_effective_m'];
  return typeof value === 'number' ? value : 0;
}

/**
 * The statements that explain the difference, most decisive first.
 *
 * A hard limit ranks above any penalty: a stairway a wheelchair cannot climb
 * decides the route whatever else is true. Among penalties, the one that cost
 * the shortest route more — the engine reports it in effective metres — ranks
 * higher. Statements about the profile's own rules (the distance, the pace)
 * are not reasons; they are consequences, and they are left out.
 */
export function rankedReasons(comparison: RouteCompareResponse): RankedReason[] {
  return comparison.explanations
    .map((explanation, order) => ({ explanation, order }))
    .filter(({ explanation }) => explanation.basis !== 'profile_rule')
    .map(({ explanation, order }) => ({
      order,
      reason: {
        explanation,
        category: categoryOf(explanation),
        hardLimit: explanation.evidence?.['hard_limit'] === true,
      },
    }))
    .sort(
      (a, b) =>
        Number(b.reason.hardLimit) - Number(a.reason.hardLimit) ||
        costOf(b.reason.explanation) - costOf(a.reason.explanation) ||
        a.order - b.order,
    )
    .map(({ reason }) => reason);
}

/** The ranked statements, grouped by topic, groups in the order of their best statement. */
export function reasonGroups(comparison: RouteCompareResponse): ReasonGroup[] {
  const groups = new Map<ReasonCategory, RankedReason[]>();
  for (const reason of rankedReasons(comparison)) {
    const list = groups.get(reason.category) ?? [];
    list.push(reason);
    groups.set(reason.category, list);
  }
  return [...groups.entries()].map(([category, reasons]) => ({
    category,
    label: CATEGORY_LABELS[category],
    reasons,
    hardLimit: reasons.some((reason) => reason.hardLimit),
  }));
}

// ---------------------------------------------------------------------------
// What the map records along a route
// ---------------------------------------------------------------------------

export type CoverageKind = 'recorded' | 'estimated' | 'unknown';

export type CoveragePart = { readonly kind: CoverageKind; readonly share: number };

export type CoverageRow = {
  readonly key: 'gradient' | 'steps' | 'surface' | 'smoothness' | 'width' | 'kerb';
  readonly label: string;
  /** What the shares are shares of. */
  readonly denominator: 'route length' | 'crossings';
  readonly status: 'measured' | 'not_applicable' | 'not_reported';
  readonly parts: readonly CoveragePart[];
  /** Exact counts, where the denominator is countable. */
  readonly counts?: { readonly recorded: number; readonly total: number };
};

const LENGTH_ROWS: ReadonlyArray<{ key: 'surface' | 'smoothness' | 'width'; label: string }> = [
  { key: 'surface', label: 'Surface' },
  { key: 'smoothness', label: 'Surface condition' },
  { key: 'width', label: 'Width' },
];

function clampShare(value: number): number {
  return Math.min(1, Math.max(0, value));
}

/**
 * How much of a route each accessibility category is on record for.
 *
 * Every row keeps its own denominator. Gradient, surface, condition and width
 * are shares of the route's length, from the API's per-category
 * `evidence_coverage` — which reports what is *missing* — and, for gradient,
 * from the summary that splits recorded from estimated. Steps are not in that
 * figure, so their row is summed from the segments' own `steps` state, by
 * length, the same denominator. Kerbs are a fact about
 * crossings, so that row is counted over crossings, from the route's own
 * crossing counts rather than the length-weighted figure: the API reports a
 * kerb gap of 0 on a route with no crossings at all, which read as a bar would
 * say "every kerb recorded" about kerbs that do not exist.
 *
 * There is deliberately no total. One "% known" across categories would add a
 * surface to a width and mean nothing.
 */
export function coverageRows(route: Route): CoverageRow[] {
  const rows: CoverageRow[] = [];
  const gradient = route.gradient;
  rows.push({
    key: 'gradient',
    label: 'Gradient',
    denominator: 'route length',
    status: 'measured',
    parts: [
      { kind: 'recorded', share: clampShare(gradient.recorded_fraction) },
      { kind: 'estimated', share: clampShare(gradient.estimated_fraction) },
      { kind: 'unknown', share: clampShare(gradient.unknown_fraction) },
    ],
  });

  rows.push(stepsRow(route));

  const coverage = route.evidence_coverage;
  for (const { key, label } of LENGTH_ROWS) {
    const missing = coverage?.[key];
    if (typeof missing !== 'number') {
      rows.push({ key, label, denominator: 'route length', status: 'not_reported', parts: [] });
      continue;
    }
    const unknown = clampShare(missing);
    rows.push({
      key,
      label,
      denominator: 'route length',
      status: 'measured',
      parts: [
        { kind: 'recorded', share: 1 - unknown },
        { kind: 'unknown', share: unknown },
      ],
    });
  }

  const crossings = route.crossing_count;
  if (crossings <= 0) {
    rows.push({
      key: 'kerb',
      label: 'Kerbs at crossings',
      denominator: 'crossings',
      status: 'not_applicable',
      parts: [],
    });
  } else {
    const unknown = Math.min(crossings, Math.max(0, route.unknown_kerb_crossing_count));
    rows.push({
      key: 'kerb',
      label: 'Kerbs at crossings',
      denominator: 'crossings',
      status: 'measured',
      parts: [
        { kind: 'recorded', share: (crossings - unknown) / crossings },
        { kind: 'unknown', share: unknown / crossings },
      ],
      counts: { recorded: crossings - unknown, total: crossings },
    });
  }
  return rows;
}

/** How much of the route's length has a recorded step state, yes or no. */
function stepsRow(route: Route): CoverageRow {
  const total = route.segments.reduce((sum, segment) => sum + segment.length_m, 0);
  if (total <= 0) {
    return {
      key: 'steps',
      label: 'Steps',
      denominator: 'route length',
      status: 'not_reported',
      parts: [],
    };
  }
  const unknown = route.segments
    .filter((segment) => segment.steps === 'unknown')
    .reduce((sum, segment) => sum + segment.length_m, 0);
  const share = clampShare(unknown / total);
  return {
    key: 'steps',
    label: 'Steps',
    denominator: 'route length',
    status: 'measured',
    parts: [
      { kind: 'recorded', share: 1 - share },
      { kind: 'unknown', share },
    ],
  };
}

/**
 * A share as a whole percentage that never rounds a real amount to nothing, or
 * a partial amount to everything: 0.3% of a route is "<1%", not "0%".
 */
export function formatShare(share: number): string {
  if (share <= 0) return '0%';
  if (share >= 1) return '100%';
  const pct = share * 100;
  if (pct < 1) return '<1%';
  if (pct > 99) return '>99%';
  return `${Math.round(pct)}%`;
}

// ---------------------------------------------------------------------------
// Gradient
// ---------------------------------------------------------------------------

/** Where a gradient figure came from, as an evidence basis. */
export function gradeBasis(extreme: GradeExtreme): EvidenceBasis {
  return extreme.source === 'osm_incline' ? 'recorded' : 'estimated';
}

// ---------------------------------------------------------------------------
// Map evidence
// ---------------------------------------------------------------------------

export type EvidenceMarker = {
  readonly id: string;
  readonly kind: 'barrier' | 'gradient';
  readonly route: RouteVariant;
  readonly position: readonly [number, number];
  readonly label: string;
  readonly basis: EvidenceBasis;
};

/** The middle of a segment's own geometry, so a marker sits on the line it names. */
export function segmentMidpoint(segment: RouteSegment): [number, number] | null {
  const points = segment.coordinates;
  if (!points || points.length === 0) return null;
  if (points.length % 2 === 1) {
    const [lng, lat] = points[(points.length - 1) / 2]!;
    return [lng, lat];
  }
  const [aLng, aLat] = points[points.length / 2 - 1]!;
  const [bLng, bLat] = points[points.length / 2]!;
  return [(aLng + bLng) / 2, (aLat + bLat) / 2];
}

function barrierBasis(route: Route, exclusion: RouteExclusion): EvidenceBasis {
  if (exclusion.reason !== 'too_steep') return 'recorded';
  // The engine judges a climb on the recorded incline where there is one and
  // on the elevation estimate otherwise, so each barrier segment is one or the
  // other — never both.
  const segments = exclusion.segmentIndexes.map((index) => route.segments[index]);
  const recorded = segments.some((segment) => segment?.incline_percent != null);
  const estimated = segments.some(
    (segment) => segment?.incline_percent == null && segment?.derived_grade_percent != null,
  );
  if (recorded && estimated) return 'mixed';
  return recorded ? 'recorded' : 'estimated';
}

/**
 * The few things worth marking on the map, all read from the response.
 *
 * One marker per group of segments the profile cannot use on the shortest
 * route — at the first of them, labelled with the whole group — and one for the
 * steepest climb on the route being looked at. Nothing is taken from the
 * basemap: a footway drawn by the tile style is not evidence of anything.
 */
export function evidenceMarkers(
  comparison: RouteCompareResponse,
  selected: RouteVariant,
): EvidenceMarker[] {
  const markers: EvidenceMarker[] = [];
  const standard = comparison.standard_route ?? null;
  if (standard) {
    for (const exclusion of exclusionsOf(standard)) {
      const first = standard.segments[exclusion.segmentIndexes[0]!];
      const position = first ? segmentMidpoint(first) : null;
      if (position === null) continue;
      markers.push({
        id: `barrier-${exclusion.reason}`,
        kind: 'barrier',
        route: 'standard',
        position,
        label: exclusionLabel(exclusion),
        basis: barrierBasis(standard, exclusion),
      });
    }
  }

  const route = selected === 'standard' ? standard : (comparison.accessible_route ?? null);
  const steepest = route?.gradient.steepest_uphill ?? null;
  const segment = steepest ? route?.segments[steepest.segment_index] : undefined;
  const position = segment ? segmentMidpoint(segment) : null;
  if (steepest && position) {
    markers.push({
      id: `gradient-${selected}`,
      kind: 'gradient',
      route: selected,
      position,
      label: `Steepest climb ${steepest.percent.toFixed(1)}%`,
      basis: gradeBasis(steepest),
    });
  }
  return markers;
}
