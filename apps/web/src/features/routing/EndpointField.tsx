'use client';

import { type ReactNode, useId } from 'react';
import { Icon } from '@/components/Icon';
import { PlaceSearch } from '@/features/geocoding/PlaceSearch';
import { cx } from '@/lib/cx';
import type { Endpoint, LngLat, PointRole } from './types';
import { formatCoordinate } from './types';
import styles from './Planner.module.css';

/** What a map click is called when nobody has named the place. */
export const MAP_POINT_LABEL = 'Selected map point';

/** The input ids, so the header's search button can focus the start field. */
export const ENDPOINT_INPUT_IDS: Readonly<Record<PointRole, string>> = {
  origin: 'endpoint-origin-input',
  destination: 'endpoint-destination-input',
};

const ROLE_COPY: Readonly<
  Record<
    PointRole,
    {
      stackLabel: string;
      compactLabel: string;
      routeLabel: string;
      searchLabel: string;
      placeholder: string;
    }
  >
> = {
  origin: {
    stackLabel: 'Start location',
    compactLabel: 'Origin',
    routeLabel: 'Starting point',
    searchLabel: 'Search for a start',
    placeholder: 'Choose a start in Waterloo…',
  },
  destination: {
    stackLabel: 'Target endpoint',
    compactLabel: 'Destination',
    routeLabel: 'Destination',
    searchLabel: 'Search for a destination',
    placeholder: 'Choose destination in Waterloo…',
  },
};

export type EndpointFieldProps = {
  readonly role: PointRole;
  readonly endpoint: Endpoint | null;
  readonly apiBaseUrl: string;
  readonly region: string;
  /**
   * `stack`: the planning form (17:3555). `compact`: beside a result (9:1905).
   * `route`: above a journey with no route (17:4120).
   */
  readonly variant?: 'stack' | 'compact' | 'route';
  /** True while the next map click will fill this field. */
  readonly picking: boolean;
  readonly onSelectPlace: (role: PointRole, position: LngLat, label: string) => void;
  readonly onPickOnMap: (role: PointRole) => void;
  /** Extra controls inside the field, such as the swap button. */
  readonly extra?: ReactNode;
  readonly fetchImpl?: typeof fetch;
};

/** The text a field shows for its endpoint: the name, and where a click has none. */
export function endpointText(endpoint: Endpoint): string {
  return endpoint.source === 'map'
    ? `${endpoint.label} · ${formatCoordinate(endpoint.position)}`
    : endpoint.label;
}

/**
 * One end of the journey, named.
 *
 * Each field owns its own search, its own results and its own live region, and
 * "Set on map" makes the next click land *here* rather than wherever the
 * planner felt like putting it. The field's text is the place it resolves to;
 * typing over it searches for another.
 */
export function EndpointField({
  role,
  endpoint,
  apiBaseUrl,
  region,
  variant = 'stack',
  picking,
  onSelectPlace,
  onPickOnMap,
  extra,
  fetchImpl,
}: EndpointFieldProps) {
  const copy = ROLE_COPY[role];
  const descriptionId = useId();

  return (
    <div
      className={cx(
        styles.endpoint,
        variant === 'compact' && styles.endpointCompact,
        variant === 'route' && styles.endpointRoute,
      )}
      data-role={role}
      data-variant={variant}
      data-testid={`endpoint-${role}`}
    >
      <PlaceSearch
        apiBaseUrl={apiBaseUrl}
        region={region}
        label={
          variant === 'compact'
            ? copy.compactLabel
            : variant === 'route'
              ? copy.routeLabel
              : copy.stackLabel
        }
        placeholder={picking ? 'Click the map to set this point' : copy.placeholder}
        submitAccessibleName={copy.searchLabel}
        testId={`place-search-${role}`}
        inputId={ENDPOINT_INPUT_IDS[role]}
        currentValue={endpoint === null ? null : endpointText(endpoint)}
        describedBy={descriptionId}
        leading={<span className={styles.endpointDot} data-role={role} aria-hidden="true" />}
        trailing={
          <>
            <button
              type="button"
              className={styles.fieldButton}
              onClick={() => onPickOnMap(role)}
              aria-pressed={picking}
              aria-label={picking ? 'Cancel setting this point on the map' : 'Set on map'}
              title={picking ? 'Click the map…' : 'Set on map'}
              data-testid={`pick-${role}`}
            >
              <Icon name="pin-location" size={18} />
            </button>
            {extra}
          </>
        }
        onSelect={(position, label) => onSelectPlace(role, position, label)}
        {...(fetchImpl ? { fetchImpl } : {})}
      >
        {/* What the field resolves to, said once for assistive technology and
            the tests; sighted readers see it as the field's own text. */}
        <span className="visually-hidden" id={descriptionId} data-testid={`endpoint-${role}-value`}>
          {endpoint === null
            ? picking
              ? 'Click the map to set this point.'
              : 'Not set.'
            : `${endpoint.label} ${formatCoordinate(endpoint.position)}`}
        </span>
      </PlaceSearch>
    </div>
  );
}
