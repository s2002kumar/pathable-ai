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
          title={<h1 className={styles.pageTitle}>Walking routes in {config.pilotRegionName}</h1>}
          intro={<PageIntro />}
          footer={<DataAttribution />}
        />
      </main>
    </div>
  );
}

/**
 * What the page is for, in two sentences, and the longer explanation behind a
 * disclosure.
 *
 * The short statement is also the text alternative the map region points at,
 * so it states what the map conveys rather than pointing at it, and it keeps
 * the two sentences that make this product safe to read: missing data is not a
 * clear path, and no route is a guarantee. It sits below the answer rather
 * than above it: on a phone the answer has to fit the first screen, and a
 * viewer who has just pressed the example is reading a result, not a preface.
 */
function PageIntro() {
  return (
    <div className={styles.intro}>
      <p className={styles.purpose} id={PILOT_DESCRIPTION_ID} data-testid="pilot-description">
        PathAble compares the shortest walking route with one that suits how you travel, using what
        OpenStreetMap actually records. Missing information is never treated as a clear path, and no
        route here is a guarantee that a journey is passable.
      </p>
      <details className="disclosure" data-testid="how-it-works">
        <summary>How it works</summary>
        <div className={styles.introBody}>
          <p>
            Click the map, or search for a place, to set a start and an end. Choose how you travel,
            and PathAble computes both routes over the recorded network and explains where they
            differ: steps, surfaces, gradients and kerbs.
          </p>
          <p>
            Every statement is labelled by where it came from — recorded in OpenStreetMap, your
            profile&rsquo;s rules, derived from an elevation model, or not recorded at all. The
            routing is deterministic rules over map attributes; nothing is predicted or scored by a
            model.
          </p>
        </div>
      </details>
    </div>
  );
}

function DataAttribution() {
  return (
    <p className={styles.attribution} data-testid="attribution">
      Map data ©{' '}
      <a href="https://www.openstreetmap.org/copyright" rel="noreferrer noopener" target="_blank">
        OpenStreetMap
      </a>{' '}
      contributors, ODbL 1.0. Development tiles served by{' '}
      <a href="https://openfreemap.org/" rel="noreferrer noopener" target="_blank">
        OpenFreeMap
      </a>
      , which has not been approved for production use.
    </p>
  );
}
