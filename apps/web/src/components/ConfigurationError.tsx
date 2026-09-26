import type { ConfigIssue } from '@/lib/public-config';
import styles from '@/app/page.module.css';

export type ConfigurationErrorProps = {
  readonly issues: readonly ConfigIssue[];
};

/**
 * Rendered instead of the application when a `NEXT_PUBLIC_*` value is present but
 * invalid.
 *
 * Every problem is listed at once rather than one per reload, and the message
 * names the exact variable — misconfiguration is the single most likely thing to
 * go wrong on a fresh clone, and a blank screen teaches nobody anything.
 */
export function ConfigurationError({ issues }: ConfigurationErrorProps) {
  return (
    <main className={styles.configError} role="alert" data-testid="configuration-error">
      <h1 className={styles.configErrorTitle}>PathAble is misconfigured</h1>
      <p className={styles.configErrorBody}>
        {issues.length === 1
          ? 'One environment variable has an invalid value:'
          : `${issues.length} environment variables have invalid values:`}
      </p>
      <ul className={styles.configErrorList}>
        {issues.map((issue) => (
          <li className={styles.configErrorItem} key={`${issue.field}:${issue.message}`}>
            {issue.field} — {issue.message}
          </li>
        ))}
      </ul>
      <p className={styles.configErrorHint}>
        Compare your <code>.env</code> against <code>.env.example</code> in the repository root,
        then restart the dev server. Next.js inlines <code>NEXT_PUBLIC_*</code> values at build
        time, so a rebuild is required after changing them.
      </p>
    </main>
  );
}
