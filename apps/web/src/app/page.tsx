import { AppHeader } from '@/components/AppHeader';
import { ConfigurationError } from '@/components/ConfigurationError';
import { RouteWorkspace } from '@/features/routing/RouteWorkspace';
import { exampleFromSearchParams } from '@/features/routing/verified-example';
import { getPublicConfig } from '@/lib/public-config';
import styles from './page.module.css';

/** Links the map region to its written description via aria-describedby. */
const PILOT_DESCRIPTION_ID = 'pilot-area-description';

const MAP_ATTRIBUTION =
  '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a>';

type HomePageProps = {
  /** Next 16 hands search parameters to a server component as a promise. */
  readonly searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function HomePage({ searchParams }: HomePageProps) {
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
    <div className={styles.shell}>
      <AppHeader apiBaseUrl={config.apiBaseUrl} pilotRegionName={config.pilotRegionName} />

      <main className={styles.main} id="main-content">
        <div className={styles.intro}>
          <h1 className={styles.pageTitle}>Walking routes in {config.pilotRegionName}</h1>
          {/* The text alternative the map region points at. It states what the
              map conveys rather than pointing at it, so it stands alone for
              anyone who cannot see the map or render WebGL. */}
          <p
            className={styles.instructions}
            id={PILOT_DESCRIPTION_ID}
            data-testid="pilot-description"
          >
            Click the map to set a start and an end. PathAble compares the shortest walking route
            with one that suits how you travel, and explains the difference using what OpenStreetMap
            actually records — steps, surfaces, gradients and kerbs. Where nothing has been recorded
            it says so: missing information is never treated as a clear path, and no route here is a
            guarantee that a journey is passable.
          </p>
        </div>

        <RouteWorkspace
          apiBaseUrl={config.apiBaseUrl}
          region={config.pilotRegionSlug}
          mapStyleUrl={config.mapStyleUrl}
          centerLat={config.pilotCenterLat}
          centerLon={config.pilotCenterLon}
          zoom={config.pilotZoom}
          regionName={config.pilotRegionName}
          attribution={MAP_ATTRIBUTION}
          describedById={PILOT_DESCRIPTION_ID}
          initialExample={example}
        />

        <p className={styles.attribution} data-testid="attribution">
          Map data ©{' '}
          <a
            href="https://www.openstreetmap.org/copyright"
            rel="noreferrer noopener"
            target="_blank"
          >
            OpenStreetMap
          </a>{' '}
          contributors, ODbL 1.0. Development tiles served by{' '}
          <a href="https://openfreemap.org/" rel="noreferrer noopener" target="_blank">
            OpenFreeMap
          </a>
          , which has not been approved for production use.
        </p>
      </main>
    </div>
  );
}
