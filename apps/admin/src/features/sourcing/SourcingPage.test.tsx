import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { SourcingPage } from "./SourcingPage";

import type { SourcingDecisionOut, SourcingRuleListOut } from "./types";
import type { SkuPickerRow } from "@/features/integrations/types";

import { api, apiGet } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  api: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}));

// The Combobox this wraps has no test coverage of its own anywhere in the
// codebase yet (open popover, debounced query, keyboard nav) — stubbing it
// here isolates SourcingPage's own logic (which this file is about) from
// re-testing that popover. Three buttons pick one of the three fixture SKUs
// below directly, the same contract (`value` / `onChange`) the real picker
// exposes.
vi.mock("@/features/integrations/pickers", () => ({
  SkuPicker: ({
    onChange,
  }: {
    value: SkuPickerRow | null;
    onChange: (v: SkuPickerRow | null) => void;
  }) => (
    <div>
      <button
        type="button"
        onClick={() => {
          onChange(TOPUP_WITH_RULE);
        }}
      >
        pick-topup-with-rule
      </button>
      <button
        type="button"
        onClick={() => {
          onChange(TOPUP_NO_RULE);
        }}
      >
        pick-topup-no-rule
      </button>
      <button
        type="button"
        onClick={() => {
          onChange(VOUCHER_NO_RULE);
        }}
      >
        pick-voucher-no-rule
      </button>
    </div>
  ),
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApi = vi.mocked(api);

const TOPUP_WITH_RULE: SkuPickerRow = {
  id: "sku-topup-rule",
  product_id: "prod-1",
  product_name: "Mobile Legends",
  product_slug: "mobile-legends",
  product_kind: "top_up",
  sku_code: "MLBB-100",
  denomination: "100",
  region: null,
  price_usd: "1.20",
  active: true,
};

const TOPUP_NO_RULE: SkuPickerRow = {
  id: "sku-topup-new",
  product_id: "prod-1",
  product_name: "Mobile Legends",
  product_slug: "mobile-legends",
  product_kind: "top_up",
  sku_code: "MLBB-500",
  denomination: "500",
  region: null,
  price_usd: "5.00",
  active: true,
};

const VOUCHER_NO_RULE: SkuPickerRow = {
  id: "sku-voucher",
  product_id: "prod-2",
  product_name: "Steam Gift",
  product_slug: "steam-gift",
  product_kind: "voucher",
  sku_code: "STEAM-10",
  denomination: null,
  region: null,
  price_usd: "10.00",
  active: true,
};

const RULES: SourcingRuleListOut = {
  items: [
    {
      sku_id: TOPUP_WITH_RULE.id,
      sku_code: TOPUP_WITH_RULE.sku_code,
      mode: "force_supplier",
      supplier_slug: "g2b",
      updated_by: "admin-1",
      updated_at: "2026-09-10T00:00:00Z",
    },
  ],
};

const DECISION: SourcingDecisionOut = {
  primary: "supplier:g2b",
  fallback: "supplier:manual",
  strict: false,
  rule_present: true,
};

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApi.mockReset();
  mockedApiGet.mockImplementation((path: string) => {
    if (path === "/api/v1/admin/sourcing/rules") return Promise.resolve(RULES);
    if (path.startsWith("/api/v1/admin/sourcing/rules/")) return Promise.resolve(DECISION);
    if (path.includes("/integrations/mappings")) return Promise.resolve({ items: [] });
    // RulesTable (rendered below the single-SKU editor on this same page)
    // fetches skus/products/brands as bare arrays, not `{ items: [] }`.
    return Promise.resolve([]);
  });
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SourcingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("reads as editing a SKU's existing rule — pre-filled mode/supplier, a banner, and a replace button", async () => {
  renderPage();
  fireEvent.click(screen.getByText("pick-topup-with-rule"));

  // Pre-filled from the existing rule (force_supplier / g2b): the "Только
  // поставщик" card is the selected one.
  await waitFor(() => {
    const card = screen.getByText("Только поставщик").closest("button");
    expect(card).toHaveAttribute("aria-pressed", "true");
  });

  // Says so, in visible text, not just via the pre-filled state.
  expect(screen.getByText(/уже есть правило/i)).toBeInTheDocument();

  // The button reads as replacing, not creating.
  expect(screen.getByRole("button", { name: /заменить правило/i })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /создать правило/i })).not.toBeInTheDocument();
});

it("reads as creating a new rule for a SKU with none yet", async () => {
  renderPage();
  fireEvent.click(screen.getByText("pick-voucher-no-rule"));

  await screen.findByText("Только склад");
  // No existing rule -> no editing banner.
  expect(screen.queryByText(/уже есть правило/i)).not.toBeInTheDocument();

  // Leave "auto" so the button's create/replace wording is what's on test —
  // at mode "auto" the button always reads "Применить (авто)" regardless.
  fireEvent.click(screen.getByText("Только склад"));

  expect(screen.getByRole("button", { name: /создать правило/i })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /заменить правило/i })).not.toBeInTheDocument();
});

it("does not offer force_inventory for a top-up SKU, and says why", async () => {
  renderPage();
  fireEvent.click(screen.getByText("pick-topup-no-rule"));

  await screen.findByText("Только склад");
  const card = screen.getByText("Только склад").closest("button");
  if (!card) throw new Error("card not found");

  expect(card).toBeDisabled();
  expect(within(card).getByText(/топ-ап нельзя выдать/i)).toBeInTheDocument();

  // Clicking a disabled card changes nothing.
  fireEvent.click(card);
  expect(card).toHaveAttribute("aria-pressed", "false");
});

it("still offers force_inventory for a voucher SKU", async () => {
  renderPage();
  fireEvent.click(screen.getByText("pick-voucher-no-rule"));

  await screen.findByText("Только склад");
  const card = screen.getByText("Только склад").closest("button");
  if (!card) throw new Error("card not found");

  expect(card).not.toBeDisabled();
  fireEvent.click(card);
  expect(card).toHaveAttribute("aria-pressed", "true");
});
