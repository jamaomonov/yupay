/**
 * Where a catalogue brand lives. Every brand has `/store/<slug>` except the CS2
 * skins one, which is the `/skins` market — its brand row exists only because an
 * order needs an active brand → product → SKU chain (plan 3a). The store page for
 * that slug redirects too, for links built elsewhere.
 */
export const CS2_SKINS_BRAND = "cs2-skins";

export function brandPath(slug: string): string {
  return slug === CS2_SKINS_BRAND ? "/skins" : `/store/${slug}`;
}
