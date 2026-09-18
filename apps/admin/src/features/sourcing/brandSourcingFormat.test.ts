import { expect, it } from "vitest";

import { cheapestSlugs, describeRoute, marginPercent, supplierLabel } from "./brandSourcingFormat";

it("labels known suppliers and falls back to the raw slug otherwise", () => {
  expect(supplierLabel("g2b")).toBe("G2Bulk");
  expect(supplierLabel("nova")).toBe("NOVA");
  expect(supplierLabel("some-future-supplier")).toBe("some-future-supplier");
});

it("describes every shape of Decision.primary the brand overview can report", () => {
  expect(describeRoute("inventory")).toBe("Склад кодов");
  expect(describeRoute("supplier:manual")).toBe("Ручная выдача");
  expect(describeRoute("supplier:g2b")).toBe("Поставщик G2Bulk");
  expect(describeRoute("invalid")).toBe("Некорректное правило");
});

it("computes the margin price_usd implies over cost_usdt — cost is the denominator", () => {
  // Same numbers the review flagged: SkuEditPage's marginFromCostAndPrice
  // says 33.33% for price 1.20 / cost 0.90 — this screen must agree, not
  // divide by price and say 25.0%.
  expect(marginPercent("1.20", "0.90")).toBe("33.3");
  expect(marginPercent("1.00", null)).toBeNull();
  // cost <= 0 can't anchor a percentage — this is the real guard now that
  // cost, not price, is the denominator.
  expect(marginPercent("1.00", "0")).toBeNull();
});

it("picks every supplier tied for cheapest, among active mappings with a recorded cost", () => {
  const suppliers = [
    { supplier_slug: "g2b", has_active_mapping: true, latest_cost_usdt: "0.90", captured_at: null },
    {
      supplier_slug: "nova",
      has_active_mapping: true,
      latest_cost_usdt: "0.79",
      captured_at: null,
    },
    {
      supplier_slug: "gengine",
      has_active_mapping: false,
      latest_cost_usdt: "0.10",
      captured_at: null,
    },
  ];
  expect(cheapestSlugs(suppliers)).toEqual(new Set(["nova"]));
});

it("treats an exact tie honestly — both suppliers come back, not just the first", () => {
  const suppliers = [
    { supplier_slug: "g2b", has_active_mapping: true, latest_cost_usdt: "0.90", captured_at: null },
    {
      supplier_slug: "nova",
      has_active_mapping: true,
      latest_cost_usdt: "0.900000",
      captured_at: null,
    },
  ];
  expect(cheapestSlugs(suppliers)).toEqual(new Set(["g2b", "nova"]));
});

it("returns an empty set when no supplier has both an active mapping and a recorded cost", () => {
  const suppliers = [
    { supplier_slug: "g2b", has_active_mapping: false, latest_cost_usdt: null, captured_at: null },
  ];
  expect(cheapestSlugs(suppliers)).toEqual(new Set());
});
