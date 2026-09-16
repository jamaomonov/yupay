import type { BrandSummary } from "./catalog";

/**
 * The other region's brand, for the two games we sell as two brands.
 *
 * A brand is one supplier game (ADR-0079), so Mobile Legends and Mobile
 * Legends RU are separate brands. The pairing is the slug convention
 * `<slug>` ↔ `<slug>-ru` rather than a column: two brands do not justify a
 * schema, and the convention is the one the seed that created them follows.
 */
export function regionSibling(slug: string, brands: BrandSummary[]): BrandSummary | null {
  const twin = slug.endsWith("-ru") ? slug.slice(0, -"-ru".length) : `${slug}-ru`;
  return brands.find((b) => b.slug === twin) ?? null;
}
