import { describe, expect, it } from "vitest";

import { sectionsOf } from "./CabinetContext";

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

  it("is empty before the summary has loaded", () => {
    expect(sectionsOf(null)).toEqual([]);
  });
});
