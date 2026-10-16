/**
 * One game, several brands: the region split (ADR-0099).
 *
 * A game is sold per region as separate brands — products, packages and the
 * player check are per brand — linked to the game's main brand. The API says
 * which: `GET /catalog/brands/{slug}` carries the brand's own `region_code`,
 * `region_of` (the main slug, on a region) and `regions` (every sellable
 * region of the game). The Mini App shows one card per game and lets the
 * customer pick the region on the top-up page. Nothing here infers a region
 * from a slug. Kept a leaf module (type imports only), so pages and tests can
 * pull it in freely.
 */

import type { MessageKey } from "./i18n/messages";

/** The region code of a game's main brand. */
export const GLOBAL_REGION = "global";

/** One sellable region of a game, as `BrandSummary.regions` lists it. */
export interface BrandRegion {
  code: string;
  slug: string;
}

/** The region fields of a brand summary — all optional (older API). */
export interface RegionFields {
  region_code?: string | null;
  region_of?: string | null;
  regions?: readonly BrandRegion[] | null;
}

const LABEL_KEYS: Record<string, MessageKey> = {
  global: "topup.region.global",
  cis: "topup.region.cis",
  ru: "topup.region.ru",
  ph: "topup.region.ph",
  my: "topup.region.my",
  sg: "topup.region.sg",
  mysg: "topup.region.mysg",
  id: "topup.region.id",
  th: "topup.region.th",
  vn: "topup.region.vn",
  tw: "topup.region.tw",
  tr: "topup.region.tr",
  eu: "topup.region.eu",
  mena: "topup.region.mena",
  bd: "topup.region.bd",
  us: "topup.region.us",
  latam: "topup.region.latam",
  br: "topup.region.br",
};

/** The game's main region reads where our customers are ("Глобальный (Узбекистан)"). */
const HOME_KEYS: Record<string, MessageKey> = {
  global: "topup.regionHome.global",
  cis: "topup.regionHome.cis",
};

/**
 * A region's display name; an unknown code falls back to its uppercase self.
 * `home` marks the game's main region — the one customers in Uzbekistan are
 * on — which says so where a home label exists.
 */
export function regionLabel(code: string, t: (key: MessageKey) => string, home = false): string {
  const key = (home ? HOME_KEYS[code] : undefined) ?? LABEL_KEYS[code];
  return key ? t(key) : code.toUpperCase();
}

/**
 * Where a route slug sits in its game. The param may name a regional brand
 * (an old "recent" entry, a history "repeat", a shared link): `base` is the
 * game's main slug — the card — and `region` the region the link meant.
 */
export function resolveRegion(
  routeSlug: string,
  summary: RegionFields | undefined,
): { base: string; region: string } {
  return {
    base: summary?.region_of ?? routeSlug,
    region: summary?.region_code ?? GLOBAL_REGION,
  };
}

/** The game's regions for the switcher; empty when there is nothing to pick. */
export function switcherRegions(summary: RegionFields | undefined): readonly BrandRegion[] {
  const regions = summary?.regions ?? [];
  return regions.length > 1 ? regions : [];
}

/** The brand slug the page must talk to for `region` — `base` when unknown. */
export function regionBrandSlug(
  regions: readonly BrandRegion[],
  region: string,
  base: string,
): string {
  return regions.find((r) => r.code === region)?.slug ?? base;
}

/**
 * Whether the account a product credits goes unchecked: it asks for fields
 * and none carries a player check (`check`, the same flag DynamicFields
 * renders the check button from). Some regions have no supplier to validate
 * an id for us (ADR-0099), so the customer is asked to mind the region.
 */
export function isUncheckedAccount(fields: readonly { check?: unknown }[]): boolean {
  return fields.length > 0 && !fields.some((f) => Boolean(f.check));
}
