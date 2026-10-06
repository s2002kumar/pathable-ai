/**
 * The four evidence categories the dock, the phone sheet and the gap cards
 * read: Stairs, Grade, Crossings, Surface. Each figure is a field of the
 * response or a reduction of its segments; each gap stays a gap.
 */
import { describe, expect, it } from 'vitest';
import type { Route } from '@pathable/contracts';
import { comparison, route, segment, shortestSegments } from '@/test/route-fixtures';
import {
  NO_RULES,
  type ProfileRules,
  categoryFacts,
  crossingsFact,
  dominantSurface,
  evaluatedWith,
  gradeFact,
  mapAge,
  plainPercent,
  stairsFact,
  surfaceFact,
  uncountedStairways,
} from './route-facts';

const STEP_FREE: ProfileRules = { excludesSteps: true, uphillLimit: null, prefersUnder: 8 };

const pair = comparison();
const accessible = pair.accessible_route as Route;
const shortest = pair.standard_route as Route;

/** The shortest route as a profile that only prices stairs would get it. */
const pricedShortest = route(
  shortestSegments().map((item) => ({ ...item, excluded_by_profile: null })),
  { profile: 'standard' },
);

describe('stairs', () => {
  it('counts the route’s recorded stairways against the shortest’s, steps as a floor', () => {
    const fact = stairsFact(accessible, shortest, STEP_FREE);

    expect(fact.value).toBe('0');
    expect(fact.valueTone).toBe('good');
    expect(fact.unit).toBe('recorded stairways');
    expect(fact.detail).toEqual({
      lead: 'vs. ',
      emphasis: '1 recorded stairway',
      // The shortest route's stairway is one this profile rules out.
      emphasisTone: 'barrier',
      tail: ' on shortest path (14 recorded steps).',
    });
    expect(fact.footer).toEqual({ icon: 'double-check', text: 'Your profile rule', tone: 'good' });
  });

  it('says a priced stairway is a cost, not a wall', () => {
    const fact = stairsFact(pricedShortest, accessible, {
      excludesSteps: false,
      uphillLimit: null,
      prefersUnder: 15,
    });

    expect(fact.value).toBe('1');
    expect(fact.valueTone).toBe('neutral');
    expect(fact.detail?.emphasisTone).toBe('neutral');
    expect(fact.footer?.text).toBe('Stairs cost extra; not ruled out');
  });

  it('leaves the step count out when nobody recorded one', () => {
    const uncounted = route([segment({ steps: 'yes', step_count: null })], { profile: 'standard' });
    const fact = stairsFact(accessible, uncounted, NO_RULES);

    expect(fact.detail?.tail).toBe(' on shortest path.');
    expect(uncountedStairways(uncounted)).toBe(1);
    expect(uncountedStairways(shortest)).toBe(0);
  });

  it('names the share of the route whose step state nobody recorded', () => {
    const partly = route([segment({ length_m: 25, steps: 'unknown' }), segment({ length_m: 75 })]);
    const fact = stairsFact(partly, null, NO_RULES);

    expect(fact.tags).toEqual(['recorded', 'not_recorded']);
    expect(fact.detail?.lead).toBe('Step state not recorded on 25% of this route.');
    // An unknown rule is not stated at all.
    expect(fact.footer).toBeNull();
  });
});

describe('grade', () => {
  it('labels a climb from OpenStreetMap recorded and one from elevation derived', () => {
    const recorded = gradeFact(accessible, shortest, NO_RULES);
    expect(recorded.tags).toEqual(['recorded']);
    expect(recorded.value).toBe('4.0%');
    expect(recorded.valueTone).toBe('neutral');
    // The shortest route's climb is the fixture's derived 1.2%.
    expect(recorded.detail?.emphasis).toBe('1.2%');

    const derived = gradeFact(shortest, null, NO_RULES);
    expect(derived.tags).toEqual(['derived']);
    expect(derived.valueTone).toBe('derived');
    expect(derived.detail).toBeNull();
  });

  it('reports no climb on record as missing, never as flat', () => {
    const unknown = route([segment()], {
      gradient: {
        steepest_uphill: null,
        steepest_downhill: null,
        recorded_fraction: 0,
        estimated_fraction: 0,
        unknown_fraction: 1,
      },
    });
    const fact = gradeFact(unknown, unknown, NO_RULES);

    expect(fact.value).toBe('—');
    expect(fact.tags).toEqual(['not_recorded']);
    expect(fact.unit).toBe('No climb on record');
    expect(fact.detail?.emphasis).toBe('no climb on record');
    expect(JSON.stringify(fact)).not.toMatch(/0\.0%/);
  });

  it('measures the climb against the traveller’s own limit, as they typed it', () => {
    const within = gradeFact(accessible, null, { ...NO_RULES, uphillLimit: 5 });
    expect(within.footer).toEqual({
      icon: 'arrow-down',
      text: 'Within your 5% limit',
      tone: 'derived',
    });

    const above = gradeFact(accessible, null, { ...NO_RULES, uphillLimit: 3.5 });
    expect(above.footer).toEqual({
      icon: 'arrow-down',
      text: 'Above your 3.5% limit',
      tone: 'barrier',
    });
  });

  it('falls back to the profile’s preference, and says nothing without one', () => {
    expect(gradeFact(accessible, null, STEP_FREE).footer?.text).toBe(
      'Profile prefers climbs under 8%',
    );
    expect(gradeFact(accessible, null, NO_RULES).footer).toBeNull();
  });
});

describe('crossings', () => {
  it('says unmapped crossings are not counted when none are mapped', () => {
    const fact = crossingsFact(shortest, accessible);

    expect(fact.value).toBe('0');
    expect(fact.detail).toEqual({
      lead: 'vs. ',
      emphasis: '1',
      emphasisTone: 'neutral',
      tail: ' mapped on shortest path.',
    });
    expect(fact.footer?.text).toBe('Unmapped crossings not counted');
    expect(crossingsFact(shortest, null).detail).toBeNull();
  });

  it('counts crossings with no kerb record as unknown, against all crossings', () => {
    const gaps = route([
      segment({ is_crossing: true, kerb: 'unknown' }),
      segment({ is_crossing: true, kerb: 'lowered' }),
    ]);
    const fact = crossingsFact(gaps, null);

    expect(fact.tags).toEqual(['not_recorded']);
    expect(fact.value).toBe('1');
    expect(fact.valueTone).toBe('unknown');
    // Read with the value: "1" "crossing has no kerb record".
    expect(fact.unit).toBe('crossing has no kerb record');
    expect(fact.detail?.lead).toBe('1 of 2 crossings on this route has a recorded kerb.');
    expect(fact.footer?.text).toBe('Missing stays unknown');
  });

  it('never reports more unknown crossings than crossings', () => {
    const fact = crossingsFact(
      { ...accessible, crossing_count: 2, unknown_kerb_crossing_count: 5 },
      null,
    );

    expect(fact.value).toBe('2');
    expect(fact.unit).toBe('crossings have no kerb record');
  });

  it('names a recorded raised kerb as recorded, and a lowered one plainly', () => {
    const lowered = crossingsFact(accessible, null);
    expect(lowered.value).toBe('1');
    expect(lowered.unit).toBe('crossing, kerb recorded');
    expect(lowered.detail).toBeNull();
    expect(lowered.footer?.text).toBe('Kerb type recorded at each');

    const raised = crossingsFact(route([segment({ is_crossing: true, kerb: 'raised' })]), null);
    expect(raised.valueTone).toBe('barrier');
    expect(raised.detail?.emphasis).toBe('1 with a raised kerb');
  });
});

describe('surface', () => {
  it('says the response carried no surface record rather than guessing one', () => {
    const fact = surfaceFact({ ...accessible, evidence_coverage: undefined } as unknown as Route);

    expect(fact.value).toBe('—');
    expect(fact.tags).toEqual(['not_recorded']);
    expect(fact.unit).toBe('Not reported');
  });

  it('states recorded and missing shares apart, and the main surface where recorded', () => {
    const fact = surfaceFact(shortest);

    expect(fact.tags).toEqual(['recorded', 'not_recorded']);
    expect(fact.value).toBe('97%');
    expect(fact.detail?.lead).toBe('Surface recorded on 97% of this route; 3% not recorded.');
    expect(fact.footer?.text).toBe('Mostly paved where recorded');
  });

  it('says a fully recorded surface is recorded, not that it is good', () => {
    const fact = surfaceFact(accessible);

    expect(fact.tags).toEqual(['recorded']);
    expect(fact.detail?.lead).toBe('Surface recorded along the whole route.');
  });

  it('names no surface when the segments record none, and mixes when none dominates', () => {
    const unrecorded = route([segment({ surface_class: 'unknown' })]);
    expect(dominantSurface(unrecorded)).toBeNull();
    expect(surfaceFact(unrecorded).footer?.text).toBe('Missing stays unknown');

    const mixed = route([
      segment({ length_m: 40, surface_class: 'paved' }),
      segment({ length_m: 30, surface_class: 'compacted' }),
      segment({ length_m: 30, surface_class: 'rough' }),
    ]);
    expect(dominantSurface(mixed)).toEqual({ name: 'paved', share: 0.4 });
    expect(surfaceFact(mixed).footer?.text).toBe('Mixed surfaces where recorded');
  });
});

describe('the four together', () => {
  it('reads them in the design’s order, with no total and no score', () => {
    const facts = categoryFacts(accessible, shortest, STEP_FREE);

    expect(facts.map((fact) => fact.key)).toEqual(['stairs', 'grade', 'crossings', 'surface']);
    expect(JSON.stringify(facts)).not.toMatch(/score|confidence|total/i);
  });
});

describe('where the answer came from', () => {
  it('names the elevation model only when a gradient was derived from it', () => {
    expect(evaluatedWith(pair)).toBe('Evaluated with OpenStreetMap & NRCan HRDEM');

    const recordedOnly = comparison({
      standard_route: { ...shortest, gradient: { ...accessible.gradient, estimated_fraction: 0 } },
      accessible_route: {
        ...accessible,
        gradient: { ...accessible.gradient, estimated_fraction: 0 },
      },
    });
    expect(evaluatedWith(recordedOnly)).toBe('Evaluated with OpenStreetMap');

    const elsewhere = comparison({
      dataset: { ...pair.dataset, source_type: 'geojson', source_name: 'city-network' },
      standard_route: null,
      accessible_route: {
        ...accessible,
        gradient: { ...accessible.gradient, estimated_fraction: 0 },
      },
    } as never);
    expect(evaluatedWith(elsewhere)).toBe('Evaluated with city-network');
  });

  it('reports the map’s age by its publication, and nothing when unreported', () => {
    const aged = (days: number | null) =>
      mapAge(comparison({ dataset: { ...pair.dataset, evidence_age_days: days } }));

    expect(aged(null)).toBeNull();
    expect(mapAge(pair)).toBeNull();
    expect(aged(0)).toBe('Map data from today');
    expect(aged(1)).toBe('Map data 1 day old');
    expect(aged(34)).toBe('Map data 34 days old');
  });

  it('repeats a declared limit as it was typed', () => {
    expect(plainPercent(5)).toBe('5%');
    expect(plainPercent(4.5)).toBe('4.5%');
  });
});
