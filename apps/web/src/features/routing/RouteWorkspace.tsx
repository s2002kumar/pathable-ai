'use client';

import { type CSSProperties, type ReactNode, useCallback, useMemo, useRef, useState } from 'react';
import type { ProfileKey, RouteCompareResponse } from '@pathable/contracts';
import type { MapMarker } from '@/features/map/MapMarkers';
import { MapPanel } from '@/features/map/MapPanel';
import { type RouteFocus, prefersReducedMotion, stairsOnRoutes } from '@/features/map/route-layers';
import { usePanelFit } from '@/features/map/usePanelFit';
import { MAP_POINT_LABEL } from './EndpointField';
import { RoutePlanner } from './RoutePlanner';
import { useMobilityProfiles } from './mobility-profiles';
import { type RouteVariant, evidenceMarkers } from './route-evidence';
import { useRouteComparison } from './useRouteComparison';
import {
  type Endpoint,
  type Journey,
  type LngLat,
  NO_UPHILL_LIMIT,
  type PlannerPoints,
  type PointRole,
  type RouteRequestState,
  type UphillLimit,
  formatDistance,
  hasPendingEndpointEdits,
  journeyOf,
  parseUphillLimit,
} from './types';
import { CAMPUS_EXAMPLE, type VerifiedExample } from './verified-example';
import styles from './RouteWorkspace.module.css';

export type RouteWorkspaceProps = {
  readonly apiBaseUrl: string;
  readonly region: string;
  readonly mapStyleUrl: string;
  readonly centerLat: number;
  readonly centerLon: number;
  readonly zoom: number;
  readonly regionName: string;
  readonly attribution: string;
  readonly describedById?: string;
  /** Injectable so tests never touch the network. */
  readonly fetchImpl?: typeof fetch;
  /**
   * Preselect an example. Resolved from the query string by the page, which is
   * a server component and can read it without an effect — so a deep link is
   * server-rendered like everything else rather than appearing a frame late.
   */
  readonly initialExample?: VerifiedExample | null;
  /** Rendered at the top of the planner: the page title. */
  readonly title?: ReactNode;
  /** Rendered near the foot of the planner: the purpose line and what it means. */
  readonly intro?: ReactNode;
  /** Rendered at the bottom of the planner: data attribution. */
  readonly footer?: ReactNode;
};

const EMPTY_POINTS: PlannerPoints = { origin: null, destination: null };

/**
 * The example's endpoints, carrying the corpus's own names for the places.
 *
 * Typed non-null so the journey built from it needs no assertion: the preset
 * always has both ends, which is the whole reason it is one press.
 */
function exampleEndpoints(example: VerifiedExample): {
  readonly origin: Endpoint;
  readonly destination: Endpoint;
} {
  return {
    origin: { position: example.origin, label: example.originLabel, source: 'example' },
    destination: {
      position: example.destination,
      label: example.destinationLabel,
      source: 'example',
    },
  };
}

/**
 * Which route the map brings forward and the panel describes.
 *
 * The profile's own route unless the viewer chose the other, and whichever
 * exists when only one does. Derived rather than stored, so a new answer can
 * never inherit a choice made about the previous one.
 */
function effectiveSelection(
  comparison: RouteCompareResponse | null,
  chosen: RouteVariant | null,
): RouteVariant | null {
  if (comparison === null) return null;
  const { standard_route: standard, accessible_route: accessible } = comparison;
  if (standard && accessible) return chosen ?? 'accessible';
  if (accessible) return 'accessible';
  return standard ? 'standard' : null;
}

/** What each pinned label says, from the evidence it marks. */
function toMapMarkers(comparison: RouteCompareResponse, selected: RouteVariant): MapMarker[] {
  return evidenceMarkers(comparison, selected).map((marker) => ({
    id: marker.id,
    position: marker.position,
    tone: marker.kind,
    label:
      marker.kind === 'barrier'
        ? `Ruled out: ${marker.label}`
        : `${marker.label} · ${marker.basis === 'recorded' ? 'recorded' : 'estimated'}`,
  }));
}

/**
 * Owns the planning state shared by the map and the panel.
 *
 * The routes have to be drawn *and* described, so neither the map nor the panel
 * can own them without reaching into the other.
 *
 * Two pieces of state, not one. `points` is the draft the viewer is assembling;
 * `submitted` is the journey they asked to compare. Keeping them apart is what
 * lets an answer stay truthfully attributed to the journey that produced it
 * while a different one is being typed above it — and it is why a half-finished
 * destination no longer fires a request.
 *
 * Layout: the map is the product, so it fills the workspace and everything else
 * floats over it. What the panel covers is measured rather than assumed,
 * because a route framed underneath the panel is the same failure as a route
 * drawn off-screen.
 */
export function RouteWorkspace({
  apiBaseUrl,
  region,
  mapStyleUrl,
  centerLat,
  centerLon,
  zoom,
  regionName,
  attribution,
  describedById,
  fetchImpl,
  initialExample,
  title,
  intro,
  footer,
}: RouteWorkspaceProps) {
  const [points, setPoints] = useState<PlannerPoints>(
    initialExample ? exampleEndpoints(initialExample) : EMPTY_POINTS,
  );
  // A deep-linked example is submitted from the first render, not pressed by a
  // simulated click in an effect: the page already knows the journey, so the
  // request goes out with everything else rather than a frame later.
  const [submitted, setSubmitted] = useState<Journey | null>(
    initialExample
      ? { ...exampleEndpoints(initialExample), profileKey: 'wheelchair' as ProfileKey }
      : null,
  );
  const [profileKey, setProfileKey] = useState<ProfileKey>('wheelchair');
  const [uphillLimit, setUphillLimit] = useState<UphillLimit>(NO_UPHILL_LIMIT);
  const [activeExampleId, setActiveExampleId] = useState<string | null>(initialExample?.id ?? null);
  const [chosenRoute, setChosenRoute] = useState<RouteVariant | null>(null);
  const [pickTarget, setPickTarget] = useState<PointRole | null>(null);
  const [fitRequest, setFitRequest] = useState(0);
  // Only meaningful where the panel is a bottom sheet; the side layout ignores
  // it in CSS. Open by default, because the answer is the reason to be here.
  const [sheetOpen, setSheetOpen] = useState(true);

  const mapRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const panelScrollRef = useRef<HTMLDivElement>(null);
  const fit = usePanelFit(mapRef, panelRef);

  const { state, retry } = useRouteComparison({
    apiBaseUrl,
    region,
    journey: submitted,
    ...(fetchImpl ? { fetchImpl } : {}),
  });
  const profiles = useMobilityProfiles({ apiBaseUrl, ...(fetchImpl ? { fetchImpl } : {}) });

  /** Commit a journey, and drop anything that described the previous one. */
  const commit = useCallback((journey: Journey) => {
    setSubmitted(journey);
    setChosenRoute(null);
    setPickTarget(null);
    setSheetOpen(true);

    // Bring the answer into view.
    //
    // Both controls that ask for one — Compare, and the example beneath it —
    // sit near the foot of the panel, and pressing a control scrolls it into
    // view. The answer then renders at the top, above the fold, and the viewer
    // is left looking at the button they just pressed. Measured: pressing the
    // example put the figures 1,788 px above the visible area.
    //
    // Scroll only. Moving focus here would take it away from the control the
    // viewer just used, and the result already announces itself through the
    // live region.
    const scroller = panelScrollRef.current;
    if (scroller && typeof scroller.scrollTo === 'function') {
      scroller.scrollTo({ top: 0, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
    }
  }, []);

  const handleRunExample = useCallback(
    (example: VerifiedExample) => {
      // One press: the endpoints, the profile and the request all land in the
      // same interaction. The journey is built here rather than read back from
      // state, because these setStates have not been applied yet. The example
      // is the corpus case as verified — the wheelchair preset with no limit
      // of the viewer's own — so an uphill limit is switched off for it.
      const endpoints = exampleEndpoints(example);
      setPoints(endpoints);
      setProfileKey('wheelchair');
      setUphillLimit(NO_UPHILL_LIMIT);
      setActiveExampleId(example.id);
      commit({ ...endpoints, profileKey: 'wheelchair' });
    },
    [commit],
  );

  const handleSelectPlace = useCallback((role: PointRole, position: LngLat, label: string) => {
    const endpoint: Endpoint = { position, label, source: 'search' };
    setActiveExampleId(null);
    setPickTarget(null);
    setPoints((current) => {
      const next = { ...current, [role]: endpoint };
      if (next.origin !== null && next.destination !== null) setSheetOpen(true);
      return next;
    });
  }, []);

  const handlePickOnMap = useCallback((role: PointRole) => {
    setPickTarget((current) => (current === role ? null : role));
  }, []);

  const handleSelectPoint = useCallback(
    (position: LngLat) => {
      const endpoint: Endpoint = { position, label: MAP_POINT_LABEL, source: 'map' };
      setActiveExampleId(null);

      if (pickTarget !== null) {
        const role = pickTarget;
        setPickTarget(null);
        setPoints((current) => ({ ...current, [role]: endpoint }));
        return;
      }

      // No field asked for this click, so fall back to filling the first empty
      // one. Convenient, and unambiguous only because every field also has an
      // explicit "Set on map" that says where a click will land.
      setPoints((current) => {
        if (current.origin === null) return { ...current, origin: endpoint };
        if (current.destination === null) {
          // The click that completes the pair is the one after which there is
          // something to ask for — and Compare lives inside the sheet, so on a
          // phone a shut sheet would leave the viewer with a finished journey
          // and no way to submit it.
          setSheetOpen(true);
          return { ...current, destination: endpoint };
        }
        return { origin: endpoint, destination: null };
      });
    },
    [pickTarget],
  );

  const handleClearPoint = useCallback((role: PointRole) => {
    setActiveExampleId(null);
    setPoints((current) => ({ ...current, [role]: null }));
  }, []);

  const handleClearAll = useCallback(() => {
    // Clearing has to clear the *request* too. Dropping the points alone would
    // leave the previous answer drawn on the map with nothing naming it.
    setPoints(EMPTY_POINTS);
    setSubmitted(null);
    setActiveExampleId(null);
    setChosenRoute(null);
    setPickTarget(null);
  }, []);

  const handleSwap = useCallback(() => {
    // Labels travel with their coordinates; swapping one without the other
    // would route to a place under another place's name.
    setPoints((current) => ({ origin: current.destination, destination: current.origin }));
  }, []);

  const pendingEdits = hasPendingEndpointEdits(points, submitted);
  const parsedLimit = parseUphillLimit(uphillLimit);

  /**
   * Re-run the journey on screen with a changed profile or limit.
   *
   * Only while its endpoints still match the draft. With an endpoint
   * half-edited, re-running would answer a question that is a mixture of two
   * — so that case waits for Compare.
   */
  const rerun = useCallback(
    (changes: Partial<Pick<Journey, 'profileKey' | 'uphillLimitPercent'>>) => {
      if (submitted === null || hasPendingEndpointEdits(points, submitted)) return;
      setChosenRoute(null);
      setSubmitted({ ...submitted, ...changes });
    },
    [points, submitted],
  );

  const handleProfileChange = useCallback(
    (key: ProfileKey) => {
      setProfileKey(key);
      rerun({ profileKey: key });
    },
    [rerun],
  );

  const handleUphillChange = useCallback(
    (next: UphillLimit) => {
      setUphillLimit(next);
      // Turning the limit on or off is a decision and applies at once; typing
      // a number waits for Enter or for leaving the field, so a half-typed
      // "1" on the way to "12" is never routed.
      if (next.enabled === uphillLimit.enabled) return;
      const parsed = parseUphillLimit(next);
      if (parsed.ok) rerun({ uphillLimitPercent: parsed.percent });
    },
    [rerun, uphillLimit.enabled],
  );

  const handleUphillCommit = useCallback(() => {
    if (!parsedLimit.ok || submitted === null) return;
    if ((submitted.uphillLimitPercent ?? null) === parsedLimit.percent) return;
    rerun({ uphillLimitPercent: parsedLimit.percent });
  }, [parsedLimit, submitted, rerun]);

  const handleCompare = useCallback(() => {
    if (!parsedLimit.ok) return;
    const journey = journeyOf(points, profileKey, parsedLimit.percent);
    if (journey === null) return;
    commit(journey);
  }, [points, profileKey, parsedLimit, commit]);

  const comparison = state.status === 'success' ? state.comparison : null;
  const selected = effectiveSelection(comparison, chosenRoute);
  const bothRoutes = Boolean(comparison?.standard_route && comparison?.accessible_route);
  // With one route there is nothing to bring forward over the other.
  const mapFocus: RouteFocus = bothRoutes ? selected : null;

  // Every recorded stairway on either route, whenever there is an answer: the
  // stairs are the most common reason the two routes differ, and a map that
  // hides them until asked is a map that hides the reason.
  const stairs = useMemo(
    () =>
      comparison === null
        ? null
        : stairsOnRoutes(comparison.standard_route, comparison.accessible_route),
    [comparison],
  );

  const markers = useMemo(
    () => (comparison === null || selected === null ? [] : toMapMarkers(comparison, selected)),
    [comparison, selected],
  );

  // CSS places the map key and MapLibre's own credit clear of the panel from
  // the first paint; this replaces that estimate with the measurement. Only the
  // side actually covered is written, so the other keeps its CSS default.
  //
  // Rounded up, never to nearest. A panel edge lands on a fractional pixel all
  // the time, and rounding down leaves the ODbL credit a fraction of a pixel
  // underneath it — which is still covered, and still a licence term.
  const insetStyle = useMemo<CSSProperties>(() => {
    const { side, amount } = fit.inset;
    if (amount <= 0 || (side !== 'bottom' && side !== 'left')) return {};
    const property = side === 'bottom' ? '--map-inset-bottom' : '--map-inset-left';
    return { [property]: `${Math.ceil(amount)}px` } as CSSProperties;
  }, [fit.inset]);

  const submittedSummary =
    submitted === null ? null : `${submitted.origin.label} to ${submitted.destination.label}`;
  const hasSomethingToFit =
    comparison !== null || points.origin !== null || points.destination !== null;

  return (
    <div className={styles.workspace} style={insetStyle} data-testid="route-workspace">
      <div className={styles.mapArea} ref={mapRef}>
        <MapPanel
          styleUrl={mapStyleUrl}
          centerLat={centerLat}
          centerLon={centerLon}
          zoom={zoom}
          regionName={regionName}
          attribution={attribution}
          {...(describedById !== undefined ? { describedById } : {})}
          standardRoute={comparison?.standard_route ?? null}
          accessibleRoute={comparison?.accessible_route ?? null}
          origin={points.origin?.position ?? null}
          destination={points.destination?.position ?? null}
          focusedRoute={mapFocus}
          fitPadding={fit.padding}
          stairs={stairs}
          markers={markers}
          fitRequest={fitRequest}
          onSelectPoint={handleSelectPoint}
        />
      </div>

      {hasSomethingToFit ? (
        <button
          type="button"
          className={styles.fitButton}
          onClick={() => setFitRequest((count) => count + 1)}
          data-testid="fit-routes"
        >
          {comparison !== null ? 'Fit routes' : 'Fit points'}
        </button>
      ) : null}

      <MapLegend
        selected={mapFocus}
        stairs={(stairs?.stairways ?? 0) > 0}
        hasRoutes={comparison !== null}
      />

      <aside
        className={styles.panelArea}
        ref={panelRef}
        aria-label="Route planner"
        data-sheet-open={sheetOpen}
      >
        {/* A real control, not an ornament. The previous layout drew a grip
            that looked draggable and was not; this one says what it does and
            does it. CSS shows it only where the panel is a bottom sheet. */}
        <div className={styles.sheetBar}>
          <p className={styles.sheetSummary} aria-hidden="true">
            {sheetSummary(state)}
          </p>
          <button
            type="button"
            className={styles.sheetToggle}
            onClick={() => setSheetOpen((open) => !open)}
            aria-expanded={sheetOpen}
            aria-controls="route-planner-panel"
            data-testid="sheet-toggle"
          >
            {sheetOpen ? 'Collapse' : 'Expand'}
          </button>
        </div>

        <div className={styles.panelInner} id="route-planner-panel" ref={panelScrollRef}>
          <div className={styles.panelTitle}>{title}</div>
          <RoutePlanner
            intro={intro}
            points={points}
            profileKey={profileKey}
            state={state}
            apiBaseUrl={apiBaseUrl}
            region={region}
            example={CAMPUS_EXAMPLE}
            exampleActive={activeExampleId === CAMPUS_EXAMPLE.id}
            canCompare={points.origin !== null && points.destination !== null && parsedLimit.ok}
            pendingEdits={pendingEdits}
            pickTarget={pickTarget}
            submittedSummary={submittedSummary}
            {...(selected ? { selectedRoute: selected } : {})}
            onSelectRoute={setChosenRoute}
            profiles={profiles}
            uphillLimit={uphillLimit}
            onUphillLimitChange={handleUphillChange}
            onUphillLimitCommit={handleUphillCommit}
            onRunExample={handleRunExample}
            onProfileChange={handleProfileChange}
            onCompare={handleCompare}
            onClearPoint={handleClearPoint}
            onClearAll={handleClearAll}
            onSwapPoints={handleSwap}
            onRetry={retry}
            onSelectPlace={handleSelectPlace}
            onPickOnMap={handlePickOnMap}
            {...(fetchImpl ? { fetchImpl } : {})}
          />
          {footer}
        </div>
      </aside>
    </div>
  );
}

/**
 * What the collapsed sheet says it is holding.
 *
 * Hidden from assistive technology: the panel it summarises stays in the
 * accessibility tree behind the toggle, and repeating the headline here would
 * announce the same figure twice. It is a visual label for a collapsed drawer,
 * so it never states a difference or a caution — those belong in the panel,
 * beside the evidence for them.
 */
function sheetSummary(state: RouteRequestState): string {
  switch (state.status) {
    case 'loading':
      return 'Comparing routes…';
    case 'error':
      return 'Could not compare these points';
    case 'success': {
      const route = state.comparison.accessible_route;
      return route
        ? `${state.comparison.profile_display_name} · ${formatDistance(route.distance_m)}`
        : state.comparison.profile_display_name;
    }
    default:
      return 'Plan a walking route';
  }
}

/**
 * The map legend.
 *
 * Outside the canvas so it is real text: a legend painted into WebGL is
 * invisible to a screen reader and unselectable, and this one carries the only
 * explanation of what the lines mean. Which route is drawn in front is said in
 * words, because a faded line is not a label.
 *
 * Hidden until there is something on the map to explain. A key to two routes
 * that do not exist yet is furniture, and on a phone it is furniture sitting on
 * the map.
 */
function MapLegend({
  selected,
  stairs,
  hasRoutes,
}: {
  readonly selected: RouteFocus;
  readonly stairs: boolean;
  readonly hasRoutes: boolean;
}) {
  if (!hasRoutes) return null;

  return (
    <div className={styles.legend} data-testid="map-legend">
      <h2 className={styles.legendHeading}>Map key</h2>
      <ul className={styles.legendList}>
        <li
          className={styles.legendItem}
          data-dimmed={selected !== null && selected !== 'accessible'}
          data-testid="legend-accessible"
        >
          <span className={styles.legendSwatch} data-variant="accessible" aria-hidden="true" />
          <span>
            Route for your profile
            {selected === 'accessible' ? (
              <span className={styles.legendNote}> · in front</span>
            ) : null}
          </span>
        </li>
        <li
          className={styles.legendItem}
          data-dimmed={selected !== null && selected !== 'standard'}
          data-testid="legend-standard"
        >
          <span className={styles.legendSwatch} data-variant="standard" aria-hidden="true" />
          <span>
            Shortest walking route
            {selected === 'standard' ? (
              <span className={styles.legendNote}> · in front</span>
            ) : null}
          </span>
        </li>
        {stairs ? (
          <li className={styles.legendItem} data-testid="legend-stairs">
            <span className={styles.legendSwatch} data-variant="stairs" aria-hidden="true" />
            <span>Stairway recorded in OpenStreetMap</span>
          </li>
        ) : null}
      </ul>
      <p className={styles.legendFootnote} data-testid="focus-note">
        Neither route is certified passable.
      </p>
    </div>
  );
}
