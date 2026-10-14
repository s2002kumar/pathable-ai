import styles from './Landing.module.css';

export type EvidenceKind = 'recorded' | 'derived' | 'missing' | 'profile';

/**
 * The four evidence labels, worded and coloured as the planner shows them:
 * neutral for a map fact, sky for an elevation estimate, amber for something
 * nobody recorded, emerald for the profile's own rule. Each also carries its
 * own mark, so the label never depends on colour alone.
 */
const LABELS: Record<EvidenceKind, string> = {
  recorded: 'Recorded · OSM',
  derived: 'Derived · HRDEM',
  missing: 'Not recorded',
  profile: 'Your profile rule',
};

export function EvidenceTag({ kind }: { readonly kind: EvidenceKind }) {
  return (
    <span className={styles.tag} data-kind={kind}>
      <span className={styles.tagMark} data-kind={kind} aria-hidden="true" />
      {LABELS[kind]}
    </span>
  );
}
