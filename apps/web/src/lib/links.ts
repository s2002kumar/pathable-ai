/**
 * Every outbound link the product prints, in one place.
 *
 * The repository is public (source-visible, all rights reserved), so the
 * methodology and data-source links point at the documents that actually
 * define the behaviour rather than at marketing copy about it.
 */
export const REPOSITORY_URL = 'https://github.com/s2002kumar/pathable-ai';

export const LINKS = {
  repository: REPOSITORY_URL,
  methodology: `${REPOSITORY_URL}/blob/main/docs/adr/0008-accessibility-cost-model.md`,
  dataSources: `${REPOSITORY_URL}/blob/main/docs/licensing/DATA_SOURCES.md`,
  architecture: `${REPOSITORY_URL}/blob/main/docs/architecture/OVERVIEW.md`,
  osmCopyright: 'https://www.openstreetmap.org/copyright',
  odbl: 'https://opendatacommons.org/licenses/odbl/1-0/',
  openFreeMap: 'https://openfreemap.org/',
} as const;
