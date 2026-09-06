// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { SkuB2bCard } from "./SkuB2bCard";

import type { Sku } from "../types";

import { apiPatch } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiPatch: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiPatch = vi.mocked(apiPatch);

const SKU: Sku = {
  id: "sku-1",
  product_id: "prod-1",
  sku_code: "robux-800",
  denomination: "800 Robux",
  region: "GLOBAL",
  price_usd: "9.99",
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

function renderCard(sku: Sku = SKU, cost: string = sku.cost_usdt ?? "") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SkuB2bCard sku={sku} cost={cost} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiPatch.mockReset();
});

it("renders the saved B2B state and a preliminary price preview", () => {
  renderCard();
  expect(screen.getByLabelText(/Виден мерчантам/)).toBeChecked();
  expect(screen.getByLabelText("Наценка B2B, %")).toHaveValue("7.00");
  // 8.00 × 1.07 = 8.56 — labelled «предварительно», the server stays the authority.
  expect(screen.getByText(/\$8\.56 · предварительно/)).toBeInTheDocument();
});

it("recomputes the preview as the markup is typed, with exact ceiling", () => {
  renderCard({ ...SKU, cost_usdt: "8.20" }, "8.20");
  fireEvent.change(screen.getByLabelText("Наценка B2B, %"), { target: { value: "10" } });
  // 8.20 × 1.10 is exactly 9.02 — a float ceil would show 9.03.
  expect(screen.getByText(/\$9\.02 · предварительно/)).toBeInTheDocument();
});

it("turns the preview into a warning when it lands below cost", () => {
  renderCard();
  fireEvent.change(screen.getByLabelText("Наценка B2B, %"), { target: { value: "-50" } });
  expect(screen.getByText(/\$4\.00 · предварительно/)).toBeInTheDocument();
  expect(screen.getByText(/ниже cost — проверь знак наценки/)).toBeInTheDocument();
});

it("renders an outright negative preview price with the warning styling", () => {
  renderCard({ ...SKU, cost_usdt: "1.00" }, "1.00");
  fireEvent.change(screen.getByLabelText("Наценка B2B, %"), { target: { value: "-150" } });
  // 1.00 × (1 − 1.50) = −0.50 — formatUsd renders the Unicode minus «−»,
  // not an ASCII hyphen, and the price line itself carries the danger tone.
  const price = screen.getByText(/≈ −\$0\.50 · предварительно/);
  expect(price).toHaveClass("text-[var(--danger)]");
  expect(screen.getByText(/ниже cost — проверь знак наценки/)).toBeInTheDocument();
});

it("explains that a SKU without a cost has no B2B price", () => {
  renderCard({ ...SKU, cost_usdt: null }, "");
  expect(
    screen.getByText("Без cost USDT у SKU нет B2B-цены — он не попадёт в каталог мерчантов."),
  ).toBeInTheDocument();
});

it("saves both fields through the dedicated B2B endpoint with an idempotency key", async () => {
  mockedApiPatch.mockResolvedValue({
    id: "sku-1",
    sku_code: "robux-800",
    visible_b2b: false,
    b2b_markup_pct: "5.50",
  });
  renderCard();

  fireEvent.click(screen.getByLabelText(/Виден мерчантам/));
  fireEvent.change(screen.getByLabelText("Наценка B2B, %"), { target: { value: "5.50" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить B2B" }));

  await waitFor(() => {
    expect(mockedApiPatch).toHaveBeenCalledTimes(1);
  });
  const [url, body, headers] = mockedApiPatch.mock.calls[0] ?? [];
  expect(url).toBe("/api/v1/admin/catalog/skus/sku-1/b2b");
  expect(body).toEqual({ markup_pct: "5.50", visible_b2b: false });
  expect(headers).toEqual(
    expect.objectContaining({ "Idempotency-Key": expect.any(String) as string }),
  );
});

it("refuses to send a markup the column cannot hold", () => {
  renderCard();
  fireEvent.change(screen.getByLabelText("Наценка B2B, %"), { target: { value: "1000" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить B2B" }));
  expect(mockedApiPatch).not.toHaveBeenCalled();
  expect(
    screen.getByText("Наценка — число до ±999.99, максимум два знака после точки."),
  ).toBeInTheDocument();
});
