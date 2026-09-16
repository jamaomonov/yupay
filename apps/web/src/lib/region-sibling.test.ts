import { describe, expect, it } from "vitest";

import { regionSibling } from "./region-sibling";

import type { BrandSummary } from "./catalog";

function brand(slug: string): BrandSummary {
  return {
    id: slug,
    slug,
    category_slug: "games",
    name: slug,
    short_description: null,
    logo_url: null,
    hero_image_url: null,
    accent_color: null,
    maintenance: false,
  };
}

describe("regionSibling", () => {
  const brands = [brand("mobile-legends"), brand("mobile-legends-ru"), brand("pubg-mobile")];

  it("pairs a global brand with its -ru twin", () => {
    expect(regionSibling("mobile-legends", brands)?.slug).toBe("mobile-legends-ru");
  });
  it("pairs a -ru brand with its global twin", () => {
    expect(regionSibling("mobile-legends-ru", brands)?.slug).toBe("mobile-legends");
  });
  it("is null for a brand with no twin", () => {
    expect(regionSibling("pubg-mobile", brands)).toBeNull();
  });
});
