'use client';

import type { VerifiedExample } from './verified-example';
import styles from './RoutePlanner.module.css';

export type VerifiedExampleCardProps = {
  readonly example: VerifiedExample;
  readonly onRun: (example: VerifiedExample) => void;
  /** True once this example's endpoints are the ones loaded. */
  readonly active: boolean;
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
export function VerifiedExampleCard({ example, onRun, active, busy }: VerifiedExampleCardProps) {
  // Once the example has been run, the answer is directly below this card and
  // needs the room. The card keeps its button and its provenance, and loses the
  // paragraph explaining an offer the viewer has already accepted.
  if (active) {
    return (
      <section className={styles.exampleCompact} data-testid="verified-example" data-active="true">
        <p className={styles.exampleDetail} id="verified-example-detail">
          <strong>Example journey:</strong> {example.originLabel} to {example.destinationLabel}.{' '}
          {example.provenance} Computed live.
        </p>
        <button
          type="button"
          className={styles.exampleButtonQuiet}
          onClick={() => onRun(example)}
          data-testid="run-verified-example"
          aria-describedby="verified-example-detail"
        >
          {busy ? 'Comparing…' : 'Run it again'}
        </button>
      </section>
    );
  }

  return (
    <section className={styles.example} data-testid="verified-example" data-active="false">
      <h3 className={styles.exampleTitle}>New here?</h3>
      <p className={styles.exampleBody}>
        Load a journey from our published evaluation corpus and compare a wheelchair route against
        the shortest walking route.
      </p>
      <button
        type="button"
        className={styles.exampleButton}
        onClick={() => onRun(example)}
        data-testid="run-verified-example"
        aria-describedby="verified-example-detail"
      >
        Try a wheelchair route example
      </button>
      <p className={styles.exampleDetail} id="verified-example-detail">
        {example.originLabel} to {example.destinationLabel}. {example.description}.{' '}
        {example.provenance} The comparison is computed live by the routing engine each time.
      </p>
    </section>
  );
}
