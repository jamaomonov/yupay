import { describe, expect, it } from "vitest";

import { CATEGORY_ICONS, offerHeadline, wearChoices } from "./skin-view";
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

  it("hides a toggle with no twin", () => {
    expect(wearChoices(family, family[1]!).stattrak).toEqual({ on: false, slug: null });
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
