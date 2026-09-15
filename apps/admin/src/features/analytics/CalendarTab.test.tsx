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
    channel: "all",
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
      refunded_usd: "0",
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
    previous: null,
    channels: [],
    hourly: [],
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
      <CalendarTab channel="all" onPick={onPick} />
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

  it("asks for one day with an exclusive upper bound", async () => {
    // Clicking the same cell twice is how a single day is asked for now that
    // the grid picks spans. One click only arms the selection.
    const onPick = renderCalendar();
    await screen.findByText("$400");

    const cell = screen.getByRole("button", { name: /^1 сентября/ });
    fireEvent.click(cell);
    expect(onPick).not.toHaveBeenCalled();
    fireEvent.click(cell);

    await waitFor(() => {
      expect(onPick).toHaveBeenCalledTimes(1);
    });
    const [since, until] = onPick.mock.calls[0] as [string, string, string];
    expect(new Date(since).getDate()).toBe(1);
    // The day after, or the day the operator clicked comes back empty.
    expect(new Date(until).getDate()).toBe(2);
  });

  it("picks a span from its two ends, in either order", async () => {
    // The whole point of the change: «с 10 по 14» used to mean typing
    // дд.мм.гггг twice, month and year included, to ask about last week.
    const onPick = renderCalendar();
    await screen.findByText("$400");

    fireEvent.click(screen.getByRole("button", { name: /^14 сентября/ }));
    fireEvent.click(screen.getByRole("button", { name: /^10 сентября/ }));

    await waitFor(() => {
      expect(onPick).toHaveBeenCalledTimes(1);
    });
    const [since, until, label] = onPick.mock.calls[0] as [string, string, string];
    expect(new Date(since).getDate()).toBe(10);
    // Clicked backwards; the span still runs 10 → 15 (exclusive), so the
    // 14th is inside it.
    expect(new Date(until).getDate()).toBe(15);
    expect(label).toBe("10 сентября — 14 сентября");
  });

  it("lets a quiet day be one end of a span", async () => {
    // These cells used to be `disabled`, which was right while a click meant
    // "open this day" and wrong the moment it could mean "start here": «с 10
    // по 14» is an ordinary question when the 10th happened to be quiet, and
    // an unclickable end makes it unaskable.
    const onPick = renderCalendar();
    await screen.findByText("$400");

    fireEvent.click(screen.getByRole("button", { name: /^3 сентября.*нет оплаченных/ }));
    fireEvent.click(screen.getByRole("button", { name: /^5 сентября/ }));

    await waitFor(() => {
      expect(onPick).toHaveBeenCalledTimes(1);
    });
    const [since] = onPick.mock.calls[0] as [string, string, string];
    expect(new Date(since).getDate()).toBe(3);
  });

  it("abandons a half-made selection on Escape", async () => {
    const onPick = renderCalendar();
    await screen.findByText("$400");

    fireEvent.click(screen.getByRole("button", { name: /^10 сентября/ }));
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: /^14 сентября/ }));

    // The second click re-arms rather than completing the abandoned span.
    expect(onPick).not.toHaveBeenCalled();
  });
});
