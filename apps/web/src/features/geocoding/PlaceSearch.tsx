'use client';

import { type ReactNode, useCallback, useId, useRef, useState } from 'react';
import { API_ROUTES, type GeocodeMatch, type GeocodeResponse } from '@pathable/contracts';
import { Icon } from '@/components/Icon';
import styles from './PlaceSearch.module.css';

/** Bounded so a slow geocoder cannot leave the form spinning. */
const SEARCH_TIMEOUT_MS = 15_000;

type SearchState =
  | { readonly status: 'idle' }
  | { readonly status: 'searching' }
  | { readonly status: 'disabled' }
  | {
      readonly status: 'results';
      readonly matches: readonly GeocodeMatch[];
      readonly attribution: string | null;
    }
  | { readonly status: 'error'; readonly message: string };

export type PlaceSearchProps = {
  readonly apiBaseUrl: string;
  readonly region: string;
  readonly onSelect: (position: { longitude: number; latitude: number }, label: string) => void;
  readonly fetchImpl?: typeof fetch;
  /**
   * Per-instance identity. The defaults are the single-field wording this
   * component shipped with, so one on its own is unchanged; a page with two
   * must give each a distinct accessible name, or every query for "Search for
   * a place" becomes ambiguous and the announcements land on the wrong field.
   */
  readonly label?: string;
  readonly placeholder?: string;
  readonly submitAccessibleName?: string;
  readonly testId?: string;
  /** The input's id, so another control (the header's search) can focus it. */
  readonly inputId?: string;
  /**
   * What the field currently resolves to. Shown as the input's text until the
   * viewer types something else, so the field reads "UW Davis Centre" rather
   * than an empty box beside a separate line naming it.
   */
  readonly currentValue?: string | null;
  /** Points at text describing the current value, for assistive technology. */
  readonly describedBy?: string;
  /** Controls drawn inside the field, after the input: swap, set on map, clear. */
  readonly trailing?: ReactNode;
  /** Drawn before the label: the endpoint's coloured dot. */
  readonly leading?: ReactNode;
  readonly className?: string;
  /** Rendered after the field: anything the field wants to say about itself. */
  readonly children?: ReactNode;
};

/**
 * Place-name search, drawn as the Golden Master's field: a small caps label
 * over the value, inside one surface.
 *
 * Submit-only, on purpose. As-you-type search would mean one request per
 * keystroke against a donated geocoding service, which its usage policy forbids
 * — and which the backend's one-request-per-second throttle would queue into a
 * uselessly laggy experience anyway. The submit button appears once there is
 * something new to search for; Enter submits as well.
 *
 * Search is also optional: when no provider is configured the API says so, and
 * this says so too rather than reporting "no results", which would send someone
 * off to rephrase a query that was never sent.
 */
export function PlaceSearch({
  apiBaseUrl,
  region,
  onSelect,
  fetchImpl,
  label = 'Search for a place',
  placeholder = 'e.g. Waterloo Public Square',
  submitAccessibleName,
  testId = 'place-search',
  inputId: providedInputId,
  currentValue = null,
  describedBy,
  trailing,
  leading,
  className,
  children,
}: PlaceSearchProps) {
  // The text the viewer has typed, or null while the field shows its value.
  const [draft, setDraft] = useState<string | null>(null);
  const [state, setState] = useState<SearchState>({ status: 'idle' });
  const inFlight = useRef<AbortController | null>(null);
  const generatedId = useId();
  const inputId = providedInputId ?? generatedId;

  const query = draft ?? currentValue ?? '';
  const searchable = draft !== null && draft.trim().length > 0 && draft !== currentValue;

  const submit = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (draft === null) return;
      const text = draft.trim();
      if (text.length === 0 || draft === currentValue) return;

      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;
      const timer = setTimeout(() => controller.abort(), SEARCH_TIMEOUT_MS);
      setState({ status: 'searching' });

      try {
        const doFetch = fetchImpl ?? globalThis.fetch;
        const response = await doFetch(`${apiBaseUrl}${API_ROUTES.searchPlaces}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ region, query: text }),
          signal: controller.signal,
          cache: 'no-store',
        });
        const body: unknown = await response.json().catch(() => null);

        if (!response.ok) {
          const message =
            typeof body === 'object' && body !== null && 'message' in body
              ? String((body as { message: unknown }).message)
              : `Search failed (HTTP ${response.status}).`;
          setState({ status: 'error', message });
          return;
        }

        const payload = body as GeocodeResponse | null;
        if (payload === null) {
          setState({ status: 'error', message: 'The search service returned nothing readable.' });
        } else if (!payload.enabled) {
          setState({ status: 'disabled' });
        } else {
          setState({
            status: 'results',
            matches: payload.matches,
            attribution: payload.attribution ?? null,
          });
        }
      } catch (error) {
        const timedOut = error instanceof Error && error.name === 'AbortError';
        setState({
          status: 'error',
          message: timedOut
            ? 'The search took too long. Try again, or click the map instead.'
            : 'The search service could not be reached. Click the map instead.',
        });
      } finally {
        clearTimeout(timer);
      }
    },
    [apiBaseUrl, region, draft, currentValue, fetchImpl],
  );

  return (
    <form
      className={[styles.form, className].filter(Boolean).join(' ')}
      onSubmit={submit}
      data-testid={testId}
    >
      <div className={styles.field}>
        {leading}
        <div className={styles.body}>
          <label className={styles.label} htmlFor={inputId}>
            {label}
          </label>
          <input
            id={inputId}
            className={styles.input}
            type="search"
            value={query}
            onChange={(event) => setDraft(event.target.value)}
            onFocus={(event) => {
              // Replacing a place is the common edit: select it so typing
              // starts over rather than appending to "UW Davis Centre".
              if (draft === null && currentValue) event.currentTarget.select();
            }}
            onKeyDown={(event) => {
              if (event.key === 'Escape' && draft !== null) {
                setDraft(null);
                setState({ status: 'idle' });
              }
            }}
            placeholder={placeholder}
            autoComplete="off"
            // No aria-live on the input: results are announced by the region below.
            enterKeyHint="search"
            {...(describedBy ? { 'aria-describedby': describedBy } : {})}
          />
        </div>
        {searchable ? (
          <button
            type="submit"
            className={styles.button}
            aria-label={submitAccessibleName ?? 'Search'}
            title="Search"
          >
            <Icon name="search" size={16} />
          </button>
        ) : null}
        {trailing}
      </div>

      {children}

      <div className={styles.results} aria-live="polite" data-search-state={state.status}>
        {state.status === 'searching' ? <p className={styles.note}>Searching…</p> : null}

        {state.status === 'disabled' ? (
          <p className={styles.note}>
            Place search is not enabled on this deployment. Click the map to choose points.
          </p>
        ) : null}

        {state.status === 'error' ? (
          <p className={styles.error} role="alert">
            {state.message}
          </p>
        ) : null}

        {state.status === 'results' && state.matches.length === 0 ? (
          <p className={styles.note}>
            Nothing matched that inside this area. Try a different name, or click the map.
          </p>
        ) : null}

        {state.status === 'results' && state.matches.length > 0 ? (
          <>
            <ul className={styles.matchList}>
              {state.matches.map((match) => (
                <li key={`${match.label}:${match.longitude}:${match.latitude}`}>
                  <button
                    type="button"
                    className={styles.match}
                    onClick={() => {
                      onSelect(
                        { longitude: match.longitude, latitude: match.latitude },
                        match.label,
                      );
                      setState({ status: 'idle' });
                      setDraft(null);
                    }}
                  >
                    {match.label}
                  </button>
                </li>
              ))}
            </ul>
            {/* The API returns the provider's attribution with every result set
                specifically so a client cannot display results without it. */}
            {state.attribution ? (
              <p className={styles.attribution} data-testid="search-attribution">
                {state.attribution}
              </p>
            ) : null}
          </>
        ) : null}
      </div>
    </form>
  );
}
