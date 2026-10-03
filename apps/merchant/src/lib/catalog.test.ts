import { describe, expect, it } from "vitest";

import { soleSku } from "./catalog";

import type { Brand, Sku } from "./types";

const sku = (id: string): Sku => ({
  sku_id: id,
  sku_code: id,
  name: id,
  kind: "amount",
  price_usd: null,
  retail_price_usd: null,
  unit_price_usd: "1.02",
  unit: null,
  min_qty: null,
  max_qty: null,
  min_amount_usd: "1",
  max_amount_usd: "500",
  image_url: null,
  updated_at: "2026-09-29T00:00:00Z",
});

const brand = (...skus: Sku[][]): Brand => ({
  brand_id: "b",
  slug: "steam",
  name: "Steam",
  category_slug: null,
  category_name: null,
  logo_url: null,
  hero_image_url: null,
  products: skus.map((s, i) => ({
    product_id: `p${String(i)}`,
    slug: `p${String(i)}`,
    name: "p",
    required_fields: [],
    skus: s,
  })),
});

describe("soleSku", () => {
  it("is the only thing a brand sells — Steam's any amount, Stars", () => {
    expect(soleSku(brand([sku("any")]))?.sku_id).toBe("any");
  });

  it("is nothing when there is a choice to make", () => {
    expect(soleSku(brand([sku("a"), sku("b")]))).toBeNull();
    expect(soleSku(brand([sku("a")], [sku("b")]))).toBeNull();
    expect(soleSku(brand([]))).toBeNull();
  });
});
