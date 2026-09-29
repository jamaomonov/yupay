// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { SkinSalesPage } from "./SkinSalesPage";

import type { SkinsSummaryOut } from "./sales-api";

import { apiGet } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);

const SUMMARY: SkinsSummaryOut = {
  days: 30,
  sold: { count: 12, revenue_usd: "420.50", cost_usd: "390.10", margin_usd: "30.40" },
  failed: { count: 2, revenue_usd: "18.00", cost_usd: "0", margin_usd: "18.00" },
  in_flight: { count: 1, revenue_usd: "5.00", cost_usd: "4.80", margin_usd: "0.20" },
  by_day: [{ day: "2026-09-29", count: 3, revenue_usd: "100.00", margin_usd: "7.25" }],
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/skins/sales"]}>
        <SkinSalesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiGet.mockResolvedValue(SUMMARY);
});

it("shows sold, revenue, cost and margin with its percent", async () => {
  renderPage();
  expect(await screen.findByText("$420.50")).toBeInTheDocument();
  expect(screen.getByText("$390.10")).toBeInTheDocument();
  expect(screen.getByText(/\$30\.40/)).toBeInTheDocument();
  expect(screen.getByText(/7\.2\s?%/)).toBeInTheDocument();
  expect(screen.getByText("12")).toBeInTheDocument();
});

it("lists received skins per day", async () => {
  renderPage();
  expect(await screen.findByText("$7.25")).toBeInTheDocument();
  expect(screen.getByText("$100.00")).toBeInTheDocument();
});

it("asks the API for the period picked", async () => {
  renderPage();
  await screen.findByText("$420.50");
  fireEvent.click(screen.getByRole("tab", { name: "7 дней" }));
  await waitFor(() => {
    expect(mockedApiGet).toHaveBeenLastCalledWith("/api/v1/admin/skins/summary?days=7");
  });
});
