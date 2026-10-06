'use client';

import { type CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ProfileKey, RouteCompareResponse } from '@pathable/contracts';
import { Icon } from '@/components/Icon';
import { ALL_LAYERS, type MapLayers } from '@/features/map/MapControls';
import type { MapMarker } from '@/features/map/MapMarkers';
import { MapPanel } from '@/features/map/MapPanel';
import {
  type RouteFocus,
  evidenceGaps,
  gapsToGeoJson,
  prefersReducedMotion,
  stairsOnRoutes,
} from '@/features/map/route-layers';
import { usePanelFit } from '@/features/map/usePanelFit';
import type { SystemStatus } from '@/features/system-status/types';
import { LINKS } from '@/lib/links';
import { PHONE_QUERY, useMediaQuery } from '@/lib/useMediaQuery';
import { ENDPOINT_INPUT_IDS, MAP_POINT_LABEL } from './EndpointField';
import { EvidenceDock, GapDock } from './EvidenceDock';
import { type DetailsSection, RouteDetails } from './RouteDetails';
import { type PlannerLayout, RoutePlanner } from './RoutePlanner';
import { barrierPins, comparePins, endpointLabels, gapCallouts, phonePins } from './map-pins';
import { useMobilityProfiles } from './mobility-profiles';
import type { RouteVariant } from './route-evidence';
import type { ProfileRules } from './route-facts';
import { routesSharePath } from './route-identity';
import { useRouteComparison } from './useRouteComparison';
import {
  type Endpoint,
  type Journey,
  type LngLat,
  NO_UPHILL_LIMIT,
  type PlannerPoints,
  type PointRole,
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
  /** The API's state, for the idle status strip. */
  readonly systemStatus?: SystemStatus;
  /** Injectable so tests never touch the network. */
  readonly fetchImpl?: typeof fetch;
  /**
   * Preselect an example. Resolved from the query string by the page, which is
   * a server component and can read it without an effect — so a deep link is
   * server-rendered like everything else rather than appearing a frame late.
   */
  readonly initialExample?: VerifiedExample | null;
};

const EMPTY_POINTS: PlannerPoints = { origin: null, destination: null };

/** Height of the phone's route pills and the gap above them. */
const PHONE_PILLS_PX = 46;

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

/**
 * The layout an answer opens in.
 *
 * No route for the profile is its own state (17:4041). Two routes that differ
 * open as a comparison (9:1905); one route, or two that are the same path,
 * open on that route's record (17:3789), because there is no difference to
 * explain and "why this route is different" would have nothing to say.
 */
export function defaultLayout(comparison: RouteCompareResponse): PlannerLayout {
  const { standard_route: standard, accessible_route: accessible } = comparison;
  if (!accessible) return 'no-route';
  if (!standard || routesSharePath(standard, accessible)) return 'evidence';
  return 'compare';
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
 * while a different one is being typed above it.
 *
 * Layout: the map is the product, so it fills the workspace and everything else
 * floats over it, as the Golden Master draws it. What the floating surfaces
 * cover is measured rather than assumed, because a route framed underneath a
 * panel is the same failure as a route drawn off-screen.
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
  systemStatus,
  fetchImpl,
  initialExample,
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
  // Which layout the viewer asked for over the answer's default; cleared by
  // every new answer, so a choice about one result never carries to the next.
  const [layoutChoice, setLayoutChoice] = useState<'compare' | 'evidence' | null>(null);
  // Whether a request in flight replaces a result already on screen (keep the
  // result's layout) or answers the planning form (keep the form).
  const [keepResultLayout, setKeepResultLayout] = useState(false);
  const [details, setDetails] = useState<DetailsSection | null>(null);
  const [layers, setLayers] = useState<MapLayers>(ALL_LAYERS);
  const [phoneEditorOpen, setPhoneEditorOpen] = useState(false);
  // Where focus goes once the layout the viewer asked for has rendered: a
  // one-shot instruction, so a ref read after the next commit, not state.
  const pendingFocus = useRef<'profile' | 'destination' | null>(null);

  const phone = useMediaQuery(PHONE_QUERY);
  const mapRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const dockRef = useRef<HTMLDivElement>(null);

  const { state, retry } = useRouteComparison({
    apiBaseUrl,
    region,
    journey: submitted,
    ...(fetchImpl ? { fetchImpl } : {}),
  });
  const profiles = useMobilityProfiles({ apiBaseUrl, ...(fetchImpl ? { fetchImpl } : {}) });

  /** Commit a journey, and drop anything that described the previous one. */
  const commit = useCallback((journey: Journey, keepLayout: boolean) => {
    setSubmitted(journey);
    setChosenRoute(null);
    setPickTarget(null);
    setLayoutChoice(null);
    setDetails(null);
    setKeepResultLayout(keepLayout);
  }, []);

  const handleRunExample = useCallback(
    (example: VerifiedExample) => {
      // One press: the endpoints, the profile and the request all land in the
      // same interaction. The example is the corpus case as verified — the
      // wheelchair preset with no limit of the viewer's own — so an uphill
      // limit is switched off for it.
      const endpoints = exampleEndpoints(example);
      setPoints(endpoints);
      setProfileKey('wheelchair');
      setUphillLimit(NO_UPHILL_LIMIT);
      setActiveExampleId(example.id);
      commit({ ...endpoints, profileKey: 'wheelchair' }, false);
    },
    [commit],
  );

  const handleSelectPlace = useCallback((role: PointRole, position: LngLat, label: string) => {
    const endpoint: Endpoint = { position, label, source: 'search' };
    setActiveExampleId(null);
    setPickTarget(null);
    setPoints((current) => ({ ...current, [role]: endpoint }));
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
        if (current.destination === null) return { ...current, destination: endpoint };
        return { origin: endpoint, destination: null };
      });
    },
    [pickTarget],
  );

  const handleClearAll = useCallback(() => {
    // Clearing has to clear the *request* too. Dropping the points alone would
    // leave the previous answer drawn on the map with nothing naming it.
    setPoints(EMPTY_POINTS);
    setSubmitted(null);
    setPhoneEditorOpen(false);
    setActiveExampleId(null);
    setChosenRoute(null);
    setPickTarget(null);
    setLayoutChoice(null);
    setDetails(null);
    setKeepResultLayout(false);
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
      setLayoutChoice(null);
      setKeepResultLayout(true);
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

  const comparison = state.status === 'success' ? state.comparison : null;
  const selected = effectiveSelection(comparison, chosenRoute);

  // What the panel shows. A request in flight keeps the layout it was asked
  // from: the form while answering the form, the result while refining one.
  let layout: PlannerLayout;
  if (submitted === null) layout = 'plan';
  else if (comparison !== null) layout = layoutChoice ?? defaultLayout(comparison);
  else layout = keepResultLayout ? 'compare' : 'plan';

  const handleCompare = useCallback(() => {
    if (!parsedLimit.ok) return;
    const journey = journeyOf(points, profileKey, parsedLimit.percent);
    if (journey === null) return;
    commit(journey, layout !== 'plan');
  }, [points, profileKey, parsedLimit, commit, layout]);

  const handleEditJourney = useCallback((target: 'profile' | 'destination') => {
    pendingFocus.current = target;
    setLayoutChoice('compare');
  }, []);

  // On a phone the form and the answer share one scrolling page. An answer
  // replacing the form would otherwise open wherever the form was scrolled to
  // — its foot, where Compare is — with the map and both routes above the
  // screen. Take the page back to the map when the first answer arrives.
  const previousLayout = useRef(layout);
  useEffect(() => {
    const before = previousLayout.current;
    previousLayout.current = layout;
    if (!phone || before !== 'plan' || layout === 'plan') return;
    window.scrollTo({ top: 0, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
  }, [layout, phone]);

  // Focus the control the no-route panel sent the viewer to, once it exists.
  useEffect(() => {
    const target = pendingFocus.current;
    if (target === null) return;
    pendingFocus.current = null;
    const element =
      target === 'destination'
        ? document.getElementById(ENDPOINT_INPUT_IDS.destination)
        : document.querySelector<HTMLInputElement>('input[name="mobility-profile"]:checked');
    element?.focus();
    element?.scrollIntoView?.({
      block: 'nearest',
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
    });
  });

  // The rules of the profile that produced the answer on screen — or, before
  // there is one, of the profile being chosen — as far as the browser knows.
  const rulesProfileKey = comparison && submitted ? submitted.profileKey : profileKey;
  const rulesProfile =
    profiles.status === 'ready' ? profiles.profiles.get(rulesProfileKey) : undefined;
  // A limit of the traveller's own turns a preset into the API's "Custom"
  // profile. It is still their wheelchair (or walker…) profile with one more
  // rule, and is named that way; the limit is shown beside it as a rule.
  const profileName =
    comparison === null
      ? null
      : comparison.profile === 'custom' && rulesProfile !== undefined
        ? rulesProfile.display_name
        : comparison.profile_display_name;
  const rules: ProfileRules = {
    excludesSteps: rulesProfile?.excludes_steps ?? null,
    uphillLimit:
      comparison && submitted
        ? (submitted.uphillLimitPercent ?? null)
        : parsedLimit.ok
          ? parsedLimit.percent
          : null,
    prefersUnder: rulesProfile?.prefers_gradient_under_percent ?? null,
  };

  // --- What the map draws, per layout ---------------------------------------
  const standard = comparison?.standard_route ?? null;
  const accessible = comparison?.accessible_route ?? null;
  const shownRoute = selected === 'standard' ? standard : (accessible ?? standard);

  const mapRoutes = useMemo(() => {
    switch (layout) {
      case 'compare':
        return { standard: layers.shortest ? standard : null, accessible };
      case 'evidence':
        return shownRoute === standard
          ? { standard: shownRoute, accessible: null }
          : { standard: null, accessible: shownRoute };
      case 'no-route':
        return { standard: layers.shortest ? standard : null, accessible: null };
      default:
        return { standard: null, accessible: null };
    }
  }, [layout, layers.shortest, standard, accessible, shownRoute]);

  const mapFocus: RouteFocus = layout === 'compare' && standard && accessible ? selected : null;

  const stairs = useMemo(() => {
    if (!layers.stairs || comparison === null) return null;
    if (layout === 'compare') return stairsOnRoutes(standard, accessible);
    if (layout === 'no-route') return stairsOnRoutes(standard);
    return null;
  }, [layers.stairs, comparison, layout, standard, accessible]);

  const gaps = useMemo(
    () => (layout === 'evidence' ? gapsToGeoJson(evidenceGaps(shownRoute)) : null),
    [layout, shownRoute],
  );

  const markers = useMemo<MapMarker[]>(() => {
    const evidence = layers.evidence;
    switch (layout) {
      case 'compare':
        if (phone && comparison) {
          return evidence ? phonePins(comparison, points) : endpointLabels(points);
        }
        return evidence && comparison && selected
          ? comparePins(comparison, selected, rules, profileName ?? undefined)
          : [];
      case 'evidence':
        return evidence ? gapCallouts(shownRoute) : [];
      case 'no-route':
        return [
          ...(evidence && comparison ? barrierPins(comparison, rules).slice(0, 2) : []),
          ...endpointLabels(points),
        ];
      default:
        return endpointLabels(points);
    }
    // `rules` is rebuilt every render; its parts are the real dependencies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    layout,
    layers.evidence,
    comparison,
    selected,
    shownRoute,
    points,
    rules.excludesSteps,
    rules.uphillLimit,
    rules.prefersUnder,
    profileName,
    phone,
  ]);

  // --- Docks ------------------------------------------------------------------
  // The phone's sheet carries the four categories itself (17:3030).
  const showCompareDock =
    !phone && layout === 'compare' && standard !== null && accessible !== null;
  const showGapDock = layout === 'evidence' && shownRoute !== null;
  const dockKey = showCompareDock ? 'compare' : showGapDock ? 'evidence' : 'none';
  const fit = usePanelFit(mapRef, panelRef, dockRef, `${layout}:${dockKey}`);

  // CSS places the map's credit clear of the floating surfaces from the first
  // paint; this replaces that estimate with the measurement. Rounded up, never
  // to nearest: a panel edge lands on a fractional pixel all the time, and
  // rounding down leaves the ODbL credit a fraction of a pixel underneath it.
  const insetStyle = useMemo<CSSProperties>(() => {
    const style: Record<string, string> = {};
    const { side, amount } = fit.inset;
    if (amount > 0 && side === 'left') style['--map-inset-left'] = `${Math.ceil(amount)}px`;
    // On a phone the comparison's pills ride the foot of the map (17:2914);
    // the credit goes above them rather than underneath.
    const pills = phone && layout === 'compare' && comparison !== null ? PHONE_PILLS_PX : 0;
    const bottom = Math.max(fit.dockInset, side === 'bottom' ? amount : 0) + pills;
    if (bottom > 0) style['--map-inset-bottom'] = `${Math.ceil(bottom)}px`;
    if (fit.dockInset > 0) style['--hud-bottom'] = `${Math.ceil(fit.dockInset) + 8}px`;
    return style as CSSProperties;
  }, [fit.inset, fit.dockInset, phone, layout, comparison]);

  const submittedSummary =
    submitted === null ? null : `${submitted.origin.label} to ${submitted.destination.label}`;
  const hasSomethingToFit =
    comparison !== null || points.origin !== null || points.destination !== null;

  const openDetails = useCallback((section: DetailsSection) => setDetails(section), []);

  return (
    <div
      className={styles.workspace}
      style={insetStyle}
      data-layout={layout}
      data-testid="route-workspace"
    >
      <div className={styles.mapArea} ref={mapRef}>
        <MapPanel
          styleUrl={mapStyleUrl}
          centerLat={centerLat}
          centerLon={centerLon}
          zoom={zoom}
          regionName={regionName}
          attribution={attribution}
          {...(describedById !== undefined ? { describedById } : {})}
          standardRoute={mapRoutes.standard}
          accessibleRoute={mapRoutes.accessible}
          origin={points.origin?.position ?? null}
          destination={points.destination?.position ?? null}
          focusedRoute={mapFocus}
          fitPadding={fit.padding}
          stairs={stairs}
          gaps={gaps}
          markers={markers}
          fitRequest={fitRequest}
          onSelectPoint={handleSelectPoint}
          veil={layout === 'plan'}
          controls={{
            layout: phone ? 'phone' : layout,
            layers,
            onLayersChange: setLayers,
            ...(hasSomethingToFit ? { onFit: () => setFitRequest((count) => count + 1) } : {}),
            fitLabel: comparison !== null ? 'Fit routes' : 'Fit points',
          }}
        />
      </div>

      {phone && layout === 'compare' && accessible ? (
        <div className={styles.phonePills} aria-hidden="true">
          <span className={styles.phonePill}>
            <span className={styles.phonePillDot} />
            Route comparison
          </span>
          <span className={styles.phoneDistance}>
            <Icon name="pin-small" />
            {formatDistance(accessible.distance_m)}
          </span>
        </div>
      ) : null}

      <aside
        className={styles.panelArea}
        ref={panelRef}
        aria-label="Route planner"
        data-layout={layout}
      >
        <RoutePlanner
          layout={layout}
          points={points}
          profileKey={profileKey}
          state={state}
          apiBaseUrl={apiBaseUrl}
          region={region}
          regionName={regionName}
          profileName={profileName}
          example={CAMPUS_EXAMPLE}
          exampleActive={activeExampleId === CAMPUS_EXAMPLE.id}
          canCompare={points.origin !== null && points.destination !== null && parsedLimit.ok}
          pendingEdits={pendingEdits}
          pickTarget={pickTarget}
          {...(selected ? { selectedRoute: selected } : {})}
          onSelectRoute={setChosenRoute}
          profiles={profiles}
          rules={rules}
          uphillLimit={uphillLimit}
          onUphillLimitChange={handleUphillChange}
          onUphillLimitCommit={handleUphillCommit}
          onRunExample={handleRunExample}
          onProfileChange={handleProfileChange}
          onCompare={handleCompare}
          onClearAll={handleClearAll}
          onSwapPoints={handleSwap}
          onRetry={retry}
          onSelectPlace={handleSelectPlace}
          onPickOnMap={handlePickOnMap}
          onRouteDetails={() => openDetails('details')}
          onOpenEvidence={() => openDetails('evidence')}
          phone={phone}
          editorOpen={phoneEditorOpen}
          onEditorToggle={setPhoneEditorOpen}
          onShowLayout={setLayoutChoice}
          onEditJourney={handleEditJourney}
          {...(fetchImpl ? { fetchImpl } : {})}
        />
      </aside>

      {showCompareDock && accessible && standard ? (
        <div className={styles.dockArea} ref={dockRef} data-layout="compare">
          {/* Always the profile's route against the shortest: every sentence in
              the dock reads "vs. … on shortest path", so swapping the two when
              the viewer brings the shortest forward would attribute the
              profile route's figures to the shortest path. The choice moves
              the map; the route's own record is under View Evidence. */}
          <EvidenceDock
            route={accessible}
            other={standard}
            rules={rules}
            profileName={profileName ?? 'profile'}
            onRouteDetails={() => openDetails('details')}
            onViewEvidence={() => setLayoutChoice('evidence')}
          />
        </div>
      ) : null}

      {showGapDock && shownRoute ? (
        <div className={styles.dockArea} ref={dockRef} data-layout="evidence">
          <GapDock
            route={shownRoute}
            rules={shownRoute === standard ? { ...rules, excludesSteps: null } : rules}
            onViewEvidence={() => openDetails('evidence')}
          />
        </div>
      ) : null}

      {layout === 'plan' && systemStatus ? <StatusStrip status={systemStatus} /> : null}

      <RouteDetails
        open={details !== null}
        section={details ?? 'details'}
        comparison={comparison}
        selectedRoute={selected ?? 'accessible'}
        onSelectRoute={setChosenRoute}
        journeySummary={submittedSummary}
        profileName={profileName}
        uphillLimit={rules.uphillLimit}
        onClose={() => setDetails(null)}
      />
    </div>
  );
}

/** How the strip names the API's state: words first, the dot only repeats them. */
function statusWords(status: SystemStatus): { lead: string; detail: string } {
  const sources = 'Powered by OpenStreetMap pedestrian topology and NRCan 1m HRDEM elevation data';
  switch (status.state) {
    case 'ready':
      return { lead: 'Ready to route', detail: sources };
    case 'checking':
      return { lead: 'Checking the routing service', detail: sources };
    case 'preparing':
      return { lead: 'Preparing routes', detail: 'loading the Waterloo routing graph' };
    case 'degraded':
      return {
        lead: 'Routing service degraded',
        detail:
          status.failing.length > 0
            ? `${status.failing.join(' and ')} unavailable`
            : 'a dependency is unavailable',
      };
    case 'unreachable':
      return { lead: 'Routing service offline', detail: status.reason };
  }
}

/**
 * The quiet strip at the foot of the map (17:3728): whether the service can
 * route right now, and what it routes over. Idle only — once there is an
 * answer, the panel says where that answer came from.
 */
function StatusStrip({ status }: { readonly status: SystemStatus }) {
  const { lead, detail } = statusWords(status);
  return (
    <div className={styles.statusArea}>
      <p
        className={styles.statusStrip}
        role="status"
        aria-live="polite"
        data-testid="system-status"
        data-status={status.state}
        {...(status.state === 'ready' ? { title: `${status.service} v${status.version}` } : {})}
      >
        <span className={styles.statusText}>
          <span className={styles.statusDot} aria-hidden="true" />
          <span>
            <strong>{lead}</strong> • {detail}
          </span>
        </span>
        <a
          className={styles.statusLink}
          href={LINKS.methodology}
          target="_blank"
          rel="noreferrer noopener"
        >
          Methodology
          <Icon name="arrow-outward" />
        </a>
      </p>
    </div>
  );
}
