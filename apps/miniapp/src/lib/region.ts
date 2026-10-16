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
  ru: "topup.region.ru",
  ph: "topup.region.ph",
  my: "topup.region.my",
  sg: "topup.region.sg",
  id: "topup.region.id",
  tr: "topup.region.tr",
  us: "topup.region.us",
  br: "topup.region.br",
};

/** A region's display name; an unknown code falls back to its uppercase self. */
export function regionLabel(code: string, t: (key: MessageKey) => string): string {
  const key = LABEL_KEYS[code];
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
