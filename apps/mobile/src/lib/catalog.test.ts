import type { BrandOut } from "@yupay/api-client/types";
import { describe, expect, it } from "vitest";

import { matches, sellable } from "./catalog";

function brand(slug: string, name: string, category_slug = "top-ups"): BrandOut {
  return {
    id: slug,
    slug,
    name,
    category_slug,
    accent_color: null,
    hero_image_url: null,
    logo_url: null,
    maintenance: false,
    short_description: null,
  };
}

describe("sellable", () => {
  it("keeps top-ups and drops gift cards and brands with their own flow", () => {
    const list = [
      brand("pubg-mobile", "PUBG Mobile"),
      brand("roblox", "Roblox", "gift-cards"),
      brand("cs2-skins", "CS2"),
      brand("steam-gifts", "Steam Игры"),
      brand("steam", "Steam"),
    ];
    expect(sellable(list).map((b) => b.slug)).toEqual(["pubg-mobile"]);
  });
});

describe("matches", () => {
  it("finds a brand by name or slug, ignoring case", () => {
    expect(matches(brand("mobile-legends", "Mobile Legends"), "legends")).toBe(true);
    expect(matches(brand("pubg-mobile", "PUBG Mobile"), "pubg")).toBe(true);
    expect(matches(brand("pubg-mobile", "PUBG Mobile"), "  ")).toBe(true);
    expect(matches(brand("pubg-mobile", "PUBG Mobile"), "free")).toBe(false);
  });
});
