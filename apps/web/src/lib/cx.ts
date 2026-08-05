/**
 * Join class names, dropping anything absent.
 *
 * Exists because `noUncheckedIndexedAccess` types every CSS-module lookup as
 * `string | undefined` — which is correct, since a typo'd class silently yields
 * undefined — and interpolating that into a template literal would paste the
 * word "undefined" into the DOM.
 */
export function cx(...values: readonly (string | false | null | undefined)[]): string {
  return values
    .filter((value): value is string => typeof value === 'string' && value !== '')
    .join(' ');
}
