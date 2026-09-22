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
          {active ? ', approximate positions, computed live.' : '. Computed live when you run it.'}
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
      <p className={styles.exampleEyebrow}>Start here</p>
      <h2 className={styles.exampleTitle}>See the difference in one press</h2>
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
        {example.originLabel} to {example.destinationLabel}: {example.description.toLowerCase()}.{' '}
        {example.provenance} The comparison is computed live by the routing engine each time.
      </p>
    </section>
  );
}
