/**
 * Coordinate formatting for display.
 *
 * Four decimal places is roughly 11 m at this latitude — precise enough to
 * identify an intersection, coarse enough not to imply survey accuracy the data
 * does not have.
 */

const DECIMALS = 4;

function format(value: number, positive: string, negative: string): string {
  const hemisphere = value >= 0 ? positive : negative;
  return `${Math.abs(value).toFixed(DECIMALS)}° ${hemisphere}`;
}

export function formatLatitude(latitude: number): string {
  return format(latitude, 'N', 'S');
}

export function formatLongitude(longitude: number): string {
  return format(longitude, 'E', 'W');
}
