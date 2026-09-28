/** Pure view helpers shared by the web and mini app skins pages. */

import type { Exterior, SkinCategory, SkinFamilyMember, SkinListing, SkinQuery } from "./skins";

const WEAR_ORDER: readonly Exterior[] = ["FN", "MW", "FT", "WW", "BS"];

/**
 * The item page's headline price. Once live offers are known it is the cheapest
 * of them — the price someone can actually pay. Before that, or with none, it is
 * the stored price from the last snapshot, shown as «от …» (`from: true`).
 */
export function offerHeadline(
  storedUzs: string | null,
  storedUsd: string | null,
  offers: readonly SkinListing[] | null,
): { uzs: string | null; usd: string | null; from: boolean } {
  if (offers && offers.length > 0) {
    const cheapest = offers.reduce((a, b) => (Number(b.price_usd) < Number(a.price_usd) ? b : a));
    return { uzs: cheapest.price_uzs, usd: cheapest.price_usd, from: false };
  }
  return { uzs: storedUzs, usd: storedUsd, from: true };
}

export interface WearChoice {
  exterior: Exterior;
  /** The twin of this wear in the current variant; `null` when it does not exist. */
  slug: string | null;
  /** It exists, has a price and has offers. */
  available: boolean;
  /** The twin's price, for the picker; `null` when it has none. */
  price_usd: string | null;
  price_uzs: string | null;
}

export interface VariantToggle {
  on: boolean;
  /** Where the toggle leads; `null` hides it (no twin to switch to). */
  slug: string | null;
}

/**
 * The item page's wear picker: every wear the skin comes in, pointing at the
 * twin in the current StatTrak/Souvenir variant, plus the two variant toggles.
 */
export function wearChoices(
  family: readonly SkinFamilyMember[],
  current: Pick<SkinFamilyMember, "exterior" | "stattrak" | "souvenir">,
): { wears: WearChoice[]; stattrak: VariantToggle; souvenir: VariantToggle } {
  const find = (exterior: Exterior | null, stattrak: boolean, souvenir: boolean) =>
    family.find(
      (m) => m.exterior === exterior && m.stattrak === stattrak && m.souvenir === souvenir,
    );
  const present = new Set(family.map((m) => m.exterior));
  const wears = WEAR_ORDER.filter((e) => present.has(e)).map((exterior) => {
    const twin = find(exterior, current.stattrak, current.souvenir);
    return {
      exterior,
      slug: twin?.slug ?? null,
      available: twin !== undefined && twin.price_usd !== null && twin.count > 0,
      price_usd: twin?.price_usd ?? null,
      price_uzs: twin?.price_uzs ?? null,
    };
  });
  // The twin in the same wear, else the nearest wear that has that variant —
  // a StatTrak that exists only in FT should still be one tap away from MW.
  const nearest = (stattrak: boolean, souvenir: boolean) => {
    const same = find(current.exterior, stattrak, souvenir);
    if (same) return same;
    const at = current.exterior === null ? 0 : WEAR_ORDER.indexOf(current.exterior);
    return family
      .filter((m) => m.stattrak === stattrak && m.souvenir === souvenir)
      .sort(
        (a, b) =>
          Math.abs((a.exterior ? WEAR_ORDER.indexOf(a.exterior) : 0) - at) -
          Math.abs((b.exterior ? WEAR_ORDER.indexOf(b.exterior) : 0) - at),
      )[0];
  };
  const toggle = (on: boolean, twin: SkinFamilyMember | undefined): VariantToggle => ({
    on,
    slug: twin?.slug ?? null,
  });
  return {
    wears,
    stattrak: toggle(
      current.stattrak,
      current.stattrak
        ? nearest(false, false)
        : current.souvenir
          ? undefined
          : nearest(true, false),
    ),
    souvenir: toggle(
      current.souvenir,
      current.souvenir
        ? nearest(false, false)
        : current.stattrak
          ? undefined
          : nearest(false, true),
    ),
  };
}

/**
 * Category tile icons: a Steam item image self-hosted as `/skins/categories/<file>`
 * in each app (Steam's CDN sends no CORS header, and a cross-origin CSS mask does
 * not render), drawn as a silhouette. `wide` items (long guns, knives) are sized by
 * width. `null` means a lucide glyph instead — a music kit's image is a square card.
 */
export const CATEGORY_ICONS: Record<SkinCategory, { file: string; wide: boolean } | null> = {
  rifles: { file: "rifles.png", wide: true },
  pistols: { file: "pistols.png", wide: false },
  smgs: { file: "smgs.png", wide: true },
  heavy: { file: "heavy.png", wide: true },
  knives: { file: "knives.png", wide: true },
  gloves: { file: "gloves.png", wide: false },
  agents: { file: "agents.png", wide: false },
  cases: { file: "cases.png", wide: false },
  keys: { file: "keys.png", wide: false },
  "music-kits": null,
  charms: { file: "charms.png", wide: false },
};

/** A knife or glove with no paint — its name is just the weapon, so a title needs a word for it. */
export function isVanilla(item: {
  category: string;
  weapon: string | null;
  skin: string | null;
}): boolean {
  return (
    item.skin === null &&
    item.weapon !== null &&
    (item.category === "knives" || item.category === "gloves")
  );
}

/** Filters set in the filter panel — the badge on its button. A price range is one. */
export function activeFilterCount(q: SkinQuery): number {
  return [
    q.exterior !== undefined,
    q.rarity !== undefined,
    q.stattrak === true,
    q.minUzs !== undefined || q.maxUzs !== undefined,
  ].filter(Boolean).length;
}

const WEAR_CATEGORIES = new Set(["rifles", "pistols", "smgs", "heavy", "knives", "gloves"]);

/**
 * Whether one copy differs from another (float, pattern, stickers). A case, key,
 * agent, music kit or charm is identical to every other copy, so its page shows
 * one price and a quantity instead of a list of identical offers.
 */
export function hasWear(category: string): boolean {
  return WEAR_CATEGORIES.has(category);
}

/**
 * An offer at the dollar price the server quoted when it refused the old one
 * (the order's `expected_amount_usd`), soʻm scaled to match in whole hundreds —
 * so the next press charges what the button says instead of failing again.
 * The server re-prices the order itself; this only keeps the page honest.
 */
export function repriceOffer<T extends { price_usd: string; price_uzs: string | null }>(
  offer: T,
  expectedUsd: string,
): T {
  const uzs =
    offer.price_uzs === null
      ? null
      : String(
          Math.round(
            (Number(offer.price_uzs) * Number(expectedUsd)) / Number(offer.price_usd) / 100,
          ) * 100,
        );
  return { ...offer, price_usd: expectedUsd, price_uzs: uzs };
}

/** One colour per wear, green (Factory New) to red (Battle-Scarred) — the market's own cue. */
const WEAR_COLORS: Record<string, string> = {
  FN: "#4ade80",
  MW: "#a3e635",
  FT: "#facc15",
  WW: "#fb923c",
  BS: "#f87171",
};

/** The colour an offer row paints its wear code in; `null` for items without wear. */
export function wearColor(exterior: string | null): string | null {
  return exterior ? (WEAR_COLORS[exterior] ?? null) : null;
}

/**
 * How much cheaper than Steam's market an offer is, in whole percent — `null` when it is
 * not at least 1 % cheaper or Steam's price is unknown (never a "−0 %" or a mark-up).
 */
export function steamDiscount(priceUsd: string, steamUsd: string | null): number | null {
  if (steamUsd === null) return null;
  const steam = Number(steamUsd);
  const price = Number(priceUsd);
  if (!(steam > 0)) return null;
  const off = Math.floor(((steam - price) / steam) * 100);
  return off >= 1 ? off : null;
}
