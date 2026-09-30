/**
 * Landing pages for the CS2 market: one per category («Ножи CS2») and one per weapon
 * («Скины AK-47») — clean, indexable URLs for what people search, where the filtered
 * `/skins?…` views are `noindex` duplicates of the hub. Weapons come from the catalogue's
 * facets, so a new weapon gets its page without a deploy.
 */

import { SKIN_CATEGORIES, type Facet, type SkinCategory, type SkinFacets } from "@yupay/utils";

export function isSkinCategory(value: string): value is SkinCategory {
  return (SKIN_CATEGORIES as readonly string[]).includes(value);
}

/** `AK-47` → `ak-47`, `Desert Eagle` → `desert-eagle`, `★ Karambit` → `karambit`. */
export function weaponSlug(weapon: string): string {
  return weapon
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function findWeapon(facets: SkinFacets, slug: string): Facet | null {
  return facets.weapons.find((w) => weaponSlug(w.value) === slug) ?? null;
}

export function categoryPath(category: string): string {
  return `/skins/category/${category}`;
}

export function weaponPath(weapon: string): string {
  return `/skins/weapon/${weaponSlug(weapon)}`;
}

/** Every landing page the facets imply, categories first — for the sitemap. */
export function landingPaths(facets: SkinFacets): string[] {
  return [
    ...facets.categories.map((c) => categoryPath(c.value)),
    ...facets.weapons.map((w) => weaponPath(w.value)).filter((p, i, all) => all.indexOf(p) === i),
  ];
}

/** Which noun a landing's count takes (`web.skins.landing.count`): a case is not a skin. */
const COUNT_UNITS: Record<string, string> = {
  cases: "cases",
  keys: "keys",
  agents: "agents",
  charms: "charms",
  "music-kits": "music",
};

export function countUnit(category: string | undefined): string {
  return (category !== undefined ? COUNT_UNITS[category] : undefined) ?? "other";
}
