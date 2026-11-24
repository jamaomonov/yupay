import type { BrandSummary } from "@/lib/catalog";

/** What most buyers come for, first; everything else keeps the API's order. */
const POPULAR = ["mobile-legends", "pubg-mobile", "free-fire", "steam", "roblox"];

/** The catalogue in shelf order — the /store page and the home teaser agree. */
export function byPopularity(brands: BrandSummary[]): BrandSummary[] {
  const rank = (slug: string): number => {
    const i = POPULAR.indexOf(slug);
    return i === -1 ? POPULAR.length : i;
  };
  return [...brands].sort((a, b) => rank(a.slug) - rank(b.slug));
}
