import { formatLatitude, formatLongitude } from '@/lib/coordinates';
import styles from './PilotPanel.module.css';

export type PilotPanelProps = {
  readonly regionName: string;
  readonly centerLat: number;
  readonly centerLon: number;
  /** Id applied to the written area description, referenced by the map region. */
  readonly descriptionId: string;
};

/**
 * The written companion to the map.
 *
 * The area description is not decoration and not a caption — it is the accessible
 * equivalent of the map for anyone who cannot see it, cannot render WebGL, or is
 * on a connection where tiles never arrive. It therefore states the same facts the
 * map conveys rather than pointing at it.
 */
export function PilotPanel({ regionName, centerLat, centerLon, descriptionId }: PilotPanelProps) {
  return (
    <aside className={styles.panel} aria-labelledby="pilot-panel-heading">
      <div className={styles.section}>
        <p className={styles.eyebrow}>Pilot area</p>
        <h1 className={styles.title} id="pilot-panel-heading">
          {regionName}
        </h1>
        <p className={styles.body} id={descriptionId} data-testid="pilot-description">
          PathAble AI is starting with {regionName}. The map is centred on the uptown core, roughly
          bounded by the University of Waterloo campus to the north, the Kitchener boundary to the
          south, and Westmount Road to the west. It covers the King Street corridor, Waterloo Public
          Square, Waterloo Park and the ION light-rail stops along Caroline Street — a mix of dense
          pedestrian streets, campus paths and suburban sidewalks that exercises most of the
          accessibility problems we intend to model.
        </p>
        <p className={styles.coords}>
          Centre {formatLatitude(centerLat)}, {formatLongitude(centerLon)}
        </p>
      </div>

      <div className={styles.notice} data-testid="development-notice">
        <p className={styles.noticeHeading}>
          <span aria-hidden="true">●</span>
          Phase 0 — foundation only
        </p>
        <p className={styles.noticeBody}>
          This is an early engineering build. There is <strong>no routing</strong>, no accessibility
          scoring and <strong>no machine learning</strong> in this application yet. Nothing shown
          here should be used to plan a journey or to judge whether a route is accessible.
        </p>
      </div>

      <div className={styles.preview}>
        <p className={styles.eyebrow}>Planned for Phase 1</p>
        <ul className={styles.previewList}>
          {[
            'Choose an origin and destination within the pilot area',
            'Pick a mobility profile — wheelchair, walker, crutches, stroller or custom',
            'Compare the shortest pedestrian route against an accessibility-aware route',
            'See why a route was chosen, and how confident the underlying data is',
          ].map((item) => (
            <li className={styles.previewItem} key={item}>
              <span className={styles.previewBullet} aria-hidden="true" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </div>

      <p className={styles.attribution} data-testid="attribution">
        Map data ©{' '}
        <a href="https://www.openstreetmap.org/copyright" rel="noreferrer noopener" target="_blank">
          OpenStreetMap
        </a>{' '}
        contributors. Development tiles served by{' '}
        <a href="https://openfreemap.org/" rel="noreferrer noopener" target="_blank">
          OpenFreeMap
        </a>
        , which has not been approved for production use.
      </p>
    </aside>
  );
}
