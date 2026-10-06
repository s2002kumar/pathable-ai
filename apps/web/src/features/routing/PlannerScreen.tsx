'use client';

import { AppHeader } from '@/components/AppHeader';
import { PlannerFooter } from '@/components/PlannerFooter';
import { useSystemStatus } from '@/features/system-status/useSystemStatus';
import { ENDPOINT_INPUT_IDS } from './EndpointField';
import { RouteWorkspace, type RouteWorkspaceProps } from './RouteWorkspace';
import styles from './PlannerScreen.module.css';

/** Links the map region to its written description via aria-describedby. */
export const PILOT_DESCRIPTION_ID = 'pilot-area-description';

export type PlannerScreenProps = Omit<RouteWorkspaceProps, 'systemStatus' | 'describedById'> & {
  /** 0 disables polling. The e2e suite uses this for deterministic assertions. */
  readonly statusPollIntervalMs?: number;
};

/**
 * The planner page (Golden Master 9:1905 and its states): the 64 px bar, the
 * map with everything floating over it, and the credit line.
 *
 * The API's readiness is probed once here and shared: the bar's region dot and
 * the idle status strip are two views of the same answer, not two requests.
 */
export function PlannerScreen({ statusPollIntervalMs, ...workspace }: PlannerScreenProps) {
  const { status } = useSystemStatus({
    apiBaseUrl: workspace.apiBaseUrl,
    ...(statusPollIntervalMs !== undefined ? { pollIntervalMs: statusPollIntervalMs } : {}),
  });

  return (
    <div className={styles.shell}>
      <AppHeader
        pilotRegionName={workspace.regionName}
        status={status}
        searchTargetId={ENDPOINT_INPUT_IDS.origin}
      />
      <main className={styles.main} id="main-content">
        {/* The map's text alternative: what it conveys, stated, including the
            two sentences that make this product safe to read. */}
        <p className="visually-hidden" id={PILOT_DESCRIPTION_ID} data-testid="pilot-description">
          PathAble compares the shortest walking route with one that suits how you travel, using
          what OpenStreetMap actually records. Missing information is never treated as a clear path,
          and no route here is a guarantee that a journey is passable.
        </p>
        <RouteWorkspace {...workspace} systemStatus={status} describedById={PILOT_DESCRIPTION_ID} />
      </main>
      <PlannerFooter />
    </div>
  );
}
