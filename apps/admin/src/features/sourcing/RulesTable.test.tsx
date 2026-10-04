import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { RulesTable } from "./RulesTable";

import type { SourcingRuleOut } from "./types";

// The table renders brand / product / denomination straight off the rule
// row — `GET /sourcing/rules` resolves them server-side — so there is no
// API to mock here and no QueryClient to provide: the component is pure
// props in, DOM out. The three bare-list mocks (`/catalog/skus`,
// `/products`, `/brands`) this file used to carry are gone with the fetches.

const RULE_BASE = {
  updated_by: "admin-1",
  cost_sync: null,
  brand_slug: null,
} satisfies Partial<SourcingRuleOut>;

const RULES: SourcingRuleOut[] = [
  {
    ...RULE_BASE,
    sku_id: "sku-1",
    sku_code: "MLBB-100",
    mode: "force_supplier",
    supplier_slug: "g2b",
    updated_at: "2026-09-10T00:00:00Z",
    denomination: "100",
    product_slug: "mobile-legends",
    brand_id: "brand-1",
    brand_name: "Mobile Legends",
  },
  {
    ...RULE_BASE,
    sku_id: "sku-2",
    sku_code: "PUBG-60",
    mode: "manual",
    supplier_slug: null,
    updated_at: "2026-09-11T00:00:00Z",
    denomination: "60",
    product_slug: "pubg-mobile",
    brand_id: "brand-2",
    brand_name: "PUBG Mobile",
  },
];

// Three rules across the same two brands as `RULES` — sku-3 adds a second
// Mobile Legends rule, so Mobile Legends holds 2 and PUBG Mobile holds 1.
// Only used by the grouping tests below; every other test keeps using the
// two-rule `RULES` fixture unchanged.
const RULES_GROUPED: SourcingRuleOut[] = [
  ...RULES,
  {
    ...RULE_BASE,
    sku_id: "sku-3",
    sku_code: "MLBB-500",
    mode: "force_inventory",
    supplier_slug: null,
    updated_at: "2026-09-12T00:00:00Z",
    denomination: "500",
    product_slug: "mobile-legends",
    brand_id: "brand-1",
    brand_name: "Mobile Legends",
  },
];

// Two distinct brands that happen to share the exact same Russian display
// name — the region rollout's real-world near miss ("Mobile Legends" vs.
// "Mobile Legends RU"), pushed one step further so the names collide
// exactly. Grouping on `brand_name` would collapse these into one section
// with one count and one React key; grouping on `brand_id` must not.
const RULES_NAME_COLLISION: SourcingRuleOut[] = [
  {
    ...RULE_BASE,
    sku_id: "sku-a",
    sku_code: "MLBB-A",
    mode: "force_supplier",
    supplier_slug: "g2b",
    updated_at: "2026-09-10T00:00:00Z",
    denomination: null,
    product_slug: "mobile-legends",
    brand_id: "brand-a",
    brand_name: "Mobile Legends",
  },
  {
    ...RULE_BASE,
    sku_id: "sku-b",
    sku_code: "MLBB-B",
    mode: "manual",
    supplier_slug: null,
    updated_at: "2026-09-11T00:00:00Z",
    denomination: null,
    product_slug: "mobile-legends-ru",
    brand_id: "brand-b",
    brand_name: "Mobile Legends",
  },
];

function renderTable(rules: SourcingRuleOut[] = RULES, onDelete = vi.fn()) {
  return {
    onDelete,
    ...render(<RulesTable rules={rules} loading={false} onDelete={onDelete} />),
  };
}

it("shows brand, product and denomination beside the SKU code", () => {
  renderTable();

  expect(screen.getByText("Mobile Legends")).toBeInTheDocument();
  expect(screen.getByText("mobile-legends")).toBeInTheDocument();
  expect(screen.getByText("PUBG Mobile")).toBeInTheDocument();
  expect(screen.getByText("100")).toBeInTheDocument();
});

it("filters by free text across brand, product, code and denomination", async () => {
  renderTable();

  fireEvent.change(screen.getByPlaceholderText("Бренд, товар, код, номинал…"), {
    target: { value: "pubg" },
  });

  await waitFor(() => {
    expect(screen.queryByText("Mobile Legends")).not.toBeInTheDocument();
  });
  expect(screen.getByText("PUBG Mobile")).toBeInTheDocument();
});

it("filters by mode", async () => {
  renderTable();

  fireEvent.change(screen.getByLabelText("Режим"), { target: { value: "manual" } });

  await waitFor(() => {
    expect(screen.queryByText("Mobile Legends")).not.toBeInTheDocument();
  });
  expect(screen.getByText("PUBG Mobile")).toBeInTheDocument();
});

it("filters by supplier, offering only suppliers present in the rules", async () => {
  renderTable();

  const supplierSelect = screen.getByLabelText("Поставщик");
  const optionValues = [...supplierSelect.querySelectorAll("option")].map((o) =>
    o.getAttribute("value"),
  );
  // sku-2's rule has no supplier_slug (manual) — only g2b shows up.
  expect(optionValues).toEqual(["", "g2b"]);

  fireEvent.change(supplierSelect, { target: { value: "g2b" } });

  await waitFor(() => {
    expect(screen.queryByText("PUBG Mobile")).not.toBeInTheDocument();
  });
  expect(screen.getByText("Mobile Legends")).toBeInTheDocument();
});

it("calls onDelete with the sku id after confirmation", () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const { onDelete } = renderTable();

  const deleteButtons = screen.getAllByRole("button", { name: "Удалить" });
  fireEvent.click(deleteButtons[0]!);

  expect(onDelete).toHaveBeenCalledWith("sku-1");
});

it("groups rules under their brand, each group naming its own rule count", () => {
  renderTable(RULES_GROUPED);

  // sku-1 and sku-3 are both Mobile Legends (2 rules); sku-2 is the only
  // PUBG Mobile rule.
  expect(screen.getByRole("region", { name: "Mobile Legends (2)" })).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "PUBG Mobile (1)" })).toBeInTheDocument();
});

it("keeps the free-text filter working across groups — a group with nothing left disappears", async () => {
  renderTable(RULES_GROUPED);
  expect(screen.getByRole("region", { name: "Mobile Legends (2)" })).toBeInTheDocument();

  fireEvent.change(screen.getByPlaceholderText("Бренд, товар, код, номинал…"), {
    target: { value: "500" },
  });

  await waitFor(() => {
    expect(screen.queryByRole("region", { name: /PUBG Mobile/ })).not.toBeInTheDocument();
  });
  // Only sku-3 (denomination 500) still matches — Mobile Legends' own count
  // drops from 2 to 1, proving the filter narrows rows inside a group too,
  // not just which groups appear.
  expect(screen.getByRole("region", { name: "Mobile Legends (1)" })).toBeInTheDocument();
});

it("keeps two different brands that share a display name in separate groups", () => {
  renderTable(RULES_NAME_COLLISION);

  // Grouping on the display name would merge brand-a and brand-b into one
  // "Mobile Legends (2)" section. Grouping on brand id keeps two sections,
  // each with its own count of 1 — and each row still lands under its own
  // brand's table, not the other one's.
  const groupedRegions = screen.getAllByRole("region", { name: "Mobile Legends (1)" });
  expect(groupedRegions).toHaveLength(2);
  expect(screen.queryByRole("region", { name: "Mobile Legends (2)" })).not.toBeInTheDocument();
  expect(within(groupedRegions[0]!).getByText(/MLBB-A|MLBB-B/)).toBeInTheDocument();
  expect(within(groupedRegions[1]!).getByText(/MLBB-A|MLBB-B/)).toBeInTheDocument();
});

it("files a rule whose SKU no longer resolves to a brand under «Без бренда»", () => {
  renderTable([
    {
      ...RULE_BASE,
      sku_id: "sku-orphan",
      sku_code: "ORPHAN-1",
      mode: "manual",
      supplier_slug: null,
      updated_at: "2026-09-12T00:00:00Z",
      denomination: null,
      product_slug: null,
      brand_id: null,
      brand_name: null,
    },
  ]);

  expect(screen.getByRole("region", { name: "Без бренда (1)" })).toBeInTheDocument();
  expect(screen.getByText("ORPHAN-1")).toBeInTheDocument();
});
