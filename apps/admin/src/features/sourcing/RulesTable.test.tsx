import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { RulesTable } from "./RulesTable";

import type { SourcingRuleOut } from "./types";

import { apiGet } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);

const SKUS = [
  { id: "sku-1", product_id: "prod-1", sku_code: "MLBB-100", denomination: "100" },
  { id: "sku-2", product_id: "prod-2", sku_code: "PUBG-60", denomination: "60" },
  // Second SKU of the same product/brand as sku-1 — used only by the
  // grouping tests below, to get a brand with more than one rule under it.
  { id: "sku-3", product_id: "prod-1", sku_code: "MLBB-500", denomination: "500" },
];
const PRODUCTS = [
  { id: "prod-1", slug: "mobile-legends", brand_id: "brand-1" },
  { id: "prod-2", slug: "pubg-mobile", brand_id: "brand-2" },
];
const BRANDS = [
  { id: "brand-1", slug: "mlbb", translations: [{ locale: "ru", name: "Mobile Legends" }] },
  { id: "brand-2", slug: "pubg", translations: [{ locale: "ru", name: "PUBG Mobile" }] },
];

const RULES: SourcingRuleOut[] = [
  {
    sku_id: "sku-1",
    sku_code: "MLBB-100",
    mode: "force_supplier",
    supplier_slug: "g2b",
    updated_by: "admin-1",
    updated_at: "2026-09-10T00:00:00Z",
  },
  {
    sku_id: "sku-2",
    sku_code: "PUBG-60",
    mode: "manual",
    supplier_slug: null,
    updated_by: "admin-1",
    updated_at: "2026-09-11T00:00:00Z",
  },
];

// Three rules across the same two brands as `RULES` — sku-3 adds a second
// Mobile Legends rule, so Mobile Legends holds 2 and PUBG Mobile holds 1.
// Only used by the grouping tests below; every other test keeps using the
// two-rule `RULES` fixture unchanged.
const RULES_GROUPED: SourcingRuleOut[] = [
  ...RULES,
  {
    sku_id: "sku-3",
    sku_code: "MLBB-500",
    mode: "force_inventory",
    supplier_slug: null,
    updated_by: "admin-1",
    updated_at: "2026-09-12T00:00:00Z",
  },
];

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/catalog/skus")) return Promise.resolve(SKUS);
    if (path.includes("/catalog/products")) return Promise.resolve(PRODUCTS);
    if (path.includes("/catalog/brands")) return Promise.resolve(BRANDS);
    return Promise.resolve([]);
  });
});

function renderTable(rules: SourcingRuleOut[] = RULES, onDelete = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    onDelete,
    ...render(
      <QueryClientProvider client={qc}>
        <RulesTable rules={rules} loading={false} onDelete={onDelete} />
      </QueryClientProvider>,
    ),
  };
}

it("shows brand, product and denomination beside the SKU code", async () => {
  renderTable();

  await screen.findByText("Mobile Legends");
  expect(screen.getByText("mobile-legends")).toBeInTheDocument();
  expect(screen.getByText("PUBG Mobile")).toBeInTheDocument();
  expect(screen.getByText("100")).toBeInTheDocument();
});

it("filters by free text across brand, product, code and denomination", async () => {
  renderTable();
  await screen.findByText("Mobile Legends");

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
  await screen.findByText("Mobile Legends");

  fireEvent.change(screen.getByLabelText("Режим"), { target: { value: "manual" } });

  await waitFor(() => {
    expect(screen.queryByText("Mobile Legends")).not.toBeInTheDocument();
  });
  expect(screen.getByText("PUBG Mobile")).toBeInTheDocument();
});

it("filters by supplier, offering only suppliers present in the rules", async () => {
  renderTable();
  await screen.findByText("Mobile Legends");

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

it("calls onDelete with the sku id after confirmation", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const { onDelete } = renderTable();
  await screen.findByText("Mobile Legends");

  const deleteButtons = screen.getAllByRole("button", { name: "Удалить" });
  fireEvent.click(deleteButtons[0]!);

  expect(onDelete).toHaveBeenCalledWith("sku-1");
});

it("groups rules under their brand, each group naming its own rule count", async () => {
  renderTable(RULES_GROUPED);

  // sku-1 and sku-3 are both Mobile Legends (2 rules); sku-2 is the only
  // PUBG Mobile rule.
  await screen.findByRole("region", { name: "Mobile Legends (2)" });
  expect(screen.getByRole("region", { name: "PUBG Mobile (1)" })).toBeInTheDocument();
});

it("keeps the free-text filter working across groups — a group with nothing left disappears", async () => {
  renderTable(RULES_GROUPED);
  await screen.findByRole("region", { name: "Mobile Legends (2)" });

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
