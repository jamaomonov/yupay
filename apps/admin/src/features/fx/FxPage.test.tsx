// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { FxPage } from "./FxPage";
import type { AdminRatesOut, ProviderChainOut } from "./types";

import { apiGet, apiPatch } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiPut: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPatch = vi.mocked(apiPatch);

const PROVIDERS: ProviderChainOut = {
  quotes: ["UZS", "RUB"],
  items: [
    {
      slug: "fxratesapi",
      title: "FXRatesAPI",
      kind: "fiat",
      enabled: true,
      configured: true,
      role: "primary",
      sort_order: 0,
      quotes: [
        { quote: "UZS", rate: "11853.55", error: null },
        { quote: "RUB", rate: "78.2", error: null },
      ],
    },
  ],
};

const RATES: AdminRatesOut = {
  base: "USD",
  rates: [
    {
      base: "USD",
      quote: "UZS",
      rate: "12700.25",
      fetched_at: "2026-08-22T00:00:00Z",
      source: "stub",
      use_manual: false,
      manual_rate: null,
      fx_rate: "12700.25",
      fx_source: "stub",
      fx_fetched_at: "2026-08-22T00:00:00Z",
    },
  ],
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <FxPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiPatch.mockReset();
  mockedApiGet.mockImplementation(async (path: string) => {
    if (path.includes("/providers")) return PROVIDERS;
    return RATES;
  });
});

it("renders each quote with the live FX rate", async () => {
  renderPage();
  expect(await screen.findByRole("heading", { name: "USD → UZS" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Курс FX" })).toBeInTheDocument();
});

it("shows each provider's live rate and the primary badge", async () => {
  renderPage();
  expect(await screen.findByText("Источники курса FX")).toBeInTheDocument();
  expect(screen.getByText("FXRatesAPI")).toBeInTheDocument();
  expect(screen.getByText("Основной")).toBeInTheDocument();
});

it("saves a typed rate and turns the manual toggle on", async () => {
  const first = RATES.rates[0];
  if (first === undefined) throw new Error("fixture");
  mockedApiPatch.mockResolvedValue({
    ...first,
    rate: "12500",
    source: "manual",
    use_manual: true,
    manual_rate: "12500",
  });
  renderPage();

  fireEvent.click(await screen.findByRole("button", { name: "Наш курс" }));
  fireEvent.change(screen.getByLabelText("Наш курс"), { target: { value: "12500" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

  await waitFor(() => {
    expect(mockedApiPatch).toHaveBeenCalledWith("/api/v1/admin/fx/rates/UZS", {
      use_manual: true,
      manual_rate: "12500",
    });
  });
});

it("does not save a rate far from FX on the first click", async () => {
  const first = RATES.rates[0];
  if (first === undefined) throw new Error("fixture");
  mockedApiPatch.mockResolvedValue({
    ...first,
    rate: "1250",
    source: "manual",
    use_manual: true,
    manual_rate: "1250",
  });
  renderPage();

  fireEvent.click(await screen.findByRole("button", { name: "Наш курс" }));
  // 1250 against an FX rate of 12700.25 — a lost zero, the exact typo that
  // silently reprices the catalogue because a pinned rate skips the band.
  fireEvent.change(screen.getByLabelText("Наш курс"), { target: { value: "1250" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

  expect(mockedApiPatch).not.toHaveBeenCalled();
  const confirm = await screen.findByRole("button", { name: "Да, сохранить этот курс" });

  fireEvent.click(confirm);
  await waitFor(() => {
    expect(mockedApiPatch).toHaveBeenCalledWith("/api/v1/admin/fx/rates/UZS", {
      use_manual: true,
      manual_rate: "1250",
    });
  });
});

it("withdraws the confirmation when the number is edited again", async () => {
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "Наш курс" }));
  fireEvent.change(screen.getByLabelText("Наш курс"), { target: { value: "1250" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  await screen.findByRole("button", { name: "Да, сохранить этот курс" });

  fireEvent.change(screen.getByLabelText("Наш курс"), { target: { value: "12500" } });
  expect(screen.getByRole("button", { name: "Сохранить" })).toBeInTheDocument();
  expect(mockedApiPatch).not.toHaveBeenCalled();
});
