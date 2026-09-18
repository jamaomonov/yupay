import { expect, it } from "vitest";

import { cheapestSlug, describeRoute, marginPercent, supplierLabel } from "./brandSourcingFormat";

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

it("computes the margin price_usd implies over cost_usdt", () => {
  expect(marginPercent("1.20", "0.90")).toBe("25.0");
  expect(marginPercent("1.00", null)).toBeNull();
  expect(marginPercent("0", "0.90")).toBeNull();
});

it("picks the cheapest actively-mapped supplier with a recorded cost", () => {
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
  expect(cheapestSlug(suppliers)).toBe("nova");
});

it("returns null when no supplier has both an active mapping and a recorded cost", () => {
  const suppliers = [
    { supplier_slug: "g2b", has_active_mapping: false, latest_cost_usdt: null, captured_at: null },
  ];
  expect(cheapestSlug(suppliers)).toBeNull();
});
