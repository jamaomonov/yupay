import type { BrandOut, OrderItemOut } from "@yupay/api-client/types";
import { describe, expect, it } from "vitest";

import { itemLabel, matches, orderImage, sellable } from "./catalog";

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
  it("keeps top-ups and the Steam wallet, drops gift cards and brands with their own flow", () => {
    const list = [
      brand("pubg-mobile", "PUBG Mobile"),
      brand("roblox", "Roblox", "gift-cards"),
      brand("cs2-skins", "CS2"),
      brand("steam-gifts", "Steam Игры"),
      brand("steam", "Steam"),
    ];
    expect(sellable(list).map((b) => b.slug)).toEqual(["pubg-mobile", "steam"]);
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

describe("orderImage", () => {
  const brands = [{ ...brand("pubg", "PUBG"), logo_url: "https://cdn/pubg.png" }];

  it("prefers the line's own picture, then the brand logo", () => {
    expect(orderImage({ image_url: "https://cdn/sku.png", brand_slug: "pubg" }, brands)).toBe(
      "https://cdn/sku.png",
    );
    expect(orderImage({ image_url: null, brand_slug: "pubg" }, brands)).toBe(
      "https://cdn/pubg.png",
    );
    expect(orderImage({ image_url: null, brand_slug: "gone" }, brands)).toBeNull();
    expect(orderImage(undefined, brands)).toBeNull();
  });
});

function line(
  qty: number,
  unit: string,
  variable: boolean,
  denomination: string | null,
): OrderItemOut {
  return {
    id: "i",
    sku_id: "s",
    qty,
    unit_price_usd: unit,
    fulfillment_state: "delivered",
    fulfillment_data: {},
    display: {
      brand_slug: "steam",
      brand_name: "Steam",
      product_slug: "p",
      product_name: "Steam Wallet",
      product_kind: "top_up",
      sku_code: "x",
      denomination,
      region: null,
      image_url: null,
      variable_amount: variable,
    },
  };
}

describe("itemLabel", () => {
  it("shows the dollars for Steam, the count for Stars, else the denomination", () => {
    expect(itemLabel(line(1, "25.000000", true, "Любая сумма"))).toBe("$25");
    expect(itemLabel(line(1, "11.300000", true, "Любая сумма"))).toBe("$11.30");
    expect(itemLabel(line(1500, "0.017200", false, "Любое количество"))).toBe("1 500");
    expect(itemLabel(line(1, "5.000000", false, "325 UC"))).toBe("325 UC");
    expect(itemLabel(undefined)).toBe("");
  });
});
