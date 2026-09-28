/** Pure view helpers for the mini app's CS2 skins pages (node-testable). */

import type { SkinFamilyMember, SkinItem, SkinQuery } from "@yupay/utils";

/** A "show more" page appends (deduped by slug — a price tick can shift a row
 *  across the cursor); a first page replaces. */
export function accumulateSkins(prev: SkinItem[], page: SkinItem[], append: boolean): SkinItem[] {
  if (!append) return page;
  const seen = new Set(prev.map((i) => i.slug));
  return [...prev, ...page.filter((i) => !seen.has(i.slug))];
}

/** Filters set in the sheet — the badge on its button. A price range is one. */
export function activeFilterCount(q: SkinQuery): number {
  return [
    q.exterior !== undefined,
    q.rarity !== undefined,
    q.stattrak === true,
    q.minUzs !== undefined || q.maxUzs !== undefined,
  ].filter(Boolean).length;
}

/** Short label of a wear tile: `FT`, `ST · FT`, `SV · MW`. */
export function familyLabel(
  m: Pick<SkinFamilyMember, "exterior" | "stattrak" | "souvenir">,
): string {
  const wear = m.exterior ?? "—";
  if (m.stattrak) return `ST · ${wear}`;
  if (m.souvenir) return `SV · ${wear}`;
  return wear;
}
