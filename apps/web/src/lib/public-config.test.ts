import { describe, expect, it } from 'vitest';
import { DEFAULTS, describeConfigIssues, parsePublicConfig } from './public-config';

/** A complete, valid environment. Individual tests override one key at a time. */
const VALID = {
  NEXT_PUBLIC_API_BASE_URL: 'http://localhost:8000',
  NEXT_PUBLIC_MAP_STYLE_URL: 'https://tiles.example.org/styles/liberty',
  NEXT_PUBLIC_PILOT_CENTER_LAT: '43.4668',
  NEXT_PUBLIC_PILOT_CENTER_LON: '-80.5164',
  NEXT_PUBLIC_PILOT_ZOOM: '14',
  NEXT_PUBLIC_PILOT_REGION_NAME: 'Waterloo, Ontario',
} as const;

function issuesFor(overrides: Record<string, string | undefined>): string[] {
  const result = parsePublicConfig({ ...VALID, ...overrides });
  if (result.ok) return [];
  return result.issues.map((issue) => issue.field);
}

describe('parsePublicConfig', () => {
  it('accepts a fully specified environment', () => {
    const result = parsePublicConfig(VALID);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.config).toEqual({
      apiBaseUrl: 'http://localhost:8000',
      mapStyleUrl: 'https://tiles.example.org/styles/liberty',
      pilotCenterLat: 43.4668,
      pilotCenterLon: -80.5164,
      pilotZoom: 14,
      pilotRegionName: 'Waterloo, Ontario',
    });
  });

  it('falls back to the documented Waterloo defaults when nothing is set', () => {
    const result = parsePublicConfig({});

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.config.pilotCenterLat).toBe(DEFAULTS.pilotCenterLat);
    expect(result.config.pilotCenterLon).toBe(DEFAULTS.pilotCenterLon);
    expect(result.config.pilotZoom).toBe(DEFAULTS.pilotZoom);
    expect(result.config.pilotRegionName).toBe(DEFAULTS.pilotRegionName);
    expect(result.config.apiBaseUrl).toBe(DEFAULTS.apiBaseUrl);
  });

  it('treats blank values as unset rather than invalid', () => {
    const result = parsePublicConfig({ ...VALID, NEXT_PUBLIC_PILOT_ZOOM: '   ' });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.config.pilotZoom).toBe(DEFAULTS.pilotZoom);
  });

  it('is not hard-coded to Waterloo', () => {
    // The pilot geography is configuration. Vancouver must work with no code change.
    const result = parsePublicConfig({
      ...VALID,
      NEXT_PUBLIC_PILOT_CENTER_LAT: '49.2827',
      NEXT_PUBLIC_PILOT_CENTER_LON: '-123.1207',
      NEXT_PUBLIC_PILOT_REGION_NAME: 'Vancouver, British Columbia',
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.config.pilotCenterLat).toBe(49.2827);
    expect(result.config.pilotRegionName).toBe('Vancouver, British Columbia');
  });

  describe('api base URL', () => {
    it('strips a trailing slash so joined paths do not double up', () => {
      const result = parsePublicConfig({
        ...VALID,
        NEXT_PUBLIC_API_BASE_URL: 'https://api.example.org/',
      });

      expect(result.ok).toBe(true);
      if (!result.ok) return;
      expect(result.config.apiBaseUrl).toBe('https://api.example.org');
    });

    it.each(['not-a-url', 'ftp://example.org', 'localhost:8000', '/relative'])(
      'rejects %s',
      (value) => {
        expect(issuesFor({ NEXT_PUBLIC_API_BASE_URL: value })).toEqual([
          'NEXT_PUBLIC_API_BASE_URL',
        ]);
      },
    );
  });

  describe('map style URL', () => {
    it('accepts a root-relative path, which is how the offline test style works', () => {
      const result = parsePublicConfig({
        ...VALID,
        NEXT_PUBLIC_MAP_STYLE_URL: '/map-styles/offline-test-style.json',
      });

      expect(result.ok).toBe(true);
      if (!result.ok) return;
      expect(result.config.mapStyleUrl).toBe('/map-styles/offline-test-style.json');
    });

    it.each(['tiles.example.org/style.json', '//evil.example.org/style.json', 'javascript:0'])(
      'rejects %s',
      (value) => {
        expect(issuesFor({ NEXT_PUBLIC_MAP_STYLE_URL: value })).toEqual([
          'NEXT_PUBLIC_MAP_STYLE_URL',
        ]);
      },
    );
  });

  describe('coordinates', () => {
    it.each(['91', '-91', '200'])('rejects out-of-range latitude %s', (value) => {
      expect(issuesFor({ NEXT_PUBLIC_PILOT_CENTER_LAT: value })).toEqual([
        'NEXT_PUBLIC_PILOT_CENTER_LAT',
      ]);
    });

    it.each(['181', '-181', '999'])('rejects out-of-range longitude %s', (value) => {
      expect(issuesFor({ NEXT_PUBLIC_PILOT_CENTER_LON: value })).toEqual([
        'NEXT_PUBLIC_PILOT_CENTER_LON',
      ]);
    });

    it.each(['-1', '23', '100'])('rejects out-of-range zoom %s', (value) => {
      expect(issuesFor({ NEXT_PUBLIC_PILOT_ZOOM: value })).toEqual(['NEXT_PUBLIC_PILOT_ZOOM']);
    });

    it.each(['north', 'NaN', '43,4668', ''])('rejects non-numeric latitude %j', (value) => {
      // The empty string is the exception: blank means "unset", so it is valid.
      const expected = value === '' ? [] : ['NEXT_PUBLIC_PILOT_CENTER_LAT'];
      expect(issuesFor({ NEXT_PUBLIC_PILOT_CENTER_LAT: value })).toEqual(expected);
    });

    it.each(['-90', '90', '0'])('accepts boundary latitude %s', (value) => {
      expect(issuesFor({ NEXT_PUBLIC_PILOT_CENTER_LAT: value })).toEqual([]);
    });

    it.each(['0', '22'])('accepts boundary zoom %s', (value) => {
      expect(issuesFor({ NEXT_PUBLIC_PILOT_ZOOM: value })).toEqual([]);
    });
  });

  it('reports every invalid variable at once', () => {
    // One problem per reload would make a broken .env a very long afternoon.
    const result = parsePublicConfig({
      NEXT_PUBLIC_API_BASE_URL: 'nope',
      NEXT_PUBLIC_MAP_STYLE_URL: 'also-nope',
      NEXT_PUBLIC_PILOT_CENTER_LAT: '500',
      NEXT_PUBLIC_PILOT_ZOOM: '99',
    });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.issues.map((issue) => issue.field).sort()).toEqual([
      'NEXT_PUBLIC_API_BASE_URL',
      'NEXT_PUBLIC_MAP_STYLE_URL',
      'NEXT_PUBLIC_PILOT_CENTER_LAT',
      'NEXT_PUBLIC_PILOT_ZOOM',
    ]);
  });

  it('names the environment variable, not the internal field', () => {
    const result = parsePublicConfig({ ...VALID, NEXT_PUBLIC_PILOT_ZOOM: '99' });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.issues[0]?.field).toBe('NEXT_PUBLIC_PILOT_ZOOM');
    expect(result.issues[0]?.message).toContain('between 0 and 22');
  });

  it('never throws, so a bad value degrades instead of white-screening', () => {
    expect(() => parsePublicConfig({ NEXT_PUBLIC_PILOT_CENTER_LAT: '💥' })).not.toThrow();
  });
});

describe('describeConfigIssues', () => {
  it('renders one readable line per problem', () => {
    expect(
      describeConfigIssues([
        { field: 'NEXT_PUBLIC_PILOT_ZOOM', message: 'must be between 0 and 22' },
        { field: 'NEXT_PUBLIC_API_BASE_URL', message: 'must be an absolute URL' },
      ]),
    ).toBe(
      'NEXT_PUBLIC_PILOT_ZOOM: must be between 0 and 22; ' +
        'NEXT_PUBLIC_API_BASE_URL: must be an absolute URL',
    );
  });
});
