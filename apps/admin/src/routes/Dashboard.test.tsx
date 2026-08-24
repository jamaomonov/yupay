// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";

import { DashboardPage } from "./Dashboard";

import { apiGet } from "@/lib/api";

/**
 * The dashboard reached for raw `.toFixed(2)` instead of the shared money
 * formatter, so UZS revenue read as "147818.00 UZS" — a number an operator has
 * to count the digits of. It also kept its own copy of the order-status
 * labels, which is how a `failed` order showed up as raw English next to
 * properly localized rows.
 */

vi.mock("@/lib/api", () => ({ apiGet: vi.fn() }));

vi.mock("@/features/auth/authStore", () => ({
  useAuthStore: (selector: (s: { me: { name: string } | null }) => unknown) =>
    selector({ me: { name: "Jam" } }),
}));

const mockedApiGet = vi.mocked(apiGet);

function renderDashboard(over: Record<string, unknown> = {}) {
  mockedApiGet.mockResolvedValue({
    generated_at: "2026-08-16T05:34:38Z",
    window_hours: 24,
    orders_in_window: 7,
    orders_delivered_in_window: 2,
    orders_failed_in_window: 4,
    revenue_in_window: [{ currency: "UZS", amount: "147818.00" }],
    margin_in_window: { amount_usd: "12.50", pct: 8.4, unknown_units: 0 },
    status_breakdown: [
      { status: "expired", count: 4 },
      { status: "delivered", count: 2 },
      { status: "failed", count: 1 },
    ],
    in_flight_tasks: 0,
    stuck_payments: 0,
    pending_orders: 0,
    inventory: { available: 0, reserved: 0, issued: 0, voided: 0, low_stock_skus: 0 },
    orders_last_7_days: [{ date: "2026-08-15", count: 7, revenue_usd: "1234.50" }],
    ...over,
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("formats UZS revenue through the shared money formatter", async () => {
  renderDashboard();

  // Grouped, and no tiyin. `Intl` separates the digits with U+00A0, but
  // `findByText` matches against whitespace-normalized text, so the expected
  // string is written with an ordinary space.
  expect(await screen.findByText("147 818 UZS")).toBeInTheDocument();
  expect(screen.queryByText(/147818\.00/)).not.toBeInTheDocument();
});

it("localizes a failed order in the status breakdown instead of leaking the raw value", async () => {
  renderDashboard();

  expect(await screen.findByText("Проблемные")).toBeInTheDocument();
  expect(screen.queryByText("failed")).not.toBeInTheDocument();
});

it("still shows a dash when nothing was earned in the window", async () => {
  renderDashboard({ revenue_in_window: [] });

  expect(await screen.findByText("—")).toBeInTheDocument();
});

it("shows the margin beside the revenue it belongs to", async () => {
  renderDashboard();
  expect(await screen.findByText(/Маржа/)).toHaveTextContent("8.4%");
});

it("names uncosted units instead of folding them into the margin", async () => {
  // Silence about them reads as "this covers everything", and the figure is
  // exactly the one an operator would price the next batch off.
  renderDashboard({
    margin_in_window: { amount_usd: "12.50", pct: 8.4, unknown_units: 6 },
  });
  expect(await screen.findByText(/без себестоимости: 6/)).toBeInTheDocument();
});

it("still renders against an API that has no margin yet", async () => {
  // The admin ships separately from the API, so a bundle can reach a
  // deployment that predates the field. Losing the line is acceptable;
  // taking the whole dashboard down with it is not.
  renderDashboard({ margin_in_window: undefined });
  expect(await screen.findByText("147 818 UZS")).toBeInTheDocument();
  expect(screen.queryByText(/Маржа/)).not.toBeInTheDocument();
});
