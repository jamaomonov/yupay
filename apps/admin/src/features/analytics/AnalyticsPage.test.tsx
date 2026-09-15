import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { AnalyticsPage } from "./AnalyticsPage";

import type { BusinessAnalytics } from "./types";

import { apiGet } from "@/lib/api";

vi.mock("@/lib/api", () => ({ apiGet: vi.fn() }));
const mockedApiGet = vi.mocked(apiGet);

/**
 * Retail and B2B are sold at different margins, so the blended headline
 * flatters one and libels the other. What is pinned here is that the toggle
 * reaches the *server* — a purely client-side filter would have to re-derive
 * the funnel, the mix and the margin from a payload that no longer carries
 * the rows it would need.
 */
function payload(): BusinessAnalytics {
  return {
    generated_at: "2026-09-15T00:00:00Z",
    range: "30d",
    channel: "all",
    since: "2026-08-16T00:00:00Z",
    until: null,
    summary: {
      gmv_usd: "100",
      orders: 2,
      paid_orders: 2,
      delivered_orders: 2,
      aov_usd: "50",
      gross_margin_usd: "10",
      margin_pct: 10,
      margin_approx: true,
      margin_unknown_units: 0,
      refunded_usd: "0",
    },
    revenue_series: [],
    funnel: {
      created: 2,
      paid: 2,
      fulfilling: 0,
      delivered: 2,
      cancelled: 0,
      expired: 0,
      refunded: 0,
      payment_conversion_pct: 100,
    },
    top_brands: [],
    top_skus: [],
    previous: null,
    channels: [
      { channel: "retail", gmv_usd: "60", orders: 1, margin_usd: "6" },
      { channel: "b2b", gmv_usd: "40", orders: 1, margin_usd: "4" },
    ],
    hourly: [],
    customers: {
      new_users_series: [],
      guest_orders: 1,
      registered_orders: 1,
      repeat_rate_pct: 0,
      top_locales: [],
    },
  };
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AnalyticsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockResolvedValue(payload());
});

it("asks the server for one half of the business", async () => {
  renderPage();
  await screen.findByText("Средний чек");

  fireEvent.click(screen.getByRole("button", { name: "B2B" }));

  await waitFor(() => {
    expect(mockedApiGet.mock.calls.some((call) => String(call[0]).includes("channel=b2b"))).toBe(
      true,
    );
  });
});

it("shows both halves side by side whichever one is selected", async () => {
  // The comparison block is the exception to the scoping: it is what the
  // scoping is compared against, so narrowing it leaves one row saying 100%.
  renderPage();

  const table = await screen.findByRole("table", { name: "Розница и B2B" });
  expect(table).toHaveTextContent("Розница");
  expect(table).toHaveTextContent("B2B");
});
