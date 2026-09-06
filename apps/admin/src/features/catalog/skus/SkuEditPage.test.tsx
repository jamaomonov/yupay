// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { SkuEditPage } from "./SkuEditPage";

import { apiGet, apiPost } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPost = vi.mocked(apiPost);

// Minimal product so the create form can actually pass `product_id`
// validation and reach the `apiPost` mutation — every other test in this
// file leaves the product list empty since it doesn't need a saveable form.
const PRODUCT = {
  id: "prod-1",
  slug: "tg-stars",
  brand_id: "brand-1",
  kind: "top_up" as const,
  supplier_hint: null,
  image_url: null,
  sort_order: 0,
  active: true,
  required_fields: [],
  translations: [],
};

const RATES = {
  base: "USD",
  rates: [
    {
      base: "USD",
      quote: "UZS",
      rate: "12700",
      fetched_at: "2026-01-01T00:00:00Z",
      source: "test",
    },
    { base: "USD", quote: "RUB", rate: "95", fetched_at: "2026-01-01T00:00:00Z", source: "test" },
  ],
};

function mockCatalog(options?: { products?: (typeof PRODUCT)[] }): void {
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/fx/rates")) return Promise.resolve(RATES);
    if (path.includes("/catalog/products")) return Promise.resolve(options?.products ?? []);
    // brands / skus — a bare list page doesn't need a selected product to
    // exercise the price/margin math, which is independent of it.
    return Promise.resolve([]);
  });
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/skus/new"]}>
        <SkuEditPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockCatalog();
});

afterEach(() => {
  vi.restoreAllMocks();
});

it("hides the margin field until a valid cost is entered", async () => {
  renderPage();
  expect(screen.queryByPlaceholderText("20")).not.toBeInTheDocument();

  const cost = await screen.findByPlaceholderText("0.60");
  fireEvent.change(cost, { target: { value: "0" } });
  expect(screen.queryByPlaceholderText("20")).not.toBeInTheDocument();

  fireEvent.change(cost, { target: { value: "1" } });
  expect(await screen.findByPlaceholderText("20")).toBeInTheDocument();
});

it("computes price_usd from cost and a typed margin percent", async () => {
  renderPage();

  const cost = await screen.findByPlaceholderText("0.60");
  fireEvent.change(cost, { target: { value: "1" } });

  const margin = await screen.findByPlaceholderText("20");
  fireEvent.change(margin, { target: { value: "25" } });

  const price = screen.getByPlaceholderText("0.85") as HTMLInputElement;
  await waitFor(() => {
    expect(price.value).toBe("1.25");
  });
});

it("computes margin percent from cost and a typed price_usd", async () => {
  renderPage();

  const cost = await screen.findByPlaceholderText("0.60");
  fireEvent.change(cost, { target: { value: "2" } });

  const price = screen.getByPlaceholderText("0.85");
  fireEvent.change(price, { target: { value: "3" } });

  const margin = (await screen.findByPlaceholderText("20")) as HTMLInputElement;
  await waitFor(() => {
    expect(margin.value).toBe("50");
  });
});

it("re-derives margin from the new cost, keeping price_usd put", async () => {
  renderPage();

  const cost = await screen.findByPlaceholderText("0.60");
  fireEvent.change(cost, { target: { value: "1" } });
  const price = screen.getByPlaceholderText("0.85") as HTMLInputElement;
  fireEvent.change(price, { target: { value: "1.50" } });
  const margin = (await screen.findByPlaceholderText("20")) as HTMLInputElement;
  await waitFor(() => {
    expect(margin.value).toBe("50");
  });

  // Cost moves (e.g. the supplier's price changed) — price_usd is left as
  // the operator set it, margin catches up to the new ratio instead.
  fireEvent.change(cost, { target: { value: "1.25" } });
  await waitFor(() => {
    expect(margin.value).toBe("20");
  });
  expect(price.value).toBe("1.50");
});

it("shows the min/max stars fields for a non-variable SKU, and hides them once variable amount is toggled on", async () => {
  renderPage();

  expect(await screen.findByPlaceholderText("50")).toBeInTheDocument();
  expect(screen.getByPlaceholderText("2500")).toBeInTheDocument();

  fireEvent.click(screen.getByLabelText("Плавающая сумма"));
  await waitFor(() => {
    expect(screen.queryByPlaceholderText("50")).not.toBeInTheDocument();
  });
  expect(screen.queryByPlaceholderText("2500")).not.toBeInTheDocument();
});

it("rejects max_qty below min_qty", async () => {
  renderPage();

  const priceUsd = await screen.findByPlaceholderText("0.85");
  fireEvent.change(priceUsd, { target: { value: "1" } });
  const skuCode = screen.getByPlaceholderText("pubg-uc-60-tr");
  fireEvent.change(skuCode, { target: { value: "tg-stars-any" } });

  const minQty = screen.getByPlaceholderText("50");
  fireEvent.change(minQty, { target: { value: "2500" } });
  const maxQty = screen.getByPlaceholderText("2500");
  fireEvent.change(maxQty, { target: { value: "50" } });

  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

  expect(await screen.findByText("Должно быть ≥ минимума")).toBeInTheDocument();
  expect(mockedApiPost).not.toHaveBeenCalled();
});

it("rejects a lone min_qty with no max_qty", async () => {
  renderPage();

  const priceUsd = await screen.findByPlaceholderText("0.85");
  fireEvent.change(priceUsd, { target: { value: "1" } });
  const skuCode = screen.getByPlaceholderText("pubg-uc-60-tr");
  fireEvent.change(skuCode, { target: { value: "tg-stars-any" } });

  const minQty = screen.getByPlaceholderText("50");
  fireEvent.change(minQty, { target: { value: "50" } });
  // max_qty stays empty — both-or-neither must reject this.

  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

  expect(await screen.findByText("Оба поля вместе, целое число ≥ 1")).toBeInTheDocument();
  expect(mockedApiPost).not.toHaveBeenCalled();
});

it("rejects a lone max_qty with no min_qty", async () => {
  renderPage();

  const priceUsd = await screen.findByPlaceholderText("0.85");
  fireEvent.change(priceUsd, { target: { value: "1" } });
  const skuCode = screen.getByPlaceholderText("pubg-uc-60-tr");
  fireEvent.change(skuCode, { target: { value: "tg-stars-any" } });

  // min_qty stays empty — both-or-neither must reject this.
  const maxQty = screen.getByPlaceholderText("2500");
  fireEvent.change(maxQty, { target: { value: "2500" } });

  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

  expect(await screen.findByText("Оба поля вместе, целое число ≥ 1")).toBeInTheDocument();
  expect(mockedApiPost).not.toHaveBeenCalled();
});

it("sends min_qty and max_qty as numbers on the create request body", async () => {
  mockCatalog({ products: [PRODUCT] });
  mockedApiPost.mockResolvedValue(undefined);
  renderPage();

  // The "Продукт" <label> also wraps a help sentence, so its computed
  // accessible name isn't the bare word — query the <select> directly
  // instead of via getByLabelText, once its option has loaded in.
  await waitFor(() => {
    expect(document.querySelector(`option[value="${PRODUCT.id}"]`)).toBeInTheDocument();
  });
  const productSelect = document.querySelector<HTMLSelectElement>('select[name="product_id"]');
  if (!productSelect) throw new Error("product_id <select> not found");
  fireEvent.change(productSelect, { target: { value: PRODUCT.id } });

  const skuCode = screen.getByPlaceholderText("pubg-uc-60-tr");
  fireEvent.change(skuCode, { target: { value: "tg-stars-any" } });
  const priceUsd = screen.getByPlaceholderText("0.85");
  fireEvent.change(priceUsd, { target: { value: "1" } });
  const minQty = screen.getByPlaceholderText("50");
  fireEvent.change(minQty, { target: { value: "50" } });
  const maxQty = screen.getByPlaceholderText("2500");
  fireEvent.change(maxQty, { target: { value: "2500" } });

  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledTimes(1);
  });
  const [path, body] = mockedApiPost.mock.calls[0] as [string, Record<string, unknown>];
  expect(path).toBe("/api/v1/admin/catalog/skus");
  expect(body).toMatchObject({ min_qty: 50, max_qty: 2500 });
});

it("previews the USD price converted per FX rate, and prefers a currency override over the conversion", async () => {
  renderPage();

  const price = await screen.findByPlaceholderText("0.85");
  fireEvent.change(price, { target: { value: "10" } });

  // Override RUB at 999 — the FX conversion would say 950 (10 × 95).
  fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
  fireEvent.change(screen.getByLabelText("Валюта переопределения цены"), {
    target: { value: "RUB" },
  });
  fireEvent.change(screen.getByPlaceholderText("0.00"), { target: { value: "999" } });

  fireEvent.click(screen.getByRole("button", { name: /Превью цены в других валютах/i }));

  const panel = await screen.findByRole("dialog", { name: "Цены в других валютах" });
  expect(within(panel).getByText("999")).toBeInTheDocument();
  // Exact, case-sensitive: the footer note also contains the word
  // "Override" (capitalised, mid-sentence) — only the badge is "override".
  expect(within(panel).getByText("override")).toBeInTheDocument();
  expect(within(panel).queryByText("950")).not.toBeInTheDocument();
});

it("shows the B2B card with the saved state on an existing SKU", async () => {
  // Full Sku shape — the edit form resets from every field of it.
  const sku = {
    id: "sku-1",
    product_id: "prod-1",
    sku_code: "stars-100",
    denomination: "100",
    region: "GLOBAL",
    price_usd: "2.00",
    cost_usdt: "8.00",
    margin_percent: null,
    variable_amount: false,
    min_amount_usd: null,
    max_amount_usd: null,
    rate_multiplier: null,
    min_qty: null,
    max_qty: null,
    image_url: null,
    sort_order: 0,
    active: true,
    visible_b2b: true,
    b2b_markup_pct: "7.00",
    price_overrides: [],
  };
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/fx/rates")) return Promise.resolve(RATES);
    if (path.includes("/catalog/products")) return Promise.resolve([PRODUCT]);
    if (path.includes("/catalog/brands")) return Promise.resolve([]);
    return Promise.resolve([sku]);
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/skus/sku-1"]}>
        <Routes>
          <Route path="/skus/:id" element={<SkuEditPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByLabelText("Наценка B2B, %")).toHaveValue("7.00");
  expect(screen.getByLabelText(/Виден мерчантам/)).toBeChecked();
  // 8.00 × 1.07 = 8.56, «предварительно» — the server stays the authority.
  expect(screen.getByText(/\$8\.56 · предварительно/)).toBeInTheDocument();
});
