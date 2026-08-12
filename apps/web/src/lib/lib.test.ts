import { describe, expect, it } from 'vitest';
import { formatLatitude, formatLongitude } from './coordinates';
import { cx } from './cx';

describe('coordinate formatting', () => {
  it.each([
    [43.4668, '43.4668° N'],
    [-33.8688, '33.8688° S'],
    [0, '0.0000° N'],
  ])('formats latitude %s as %s', (value, expected) => {
    expect(formatLatitude(value)).toBe(expected);
  });

  it.each([
    [-80.5164, '80.5164° W'],
    [151.2093, '151.2093° E'],
    [0, '0.0000° E'],
  ])('formats longitude %s as %s', (value, expected) => {
    expect(formatLongitude(value)).toBe(expected);
  });

  it('pads to four decimals so the precision claim is consistent', () => {
    // ~11 m at this latitude: enough to identify an intersection, not enough to
    // imply survey accuracy the data does not have.
    expect(formatLatitude(43.5)).toBe('43.5000° N');
  });

  it('rounds rather than truncating', () => {
    expect(formatLatitude(43.46685)).toBe('43.4669° N');
  });
});

describe('cx', () => {
  it('joins present class names', () => {
    expect(cx('a', 'b')).toBe('a b');
  });

  it('drops undefined, which is what a missing CSS-module class yields', () => {
    expect(cx('a', undefined, 'b')).toBe('a b');
  });

  it('drops empty strings, null and false', () => {
    expect(cx('a', '', null, false, 'b')).toBe('a b');
  });

  it('returns an empty string when nothing survives', () => {
    expect(cx(undefined, null, false)).toBe('');
  });
});
