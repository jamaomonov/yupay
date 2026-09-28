import { describe, expect, it } from "vitest";

import {
  activeFilterCount,
  CATEGORY_ICONS,
  hasWear,
  isVanilla,
  offerHeadline,
  repriceOffer,
  wearChoices,
} from "./skin-view";
import { DEFAULT_SORT, SKIN_CATEGORIES } from "./skins";

import type { SkinFamilyMember, SkinListing } from "./skins";

const m = (
  slug: string,
  exterior: SkinFamilyMember["exterior"],
  over: Partial<SkinFamilyMember> = {},
): SkinFamilyMember => ({
  slug,
  exterior,
  stattrak: false,
  souvenir: false,
  price_usd: "10.00",
  price_uzs: "127000",
  count: 3,
  ...over,
});

const offer = (id: number, usd: string, uzs: string | null): SkinListing => ({
  listing_id: id,
  price_usd: usd,
  price_uzs: uzs,
  float_value: null,
  paint_seed: null,
  stickers: [],
  inspect_url: null,
});

describe("DEFAULT_SORT", () => {
  it("opens on the dearest items, as skinsavdo.uz does", () => {
    expect(DEFAULT_SORT).toBe("-price");
  });
});

describe("offerHeadline", () => {
  it("is the cheapest live offer once offers are known", () => {
    const h = offerHeadline("357300", "28.13", [
      offer(1, "28.40", "360700"),
      offer(2, "28.30", "359400"),
    ]);
    expect(h).toEqual({ uzs: "359400", usd: "28.30", from: false });
  });

  it("falls back to the stored price, marked «от», before or without offers", () => {
    expect(offerHeadline("357300", "28.13", null)).toEqual({
      uzs: "357300",
      usd: "28.13",
      from: true,
    });
    expect(offerHeadline("357300", "28.13", [])).toEqual({
      uzs: "357300",
      usd: "28.13",
      from: true,
    });
  });
});

describe("wearChoices", () => {
  const family = [
    m("ft", "FT"),
    m("mw", "MW"),
    m("bs", "BS", { price_usd: null, price_uzs: null, count: 0 }),
    m("st-ft", "FT", { stattrak: true }),
  ];

  it("lists the wears of the current variant in game order, sold-out ones marked", () => {
    const c = wearChoices(family, family[0]!);
    expect(c.wears.map((w) => [w.exterior, w.slug, w.available])).toEqual([
      ["MW", "mw", true],
      ["FT", "ft", true],
      ["BS", "bs", false],
    ]);
  });

  it("offers the StatTrak twin of the same wear, and back", () => {
    expect(wearChoices(family, family[0]!).stattrak).toEqual({ on: false, slug: "st-ft" });
    expect(wearChoices(family, family[3]!).stattrak).toEqual({ on: true, slug: "ft" });
  });

  it("falls back to the nearest wear that has the variant", () => {
    // StatTrak exists only in FT; from plain MW the toggle leads there, not nowhere.
    expect(wearChoices(family, family[1]!).stattrak).toEqual({ on: false, slug: "st-ft" });
  });

  it("switches a vanilla knife (no wear) to its StatTrak twin", () => {
    const knife = [m("karambit", null), m("st-karambit", null, { stattrak: true })];
    expect(wearChoices(knife, knife[0]!).stattrak).toEqual({ on: false, slug: "st-karambit" });
    expect(wearChoices(knife, knife[0]!).wears).toEqual([]);
  });

  it("hides a toggle with no twin in any wear", () => {
    expect(wearChoices(family, family[0]!).souvenir).toEqual({ on: false, slug: null });
  });

  it("jumps to another wear keeping the variant", () => {
    const c = wearChoices(family, family[3]!);
    expect(c.wears.map((w) => w.slug)).toEqual([null, "st-ft", null]);
  });
});

describe("CATEGORY_ICONS", () => {
  it("covers every category; music kits use a glyph", () => {
    for (const c of SKIN_CATEGORIES) expect(c in CATEGORY_ICONS).toBe(true);
    expect(CATEGORY_ICONS["music-kits"]).toBeNull();
    expect(CATEGORY_ICONS.rifles?.file).toBe("rifles.png");
  });
});

describe("isVanilla", () => {
  it("is a knife or glove with no paint", () => {
    expect(isVanilla({ category: "knives", weapon: "Karambit", skin: null })).toBe(true);
    expect(isVanilla({ category: "knives", weapon: "Karambit", skin: "Fade" })).toBe(false);
    expect(isVanilla({ category: "cases", weapon: null, skin: null })).toBe(false);
  });
});

describe("activeFilterCount", () => {
  it("counts what the filter sheet sets, not category, search or sort", () => {
    expect(activeFilterCount({ sort: "popular" })).toBe(0);
    expect(
      activeFilterCount({
        sort: "price",
        category: "rifles",
        exterior: "FT",
        stattrak: true,
        minUzs: 1,
      }),
    ).toBe(3);
    expect(activeFilterCount({ sort: "popular", minUzs: 1, maxUzs: 9, rarity: "Covert" })).toBe(2);
  });
});

describe("hasWear", () => {
  it("is true for guns, knives and gloves, false for cases, keys, agents, kits, charms", () => {
    for (const c of ["rifles", "pistols", "smgs", "heavy", "knives", "gloves"])
      expect(hasWear(c)).toBe(true);
    for (const c of ["cases", "keys", "agents", "music-kits", "charms"])
      expect(hasWear(c)).toBe(false);
  });
});

describe("repriceOffer", () => {
  const offer = { listing_id: 1, price_usd: "30.00", price_uzs: "381000" };

  it("takes the server's dollar price and scales soʻm to it, in whole hundreds", () => {
    expect(repriceOffer(offer, "31.50")).toEqual({
      listing_id: 1,
      price_usd: "31.50",
      price_uzs: "400100",
    });
  });

  it("keeps soʻm unknown when it was unknown", () => {
    expect(repriceOffer({ ...offer, price_uzs: null }, "31.50").price_uzs).toBeNull();
  });
});
