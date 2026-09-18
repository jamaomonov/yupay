import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { BrandSourcingPage } from "./BrandSourcingPage";

import type { SourcingBrandOverviewOut, SourcingBulkRuleOut } from "./types";

import { apiGet, apiPut } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPut: vi.fn(),
  ApiError: class ApiError extends Error {
    constructor(
      public status: number,
      public statusText: string,
      public body: unknown,
    ) {
      super(`${status.toString()} ${statusText}`);
    }
  },
  formatApiError: (err: { message: string }) => err.message,
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPut = vi.mocked(apiPut);

const BRANDS = [
  {
    id: "brand-1",
    slug: "mlbb",
    category_id: "cat-1",
    logo_url: null,
    hero_image_url: null,
    accent_color: null,
    sort_order: 0,
    active: true,
    maintenance: false,
    visible_b2b: true,
    translations: [{ locale: "ru", name: "Mobile Legends" }],
  },
];

const OVERVIEW: SourcingBrandOverviewOut = {
  items: [
    {
      sku_id: "sku-1",
      sku_code: "MLBB-100",
      denomination: "100",
      product_slug: "mobile-legends",
      price_usd: "1.20",
      cost_usdt: "0.90",
      primary: "supplier:g2b",
      rule_present: false,
      suppliers: [
        {
          supplier_slug: "g2b",
          has_active_mapping: true,
          latest_cost_usdt: "0.90",
          captured_at: "2026-09-10T00:00:00Z",
        },
        {
          supplier_slug: "gengine",
          has_active_mapping: false,
          latest_cost_usdt: null,
          captured_at: null,
        },
        {
          supplier_slug: "nova",
          has_active_mapping: true,
          latest_cost_usdt: "0.79",
          captured_at: "2026-09-15T00:00:00Z",
        },
      ],
    },
    {
      sku_id: "sku-2",
      sku_code: "MLBB-500",
      denomination: "500",
      product_slug: "mobile-legends",
      price_usd: "5.00",
      cost_usdt: "3.80",
      primary: "supplier:nova",
      rule_present: true,
      suppliers: [
        {
          supplier_slug: "g2b",
          has_active_mapping: true,
          latest_cost_usdt: "4.00",
          captured_at: "2026-09-10T00:00:00Z",
        },
        {
          supplier_slug: "gengine",
          has_active_mapping: false,
          latest_cost_usdt: null,
          captured_at: null,
        },
        {
          supplier_slug: "nova",
          has_active_mapping: true,
          latest_cost_usdt: "3.80",
          captured_at: "2026-09-15T00:00:00Z",
        },
      ],
    },
  ],
};

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiPut.mockReset();
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/catalog/brands")) return Promise.resolve(BRANDS);
    if (path.includes("/admin/sourcing/brands/")) return Promise.resolve(OVERVIEW);
    return Promise.resolve({ items: [] });
  });
});

function renderPage(initialPath = "/sourcing/brands/mlbb") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/sourcing/brands/:brandSlug" element={<BrandSourcingPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("renders one row per SKU with its route and each supplier's cost, cheapest marked", async () => {
  renderPage();

  await screen.findByText(/MLBB-100/);
  expect(screen.getByText(/MLBB-500/)).toBeInTheDocument();

  // NOVA (0.79) beats G2B (0.90) for sku-1 — its cost cell carries the marker.
  const cheapestBadges = screen.getAllByText("дешевле всех");
  expect(cheapestBadges.length).toBeGreaterThan(0);
});

it("does not offer a supplier with no active mapping, and shows why", async () => {
  renderPage();
  await screen.findByText(/MLBB-100/);

  // G-Engine has no active mapping on either SKU — the gap is visible text,
  // not merely a disabled control, and once per row (two rows).
  expect(screen.getAllByText("нет маппинга")).toHaveLength(2);
  expect(screen.queryByRole("button", { name: /Переключить на gengine/ })).not.toBeInTheDocument();
});

it("calls the bulk endpoint once with the ticked SKU ids", async () => {
  mockedApiPut.mockResolvedValue({
    items: [
      { sku_id: "sku-1", ok: true, error: null },
      { sku_id: "sku-2", ok: true, error: null },
    ],
  } satisfies SourcingBulkRuleOut);

  renderPage();
  await screen.findByText(/MLBB-100/);

  fireEvent.click(screen.getByLabelText("Выбрать MLBB-100"));
  fireEvent.click(screen.getByLabelText("Выбрать MLBB-500"));

  fireEvent.click(screen.getByRole("button", { name: "Применить к 2" }));

  await waitFor(() => {
    expect(mockedApiPut).toHaveBeenCalledTimes(1);
  });
  const body = mockedApiPut.mock.calls[0]?.[1] as {
    sku_ids: string[];
    mode: string;
    supplier_slug: string | null;
  };
  expect(body.sku_ids.sort()).toEqual(["sku-1", "sku-2"]);
  expect(body.mode).toBe("force_supplier");
});

it("renders which SKUs failed and why, and leaves the successful ones ticked off", async () => {
  mockedApiPut.mockResolvedValue({
    items: [
      { sku_id: "sku-1", ok: true, error: null },
      { sku_id: "sku-2", ok: false, error: "нет активного маппинга на g2b" },
    ],
  } satisfies SourcingBulkRuleOut);

  renderPage();
  await screen.findByText(/MLBB-100/);

  fireEvent.click(screen.getByLabelText("Выбрать MLBB-100"));
  fireEvent.click(screen.getByLabelText("Выбрать MLBB-500"));
  fireEvent.click(screen.getByRole("button", { name: "Применить к 2" }));

  await screen.findByText("нет активного маппинга на g2b");

  // The failed SKU stays ticked (easy to retry); the successful one is
  // dropped from the selection — it is done.
  expect(screen.getByLabelText("Выбрать MLBB-500")).toBeChecked();
  expect(screen.getByLabelText("Выбрать MLBB-100")).not.toBeChecked();
});
