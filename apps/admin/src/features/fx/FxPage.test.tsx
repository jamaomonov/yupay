// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { FxPage } from "./FxPage";
import type { AdminRatesOut } from "./types";

import { apiGet, apiPatch } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPatch = vi.mocked(apiPatch);

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
});

it("renders each quote with the live FX rate", async () => {
  mockedApiGet.mockResolvedValue(RATES);
  renderPage();
  expect(await screen.findByRole("heading", { name: "USD → UZS" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Курс FX" })).toBeInTheDocument();
});

it("saves a typed rate and turns the manual toggle on", async () => {
  mockedApiGet.mockResolvedValue(RATES);
  mockedApiPatch.mockResolvedValue({
    ...RATES.rates[0],
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
