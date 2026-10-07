import type { Metadata } from 'next';
import { ConfigurationError } from '@/components/ConfigurationError';
import { PlannerScreen } from '@/features/routing/PlannerScreen';
import { exampleFromSearchParams } from '@/features/routing/verified-example';
import { getPublicConfig } from '@/lib/public-config';

export const metadata: Metadata = {
  title: 'Route Planner — PathAble',
};

/**
 * The OpenStreetMap credit MapLibre draws on the canvas, and the tile host's.
 * OpenFreeMap serves the development tiles; it has not been approved for
 * production use, and the credit says so where the tiles are.
 */
const MAP_ATTRIBUTION =
  '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a> · ' +
  '<a href="https://openfreemap.org/" target="_blank" rel="noreferrer">OpenFreeMap</a> development tiles';

type PlannerPageProps = {
  /** Next 16 hands search parameters to a server component as a promise. */
  readonly searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function PlannerPage({ searchParams }: PlannerPageProps) {
  // Resolved here rather than in a client effect: the page already knows the
  // URL, so a deep-linked walkthrough renders with its journey already chosen
  // instead of filling itself in a frame later.
  const example = exampleFromSearchParams(await searchParams);
  const result = getPublicConfig();

  if (!result.ok) {
    return <ConfigurationError issues={result.issues} />;
  }

  const { config } = result;

  return (
    <PlannerScreen
      apiBaseUrl={config.apiBaseUrl}
      region={config.pilotRegionSlug}
      mapStyleUrl={config.mapStyleUrl}
      centerLat={config.pilotCenterLat}
      centerLon={config.pilotCenterLon}
      zoom={config.pilotZoom}
      regionName={config.pilotRegionName}
      attribution={MAP_ATTRIBUTION}
      initialExample={example}
    />
  );
}
