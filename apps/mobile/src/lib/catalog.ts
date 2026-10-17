import type { BrandOut } from "@yupay/api-client/types";

/**
 * Brands with a flow of their own, not built in the app yet: game gifts, skins, and the Steam
 * wallet (an amount the buyer types, not a denomination).
 */
const OWN_FLOW = new Set(["steam-gifts", "cs2-skins", "steam"]);

/**
 * Brands the app sells. Gift cards stay out of the first version (ADR-0100): they carry the
 * clearest store-billing risk.
 */
export function sellable(brands: readonly BrandOut[]): BrandOut[] {
  return brands.filter(
    (brand) => brand.category_slug !== "gift-cards" && !OWN_FLOW.has(brand.slug),
  );
}

/** Case-insensitive match on the brand name or slug. */
export function matches(brand: BrandOut, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === "") return true;
  return brand.name.toLowerCase().includes(q) || brand.slug.includes(q);
}
