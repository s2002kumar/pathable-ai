/**
 * Browser-visible configuration.
 *
 * SECURITY: every value here comes from a `NEXT_PUBLIC_*` variable, which Next
 * inlines into the client bundle at build time. Anything added to this module is
 * readable by every visitor. Never put a credential, token or private hostname
 * behind a NEXT_PUBLIC_ prefix.
 *
 * The `process.env.NEXT_PUBLIC_X` references below must stay literal — Next
 * performs a static text substitution, so `process.env[name]` would silently
 * resolve to undefined in the browser.
 */
import { z } from 'zod';

/** Waterloo, Ontario. The pilot geography is configuration, not an assumption. */
export const DEFAULTS = {
  apiBaseUrl: 'http://localhost:8000',
  mapStyleUrl: 'https://tiles.openfreemap.org/styles/liberty',
  pilotCenterLat: 43.4668,
  pilotCenterLon: -80.5164,
  pilotZoom: 14,
  pilotRegionName: 'Waterloo, Ontario',
  pilotRegionSlug: 'waterloo',
} as const;

const httpUrl = z
  .string()
  .trim()
  .min(1)
  .refine(
    (value) => {
      try {
        const parsed = new URL(value);
        return parsed.protocol === 'http:' || parsed.protocol === 'https:';
      } catch {
        return false;
      }
    },
    { message: 'must be an absolute http:// or https:// URL' },
  );

/** Map styles may also be same-origin paths, which is how the offline test style works. */
const styleUrl = z
  .string()
  .trim()
  .min(1)
  .refine(
    (value) => {
      if (value.startsWith('/')) return !value.startsWith('//');
      try {
        const parsed = new URL(value);
        return parsed.protocol === 'http:' || parsed.protocol === 'https:';
      } catch {
        return false;
      }
    },
    { message: 'must be an absolute http(s) URL or a root-relative path such as /map/style.json' },
  );

const coordinate = (min: number, max: number, label: string) =>
  z.coerce
    .number({ message: `${label} must be a number` })
    .refine(Number.isFinite, { message: `${label} must be a finite number` })
    .refine((value) => value >= min && value <= max, {
      message: `${label} must be between ${min} and ${max}`,
    });

export const publicConfigSchema = z.object({
  apiBaseUrl: httpUrl
    // A trailing slash here produces `//api/v1/...` once paths are appended.
    .transform((value) => value.replace(/\/+$/, '')),
  mapStyleUrl: styleUrl,
  pilotCenterLat: coordinate(-90, 90, 'NEXT_PUBLIC_PILOT_CENTER_LAT'),
  pilotCenterLon: coordinate(-180, 180, 'NEXT_PUBLIC_PILOT_CENTER_LON'),
  pilotZoom: coordinate(0, 22, 'NEXT_PUBLIC_PILOT_ZOOM'),
  pilotRegionName: z.string().trim().min(1).max(80),
  // Must match a `pilot_regions.slug` in the API. The pattern mirrors the
  // backend's own validation so a typo fails at boot rather than as a 422 on
  // the first route request.
  pilotRegionSlug: z
    .string()
    .trim()
    .min(1)
    .max(64)
    .regex(/^[a-z0-9-]+$/, { message: 'must be lowercase letters, digits and hyphens' }),
});

export type PublicConfig = z.infer<typeof publicConfigSchema>;

export type ConfigIssue = { readonly field: string; readonly message: string };

export type ConfigResult =
  | { readonly ok: true; readonly config: PublicConfig }
  | { readonly ok: false; readonly issues: readonly ConfigIssue[] };

type RawConfig = Readonly<Record<string, string | undefined>>;

/** Absent or blank means "use the documented default"; present but wrong is an error. */
function withDefault(value: string | undefined, fallback: string | number): string {
  const trimmed = value?.trim();
  return trimmed === undefined || trimmed === '' ? String(fallback) : trimmed;
}

/**
 * Validate raw environment values.
 *
 * Pure and total: it never throws and never reads `process.env` itself, which is
 * what makes the invalid-configuration paths straightforward to test.
 */
export function parsePublicConfig(raw: RawConfig): ConfigResult {
  const parsed = publicConfigSchema.safeParse({
    apiBaseUrl: withDefault(raw.NEXT_PUBLIC_API_BASE_URL, DEFAULTS.apiBaseUrl),
    mapStyleUrl: withDefault(raw.NEXT_PUBLIC_MAP_STYLE_URL, DEFAULTS.mapStyleUrl),
    pilotCenterLat: withDefault(raw.NEXT_PUBLIC_PILOT_CENTER_LAT, DEFAULTS.pilotCenterLat),
    pilotCenterLon: withDefault(raw.NEXT_PUBLIC_PILOT_CENTER_LON, DEFAULTS.pilotCenterLon),
    pilotZoom: withDefault(raw.NEXT_PUBLIC_PILOT_ZOOM, DEFAULTS.pilotZoom),
    pilotRegionName: withDefault(raw.NEXT_PUBLIC_PILOT_REGION_NAME, DEFAULTS.pilotRegionName),
    pilotRegionSlug: withDefault(raw.NEXT_PUBLIC_PILOT_REGION_SLUG, DEFAULTS.pilotRegionSlug),
  });

  if (parsed.success) {
    return { ok: true, config: parsed.data };
  }

  const fieldToEnvVar: Record<string, string> = {
    apiBaseUrl: 'NEXT_PUBLIC_API_BASE_URL',
    mapStyleUrl: 'NEXT_PUBLIC_MAP_STYLE_URL',
    pilotCenterLat: 'NEXT_PUBLIC_PILOT_CENTER_LAT',
    pilotCenterLon: 'NEXT_PUBLIC_PILOT_CENTER_LON',
    pilotZoom: 'NEXT_PUBLIC_PILOT_ZOOM',
    pilotRegionName: 'NEXT_PUBLIC_PILOT_REGION_NAME',
    pilotRegionSlug: 'NEXT_PUBLIC_PILOT_REGION_SLUG',
  };

  return {
    ok: false,
    issues: parsed.error.issues.map((issue) => {
      const key = String(issue.path[0] ?? '');
      return { field: fieldToEnvVar[key] ?? key, message: issue.message };
    }),
  };
}

/** Read the inlined values. Kept separate so tests can supply their own map. */
export function readRawPublicConfig(): RawConfig {
  return {
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
    NEXT_PUBLIC_MAP_STYLE_URL: process.env.NEXT_PUBLIC_MAP_STYLE_URL,
    NEXT_PUBLIC_PILOT_CENTER_LAT: process.env.NEXT_PUBLIC_PILOT_CENTER_LAT,
    NEXT_PUBLIC_PILOT_CENTER_LON: process.env.NEXT_PUBLIC_PILOT_CENTER_LON,
    NEXT_PUBLIC_PILOT_ZOOM: process.env.NEXT_PUBLIC_PILOT_ZOOM,
    NEXT_PUBLIC_PILOT_REGION_NAME: process.env.NEXT_PUBLIC_PILOT_REGION_NAME,
    NEXT_PUBLIC_PILOT_REGION_SLUG: process.env.NEXT_PUBLIC_PILOT_REGION_SLUG,
  };
}

/** Format issues into a message that names every offending variable at once. */
export function describeConfigIssues(issues: readonly ConfigIssue[]): string {
  return issues.map((issue) => `${issue.field}: ${issue.message}`).join('; ');
}

export function getPublicConfig(): ConfigResult {
  return parsePublicConfig(readRawPublicConfig());
}
