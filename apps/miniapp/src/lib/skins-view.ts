/** Pure view helpers for the mini app's CS2 skins pages (node-testable). */

import type { SkinItem } from "@yupay/utils";

/** A "show more" page appends (deduped by slug — a price tick can shift a row
 *  across the cursor); a first page replaces. */
export function accumulateSkins(prev: SkinItem[], page: SkinItem[], append: boolean): SkinItem[] {
  if (!append) return page;
  const seen = new Set(prev.map((i) => i.slug));
  return [...prev, ...page.filter((i) => !seen.has(i.slug))];
}
