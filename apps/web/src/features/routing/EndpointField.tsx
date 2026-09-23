'use client';

import { PlaceSearch } from '@/features/geocoding/PlaceSearch';
import type { Endpoint, LngLat, PointRole } from './types';
import { formatCoordinate } from './types';
import styles from './RoutePlanner.module.css';

/** What a map click is called when nobody has named the place. */
export const MAP_POINT_LABEL = 'Selected map point';

const ROLE_COPY: Readonly<
  Record<PointRole, { label: string; searchLabel: string; placeholder: string; marker: string }>
> = {
  origin: {
    label: 'Start',
    searchLabel: 'Search for a start',
    placeholder: 'Search a place, or set it on the map',
    marker: 'A',
  },
  destination: {
    label: 'Destination',
    searchLabel: 'Search for a destination',
    placeholder: 'Search a place, or set it on the map',
    marker: 'B',
  },
};

export type EndpointFieldProps = {
  readonly role: PointRole;
  readonly endpoint: Endpoint | null;
  readonly apiBaseUrl: string;
  readonly region: string;
  /** True while the next map click will fill this field. */
  readonly picking: boolean;
  readonly onSelectPlace: (role: PointRole, position: LngLat, label: string) => void;
  readonly onPickOnMap: (role: PointRole) => void;
  readonly onClear: (role: PointRole) => void;
  readonly fetchImpl?: typeof fetch;
};

/**
 * One end of the journey, named.
 *
 * Two of these replace the single search box that filled "whichever point is
 * empty". That implicit target was the bug: a person searching for their
 * destination had no way to say so, and the answer depended on which field
 * happened to be blank.
 *
 * Each field owns its own search, its own results and its own live region, and
 * "Set on map" makes the next click land *here* rather than wherever the
 * planner felt like putting it.
 */
export function EndpointField({
  role,
  endpoint,
  apiBaseUrl,
  region,
  picking,
  onSelectPlace,
  onPickOnMap,
  onClear,
  fetchImpl,
}: EndpointFieldProps) {
  const copy = ROLE_COPY[role];

  return (
    <div className={styles.endpoint} data-role={role} data-testid={`endpoint-${role}`}>
      <span className={styles.endpointMarker} data-marker={copy.marker} aria-hidden="true">
        {copy.marker}
      </span>

      <div className={styles.endpointBody}>
        <PlaceSearch
          apiBaseUrl={apiBaseUrl}
          region={region}
          // The visible label is the endpoint's name; the submit button needs
          // its own accessible name, because two buttons both called "Search"
          // on one page are two buttons nobody can tell apart.
          label={copy.label}
          placeholder={copy.placeholder}
          submitAccessibleName={copy.searchLabel}
          testId={`place-search-${role}`}
          onSelect={(position, label) => onSelectPlace(role, position, label)}
          {...(fetchImpl ? { fetchImpl } : {})}
        >
          {endpoint === null ? (
            <p className={styles.endpointEmpty} data-testid={`endpoint-${role}-value`}>
              {picking ? 'Click the map to set this point.' : 'Not set.'}
            </p>
          ) : (
            <p className={styles.endpointValue} data-testid={`endpoint-${role}-value`}>
              <span className={styles.endpointName}>{endpoint.label}</span>{' '}
              <span className={styles.endpointCoords}>{formatCoordinate(endpoint.position)}</span>
            </p>
          )}

          <div className={styles.endpointActions}>
            <button
              type="button"
              className={styles.quietButton}
              onClick={() => onPickOnMap(role)}
              aria-pressed={picking}
              data-testid={`pick-${role}`}
            >
              {picking ? 'Click the map…' : 'Set on map'}
            </button>
            <button
              type="button"
              className={styles.quietButton}
              onClick={() => onClear(role)}
              disabled={endpoint === null}
              data-testid={`clear-${role}`}
            >
              Clear
            </button>
          </div>
        </PlaceSearch>
      </div>
    </div>
  );
}
