/** Pure view helpers for the mini app's CS2 skins pages (node-testable). */

import type { SkinFamilyMember, SkinItem } from "@yupay/utils";

/** A "show more" page appends (deduped by slug — a price tick can shift a row
 *  across the cursor); a first page replaces. */
export function accumulateSkins(prev: SkinItem[], page: SkinItem[], append: boolean): SkinItem[] {
  if (!append) return page;
  const seen = new Set(prev.map((i) => i.slug));
  return [...prev, ...page.filter((i) => !seen.has(i.slug))];
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
