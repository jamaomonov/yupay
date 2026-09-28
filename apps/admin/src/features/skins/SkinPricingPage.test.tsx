// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { SkinPricingPage } from "./SkinPricingPage";

import type { AdminSkinItemsOut, SkinsPricingOut } from "./pricing-api";

import { ApiError, apiGet, apiPatch, apiPut } from "@/lib/api";

vi.mock("@/lib/api", () => {
  class ApiError extends Error {
    constructor(
      public status: number,
      public statusText: string,
      public body: unknown,
    ) {
      super(`${String(status)} ${statusText}`);
    }
  }
  return { apiGet: vi.fn(), apiPut: vi.fn(), apiPatch: vi.fn(), ApiError };
});

const mockedGet = vi.mocked(apiGet);
const mockedPut = vi.mocked(apiPut);
const mockedPatch = vi.mocked(apiPatch);

const PRICING: SkinsPricingOut = {
  enabled: true,
  sync_enabled: true,
  categories: ["rifles", "knives"],
  rules: {
    expenses_percent: "3",
    retail: [
      { from_usd: "0", percent: "10" },
      { from_usd: "10", percent: "7" },
    ],
    b2b: [{ from_usd: "0", percent: "6" }],
    liquidity: [{ min_count: 0, pp: "0" }],
    category_pp: { knives: "-2" },
    weapon_pp: {},
    min_margin_usd: "0.10",
    price_floor_usd: "0.20",
    uzs_round_to: 100,
    cap_at_steam: false,
  },
};

const ITEMS: AdminSkinItemsOut = {
  items: [
    {
      slug: "awp-asiimov-ft",
      name: "AWP | Asiimov (Field-Tested)",
      category: "rifles",
      weapon: "AWP",
      image_url: null,
      count_auto: 30,
      cost_usd: "70.5",
      sell_price_usd: "80.00",
      margin_override_pp: "3.50",
      fixed_price_usd: null,
    },
  ],
};

function route(path: string): Promise<unknown> {
  if (path.startsWith("/api/v1/admin/skins/pricing/preview")) {
    return Promise.resolve({
      price_usd: "11.20",
      cost_usd: "10",
      expenses_usd: "0.30",
      bracket_margin_usd: "0.70",
      category_pp: "0",
      weapon_pp: "0",
      liquidity_pp: "0",
      item_pp: "0",
      effective_percent: "12",
      applied: "formula",
    });
  }
  if (path.startsWith("/api/v1/admin/skins/pricing")) return Promise.resolve(PRICING);
  if (path.startsWith("/api/v1/admin/skins/items")) return Promise.resolve(ITEMS);
  return Promise.reject(new Error(path));
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SkinPricingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedGet.mockReset();
  mockedPut.mockReset();
  mockedPatch.mockReset();
  mockedGet.mockImplementation((p: string) => route(p));
});

it("saves the edited rules with an Idempotency-Key", async () => {
  mockedPut.mockResolvedValue(PRICING);
  renderPage();
  const expenses = await screen.findByLabelText("Расходы, %");
  fireEvent.change(expenses, { target: { value: "4" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить правила" }));
  await waitFor(() => {
    expect(mockedPut).toHaveBeenCalledTimes(1);
  });
  const [path, body, headers] = mockedPut.mock.calls[0]!;
  expect(path).toBe("/api/v1/admin/skins/pricing");
  expect(body).toMatchObject({ expenses_percent: "4", retail: PRICING.rules.retail });
  expect(headers).toEqual(expect.objectContaining({ "Idempotency-Key": expect.any(String) }));
});

it("shows the server's refusal and keeps what was typed", async () => {
  mockedPut.mockRejectedValue(
    new ApiError(422, "Unprocessable", { detail: "retail: brackets must ascend strictly" }),
  );
  renderPage();
  const expenses = await screen.findByLabelText("Расходы, %");
  fireEvent.change(expenses, { target: { value: "5" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить правила" }));
  expect(await screen.findByText(/brackets must ascend strictly/)).toBeInTheDocument();
  expect(screen.getByLabelText("Расходы, %")).toHaveValue(5);
});

it("previews a price with its breakdown", async () => {
  renderPage();
  fireEvent.change(await screen.findByLabelText("Себестоимость, $"), { target: { value: "10" } });
  fireEvent.click(screen.getByRole("button", { name: "Рассчитать" }));
  expect(await screen.findByText("$11.20")).toBeInTheDocument();
  const call = mockedGet.mock.calls.find(([p]) => p.includes("/pricing/preview"));
  expect(call?.[0]).toContain("cost_usd=10");
});

it("clears an item's override by sending null", async () => {
  mockedPatch.mockResolvedValue({ margin_override_pp: null, fixed_price_usd: null });
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: /AWP \| Asiimov/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Сбросить наценку" }));
  await waitFor(() => {
    expect(mockedPatch).toHaveBeenCalledTimes(1);
  });
  const [path, body, headers] = mockedPatch.mock.calls[0]!;
  expect(path).toBe("/api/v1/admin/skins/items/awp-asiimov-ft");
  expect(body).toEqual({ margin_override_pp: null, fixed_price_usd: null });
  expect(headers).toEqual(expect.objectContaining({ "Idempotency-Key": expect.any(String) }));
});

it("keeps what was typed while a save was in flight", async () => {
  let finish: (v: SkinsPricingOut) => void = () => undefined;
  mockedPut.mockReturnValue(
    new Promise<SkinsPricingOut>((resolve) => {
      finish = resolve;
    }),
  );
  renderPage();
  const expenses = await screen.findByLabelText("Расходы, %");
  fireEvent.change(expenses, { target: { value: "4" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить правила" }));
  fireEvent.change(expenses, { target: { value: "6" } });
  finish({ ...PRICING, rules: { ...PRICING.rules, expenses_percent: "4" } });
  expect(await screen.findByText("Правила сохранены, каталог пересчитан")).toBeInTheDocument();
  expect(screen.getByLabelText("Расходы, %")).toHaveValue(6);
});

it("asks for every number before sending anything", async () => {
  renderPage();
  const floor = await screen.findByLabelText("Мин. цена, $");
  fireEvent.change(floor, { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить правила" }));
  expect(await screen.findByText("Заполните все числа в правилах")).toBeInTheDocument();
  expect(mockedPut).not.toHaveBeenCalled();
});
