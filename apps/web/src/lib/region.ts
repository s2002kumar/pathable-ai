/**
 * Canadian province and territory abbreviations, as Canada Post writes them.
 *
 * The Golden Master labels the region "Waterloo, ON"; the configuration names
 * it in full. Shortening a known province is deterministic; anything else is
 * shown exactly as configured rather than guessed at.
 */
const PROVINCES: Readonly<Record<string, string>> = {
  alberta: 'AB',
  'british columbia': 'BC',
  manitoba: 'MB',
  'new brunswick': 'NB',
  'newfoundland and labrador': 'NL',
  'northwest territories': 'NT',
  'nova scotia': 'NS',
  nunavut: 'NU',
  ontario: 'ON',
  'prince edward island': 'PE',
  quebec: 'QC',
  saskatchewan: 'SK',
  yukon: 'YT',
};

/** "Waterloo, Ontario" → "Waterloo, ON"; anything unrecognised unchanged. */
export function shortRegionName(name: string): string {
  const comma = name.lastIndexOf(',');
  if (comma < 0) return name;
  const place = name.slice(0, comma).trim();
  const province = name.slice(comma + 1).trim();
  const code = PROVINCES[province.toLowerCase()];
  return code === undefined ? name : `${place}, ${code}`;
}
