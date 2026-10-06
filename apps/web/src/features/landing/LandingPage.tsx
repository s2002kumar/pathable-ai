import Link from 'next/link';
import { Icon, type IconName } from '@/components/Icon';
import { LINKS } from '@/lib/links';
import { EXAMPLE_QUERY_PARAM } from '@/features/routing/verified-example';
import { RouteVisual } from './RouteVisual';
import { VERIFIED_ROUTE } from './verified-route';
import styles from './Landing.module.css';

const PLANNER_EXAMPLE = `/planner?${EXAMPLE_QUERY_PARAM}=campus-library-to-student-life`;

const route = VERIFIED_ROUTE;
const extra = route.extraDistanceM.toFixed(1);
const percent = Math.round(route.extraDistanceFraction * 100);
const missingShare = Math.round(route.accessible.unknownDataFraction * 100);

/**
 * The product's front door (Golden Master 10:2318, phone 17:3167).
 *
 * Every figure on it is one of three kinds, and only these: the verified
 * example as the routing API recorded it (`verified-route.ts`, dated, with the
 * dataset checksum), counts from the claims ledger (180,554 segments, 1 m
 * HRDEM), or statements of how the system behaves. No user counts, no
 * benchmarks that were not run, no "AI".
 */
export function LandingPage() {
  return (
    <div className={styles.page}>
      <LandingHeader />
      <main id="main-content">
        <Hero />
        <Comparison />
        <EvidenceModel />
        <Engineering />
        <Architecture />
        <Integrity />
        <FinalCta />
      </main>
      <LandingFooter />
    </div>
  );
}

function Brand() {
  return (
    <span className={styles.wordmark}>
      Path<span>Able</span>
    </span>
  );
}

function LandingHeader() {
  return (
    <header className={styles.header}>
      <div className={styles.headerInner}>
        <div className={styles.headerLead}>
          <Link href="/" className={styles.brandLink} aria-label="PathAble home">
            <span className={styles.brandDot} aria-hidden="true" />
            <Brand />
          </Link>
          <span className={styles.regionChip}>
            <span className={styles.chipDot} aria-hidden="true" />
            Waterloo, ON
          </span>
          <nav className={styles.nav} aria-label="Sections">
            <a href="#how-it-works">How It Works</a>
            <a href="#evidence">Evidence Model</a>
            <a href="#architecture">Architecture</a>
            <a href="#integrity">Integrity Principles</a>
          </nav>
        </div>
        <div className={styles.headerActions}>
          <a
            className={styles.githubButton}
            href={LINKS.repository}
            target="_blank"
            rel="noreferrer noopener"
          >
            <span className={styles.mono}>src/</span> GitHub
          </a>
          <Link href="/planner" className={styles.plannerButton} data-testid="header-explore">
            <span className={styles.plannerLong}>Explore Planner</span>
            <span className={styles.plannerShort}>Planner</span>
          </Link>
        </div>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------------------
// 1. Hero (10:2323, 17:3169)
// ---------------------------------------------------------------------------

function Hero() {
  return (
    <section className={styles.heroField} aria-labelledby="hero-heading">
      <div className={styles.glow} aria-hidden="true" />
      <div className={styles.hero}>
        <div className={styles.heroCopy}>
          <p className={styles.eyebrowBadge}>
            <span className={styles.chipDot} aria-hidden="true" />
            Accessibility-aware pedestrian routing · Waterloo, ON
          </p>
          <h1 className={styles.heroTitle} id="hero-heading">
            Routes that account for what you can <em>actually</em> <em>traverse</em>.
          </h1>
          <p className={styles.heroLead}>
            Compare the shortest pedestrian route with one adapted to your mobility needs — and see
            exactly why they differ.
          </p>
          <div className={styles.ctaRow}>
            <Link href="/planner" className={styles.primaryCta} data-testid="hero-explore">
              Explore Planner
              <Icon name="arrow-right" />
            </Link>
            <a
              className={styles.secondaryCta}
              href={LINKS.repository}
              target="_blank"
              rel="noreferrer noopener"
            >
              <span className={styles.monoGreen}>git::</span> View GitHub
            </a>
            <p className={styles.pilotNote}>
              <span className={styles.pilotDot} aria-hidden="true" />
              Waterloo pilot · 180,554 segments
            </p>
          </div>
        </div>

        <figure className={styles.visual} data-testid="hero-visual">
          <div className={styles.visualBar}>
            <span className={styles.windowDots} aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
            <span className={styles.visualTitle}>Local demo · Deployment pending</span>
            <Link href={PLANNER_EXAMPLE} className={styles.visualPath}>
              {PLANNER_EXAMPLE}
            </Link>
            <span className={styles.visualTags}>
              <span className={styles.monoGreen}>● VERSIONED_POSTGIS_GRAPH</span>
              <span>NRCAN_HRDEM_1M</span>
            </span>
          </div>
          <div className={styles.visualCanvas}>
            <RouteVisual
              width={1184}
              height={560}
              box={{ x: 470, y: 70, width: 640, height: 330 }}
            />
            <HeroHud />
            <div className={styles.visualDock}>
              <p className={styles.visualDockTitle}>
                <Icon name="fork" size={13} />
                Why this route is different
              </p>
              <p className={styles.visualDockText}>
                The wheelchair route is {extra} m longer ({percent}%) and avoids all{' '}
                {route.standard.stairways} stairways recorded on the shortest route. Missing
                accessibility data remains unknown.
              </p>
            </div>
          </div>
          <figcaption className={styles.visualCaption}>
            Recorded from the routing API on {route.recordedOn} · dataset{' '}
            {route.datasetChecksum.slice(0, 8)} · routing policy {route.routingPolicyVersion}. Open
            the planner to compute it live.
          </figcaption>
        </figure>

        {/* 17:3193 — the phone's compact presentation card. */}
        <figure className={styles.phoneVisual}>
          <div className={styles.phoneCanvas}>
            <RouteVisual
              width={358}
              height={320}
              compact
              box={{ x: 40, y: 50, width: 270, height: 190 }}
            />
            <div className={styles.phoneChips}>
              <span className={styles.phoneChip}>
                <span className={styles.chipDot} aria-hidden="true" />
                Verified Waterloo example
              </span>
              <span className={styles.phoneChipMono}>1m HRDEM</span>
            </div>
            <div className={styles.phoneCompare}>
              <span className={styles.phoneOption}>
                <span className={styles.phoneOptionHead} data-tone="good">
                  <Icon name="profile-wheelchair" size={11} /> Adaptive
                </span>
                <span className={styles.phoneOptionFigure}>
                  {Math.round(route.accessible.distanceM)}
                  <small>m</small> <span>{route.accessible.stairways} stairways</span>
                </span>
              </span>
              <span className={styles.phoneOption}>
                <span className={styles.phoneOptionHead} data-tone="barrier">
                  <Icon name="profile-walking" size={11} /> Shortest
                </span>
                <span className={styles.phoneOptionFigure}>
                  {Math.round(route.standard.distanceM)}
                  <small>m</small> <span>{route.standard.stairways} stairways</span>
                </span>
              </span>
            </div>
          </div>
          <figcaption className={styles.phoneStrip}>
            <span className={styles.phoneStripHead}>
              <span>Active constraint evaluation</span>
              <span className={styles.monoGreen}>Wheelchair profile</span>
            </span>
            <span className={styles.phoneStripLine}>
              <Icon name="fork" size={12} />+{extra} m (+{percent}%) to avoid{' '}
              {route.standard.stairways} stairways
            </span>
          </figcaption>
        </figure>
      </div>
    </section>
  );
}

function HeroHud() {
  return (
    <div className={styles.hud}>
      <div className={styles.hudHead}>
        <span className={styles.hudTitle}>Route Evaluation</span>
        <span className={styles.hudTag}>Active profile</span>
      </div>
      <div className={styles.hudCard}>
        <div className={styles.hudCardHead}>
          <span className={styles.hudName}>
            <span className={styles.hudDot} aria-hidden="true" />
            Wheelchair Route
          </span>
          <span className={styles.monoGreenSmall}>Wheelchair profile</span>
        </div>
        <p className={styles.hudFigures}>
          <span className={styles.hudDistance}>{Math.round(route.accessible.distanceM)} m</span>
          <span>
            +{extra} m (+{percent}%)
          </span>
        </p>
        <p className={styles.hudPills}>
          <span>{route.accessible.stairways} stairways</span>
          <span>grade: derived</span>
          <span className={styles.monoGreenSmall}>gaps shown</span>
        </p>
      </div>
      <div className={styles.hudCardMuted}>
        <div className={styles.hudCardHead}>
          <span className={styles.hudNameMuted}>
            <span className={styles.hudDotBarrier} aria-hidden="true" />
            Shortest (Direct)
          </span>
          <span className={styles.barrierSmall}>Excluded by profile</span>
        </div>
        <p className={styles.hudFiguresMuted}>
          <span className={styles.hudDistance}>{Math.round(route.standard.distanceM)} m</span>
          <span>{route.standard.stairways} stairways</span>
        </p>
        <p className={styles.hudWarning}>
          <Icon name="cancel-circle" size={12} />
          {route.standard.recordedSteps} recorded steps · {route.standard.stairwaysWithoutStepCount}{' '}
          counts missing
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 2. Comparison (10:2455, 17:3257)
// ---------------------------------------------------------------------------

function SectionHead({
  eyebrow,
  title,
  lead,
  phoneTitle,
  phoneLead,
  id,
}: {
  readonly eyebrow: string;
  readonly title: string;
  readonly lead: string;
  readonly phoneTitle?: string;
  readonly phoneLead?: string;
  readonly id: string;
}) {
  return (
    <div className={styles.sectionHead}>
      <p className={styles.eyebrow}>{eyebrow}</p>
      <h2 className={styles.sectionTitle} id={id}>
        <span className={phoneTitle ? styles.desktopOnly : undefined}>{title}</span>
        {phoneTitle ? <span className={styles.phoneOnly}>{phoneTitle}</span> : null}
      </h2>
      <p className={styles.sectionLead}>
        <span className={phoneLead ? styles.desktopOnly : undefined}>{lead}</span>
        {phoneLead ? <span className={styles.phoneOnly}>{phoneLead}</span> : null}
      </p>
    </div>
  );
}

function Fact({
  icon,
  title,
  detail,
  tone,
}: {
  readonly icon: IconName;
  readonly title: string;
  readonly detail: string;
  readonly tone: 'barrier' | 'good' | 'derived' | 'neutral';
}) {
  return (
    <li className={styles.fact}>
      <span className={styles.factIcon} data-tone={tone}>
        <Icon name={icon} size={16} />
      </span>
      <span>
        <span className={styles.factTitle}>{title}</span>
        <span className={styles.factDetail}>{detail}</span>
      </span>
    </li>
  );
}

function Comparison() {
  return (
    <section className={styles.sectionDark} id="how-it-works" aria-labelledby="comparison-heading">
      <div className={styles.container}>
        <SectionHead
          id="comparison-heading"
          eyebrow="Reroute analysis"
          title="The real trade-offs ordinary pedestrian routers hide."
          lead="Shortest-path routing can prefer a physically shorter path that conflicts with a mobility profile. PathAble exposes the recorded barriers and the distance trade-off."
          phoneTitle="Direct Route vs. Wheelchair Route"
          phoneLead="Verified Waterloo example from the implemented routing API."
        />

        <div className={styles.tradeGrid}>
          <article className={styles.tradeCard} data-variant="standard">
            <header className={styles.tradeHead}>
              <h3>
                <span className={styles.tradeDot} data-variant="standard" aria-hidden="true" />
                Shortest pedestrian route
              </h3>
              <span className={styles.tradeTag} data-variant="standard">
                <span className={styles.desktopOnly}>Direct / naïve</span>
                <span className={styles.phoneOnly}>Shortest baseline</span>
              </span>
            </header>
            <p className={styles.tradeFigure}>
              <span>{Math.round(route.standard.distanceM)} m</span>
              <small>{route.standard.stairways} stairways</small>
            </p>
            <ul className={`${styles.factList} ${styles.desktopOnly}`}>
              <Fact
                icon="stairs"
                tone="barrier"
                title={`${route.standard.stairways} recorded stairways`}
                detail="On the shortest route; each one ruled out by the wheelchair profile"
              />
              <Fact
                icon="trending-up"
                tone="barrier"
                title={`${route.standard.recordedSteps} recorded steps`}
                detail={`Plus ${route.standard.stairwaysWithoutStepCount} stairways with no recorded step count`}
              />
              <Fact
                icon="ruler"
                tone="neutral"
                title="Shortest-distance baseline"
                detail="Computed on every request, beside the profile's route"
              />
            </ul>
            <dl className={`${styles.metricGrid} ${styles.phoneOnly}`}>
              <div>
                <dt>Distance</dt>
                <dd>
                  {Math.round(route.standard.distanceM)} m · {route.standard.stairways} stairways
                </dd>
              </div>
              <div>
                <dt>Stairs</dt>
                <dd data-tone="barrier">{route.standard.recordedSteps} recorded steps</dd>
              </div>
              <div>
                <dt>Step counts</dt>
                <dd data-tone="barrier">
                  {route.standard.recordedSteps} recorded ·{' '}
                  {route.standard.stairwaysWithoutStepCount} missing
                </dd>
              </div>
              <div>
                <dt>Detour</dt>
                <dd>0 m (baseline)</dd>
              </div>
            </dl>
            <p className={styles.tradeStatus} data-tone="barrier">
              <Icon name="cancel-circle" size={15} />
              <span className={styles.desktopOnly}>
                Recorded stairways violate the wheelchair profile
              </span>
              <span className={styles.phoneOnly}>
                {route.standard.stairways} recorded stairways
              </span>
            </p>
          </article>

          <article className={styles.tradeCard} data-variant="accessible">
            <header className={styles.tradeHead}>
              <h3>
                <span className={styles.tradeDot} data-variant="accessible" aria-hidden="true" />
                Wheelchair route
              </h3>
              <span className={styles.tradeTag} data-variant="accessible">
                <span className={styles.desktopOnly}>Adaptive graph</span>
                <span className={styles.phoneOnly}>Wheelchair route</span>
              </span>
            </header>
            <p className={styles.tradeFigure} data-tone="good">
              <span>{Math.round(route.accessible.distanceM)} m</span>
              <small>
                +{extra} m <em>(+{percent}% vs shortest)</em>
              </small>
            </p>
            <ul className={`${styles.factList} ${styles.desktopOnly}`}>
              <Fact
                icon="check-circle"
                tone="good"
                title={`${route.accessible.stairways} recorded stairways`}
                detail={`Avoids all ${route.standard.stairways} stairways recorded on the shortest route`}
              />
              <Fact
                icon="dash"
                tone="derived"
                title="Grade evidence derived from HRDEM"
                detail="Gradient source: NRCan HRDEM-derived elevation"
              />
              <Fact
                icon="verified"
                tone="good"
                title={`At least one accessibility attribute is missing on ${missingShare}% of this route`}
                detail="Missing data remains explicit in the route evidence"
              />
            </ul>
            <dl className={`${styles.metricGrid} ${styles.phoneOnly}`}>
              <div>
                <dt>Distance</dt>
                <dd>
                  {Math.round(route.accessible.distanceM)} m · +{extra} m
                </dd>
              </div>
              <div>
                <dt>Stairs</dt>
                <dd data-tone="good">{route.accessible.stairways} recorded</dd>
              </div>
              <div>
                <dt>Grade source</dt>
                <dd data-tone="derived">Derived · HRDEM</dd>
              </div>
              <div>
                <dt>Trade-off</dt>
                <dd>+{percent}% vs shortest</dd>
              </div>
            </dl>
            <p className={styles.tradeStatus} data-tone="good">
              <Icon name="shield" size={15} />
              <span className={styles.desktopOnly}>
                Profile route avoids all {route.standard.stairways} recorded stairways
              </span>
              <span className={styles.phoneOnly}>
                Data gaps remain explicit · Missing stays explicit
              </span>
            </p>
          </article>
        </div>

        <p className={styles.callout}>
          <Icon name="info-small" />
          Verified Waterloo example ({route.originLabel} → {route.destinationLabel}) recorded from
          the implemented routing API: {route.standard.distanceM} m shortest vs{' '}
          {route.accessible.distanceM} m wheelchair route. One journey, not typical of all.
        </p>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// 3. Evidence model (10:2546, 17:3340)
// ---------------------------------------------------------------------------

const STATES: ReadonlyArray<{
  readonly n: string;
  readonly title: string;
  readonly tone: 'good' | 'derived' | 'barrier' | 'neutral';
  readonly icon: IconName;
  readonly body: string;
  readonly phoneBody: string;
  readonly footLabel: string;
  readonly foot: string;
}> = [
  {
    n: '01',
    title: 'Recorded · OSM',
    tone: 'good',
    icon: 'dataset',
    body: 'Physical features explicitly tagged in OpenStreetMap: stairways and step counts, surfaces, kerbs at crossings, widths and the rare recorded incline.',
    phoneBody: 'Explicit map facts such as recorded stairways and surface tags.',
    footLabel: 'Source',
    foot: 'OSM tags on each segment',
  },
  {
    n: '02',
    title: 'Derived · HRDEM',
    tone: 'derived',
    icon: 'terrain',
    body: 'Slope and elevation profiles calculated deterministically from Natural Resources Canada 1m High-Resolution Digital Elevation Model (HRDEM).',
    phoneBody:
      'Segment slope and elevation difference calculated deterministically via NRCan 1m high-resolution DEM.',
    footLabel: 'Source',
    foot: 'NRCan LiDAR 1m Grid',
  },
  {
    n: '03',
    title: 'Not recorded',
    tone: 'barrier',
    icon: 'help',
    body: 'Gaps where open data contains no kerb or surface tags. PathAble flags these as unconfirmed rather than assuming they are accessible.',
    phoneBody:
      'Gaps in open data flagged explicitly as unconfirmed rather than assumed step-free or safe.',
    footLabel: 'Handling',
    foot: 'Explicit Unknown (Null)',
  },
  {
    n: '04',
    title: 'Your profile rule',
    tone: 'neutral',
    icon: 'tune-small',
    body: 'Limits and constraints of the chosen mobility profile (Wheelchair, Cane, Stroller…) and a custom uphill limit of your own.',
    phoneBody: 'Profile limits, such as no recorded stairs, and a custom maximum uphill gradient.',
    footLabel: 'Applied',
    foot: 'By the routing service, per request',
  },
];

function EvidenceModel() {
  return (
    <section className={styles.sectionMid} id="evidence" aria-labelledby="evidence-heading">
      <div className={styles.container}>
        <SectionHead
          id="evidence-heading"
          eyebrow="Transparent ontology"
          title="PathAble shows what it knows — and what it doesn't."
          lead="No aggregate confidence scores or fabricated guarantees. Every accessibility fact is categorized transparently into one of four immutable states."
        />
        <ul className={styles.stateGrid}>
          {STATES.map((state) => (
            <li key={state.n} className={styles.stateCard} data-tone={state.tone}>
              <div className={styles.stateHead}>
                <span className={styles.stateTag} data-tone={state.tone}>
                  Category {state.n}
                </span>
                <span className={styles.stateIcon} data-tone={state.tone}>
                  <Icon name={state.icon} size={16} />
                </span>
                <span className={styles.stateDot} data-tone={state.tone} aria-hidden="true" />
              </div>
              <h3 className={styles.stateTitle}>{state.title}</h3>
              <p className={styles.stateBody}>
                <span className={styles.desktopOnly}>{state.body}</span>
                <span className={styles.phoneOnly}>{state.phoneBody}</span>
              </p>
              <p className={styles.stateFoot}>
                {state.footLabel}: <strong>{state.foot}</strong>
              </p>
            </li>
          ))}
        </ul>
        <div className={styles.banner}>
          <span className={styles.bannerIcon} aria-hidden="true">
            <Icon name="rule" />
          </span>
          <div>
            <p className={styles.bannerTitle}>No synthetic confidence scores.</p>
            <p className={styles.bannerText}>
              Missing data is represented as an explicit unknown, never smoothed away or
              hallucinated.
            </p>
          </div>
          <span className={styles.bannerCode}>DETERMINISTIC_EVIDENCE_ONLY</span>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// 4. Engineering (10:2635) and 5. Architecture (10:2675), phone 17:3387
// ---------------------------------------------------------------------------

const FACTS: ReadonlyArray<{
  readonly title: string;
  readonly short: string;
  readonly phoneLabel: string;
  readonly body: string;
  readonly tone: 'good' | 'derived' | 'neutral';
}> = [
  {
    title: '180,554 physical pedestrian segments',
    short: '180,554',
    phoneLabel: 'Pedestrian segments',
    body: 'The Waterloo pilot network from OpenStreetMap: 155,714 nodes and 361,108 directed routing edges.',
    tone: 'good',
  },
  {
    title: 'PostgreSQL / PostGIS',
    short: 'PostGIS',
    phoneLabel: 'GiST spatial index',
    body: 'Geospatial graph stored and queried in PostgreSQL/PostGIS with GiST spatial indexes.',
    tone: 'neutral',
  },
  {
    title: '1 m NRCan HRDEM elevation',
    short: '1 m',
    phoneLabel: 'NRCan HRDEM elevation',
    body: 'Deterministic grade derived from NRCan HRDEM 1 m LiDAR over the Waterloo pilot. A bare-earth model: it cannot see a ramp or a step.',
    tone: 'derived',
  },
  {
    title: 'Dijkstra + A* routing',
    short: 'Dijkstra+A*',
    phoneLabel: 'Profile cost weights',
    body: 'Both agree on optimal cost on every routable journey of the twenty-journey corpus. Costs use distance, profile rules, derived grade and missing evidence.',
    tone: 'good',
  },
  {
    title: 'Versioned datasets',
    short: 'Versioned',
    phoneLabel: 'Activation + rollback',
    body: 'Sealed dataset snapshots; a candidate goes live only on a stored route regression, and rollback reactivates the previous one.',
    tone: 'neutral',
  },
  {
    title: 'Provenance & uncertainty',
    short: 'Per-segment',
    phoneLabel: 'Provenance & evidence basis',
    body: 'Source provenance and evidence basis are preserved into every route explanation.',
    tone: 'derived',
  },
];

const PIPELINE: ReadonlyArray<{
  readonly stage: string;
  readonly title: string;
  readonly body: string;
  readonly tone: 'good' | 'derived';
}> = [
  {
    stage: 'Input data',
    title: 'OpenStreetMap + NRCan 1m DEM',
    body: 'Raw geometries & elevation tiles',
    tone: 'good',
  },
  {
    stage: 'Topology',
    title: 'Versioned PostGIS Graph',
    body: 'Noded pedestrian edges & intersections',
    tone: 'derived',
  },
  {
    stage: 'Classifier',
    title: 'Accessibility Evidence Layer',
    body: 'Recorded, derived and missing, per segment',
    tone: 'good',
  },
  {
    stage: 'Solver',
    title: 'Routing Engine (A* / Dijkstra)',
    body: 'Profile costs and hard limits',
    tone: 'derived',
  },
  { stage: 'API layer', title: 'FastAPI Backend', body: 'Typed JSON over OpenAPI', tone: 'good' },
  {
    stage: 'Client',
    title: 'PathAble Interface',
    body: 'Interactive Route Comparison HUD',
    tone: 'good',
  },
];

function Engineering() {
  return (
    <section className={styles.sectionDark} aria-labelledby="engineering-heading">
      <div className={styles.container}>
        <SectionHead
          id="engineering-heading"
          eyebrow="System architecture"
          title="Measured Engineering Facts"
          lead="Verifiable figures and invariants of the Waterloo pilot, each traceable to evidence in the repository."
          phoneTitle="Engineering Proof & Pipeline"
          phoneLead="Deterministic spatial computing over open civic infrastructure."
        />
        <ul className={styles.factGrid}>
          {FACTS.map((fact) => (
            <li key={fact.title} className={styles.factCard}>
              <p className={styles.factCardTitle} data-tone={fact.tone}>
                <span className={styles.desktopOnly}>{fact.title}</span>
                <span className={styles.phoneOnly}>{fact.short}</span>
              </p>
              <p className={styles.factCardBody}>
                <span className={styles.desktopOnly}>{fact.body}</span>
                <span className={styles.phoneOnly}>{fact.phoneLabel}</span>
              </p>
            </li>
          ))}
        </ul>

        {/* 17:3426 — the phone folds the architecture into this section. */}
        <div className={`${styles.flowCard} ${styles.phoneOnly}`}>
          <p className={styles.flowTitle}>Deterministic graph flow</p>
          <ol className={styles.flowList}>
            <li>
              <span>01</span>OpenStreetMap + NRCan 1m DEM
            </li>
            <li>
              <span>02</span>Versioned PostGIS Graph
            </li>
            <li>
              <span>03</span>Accessibility Evidence Layer &amp; Routing Engine
            </li>
            <li data-tone="good">
              <span>04</span>FastAPI Backend → PathAble Interface
            </li>
          </ol>
          <p className={styles.flowNote}>
            Municipal research datasets stay isolated from the production routing graph until
            licensing and validation gates pass.
          </p>
        </div>
      </div>
    </section>
  );
}

function Architecture() {
  return (
    <section
      className={`${styles.sectionMid} ${styles.desktopOnly}`}
      id="architecture"
      aria-labelledby="architecture-heading"
    >
      <div className={styles.container}>
        <SectionHead
          id="architecture-heading"
          eyebrow="Dataflow specification"
          title="Implemented Routing Architecture"
          lead="Deterministic transformation pipeline from raw geographic data products to request-time accessibility routing."
        />
        <ol className={styles.pipeline}>
          {PIPELINE.map((step, index) => (
            <li key={step.title} className={styles.pipelineItem}>
              <div className={styles.step} data-last={index === PIPELINE.length - 1}>
                <p className={styles.stepStage} data-tone={step.tone}>
                  {step.stage}
                </p>
                <p className={styles.stepTitle}>{step.title}</p>
                <p className={styles.stepBody}>{step.body}</p>
              </div>
              {index < PIPELINE.length - 1 ? (
                <span className={styles.stepArrow} aria-hidden="true">
                  <Icon name="arrow-right-small" />
                </span>
              ) : null}
            </li>
          ))}
        </ol>
        <div className={styles.researchNote}>
          <Icon name="science" />
          <div>
            <p className={styles.researchTitle}>Research vs. Production:</p>
            <p className={styles.researchText}>
              The City of Kitchener Active Transportation inventory is maintained separately in a
              research pipeline. Its assertions do not enter the production routing graph.
            </p>
            <p className={styles.researchCheck}>
              <span aria-hidden="true">✓</span> No machine-learning prediction currently affects
              PathAble routing.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// 6. Integrity (10:2762, 17:3467)
// ---------------------------------------------------------------------------

const PRINCIPLES = [
  {
    n: '01',
    title: 'Missing ≠ accessible',
    body: 'A crossing lacking a kerb tag in OpenStreetMap is not assumed ramped. Absence of recorded barriers is never treated as proof of accessibility.',
  },
  {
    n: '02',
    title: 'Agreement ≠ independent confirmation',
    body: 'Multiple community maps repeating the same untagged or copied feature do not constitute independent ground truth.',
  },
  {
    n: '03',
    title: 'Research evidence ≠ production evidence',
    body: 'Experimental civic datasets and exploratory barrier audits remain segregated in research until validation standards are met.',
  },
] as const;

function Integrity() {
  return (
    <section className={styles.sectionDark} id="integrity" aria-labelledby="integrity-heading">
      <div className={styles.container}>
        <SectionHead
          id="integrity-heading"
          eyebrow="Core ethos"
          title="What PathAble refuses to assume"
          lead="Accessibility systems fail when they substitute optimistic assumptions for physical verification. We adhere strictly to three refusal principles."
          phoneLead="Core axioms behind every calculated segment."
        />
        <ol className={styles.principles}>
          {PRINCIPLES.map((principle) => (
            <li key={principle.n} className={styles.principle}>
              <h3 className={styles.principleTitle}>
                <span className={styles.desktopOnly}>
                  {principle.n} / {principle.title}
                </span>
                <span className={styles.phoneOnly}>{principle.title}</span>
                <span className={`${styles.principleNumber} ${styles.phoneOnly}`}>
                  {principle.n}
                </span>
              </h3>
              <p className={styles.principleBody}>{principle.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// 7. CTA (10:2790) and footer (10:2809)
// ---------------------------------------------------------------------------

function FinalCta() {
  return (
    <section className={styles.ctaSection} aria-labelledby="cta-heading">
      <div className={styles.ctaCard}>
        <div className={styles.ctaGlow} aria-hidden="true" />
        <div className={styles.ctaCopy}>
          <h2 className={styles.ctaTitle} id="cta-heading">
            Ready to evaluate PathAble?
          </h2>
          <p className={styles.ctaText}>
            Explore the route comparison planner in Waterloo, or audit the graph pipeline and
            routing architecture on GitHub.
          </p>
        </div>
        <div className={styles.ctaActions}>
          <Link href="/planner" className={styles.primaryCta}>
            Explore Planner
            <Icon name="arrow-right" />
          </Link>
          <a
            className={styles.secondaryCta}
            href={LINKS.repository}
            target="_blank"
            rel="noreferrer noopener"
          >
            <span className={styles.monoGreen}>src/</span> View GitHub
          </a>
        </div>
      </div>
    </section>
  );
}

function LandingFooter() {
  return (
    <footer className={styles.footer} data-testid="landing-footer">
      <div className={styles.footerMain}>
        <div className={styles.footerBrand}>
          <p className={styles.footerName}>
            <Brand />
            <span className={styles.footerTag}>Waterloo pilot</span>
          </p>
          <p className={styles.footerText}>
            Accessibility-aware pedestrian routing built on a versioned pedestrian graph and NRCan
            elevation evidence.
          </p>
          <p className={styles.footerAttribution}>
            Map data ©{' '}
            <a href={LINKS.osmCopyright} target="_blank" rel="noreferrer noopener">
              OpenStreetMap contributors
            </a>
            , ODbL 1.0 · NRCan HRDEM, contains information licensed under the Open Government
            Licence – Canada
          </p>
        </div>
        <nav className={styles.footerNav} aria-label="Footer">
          <a href={LINKS.methodology} target="_blank" rel="noreferrer noopener">
            Methodology
          </a>
          <a href={LINKS.dataSources} target="_blank" rel="noreferrer noopener">
            About Open Data
          </a>
          <a href={LINKS.repository} target="_blank" rel="noreferrer noopener">
            GitHub Repository
          </a>
          <a href={LINKS.odbl} target="_blank" rel="noreferrer noopener">
            ODbL License
          </a>
        </nav>
      </div>
      <div className={styles.footerBase}>
        <p>© 2026 PathAble Project. All rights reserved.</p>
        <p className={styles.mono}>EPSG:4326 · WGS 84</p>
      </div>
    </footer>
  );
}
