/**
 * One game, two brands: the region split.
 *
 * Mobile Legends and Magic Chess: Go Go are sold as separate brands per
 * region (`<slug>` and `<slug>-ru`, ADR-0079) because the two regions are
 * different supplier games — products, packages and the player check are per
 * brand. The web storefront shows two pages; the Mini App shows one card and
 * lets the customer pick the region on the top-up page. These helpers are the
 * whole pairing rule, so the page and the list cannot disagree about it.
 * Kept a leaf module: no imports, so both pages can pull it in.
 */

export const RU_SUFFIX = "-ru";

export type Region = "global" | "ru";

/** `mobile-legends-ru` → `mobile-legends`; anything else unchanged. */
export function baseSlug(slug: string): string {
  return slug.endsWith(RU_SUFFIX) ? slug.slice(0, -RU_SUFFIX.length) : slug;
}

/** Whether the catalogue carries a `-ru` twin for `base`. */
export function hasRuTwin(base: string, slugs: readonly string[]): boolean {
  return slugs.includes(`${base}${RU_SUFFIX}`);
}

/** The brand slug the page must talk to for `region`. */
export function regionSlug(base: string, region: Region): string {
  return region === "ru" ? `${base}${RU_SUFFIX}` : base;
}

/**
 * A route param may name either half of a pair (old "recent" entries and
 * shared links carry `mobile-legends-ru`). Resolve it to the base card plus
 * the region it meant — but only when the base is a real brand, so a brand
 * that merely ends in `-ru` is not torn apart.
 */
export function splitRegion(
  slug: string,
  slugs: readonly string[],
): { base: string; region: Region } {
  const base = baseSlug(slug);
  if (base !== slug && slugs.includes(base)) return { base, region: "ru" };
  return { base: slug, region: "global" };
}

/** The list with RU twins folded into their base card. Order preserved. */
export function mergeRegions<T extends { slug: string }>(games: readonly T[]): T[] {
  const slugs = games.map((g) => g.slug);
  return games.filter((g) => {
    const base = baseSlug(g.slug);
    return base === g.slug || !slugs.includes(base);
  });
}
