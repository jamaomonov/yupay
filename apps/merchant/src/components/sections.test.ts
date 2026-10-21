import { describe, expect, it } from "vitest";

import { sectionSlugOf, sectionsOf } from "./CabinetContext";

import type { BrandSummary } from "@/lib/types";

const card = (slug: string, section: [string, string] | null): BrandSummary => ({
  brand_id: slug,
  slug,
  name: slug,
  category_slug: section?.[0] ?? null,
  category_name: section?.[1] ?? null,
  logo_url: null,
  from_usd: "1.00",
  from_product: "p",
  sku_count: 1,
  product_names: ["p"],
});

describe("sectionsOf", () => {
  it("counts brands per section from the grid's cards, in catalogue order", () => {
    const sections = sectionsOf({
      brands: [
        card("a", ["top-ups", "Игры"]),
        card("b", ["gift-cards", "Карты"]),
        card("c", ["top-ups", "Игры"]),
        card("d", null),
      ],
    });
    expect(sections).toEqual([
      { slug: "top-ups", name: "Игры", count: 2 },
      { slug: "gift-cards", name: "Карты", count: 1 },
    ]);
  });

  it("lifts Steam and Telegram into sections of their own, first", () => {
    const sections = sectionsOf(
      {
        brands: [
          card("pubg", ["top-ups", "Пополнения"]),
          card("steam", ["top-ups", "Пополнения"]),
          card("telegram-stars", ["top-ups", "Пополнения"]),
          card("telegram-premium", ["top-ups", "Пополнения"]),
          card("steam-wallet", ["gift-cards", "Карты"]),
        ],
      },
      (slug) => (slug === "steam" ? "Пополнение Steam" : "Пополнение Telegram"),
    );
    expect(sections).toEqual([
      { slug: "steam", name: "Пополнение Steam", count: 1 },
      { slug: "telegram", name: "Пополнение Telegram", count: 2 },
      { slug: "top-ups", name: "Пополнения", count: 1 },
      { slug: "gift-cards", name: "Карты", count: 1 },
    ]);
    expect(sectionSlugOf({ slug: "telegram-premium", category_slug: "top-ups" })).toBe("telegram");
    expect(sectionSlugOf({ slug: "steam-wallet", category_slug: "gift-cards" })).toBe("gift-cards");
  });

  it("leaves out a pinned section with no brand in the catalog", () => {
    expect(sectionsOf({ brands: [card("pubg", ["top-ups", "Пополнения"])] })).toEqual([
      { slug: "top-ups", name: "Пополнения", count: 1 },
    ]);
  });

  it("is empty before the summary has loaded", () => {
    expect(sectionsOf(null)).toEqual([]);
  });
});
