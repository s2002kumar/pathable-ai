/**
 * What each layout pins to the map, read from the response.
 *
 * The Golden Master asks for two or three prominent annotations at a time, so
 * every builder here caps itself and orders by importance: a limit the profile
 * cannot relax first, then the climb on the route being looked at, then what
 * nobody recorded. Every pin repeats a statement the panel makes in full; a
 * pin never carries a fact the panel does not.
 */

import type { Route, RouteCompareResponse } from '@pathable/contracts';
import type { MapMarker } from '@/features/map/MapMarkers';
import { evidenceGaps } from '@/features/map/route-layers';
import { limitText } from './UphillLimitControl';
import {
  type RouteVariant,
  exclusionLabel,
  exclusionsOf,
  gradeBasis,
  segmentMidpoint,
} from './route-evidence';
import { EVIDENCE_LABELS, type ProfileRules } from './route-facts';
import type { PlannerPoints } from './types';

/** At most this many pins are prominent at once. */
export const MAX_PINS = 3;

const TAG_RECORDED = EVIDENCE_LABELS.recorded;
const TAG_DERIVED = EVIDENCE_LABELS.derived;

/** Pins for what the profile rules out on the shortest route. */
export function barrierPins(comparison: RouteCompareResponse, rules: ProfileRules): MapMarker[] {
  const standard = comparison.standard_route ?? null;
  if (standard === null) return [];
  const pins: MapMarker[] = [];
  for (const exclusion of exclusionsOf(standard)) {
    const segments = exclusion.segmentIndexes.map((index) => standard.segments[index]);
    const first = segments[0];
    const position = first ? segmentMidpoint(first) : null;
    if (position === null) continue;
    const count = exclusion.segmentIndexes.length;

    if (exclusion.reason === 'too_steep') {
      // The steepest of the ruled-out climbs, on the gradient routing used:
      // recorded where OpenStreetMap has one, estimated otherwise.
      let steepest: { percent: number; recorded: boolean } | null = null;
      for (const segment of segments) {
        if (!segment) continue;
        const recorded = segment.incline_percent ?? null;
        const percent = recorded ?? segment.derived_grade_percent ?? null;
        if (percent === null) continue;
        if (steepest === null || percent > steepest.percent) {
          steepest = { percent, recorded: recorded !== null };
        }
      }
      pins.push({
        id: `barrier-${exclusion.reason}`,
        position,
        tone: 'barrier',
        icon: 'trending-up',
        mono: true,
        label:
          steepest === null
            ? exclusionLabel(exclusion)
            : `${steepest.percent.toFixed(1)}% climb on the shortest route`,
        tag: steepest?.recorded ? TAG_RECORDED : TAG_DERIVED,
        detail:
          rules.uphillLimit === null
            ? `${count} ${count === 1 ? 'segment' : 'segments'} above your limit`
            : `Exceeds your ${limitText(rules.uphillLimit)} uphill limit`,
      });
      continue;
    }

    pins.push({
      id: `barrier-${exclusion.reason}`,
      position,
      tone: 'barrier',
      icon: exclusion.reason === 'steps' ? 'pin-stairs' : 'block',
      label:
        exclusion.reason === 'steps'
          ? `${count} recorded ${count === 1 ? 'stairway' : 'stairways'}`
          : exclusionLabel(exclusion),
      tag: TAG_RECORDED,
      detail:
        exclusion.reason === 'steps' && exclusion.recordedSteps > 0
          ? `${exclusion.recordedSteps} recorded steps · shortest route, ruled out`
          : 'Shortest route · ruled out by your profile',
    });
  }
  return pins;
}

/** The steepest climb on the route being looked at. */
export function climbPin(
  comparison: RouteCompareResponse,
  selected: RouteVariant,
  profileName: string = comparison.profile_display_name,
): MapMarker | null {
  const route =
    selected === 'standard'
      ? (comparison.standard_route ?? null)
      : (comparison.accessible_route ?? null);
  const steepest = route?.gradient.steepest_uphill ?? null;
  const segment = steepest ? route?.segments[steepest.segment_index] : undefined;
  const position = segment ? segmentMidpoint(segment) : null;
  if (!steepest || position === null) return null;
  const estimated = gradeBasis(steepest) !== 'recorded';
  return {
    id: `gradient-${selected}`,
    position,
    tone: 'gradient',
    icon: 'pin-check',
    mono: true,
    label: `Max ${estimated ? 'estimated ' : ''}grade ${steepest.percent.toFixed(1)}%`,
    tag: estimated ? TAG_DERIVED : TAG_RECORDED,
    detail:
      selected === 'standard'
        ? 'Steepest climb on the shortest route'
        : `Steepest climb on the ${profileName.toLowerCase()} route`,
  };
}

/** Crossings on a route whose kerb nobody recorded, pinned at the first. */
export function kerbPin(route: Route | null, id: string): MapMarker | null {
  if (route === null) return null;
  const count = Math.max(0, route.unknown_kerb_crossing_count);
  if (count === 0) return null;
  const first = evidenceGaps(route).find((gap) => gap.kind === 'kerb');
  const position = first ? segmentMidpoint(first.segment) : null;
  if (position === null) return null;
  return {
    id,
    position,
    tone: 'unknown',
    icon: 'pin-question',
    label: `${count} ${count === 1 ? 'crossing has' : 'crossings have'} no kerb record`,
    tag: EVIDENCE_LABELS.not_recorded,
    detail: 'Kerb not recorded in OpenStreetMap',
  };
}

/** The comparison's pins (9:1905): barriers, the climb, then a kerb gap. */
export function comparePins(
  comparison: RouteCompareResponse,
  selected: RouteVariant,
  rules: ProfileRules,
  profileName: string = comparison.profile_display_name,
): MapMarker[] {
  const route =
    selected === 'standard'
      ? (comparison.standard_route ?? null)
      : (comparison.accessible_route ?? null);
  const pins = [
    ...barrierPins(comparison, rules),
    climbPin(comparison, selected, profileName),
    kerbPin(route, `kerb-${selected}`),
  ].filter((pin): pin is MapMarker => pin !== null);
  return pins.slice(0, MAX_PINS);
}

/**
 * The phone's map annotations (17:2865): compact badges for what the profile
 * rules out and the climb on the shortest route, and the two place names.
 */
export function phonePins(comparison: RouteCompareResponse, points: PlannerPoints): MapMarker[] {
  const standard = comparison.standard_route ?? null;
  const badges: MapMarker[] = [];
  if (standard) {
    for (const exclusion of exclusionsOf(standard)) {
      const first = standard.segments[exclusion.segmentIndexes[0]!];
      const position = first ? segmentMidpoint(first) : null;
      if (position === null) continue;
      const count = exclusion.segmentIndexes.length;
      badges.push({
        id: `badge-${exclusion.reason}`,
        variant: 'badge',
        tone: 'barrier',
        icon: exclusion.reason === 'steps' ? 'stairs' : 'trending-up',
        position,
        label:
          exclusion.reason === 'steps'
            ? `${count} ${count === 1 ? 'stairway' : 'stairways'}`
            : exclusionLabel(exclusion),
      });
    }
    const steepest = standard.gradient.steepest_uphill;
    const segment = steepest ? standard.segments[steepest.segment_index] : undefined;
    const position = segment ? segmentMidpoint(segment) : null;
    if (steepest && position) {
      badges.push({
        id: 'badge-climb',
        variant: 'badge',
        tone: 'unknown',
        icon: 'trending-up',
        position,
        label: `${steepest.percent.toFixed(1)}% climb`,
      });
    }
  }
  return [...badges.slice(0, 2), ...endpointLabels(points)];
}

/** The evidence view's callouts (17:3789): the first kerb gap and the longest surface gap. */
export function gapCallouts(route: Route | null): MapMarker[] {
  if (route === null) return [];
  const gaps = evidenceGaps(route);
  const callouts: MapMarker[] = [];
  const kerb = gaps.find((gap) => gap.kind === 'kerb');
  const kerbPosition = kerb ? segmentMidpoint(kerb.segment) : null;
  if (kerbPosition) {
    callouts.push({
      id: 'gap-kerb',
      variant: 'callout',
      tone: 'unknown',
      icon: 'warning',
      position: kerbPosition,
      label: 'Unrecorded kerb state',
      detail: 'Kerb information not recorded at this crossing',
    });
  }
  const surface = gaps
    .filter((gap) => gap.kind === 'surface')
    .sort((a, b) => b.segment.length_m - a.segment.length_m)[0];
  const surfacePosition = surface ? segmentMidpoint(surface.segment) : null;
  if (surfacePosition) {
    callouts.push({
      id: 'gap-surface',
      variant: 'callout',
      tone: 'unknown',
      icon: 'stack',
      position: surfacePosition,
      label: 'Surface data gap',
      detail: 'Surface information not recorded on this segment',
    });
  }
  return callouts;
}

/** Names beside A and B, for the layouts that draw them (17:3555, 17:4041). */
export function endpointLabels(points: PlannerPoints): MapMarker[] {
  const labels: MapMarker[] = [];
  if (points.origin) {
    labels.push({
      id: 'endpoint-origin',
      variant: 'endpoint',
      tone: 'origin',
      position: [points.origin.position.longitude, points.origin.position.latitude],
      label: points.origin.label,
      tag: 'Origin',
    });
  }
  if (points.destination) {
    labels.push({
      id: 'endpoint-destination',
      variant: 'endpoint',
      tone: 'destination',
      position: [points.destination.position.longitude, points.destination.position.latitude],
      label: points.destination.label,
      tag: 'Destination',
    });
  }
  return labels;
}
