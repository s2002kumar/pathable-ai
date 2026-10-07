import { Icon } from '@/components/Icon';
import { LINKS } from '@/lib/links';
import styles from './PlannerFooter.module.css';

/**
 * The planner's credit line (Golden Master 9:2282).
 *
 * Names both sources a route rests on and links the licence the network is
 * published under. The map canvas carries its own OpenStreetMap credit as well;
 * this one is the full statement, and it is never covered by anything.
 *
 * The elevation statement is the Open Government Licence – Canada's required
 * wording. The panel shows grades derived from HRDEM on its first screen, so
 * the statement cannot live only behind "Route Details"; the response's own
 * `elevation_attribution` is repeated there in full. The tile host is named
 * as a development service because ADR 0005 has not approved it for production.
 */
export function PlannerFooter() {
  return (
    <footer className={styles.footer} data-testid="attribution">
      <div className={styles.credits}>
        <p className={styles.sources}>
          <span className={styles.mark} aria-hidden="true">
            <Icon name="fork" />
          </span>
          <span>
            Data sources: OpenStreetMap pedestrian network • Natural Resources Canada (NRCan)
            High-Resolution Digital Elevation Model (HRDEM)
          </span>
        </p>
        <p className={styles.notes}>
          <span data-testid="elevation-licence">
            HRDEM: contains information licensed under the Open Government Licence – Canada.
          </span>{' '}
          Development map tiles served by OpenFreeMap, which has not been approved for production
          use.
        </p>
      </div>
      <ul className={styles.links}>
        <li>
          <a href={LINKS.methodology} rel="noreferrer noopener" target="_blank">
            Accessibility Methodology
          </a>
        </li>
        <li>
          <a href={LINKS.dataSources} rel="noreferrer noopener" target="_blank">
            About Open Data
          </a>
        </li>
        <li>
          <a className={styles.licence} href={LINKS.odbl} rel="noreferrer noopener" target="_blank">
            Open Database License (ODbL)
          </a>
        </li>
      </ul>
    </footer>
  );
}
