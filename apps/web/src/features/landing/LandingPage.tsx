import Link from 'next/link';
import { Icon } from '@/components/Icon';
import { TO_PLANNER } from '@/components/PageTransition';
import { LINKS } from '@/lib/links';
import { EXAMPLE_QUERY_PARAM } from '@/features/routing/verified-example';
import { EvidenceExplorer } from './EvidenceExplorer';
import { EvidenceTag, type EvidenceKind } from './EvidenceTag';
import { FIGURES, ROUTE, journeyGeometry, metres, percent, sharedLengths } from './journey';
import { bounds, pathData } from './stage-frame';
import { LandingMotion } from './LandingMotion';
import { RouteStage, type StageStep } from './RouteStage';
import styles from './Landing.module.css';

const PLANNER = '/planner';
const PLANNER_EXAMPLE = `/planner?${EXAMPLE_QUERY_PARAM}=campus-library-to-student-life`;
const INTO_PLANNER = [TO_PLANNER];

/**
 * The product's front door.
 *
 * Every figure on it is one of three kinds, and only these: the verified
 * example as the routing API recorded it (`verified-route.ts`, dated, with
 * the dataset checksum, read through `journey.ts`), measurements quoted from
 * the claims ledger with their conditions, or statements of how the system
 * behaves. No user counts, no benchmark that was not run, no "AI".
 *
 * One stage carries the visual story: it sits beside the hero and the four
 * story steps (above them on a phone) and follows whichever step is being
 * read. Everything it shows is also written down, so the page reads the same
 * with motion reduced, with script off, or with a screen reader.
 */
export function LandingPage() {
  return (
    <div className={styles.page}>
      <LandingHeader />
      <main id="main-content">
        <div className={styles.split} data-story-root="" data-step={'overview' satisfies StageStep}>
          <Hero />
          <div className={styles.stageColumn}>
            <RouteStage />
          </div>
          <Story />
        </div>
        <Evidence />
        <Engineering />
        <Integrity />
        <FinalCta />
      </main>
      <LandingFooter />
      <LandingMotion />
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
          <span className={styles.regionChip}>Waterloo, ON</span>
          <nav className={styles.nav} aria-label="Sections">
            <a href="#how-it-works">How it works</a>
            <a href="#evidence">Evidence</a>
            <a href="#engineering">Engineering</a>
            <a href="#integrity">Principles</a>
          </nav>
        </div>
        <div className={styles.headerActions}>
          <a
            className={styles.githubButton}
            href={LINKS.repository}
            target="_blank"
            rel="noreferrer noopener"
          >
            <span className={styles.mono}>src/</span>
            <span className={styles.githubText}>GitHub</span>
          </a>
          <Link
            href={PLANNER}
            className={styles.plannerButton}
            data-testid="header-explore"
            transitionTypes={INTO_PLANNER}
          >
            <span className={styles.plannerLong}>Open planner</span>
            <span className={styles.plannerShort}>Planner</span>
          </Link>
        </div>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------------------
// Hero
// ---------------------------------------------------------------------------

function Hero() {
  return (
    <section className={styles.hero} aria-labelledby="hero-heading" data-story-step="overview">
      <div className={styles.heroCopy}>
        <p className={styles.eyebrowBadge}>
          <span className={styles.liveDot} aria-hidden="true" />
          Accessibility-aware pedestrian routing · Waterloo pilot
        </p>
        <h1 className={styles.heroTitle} id="hero-heading">
          Routes that account for what you can <em>actually traverse</em>.
        </h1>
        <p className={styles.heroLead}>
          Compare the shortest pedestrian route with one adapted to your mobility needs — and see
          exactly why they differ.
        </p>
        <div className={styles.ctaRow}>
          <Link
            href={PLANNER}
            className={styles.primaryCta}
            data-testid="hero-explore"
            transitionTypes={INTO_PLANNER}
          >
            Open the planner
            <Icon name="arrow-right" />
          </Link>
          <a
            className={styles.secondaryCta}
            href={LINKS.repository}
            target="_blank"
            rel="noreferrer noopener"
          >
            <span className={styles.monoGreen}>git::</span> View the source
          </a>
        </div>
      </div>

      <div className={styles.readout} data-testid="hero-readout">
        <dl className={styles.readoutRows}>
          <div className={styles.readoutRow} data-route="standard">
            <dt>
              <span className={styles.legendLine} data-kind="standard" />
              Shortest walking route
            </dt>
            <dd className={styles.readoutFigure}>{FIGURES.standardDistance}</dd>
            <dd className={styles.readoutDetail} data-tone="barrier">
              {ROUTE.standard.stairways} recorded stairways
            </dd>
          </div>
          <div className={styles.readoutRow} data-route="accessible">
            <dt>
              <span className={styles.legendLine} data-kind="accessible" />
              Wheelchair profile route
            </dt>
            <dd className={styles.readoutFigure}>{FIGURES.accessibleDistance}</dd>
            <dd className={styles.readoutDetail} data-tone="good">
              {ROUTE.accessible.stairways} recorded stairways
            </dd>
          </div>
        </dl>
        <p className={styles.readoutSummary}>
          The wheelchair route is {FIGURES.extra} longer ({FIGURES.extraPercent}) and avoids all{' '}
          {ROUTE.standard.stairways} stairways recorded on the shortest route. Missing accessibility
          data remains unknown.
        </p>
        <p className={styles.readoutSource}>
          Recorded from the routing API on {ROUTE.recordedOn} · dataset {FIGURES.datasetShort} ·
          routing policy {ROUTE.routingPolicyVersion}.{' '}
          <Link href={PLANNER_EXAMPLE} transitionTypes={INTO_PLANNER}>
            Compute this journey live
          </Link>
        </p>
      </div>

      <p className={styles.truthLine}>
        <span>Local demo · Not deployed</span>
        <span aria-hidden="true">·</span>
        <span>It advises; it does not certify.</span>
      </p>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Story — the stage follows these four steps
// ---------------------------------------------------------------------------

type StoryStep = {
  readonly step: Exclude<StageStep, 'overview'>;
  readonly title: string;
  readonly body: string;
  readonly tags: readonly EvidenceKind[];
  readonly facts: readonly string[];
};

function storySteps(): readonly StoryStep[] {
  const shared = sharedLengths();
  const { standard, accessible } = ROUTE;
  const counted = standard.stairways - standard.stairwaysWithoutStepCount;
  return [
    {
      step: 'together',
      title: 'Both routes leave the library together.',
      body:
        `They share the first ${metres(shared.startM, 0)} and the last ${metres(shared.endM, 0)}. ` +
        'PathAble computes the shortest walk on every request, beside the profile’s route, so ' +
        'every difference is measured against it.',
      tags: [],
      facts: [
        `${metres(shared.startM, 0)} shared at the start`,
        `${metres(shared.endM, 0)} at the end`,
      ],
    },
    {
      step: 'stairs',
      title: `The shortest route takes ${standard.stairways} recorded stairways.`,
      body:
        `OpenStreetMap records ${standard.recordedSteps} steps across ${counted} of them. The ` +
        `other ${standard.stairwaysWithoutStepCount} have no recorded step count — unknown, ` +
        'not zero.',
      tags: ['recorded'],
      facts: [
        `${standard.stairways} stairways`,
        `${standard.recordedSteps} recorded steps`,
        `${standard.stairwaysWithoutStepCount} counts missing`,
      ],
    },
    {
      step: 'rule',
      title: 'The wheelchair profile rules every one of them out.',
      body:
        'A recorded stairway is a hard limit for this profile, and PathAble never relaxes a hard ' +
        `limit to find a route. Its route goes around: ${FIGURES.accessibleDistance} with no ` +
        `recorded stairways, ${FIGURES.extra} (${FIGURES.extraPercent}) longer.`,
      tags: ['profile'],
      facts: [
        `+${FIGURES.extra}`,
        `${FIGURES.extraPercent} longer`,
        `${accessible.stairways} recorded stairways`,
      ],
    },
    {
      step: 'unknown',
      title: 'What nobody recorded stays unknown.',
      body:
        `No surface is recorded on ${FIGURES.surfaceMissing.accessible} of the wheelchair route, ` +
        'and no width or smoothness on any of it. PathAble reports each gap and adds a cost for ' +
        'it; a missing tag is never read as a clear path. Gradient is estimated from the 1 m ' +
        `elevation model on ${percent(accessible.gradient.estimatedFraction)} of the route, ` +
        'because OpenStreetMap records none here.',
      tags: ['missing', 'derived'],
      facts: [
        `Surface missing on ${FIGURES.surfaceMissing.accessible}`,
        `Gradient derived on ${percent(accessible.gradient.estimatedFraction)}`,
      ],
    },
  ];
}

function Story() {
  return (
    <section className={styles.story} id="how-it-works" aria-labelledby="story-heading">
      <div className={styles.storyHead}>
        <p className={styles.eyebrow}>How it works</p>
        <h2 className={styles.sectionTitle} id="story-heading">
          One journey, taken apart.
        </h2>
        <p className={styles.sectionLead}>
          Four things happen between the Davis Centre library and the Student Life Centre on the
          University of Waterloo campus. Every figure here comes from the recorded response.
        </p>
      </div>
      <ol className={styles.steps}>
        {storySteps().map((step, index) => (
          <li key={step.step} className={styles.step} data-story-step={step.step}>
            <p className={styles.stepIndex}>{String(index + 1).padStart(2, '0')}</p>
            <h3 className={styles.stepTitle}>{step.title}</h3>
            <p className={styles.stepBody}>{step.body}</p>
            {step.tags.length > 0 ? (
              <p className={styles.stepTags}>
                {step.tags.map((tag) => (
                  <EvidenceTag key={tag} kind={tag} />
                ))}
              </p>
            ) : null}
            <ul className={styles.stepFacts}>
              {step.facts.map((fact) => (
                <li key={fact}>{fact}</li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
      <div className={styles.callout}>
        <Icon name="info-small" />
        <p>
          Verified Waterloo example ({ROUTE.originLabel} → {ROUTE.destinationLabel}) recorded from
          the implemented routing API: {ROUTE.standard.distanceM} m shortest vs{' '}
          {ROUTE.accessible.distanceM} m wheelchair route. One journey, not typical of all. Across a
          20-journey corpus fixed before any route was computed, 18 route differently (median detour
          86.1 m) and one has no route at all.
        </p>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Evidence
// ---------------------------------------------------------------------------

const KINDS: ReadonlyArray<{ readonly kind: EvidenceKind; readonly body: string }> = [
  {
    kind: 'recorded',
    body: 'Physical features explicitly tagged in OpenStreetMap: stairways and step counts, surfaces, kerbs at crossings, widths and the rare recorded incline.',
  },
  {
    kind: 'derived',
    body: 'Slope calculated deterministically from Natural Resources Canada’s 1 m High-Resolution Digital Elevation Model, and always labelled as an estimate.',
  },
  {
    kind: 'missing',
    body: 'Gaps where open data contains no tag. PathAble flags them as unconfirmed and costs them, rather than assuming they are accessible.',
  },
  {
    kind: 'profile',
    body: 'Limits of the chosen mobility profile — wheelchair, walker, stroller, crutches or cane — and a custom uphill limit of your own.',
  },
];

function Evidence() {
  return (
    <section className={styles.section} id="evidence" aria-labelledby="evidence-heading">
      <div className={styles.container}>
        <div className={styles.sectionHead} data-reveal="">
          <p className={styles.eyebrow}>Evidence model</p>
          <h2 className={styles.sectionTitle} id="evidence-heading">
            PathAble shows what it knows — and what it doesn&rsquo;t.
          </h2>
          <p className={styles.sectionLead}>
            No aggregate confidence score. Every accessibility fact is one of four kinds, kept apart
            from the database to this page. Pick a lens to see both routes drawn to scale, segment
            by segment, the way the routing engine reads them.
          </p>
        </div>
        <div data-reveal="">
          <EvidenceExplorer />
        </div>
        <ul className={styles.kinds} data-reveal="">
          {KINDS.map(({ kind, body }) => (
            <li key={kind} className={styles.kind}>
              <EvidenceTag kind={kind} />
              <p>{body}</p>
            </li>
          ))}
        </ul>
        <p className={styles.banner} data-reveal="">
          <strong>No synthetic confidence scores.</strong> Missing data is represented as an
          explicit unknown, never smoothed away or guessed.
        </p>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Engineering
// ---------------------------------------------------------------------------

/** Each figure is the claims ledger's wording, with the conditions it carries there. */
const MEASURES: ReadonlyArray<{
  readonly figure: string;
  readonly label: string;
  readonly body: string;
}> = [
  {
    figure: '180,554',
    label: 'pedestrian segments',
    body: 'The Waterloo pilot network from OpenStreetMap: 155,714 nodes and 361,108 directed routing edges.',
  },
  {
    figure: '46 of 180,554',
    label: 'segments with an OSM incline',
    body: 'Just 0.03% — so grade comes from NRCan’s 1 m HRDEM, chosen by measuring that a 30 m model’s error exceeds the signal: RMSE 4.06 pp against a 1.78% median grade over 50 m.',
  },
  {
    figure: '1,970 / 7,409',
    label: 'nodes expanded at the median, A* / Dijkstra',
    body: 'They agree on optimal cost on every routable journey of the corpus. A* is not faster here: 195 ms against 213 ms at p50, one laptop, warm graph.',
  },
  {
    figure: '18 of 20',
    label: 'corpus journeys route differently',
    body: 'Median detour 86.1 m across those 18. One journey has no route at all: its connection leaves the pilot area, and PathAble says so instead of inventing one.',
  },
  {
    figure: '46.83 s → 22.14 s',
    label: 'median graph load',
    body: 'After profiling found ORM entity construction to be the bottleneck. Peak Python heap 1,381.3 MB → 700.7 MB, with identical node and segment fingerprints. Same laptop, under memory pressure.',
  },
];

const LINE: ReadonlyArray<{ readonly title: string; readonly body: string }> = [
  {
    title: 'Sealed, versioned graph',
    body: 'PostGIS, checksummed; live only after a stored route regression',
  },
  { title: 'Evidence per segment', body: 'Recorded, derived and missing, kept apart' },
  { title: 'Dijkstra + A*', body: 'Profile costs and hard limits' },
  { title: 'FastAPI', body: 'Typed OpenAPI; contract drift fails CI' },
  { title: 'This interface', body: 'The comparison, with its evidence' },
];

function Engineering() {
  return (
    <section className={styles.section} id="engineering" aria-labelledby="engineering-heading">
      <div className={styles.container}>
        <div className={styles.sectionHead} data-reveal="">
          <p className={styles.eyebrow}>Engineering</p>
          <h2 className={styles.sectionTitle} id="engineering-heading">
            Measured, with the conditions attached.
          </h2>
          <p className={styles.sectionLead}>
            Figures from runs recorded in the repository&rsquo;s evidence. Wall-clock numbers come
            from one laptop: a shape, not a service level.
          </p>
        </div>

        <ul className={styles.measures} data-reveal="">
          {MEASURES.map((measure) => (
            <li key={measure.label} className={styles.measure}>
              <p className={styles.measureFigure}>{measure.figure}</p>
              <p className={styles.measureLabel}>{measure.label}</p>
              <p className={styles.measureBody}>{measure.body}</p>
            </li>
          ))}
        </ul>

        <div className={styles.lineCard} data-reveal="">
          <h3 className={styles.lineTitle}>From open data to a route</h3>
          <div className={styles.lineSources}>
            <span>OpenStreetMap extract</span>
            <span>NRCan HRDEM 1 m</span>
          </div>
          <ol className={styles.line}>
            {LINE.map((station) => (
              <li key={station.title} className={styles.station}>
                <span className={styles.stationDot} aria-hidden="true" />
                <span className={styles.stationTitle}>{station.title}</span>
                <span className={styles.stationBody}>{station.body}</span>
              </li>
            ))}
          </ol>
          <div className={styles.spur}>
            <span className={styles.spurLine} aria-hidden="true" />
            <p>
              The <strong>City of Kitchener Active Transportation inventory</strong> is kept in a
              separate research pipeline. Its assertions do not enter the production routing graph.
            </p>
          </div>
          <p className={styles.noModel}>
            <Icon name="check-circle-outline" size={14} />
            No machine-learning prediction currently affects PathAble routing.
          </p>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Integrity
// ---------------------------------------------------------------------------

const PRINCIPLES = [
  {
    left: 'Missing',
    right: 'accessible',
    body: 'A crossing lacking a kerb tag in OpenStreetMap is not assumed ramped. Absence of recorded barriers is never treated as proof of accessibility.',
  },
  {
    left: 'Agreement',
    right: 'independent confirmation',
    body: 'Several community maps repeating the same untagged or copied feature do not make independent ground truth.',
  },
  {
    left: 'Research evidence',
    right: 'production evidence',
    body: 'Experimental civic datasets and exploratory barrier audits stay in research until validation standards are met.',
  },
] as const;

function Integrity() {
  return (
    <section className={styles.section} id="integrity" aria-labelledby="integrity-heading">
      <div className={styles.container}>
        <div className={styles.sectionHead} data-reveal="">
          <p className={styles.eyebrow}>Principles</p>
          <h2 className={styles.sectionTitle} id="integrity-heading">
            What PathAble refuses to assume.
          </h2>
        </div>
        <ol className={styles.principles}>
          {PRINCIPLES.map((principle, index) => (
            <li key={principle.left} className={styles.principle} data-reveal="">
              <span className={styles.principleNumber}>{String(index + 1).padStart(2, '0')}</span>
              <h3 className={styles.principleTitle}>
                {principle.left} <span className={styles.notEqual}>≠</span> {principle.right}
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
// Into the planner, and the footer
// ---------------------------------------------------------------------------

/** The same two recorded routes, small: the journey the buttons below open. */
function JourneyMark() {
  const g = journeyGeometry();
  const box = bounds([...g.standard, ...g.accessible], 6);
  return (
    <svg
      className={styles.ctaRoutes}
      viewBox={`${box.x} ${box.y} ${box.width} ${box.height}`}
      aria-hidden="true"
      focusable="false"
    >
      <path d={pathData(g.standard)} data-kind="standard" />
      <path d={pathData(g.accessible)} data-kind="accessible" />
      {g.stairs.map((group, index) => (
        <circle key={index} cx={group.at[0]} cy={group.at[1]} r={3.2} />
      ))}
    </svg>
  );
}

function FinalCta() {
  return (
    <section className={styles.ctaSection} aria-labelledby="cta-heading">
      <div className={styles.ctaCard} data-reveal="">
        <JourneyMark />
        <div className={styles.ctaCopy}>
          <h2 className={styles.ctaTitle} id="cta-heading">
            See it compute.
          </h2>
          <p className={styles.ctaText}>
            The planner routes the same journey live against the Waterloo network, or any two points
            you place inside the pilot area — with its reasons and its gaps shown.
          </p>
        </div>
        <div className={styles.ctaActions}>
          <Link href={PLANNER_EXAMPLE} className={styles.primaryCta} transitionTypes={INTO_PLANNER}>
            Open the verified journey
            <Icon name="arrow-right" />
          </Link>
          <Link href={PLANNER} className={styles.secondaryCta} transitionTypes={INTO_PLANNER}>
            Plan your own route
          </Link>
        </div>
        <p className={styles.ctaNote}>
          Runs locally against the real Waterloo dataset. Not deployed.
        </p>
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
