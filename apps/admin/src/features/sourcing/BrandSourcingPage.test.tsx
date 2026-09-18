import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { BrandSourcingPage } from "./BrandSourcingPage";

import type { SourcingBrandOverviewOut, SourcingBulkRuleOut } from "./types";

import { ApiError, apiGet, apiPut } from "@/lib/api";

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
      fallback: null,
      rule_present: false,
      suppliers: [
        {
          supplier_slug: "g2b",
          has_active_mapping: true,
          latest_cost_usdt: "0.90",
          captured_at: "2026-09-10T00:00:00Z",
          cost_source: "history",
        },
        {
          supplier_slug: "gengine",
          has_active_mapping: false,
          latest_cost_usdt: null,
          captured_at: null,
          cost_source: null,
        },
        {
          supplier_slug: "nova",
          has_active_mapping: true,
          latest_cost_usdt: "0.79",
          captured_at: "2026-09-15T00:00:00Z",
          cost_source: "history",
        },
        // Actively mapped but never price-synced (waxpeer's real-world
        // shape: it has no price rows by design) — must render as unknown
        // cost, never as "0,00".
        {
          supplier_slug: "waxpeer",
          has_active_mapping: true,
          latest_cost_usdt: null,
          captured_at: null,
          cost_source: null,
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
      fallback: null,
      rule_present: true,
      suppliers: [
        {
          supplier_slug: "g2b",
          has_active_mapping: true,
          latest_cost_usdt: "4.00",
          captured_at: "2026-09-10T00:00:00Z",
          cost_source: "history",
        },
        {
          supplier_slug: "gengine",
          has_active_mapping: false,
          latest_cost_usdt: null,
          captured_at: null,
          cost_source: null,
        },
        {
          supplier_slug: "nova",
          has_active_mapping: true,
          latest_cost_usdt: "3.80",
          captured_at: "2026-09-15T00:00:00Z",
          cost_source: "history",
        },
        {
          supplier_slug: "waxpeer",
          has_active_mapping: true,
          latest_cost_usdt: null,
          captured_at: null,
          cost_source: null,
        },
      ],
    },
  ],
};

// A voucher SKU on the automatic route: `primary="inventory"`,
// `fallback="supplier:g2b"` — warehouse first, g2b as backup (whole-branch
// review Important #1 and #2). Used by tests below that need the code
// warehouse to actually be the current route, which `OVERVIEW` above never
// exercises (every row there already routes to a supplier).
const VOUCHER_OVERVIEW: SourcingBrandOverviewOut = {
  items: [
    {
      sku_id: "sku-9",
      sku_code: "GIFT-10",
      denomination: null,
      product_slug: "steam-gift",
      price_usd: "10.00",
      cost_usdt: "8.00",
      primary: "inventory",
      fallback: "supplier:g2b",
      rule_present: false,
      suppliers: [
        {
          supplier_slug: "g2b",
          has_active_mapping: true,
          latest_cost_usdt: "8.00",
          captured_at: "2026-09-10T00:00:00Z",
          cost_source: "history",
        },
        {
          supplier_slug: "nova",
          has_active_mapping: true,
          latest_cost_usdt: "7.50",
          captured_at: "2026-09-15T00:00:00Z",
          cost_source: "history",
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
  // The header "Применить к N" action now confirms before it writes
  // (Important 6) — default every test to "operator confirmed" so the
  // existing bulk-apply assertions below still exercise the mutation.
  vi.spyOn(window, "confirm").mockReturnValue(true);
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

it("renders one row per SKU with its route and each supplier's cost", async () => {
  renderPage();

  await screen.findByText(/MLBB-100/);
  expect(screen.getByText(/MLBB-500/)).toBeInTheDocument();
});

it("marks the cheapest supplier's own cell — not just anywhere on the page", async () => {
  renderPage();
  await screen.findByText(/MLBB-100/);

  const row = screen.getByText(/MLBB-100/).closest("tr");
  if (!row) throw new Error("row not found");
  // NOVA (0.79) beats G2B (0.90) for sku-1 — the badge must sit in NOVA's
  // own cost cell, not merely appear somewhere in the row. A reversed
  // comparator (picks the most expensive) would still make
  // `getAllByText("дешевле всех").length > 0` true, which is why that used
  // to be the whole assertion. The cost cell carries its raw value as a
  // `title` (for the near-tie precision fix below), so query by that
  // rather than the rounded, possibly-split display text.
  const novaCell = within(row).getByTitle("0.79 USDT").closest("td");
  expect(novaCell).not.toBeNull();
  expect(within(novaCell as HTMLElement).getByText("дешевле всех")).toBeInTheDocument();

  const g2bCell = within(row).getByTitle("0.90 USDT").closest("td");
  expect(g2bCell).not.toBeNull();
  expect(within(g2bCell as HTMLElement).queryByText("дешевле всех")).not.toBeInTheDocument();
});

it("shows an actively-mapped-but-unpriced supplier as unknown cost, never as 0,00", async () => {
  renderPage();
  await screen.findByText(/MLBB-100/);

  const row = screen.getByText(/MLBB-100/).closest("tr");
  if (!row) throw new Error("row not found");
  // waxpeer: has_active_mapping true, latest_cost_usdt null — a real cost
  // can never be 0 (positive-cost CHECK constraint), so "0,00" is a number
  // the system cannot produce.
  expect(within(row).getByText("цена не снята")).toBeInTheDocument();
  expect(within(row).queryByText(/0,00/)).not.toBeInTheDocument();
  // Unknown cost never wins "дешевле всех" — cheapestSlugs skips it.
  const waxpeerButton = within(row).getByRole("button", { name: "Переключить на waxpeer" });
  expect(
    within(waxpeerButton.closest("td") as HTMLElement).queryByText("дешевле всех"),
  ).not.toBeInTheDocument();
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

it("asks for confirmation before a bulk apply, naming the count and the target", async () => {
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

  renderPage();
  await screen.findByText(/MLBB-100/);

  fireEvent.click(screen.getByLabelText("Выбрать MLBB-100"));
  fireEvent.click(screen.getByRole("button", { name: /Применить к 1/ }));

  expect(confirmSpy).toHaveBeenCalledTimes(1);
  expect(confirmSpy.mock.calls[0]?.[0]).toMatch(/1 SKU/);
  expect(confirmSpy.mock.calls[0]?.[0]).toMatch(/G2Bulk/);
  // Declining the confirmation must not write anything.
  expect(mockedApiPut).not.toHaveBeenCalled();
});

it("sends the clicked column's own slug, not the row's cheapest slug", async () => {
  mockedApiPut.mockResolvedValue({
    items: [{ sku_id: "sku-2", ok: true, error: null }],
  } satisfies SourcingBulkRuleOut);

  renderPage();
  await screen.findByText(/MLBB-500/);

  const row = screen.getByText(/MLBB-500/).closest("tr");
  if (!row) throw new Error("row not found");
  // For sku-2, NOVA (3.80) is both the cheapest AND already the current
  // route; G2B (4.00) is the pricier column. Clicking G2B's own switch
  // must send "g2b" — if the button silently substituted the row's
  // cheapest slug instead, this would send "nova" and the money would go
  // to the wrong supplier.
  fireEvent.click(within(row).getByRole("button", { name: "Переключить на g2b" }));

  await waitFor(() => {
    expect(mockedApiPut).toHaveBeenCalledTimes(1);
  });
  const body = mockedApiPut.mock.calls[0]?.[1] as {
    sku_ids: string[];
    mode: string;
    supplier_slug: string | null;
  };
  expect(body.sku_ids).toEqual(["sku-2"]);
  expect(body.mode).toBe("force_supplier");
  expect(body.supplier_slug).toBe("g2b");
});

it("never sends a supplier_slug alongside mode: auto, even with a supplier still picked", async () => {
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

  // `bulkSupplier` stays at its default ("g2b") — never touched — while the
  // operator switches the bulk mode to "Авто". This is the exact ternary
  // (`bulkMode === "force_supplier" ? bulkSupplier : null`) ADR-0081's
  // "no reserve supplier reaches auto" guarantee rests on: a leftover
  // picked supplier must not leak into an "auto" request.
  fireEvent.change(screen.getByLabelText("Режим для 2 SKU"), { target: { value: "auto" } });
  fireEvent.click(screen.getByRole("button", { name: /Применить к 2/ }));

  await waitFor(() => {
    expect(mockedApiPut).toHaveBeenCalledTimes(1);
  });
  const body = mockedApiPut.mock.calls[0]?.[1] as { mode: string; supplier_slug: string | null };
  expect(body.mode).toBe("auto");
  expect(body.supplier_slug).toBeNull();
});

it("keeps other rows' failure reasons when one row's own switch is retried", async () => {
  mockedApiPut.mockResolvedValueOnce({
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

  // Retry sku-1 from its own row control — sku-2's still-current failure
  // reason must survive, not get wiped by a wholesale map replacement.
  mockedApiPut.mockResolvedValueOnce({
    items: [{ sku_id: "sku-1", ok: true, error: null }],
  } satisfies SourcingBulkRuleOut);
  const row1 = screen.getByText(/MLBB-100/).closest("tr");
  if (!row1) throw new Error("row not found");
  fireEvent.click(within(row1).getByRole("button", { name: "склад" }));

  await waitFor(() => {
    expect(mockedApiPut).toHaveBeenCalledTimes(2);
  });
  expect(screen.getByText("нет активного маппинга на g2b")).toBeInTheDocument();
});

it("disables only the row whose own switch is in flight, not every row", async () => {
  // An object property, not a bare `let`, so TS doesn't narrow the
  // closure-assigned value back to its initial `null` at the read site
  // below.
  const deferred: { resolve: ((value: SourcingBulkRuleOut) => void) | null } = { resolve: null };
  mockedApiPut.mockImplementation(
    () =>
      new Promise<SourcingBulkRuleOut>((resolve) => {
        deferred.resolve = resolve;
      }),
  );

  renderPage();
  await screen.findByText(/MLBB-100/);

  const row1 = screen.getByText(/MLBB-100/).closest("tr");
  const row2 = screen.getByText(/MLBB-500/).closest("tr");
  if (!row1 || !row2) throw new Error("row not found");

  fireEvent.click(within(row1).getByRole("button", { name: "авто" }));

  // Row 1's own quick controls are disabled while its write is in flight...
  expect(within(row1).getByRole("button", { name: "авто" })).toBeDisabled();
  // ...but row 2 has nothing in flight and stays usable.
  expect(within(row2).getByRole("button", { name: "авто" })).not.toBeDisabled();

  deferred.resolve?.({ items: [{ sku_id: "sku-1", ok: true, error: null }] });
  await waitFor(() => {
    expect(within(row1).getByRole("button", { name: "авто" })).not.toBeDisabled();
  });
});

it("renders an error state, not the empty state, when the brand overview fails to load", async () => {
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/catalog/brands")) return Promise.resolve(BRANDS);
    if (path.includes("/admin/sourcing/brands/")) {
      return Promise.reject(new ApiError(404, "Not Found", { detail: "Бренд не найден" }));
    }
    return Promise.resolve({ items: [] });
  });

  renderPage();

  expect(await screen.findByText("Бренд не найден")).toBeInTheDocument();
  expect(screen.queryByText("У этого бренда нет активных SKU.")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Повторить/i })).toBeInTheDocument();
});

it("marks the fallback supplier current for a voucher SKU routed through the warehouse (Important #2)", async () => {
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/catalog/brands")) return Promise.resolve(BRANDS);
    if (path.includes("/admin/sourcing/brands/")) return Promise.resolve(VOUCHER_OVERVIEW);
    return Promise.resolve({ items: [] });
  });

  renderPage();
  await screen.findByText(/GIFT-10/);
  const row = screen.getByText(/GIFT-10/).closest("tr");
  if (!row) throw new Error("row not found");

  // g2b is `fallback`, not `primary` — it must read as the current cost
  // owner, with no switch button offered for it.
  expect(within(row).getByText(/текущий/)).toBeInTheDocument();
  expect(within(row).queryByRole("button", { name: "Переключить на g2b" })).not.toBeInTheDocument();
  // nova is neither `primary` nor `fallback` — it stays an ordinary,
  // switchable candidate.
  expect(within(row).getByRole("button", { name: "Переключить на nova" })).toBeInTheDocument();
});

it("labels a supplier switch on an inventory-routed row as bypassing the warehouse (Important #1)", async () => {
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/catalog/brands")) return Promise.resolve(BRANDS);
    if (path.includes("/admin/sourcing/brands/")) return Promise.resolve(VOUCHER_OVERVIEW);
    return Promise.resolve({ items: [] });
  });

  renderPage();
  await screen.findByText(/GIFT-10/);
  const row = screen.getByText(/GIFT-10/).closest("tr");
  if (!row) throw new Error("row not found");

  // nova's own switch button — the only offerable one on this row (g2b is
  // already current as the fallback) — must read as taking the warehouse
  // out of routing, not as an ordinary "сюда →" preference change.
  const novaButton = within(row).getByRole("button", { name: "Переключить на nova" });
  expect(novaButton).toHaveTextContent("в обход склада");
  expect(novaButton).not.toHaveTextContent("сюда →");
});

it("adds the warehouse-bypass consequence to the bulk-apply confirmation (Important #1)", async () => {
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/catalog/brands")) return Promise.resolve(BRANDS);
    if (path.includes("/admin/sourcing/brands/")) return Promise.resolve(VOUCHER_OVERVIEW);
    return Promise.resolve({ items: [] });
  });
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

  renderPage();
  await screen.findByText(/GIFT-10/);

  // Default bulk mode is force_supplier / g2b — ticking this inventory-
  // routed row and applying must warn before anything is written.
  fireEvent.click(screen.getByLabelText("Выбрать GIFT-10"));
  fireEvent.click(screen.getByRole("button", { name: /Применить к 1/ }));

  expect(confirmSpy).toHaveBeenCalledTimes(1);
  const message = confirmSpy.mock.calls[0]?.[0] ?? "";
  expect(message).toMatch(/1 SKU/);
  expect(message).toMatch(/1 из них/);
  expect(message).toMatch(/склад/);
  expect(mockedApiPut).not.toHaveBeenCalled();
});

it("marks a row's cost as stale right after a successful switch — the write doesn't reprice it (Important #4)", async () => {
  mockedApiPut.mockResolvedValue({
    items: [{ sku_id: "sku-1", ok: true, error: null }],
  } satisfies SourcingBulkRuleOut);

  renderPage();
  await screen.findByText(/MLBB-100/);
  const row1 = screen.getByText(/MLBB-100/).closest("tr");
  if (!row1) throw new Error("row not found");

  expect(within(row1).queryByText(/не обновилась/)).not.toBeInTheDocument();

  fireEvent.click(within(row1).getByRole("button", { name: "авто" }));

  await waitFor(() => {
    expect(within(row1).getByText(/не обновилась/)).toBeInTheDocument();
  });
  // The other, untouched row must not be flagged.
  const row2 = screen.getByText(/MLBB-500/).closest("tr");
  if (!row2) throw new Error("row not found");
  expect(within(row2).queryByText(/не обновилась/)).not.toBeInTheDocument();
});
