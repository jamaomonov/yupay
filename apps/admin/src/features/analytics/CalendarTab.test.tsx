import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CalendarTab } from "./CalendarTab";

import type { BusinessAnalytics } from "./types";

import { apiGet } from "@/lib/api";

vi.mock("@/lib/api", () => ({ apiGet: vi.fn() }));
const mockedApiGet = vi.mocked(apiGet);

/**
 * The calendar's date arithmetic is the part worth pinning.
 *
 * Three things in it are easy to get wrong and invisible when wrong: the week
 * starts on Monday while `getDay()` counts from Sunday, the series is keyed by
 * *local* date while the API speaks ISO instants, and `until` is exclusive —
 * so "1 September" has to be asked for as 1 → 2 September, or the day the
 * operator clicked comes back empty.
 */
function payload(series: BusinessAnalytics["revenue_series"]): BusinessAnalytics {
  return {
    generated_at: "2026-09-15T00:00:00Z",
    range: null,
    since: "2026-09-01T00:00:00Z",
    until: "2026-10-01T00:00:00Z",
    summary: {
      gmv_usd: "0",
      orders: 0,
      paid_orders: 0,
      delivered_orders: 0,
      aov_usd: "0",
      gross_margin_usd: "0",
      margin_pct: 0,
      margin_approx: true,
      margin_unknown_units: 0,
    },
    revenue_series: series,
    funnel: {
      created: 0,
      paid: 0,
      fulfilling: 0,
      delivered: 0,
      cancelled: 0,
      expired: 0,
      refunded: 0,
      payment_conversion_pct: 0,
    },
    top_brands: [],
    top_skus: [],
    customers: {
      new_users_series: [],
      guest_orders: 0,
      registered_orders: 0,
      repeat_rate_pct: 0,
      top_locales: [],
    },
  };
}

function renderCalendar(onPick = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <CalendarTab onPick={onPick} />
    </QueryClientProvider>,
  );
  return onPick;
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  // A month that starts on a Tuesday, so the leading-blank count is not zero
  // and an off-by-one in the Monday-first shift would show.
  vi.setSystemTime(new Date(2026, 8, 15, 12, 0, 0));
  mockedApiGet.mockResolvedValue(
    payload([
      {
        date: "2026-09-01",
        revenue_usd: "400.00",
        orders: 4,
        margin_usd: "12.00",
        margin_unknown_units: 0,
      },
      {
        date: "2026-09-02",
        revenue_usd: "100.00",
        orders: 1,
        margin_usd: "48.00",
        margin_unknown_units: 0,
      },
    ]),
  );
});

describe("the month grid", () => {
  it("shows what each day earned and what it kept", async () => {
    renderCalendar();

    // Revenue alone cannot say which day was good: this one took four times
    // as much and kept a quarter of it.
    expect(await screen.findByText("$400")).toBeInTheDocument();
    expect(screen.getByText("+$12")).toBeInTheDocument();
    expect(screen.getByText("+$48")).toBeInTheDocument();
  });

  it("asks for the clicked day with an exclusive upper bound", async () => {
    const onPick = renderCalendar();
    await screen.findByText("$400");

    fireEvent.click(screen.getByTitle("1 Сентябрь"));

    await waitFor(() => {
      expect(onPick).toHaveBeenCalledTimes(1);
    });
    const [since, until] = onPick.mock.calls[0] as [string, string, string];
    expect(new Date(since).getDate()).toBe(1);
    // The day after, or the day the operator clicked comes back empty.
    expect(new Date(until).getDate()).toBe(2);
  });

  it("leaves a day with no paid orders unclickable", async () => {
    const onPick = renderCalendar();
    await screen.findByText("$400");

    // Every day but the two seeded ones, so take the first.
    const quiet = screen.getAllByTitle("Нет оплаченных заказов")[0];
    expect(quiet).toBeDefined();
    expect(quiet).toBeDisabled();
    fireEvent.click(quiet as HTMLElement);
    expect(onPick).not.toHaveBeenCalled();
  });
});
