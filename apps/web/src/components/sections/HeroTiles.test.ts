import { expect, it, vi } from "vitest";

import type { BrandSummary } from "@/lib/catalog";

vi.mock("./CS2SkinsBand", () => ({ showcase: vi.fn() }));

const { categoryHref, logos } = await import("./HeroTiles");

function brand(slug: string, category_slug: string, logo_url: string | null): BrandSummary {
  return {
    id: slug,
    slug,
    category_slug,
    name: slug,
    short_description: null,
    logo_url,
    hero_image_url: null,
    accent_color: null,
    maintenance: false,
  };
}

// Production files games under `top-ups`, not `games` — a hard-coded slug led nowhere.
const BRANDS = [
  brand("pubg-mobile", "top-ups", "https://cdn.yupay.uz/pubg.png"),
  brand("roblox", "gift-cards", "https://cdn.yupay.uz/roblox.webp"),
  brand("discord", "gift-cards", null),
];

it("links a tile to the category its brands actually live in", () => {
  expect(categoryHref("ru", BRANDS, "pubg-mobile", "games")).toBe("/store?cat=top-ups");
  expect(categoryHref("en", BRANDS, "roblox", "gift-cards")).toBe("/en/store?cat=gift-cards");
  expect(categoryHref("ru", [], "pubg-mobile", "games")).toBe("/store?cat=games");
});

it("fronts a tile only with the logos that exist, in the order asked", () => {
  expect(logos(BRANDS, ["roblox", "discord", "pubg-mobile", "minecraft"])).toEqual([
    "https://cdn.yupay.uz/roblox.webp",
    "https://cdn.yupay.uz/pubg.png",
  ]);
});
