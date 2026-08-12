import { AppHeader } from '@/components/AppHeader';
import { ConfigurationError } from '@/components/ConfigurationError';
import { PilotPanel } from '@/components/PilotPanel';
import { MapPanel } from '@/features/map/MapPanel';
import { getPublicConfig } from '@/lib/public-config';
import styles from './page.module.css';

/** Links the map region to its written description via aria-describedby. */
const PILOT_DESCRIPTION_ID = 'pilot-area-description';

const MAP_ATTRIBUTION =
  '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a>';

export default function HomePage() {
  const result = getPublicConfig();

  if (!result.ok) {
    return <ConfigurationError issues={result.issues} />;
  }

  const { config } = result;

  return (
    <div className={styles.shell}>
      <AppHeader apiBaseUrl={config.apiBaseUrl} pilotRegionName={config.pilotRegionName} />

      <main className={styles.workspace} id="main-content">
        <div className={styles.mapArea}>
          <MapPanel
            styleUrl={config.mapStyleUrl}
            centerLat={config.pilotCenterLat}
            centerLon={config.pilotCenterLon}
            zoom={config.pilotZoom}
            regionName={config.pilotRegionName}
            attribution={MAP_ATTRIBUTION}
            describedById={PILOT_DESCRIPTION_ID}
          />
        </div>

        <div className={styles.panelArea}>
          <PilotPanel
            regionName={config.pilotRegionName}
            centerLat={config.pilotCenterLat}
            centerLon={config.pilotCenterLon}
            descriptionId={PILOT_DESCRIPTION_ID}
          />
        </div>
      </main>
    </div>
  );
}
