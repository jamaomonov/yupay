/** Pure view helpers for the mini app's CS2 skins pages (node-testable). */

import type { SkinFacets, SkinItem, SkinQuery } from "@yupay/utils";

/** A "show more" page appends (deduped by slug — a price tick can shift a row
 *  across the cursor); a first page replaces. */
export function accumulateSkins(prev: SkinItem[], page: SkinItem[], append: boolean): SkinItem[] {
  if (!append) return page;
  const seen = new Set(prev.map((i) => i.slug));
  return [...prev, ...page.filter((i) => !seen.has(i.slug))];
}

/** Facets together with the category they were counted for. */
export interface ScopedFacets {
  category: string | undefined;
  facets: SkinFacets;
}

/**
 * The weapon row. Empty while the facets in hand still describe the previous
 * category — for one round-trip after a tap they would list AK-47 under
 * «Пистолеты», and tapping it gives an empty grid. The chosen weapon is kept.
 */
export function visibleWeapons(query: SkinQuery, scoped: ScopedFacets | undefined): string[] {
  if (!query.category || scoped?.category !== query.category) return [];
  const listed = scoped.facets.weapons.map((f) => f.value);
  return query.weapon && !listed.includes(query.weapon) ? [query.weapon, ...listed] : listed;
}
