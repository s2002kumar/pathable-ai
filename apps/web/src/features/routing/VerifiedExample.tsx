'use client';

import type { VerifiedExample } from './verified-example';
import styles from './RoutePlanner.module.css';

export type VerifiedExampleCardProps = {
  readonly example: VerifiedExample;
  readonly onRun: (example: VerifiedExample) => void;
  /** True once this example's endpoints are the ones loaded. */
  readonly active: boolean;
  /** True once any endpoint is set, by the example or by hand. */
  readonly journeyStarted?: boolean;
  readonly busy: boolean;
};

/**
 * The shortest path to seeing what the product does.
 *
 * One press fills both endpoints and selects the wheelchair profile, which is
 * all the request needs — the comparison then runs through the same code a
 * hand-placed pair of points does. It is deliberately a preset and not a
 * shortcut: no route, distance or explanation is bundled here, so what appears
 * afterwards is the live answer and can be wrong in public if the engine
 * regresses.
 */
export function VerifiedExampleCard({
  example,
  onRun,
  active,
  journeyStarted = false,
  busy,
}: VerifiedExampleCardProps) {
  // Once a journey is under way — this example's, or one the viewer started by
  // hand — the answer is directly below this card and needs the room. The card
  // keeps its button and its provenance, and loses the paragraph explaining an
  // offer the viewer has already accepted or declined.
  if (active || journeyStarted) {
    return (
      <section
        className={styles.exampleCompact}
        data-testid="verified-example"
        data-active={active}
      >
        <p className={styles.exampleDetail} id="verified-example-detail">
          <strong>Example journey:</strong> {example.originLabel} to {example.destinationLabel}
          {active ? ', computed live.' : '. Computed live when you run it.'}
        </p>
        <button
          type="button"
          className={styles.exampleButtonQuiet}
          onClick={() => onRun(example)}
          data-testid="run-verified-example"
          aria-describedby="verified-example-detail"
        >
          {busy && active ? 'Comparing…' : active ? 'Run it again' : 'Try the example'}
        </button>
      </section>
    );
  }

  return (
    <section className={styles.example} data-testid="verified-example" data-active="false">
      <button
        type="button"
        className={styles.exampleButton}
        onClick={() => onRun(example)}
        data-testid="run-verified-example"
        aria-describedby="verified-example-detail"
      >
        Try a wheelchair route example
      </button>
      {/* Short enough to read before pressing. The corpus's own caveat — these
          are approximate positions, not surveyed points — moves behind the
          disclosure rather than out of the product: it qualifies the inputs,
          and the inputs are the only thing this preset supplies. */}
      <p className={styles.exampleDetail} id="verified-example-detail">
        {example.originLabel} to {example.destinationLabel}, computed live.
      </p>
      <details className="disclosure" data-testid="verified-example-provenance">
        <summary>Where these points come from</summary>
        <div className={styles.exampleProvenance}>
          <p>
            {example.description}. {example.provenance} PathAble snaps them to the nearest routable
            segment exactly as it would a map click, and the comparison is computed by the routing
            engine on every press — no distance, stairway count or explanation is stored here.
          </p>
        </div>
      </details>
    </section>
  );
}
