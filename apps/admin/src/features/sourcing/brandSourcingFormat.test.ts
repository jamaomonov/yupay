import { expect, it } from "vitest";

import {
  bulkConfirmMessage,
  bypassesInventory,
  cheapestSlugs,
  describeRoute,
  inventoryRoutedCount,
  isCurrentSupplierRoute,
  marginPercent,
  partitionForceInventorySelection,
  supplierLabel,
} from "./brandSourcingFormat";

import type { SourcingBrandSupplierOut } from "./types";

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
  const suppliers: SourcingBrandSupplierOut[] = [
    {
      supplier_slug: "g2b",
      has_active_mapping: true,
      latest_cost_usdt: "0.90",
      captured_at: null,
      cost_source: "history",
    },
    {
      supplier_slug: "nova",
      has_active_mapping: true,
      latest_cost_usdt: "0.79",
      captured_at: null,
      cost_source: "history",
    },
    {
      supplier_slug: "gengine",
      has_active_mapping: false,
      latest_cost_usdt: "0.10",
      captured_at: null,
      cost_source: "history",
    },
  ];
  expect(cheapestSlugs(suppliers)).toEqual(new Set(["nova"]));
});

it("treats an exact tie honestly — both suppliers come back, not just the first", () => {
  const suppliers: SourcingBrandSupplierOut[] = [
    {
      supplier_slug: "g2b",
      has_active_mapping: true,
      latest_cost_usdt: "0.90",
      captured_at: null,
      cost_source: "history",
    },
    {
      supplier_slug: "nova",
      has_active_mapping: true,
      latest_cost_usdt: "0.900000",
      captured_at: null,
      cost_source: "history",
    },
  ];
  expect(cheapestSlugs(suppliers)).toEqual(new Set(["g2b", "nova"]));
});

it("returns an empty set when no supplier has both an active mapping and a recorded cost", () => {
  const suppliers: SourcingBrandSupplierOut[] = [
    {
      supplier_slug: "g2b",
      has_active_mapping: false,
      latest_cost_usdt: null,
      captured_at: null,
      cost_source: null,
    },
  ];
  expect(cheapestSlugs(suppliers)).toEqual(new Set());
});

it("treats a `current` cost exactly like a captured one in the cheapest comparison", () => {
  const suppliers: SourcingBrandSupplierOut[] = [
    {
      supplier_slug: "g2b",
      has_active_mapping: true,
      latest_cost_usdt: "1.00",
      captured_at: null,
      cost_source: "current",
    },
    {
      supplier_slug: "nova",
      has_active_mapping: true,
      latest_cost_usdt: "1.50",
      captured_at: "2026-09-10T00:00:00Z",
      cost_source: "history",
    },
  ];
  expect(cheapestSlugs(suppliers)).toEqual(new Set(["g2b"]));
});

it("treats a selected id no longer in the loaded overview as applicable, not silently dropped (Important #4)", () => {
  const items = [
    { sku_id: "sku-1", product_kind: "voucher" },
    { sku_id: "sku-2", product_kind: "top_up" },
  ];
  // sku-3 was ticked before the brand overview refetched without it —
  // deactivated between load and apply. The selection survives a refetch
  // (`BrandSourcingPage` never prunes `selected` against `items`), so it
  // stays ticked even though `items` no longer carries it. It must land in
  // `applicable` so the server answers for it with its own per-item "not
  // found", the same way every other mode already sends and reports it —
  // not vanish from both lists while staying ticked forever.
  const { applicable, blocked } = partitionForceInventorySelection(
    items,
    new Set(["sku-1", "sku-2", "sku-3"]),
  );
  expect(applicable.sort()).toEqual(["sku-1", "sku-3"]);
  expect(blocked).toEqual(["sku-2"]);
});

it("marks a supplier current when it's the primary route", () => {
  expect(isCurrentSupplierRoute({ primary: "supplier:g2b", fallback: null }, "g2b")).toBe(true);
  expect(isCurrentSupplierRoute({ primary: "supplier:g2b", fallback: null }, "nova")).toBe(false);
});

it("marks the warehouse's fallback supplier current too — whole-branch review Important #2", () => {
  // A voucher SKU's automatic route: warehouse first, this supplier as
  // backup. Reading only `primary` used to mark no supplier at all here.
  const item = { primary: "inventory", fallback: "supplier:g2b" };
  expect(isCurrentSupplierRoute(item, "g2b")).toBe(true);
  // A supplier that ISN'T the fallback stays a plain candidate, not current.
  expect(isCurrentSupplierRoute(item, "nova")).toBe(false);
});

it('never marks a supplier current from `primary: "inventory"` alone, without a matching fallback', () => {
  expect(isCurrentSupplierRoute({ primary: "inventory", fallback: null }, "g2b")).toBe(false);
});

it("flags a row as warehouse-bypassing only when its route is inventory today — Important #1", () => {
  expect(bypassesInventory({ primary: "inventory" })).toBe(true);
  expect(bypassesInventory({ primary: "supplier:g2b" })).toBe(false);
  expect(bypassesInventory({ primary: "supplier:manual" })).toBe(false);
});

it("counts only the selected SKUs that route through the warehouse today", () => {
  const items = [
    { sku_id: "a", primary: "inventory" },
    { sku_id: "b", primary: "supplier:g2b" },
    { sku_id: "c", primary: "inventory" },
  ];
  expect(inventoryRoutedCount(items, new Set(["a", "b", "c"]))).toBe(2);
  expect(inventoryRoutedCount(items, new Set(["b"]))).toBe(0);
  expect(inventoryRoutedCount(items, new Set())).toBe(0);
});

it("names the count and target in the bulk-apply confirmation, with no warehouse warning when nothing bypasses it", () => {
  const message = bulkConfirmMessage(3, "force_supplier", "g2b", 0);
  expect(message).toBe("Переключить 3 SKU на поставщика G2Bulk?");
});

it("appends the warehouse-bypass consequence only for force_supplier with an affected row — Important #1", () => {
  const withBypass = bulkConfirmMessage(3, "force_supplier", "nova", 2);
  expect(withBypass).toMatch(/^Переключить 3 SKU на поставщика NOVA\?/);
  expect(withBypass).toMatch(/2 из них/);
  expect(withBypass).toMatch(/склад/);

  // force_inventory can't itself take the warehouse out of routing, so the
  // consequence sentence never applies there even with a nonzero
  // bypassCount in the caller's own bookkeeping (it wouldn't be, but the
  // message must stay mode-gated regardless) — exact-match the message so
  // an accidentally appended sentence can't hide behind a loose `toMatch`.
  expect(bulkConfirmMessage(3, "force_inventory", "g2b", 2)).toBe(
    "Переключить 3 SKU на режим «Только склад»?",
  );
});
