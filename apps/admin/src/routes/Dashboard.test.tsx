// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
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

/** Wait for the payload to actually land.
 *
 * A card's *label* renders before the query resolves — the value falls back
 * to zero — so awaiting one proves nothing, and an assertion about absence
 * made against the pre-load render passes for the wrong reason. The charged
 * line only exists once there is data. */
async function loaded(): Promise<void> {
  await screen.findByText("147 818 UZS");
}

function cardFor(label: string): HTMLElement {
  const card = screen.getByText(label).closest("article");
  if (card === null) throw new Error(`no card for ${label}`);
  return card;
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

  // Scoped to the card: «Возвраты» is also a dash on a payload with no
  // totals, and an unscoped query cannot tell which one it found.
  await screen.findByText("Выручка");
  expect(within(cardFor("Выручка")).getByText("—")).toBeInTheDocument();
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

const TOTALS = {
  orders: 7,
  delivered: 2,
  failed: 4,
  revenue_usd: "120.00",
  margin_usd: "12.50",
  refunded_usd: "0",
};

it("reads a headline as a movement, not an absolute", async () => {
  // "7 заказов" is neither good nor bad without the number it replaced.
  renderDashboard({ totals: TOTALS, previous: { ...TOTALS, orders: 4 } });
  await loaded();

  expect(within(cardFor("Заказы (24ч)")).getByText("+75%")).toBeInTheDocument();
});

it("flips the colours where up is bad", async () => {
  // More cancellations than yesterday is a red number, not a green one.
  renderDashboard({ totals: TOTALS, previous: { ...TOTALS, failed: 2 } });
  await loaded();

  const chip = within(cardFor("Отменено / истекло")).getByText("+100%");
  expect(chip.className).toContain("--danger-fg");
});

it("draws no chip at all for a shop with no yesterday", async () => {
  // A blank is honest here; "+100% против нуля" is not.
  renderDashboard({ totals: TOTALS, previous: null });
  await loaded();

  expect(screen.queryByText(/к прошлым 24ч/)).not.toBeInTheDocument();
});

it("says what was refunded beside the gross it is missing from", async () => {
  renderDashboard({ totals: { ...TOTALS, refunded_usd: "30.00" } });
  await loaded();

  expect(within(cardFor("Возвраты")).getByText("30,00 USD")).toBeInTheDocument();
});

it("names both halves of the business", async () => {
  // "7 заказов" does not say whether the wholesale side moved at all, and it
  // is the half that moves in steps of one.
  renderDashboard({
    totals: TOTALS,
    channels_in_window: [
      { channel: "retail", orders: 6, revenue_usd: "100.00" },
      { channel: "b2b", orders: 1, revenue_usd: "20.00" },
    ],
  });
  await loaded();

  const strip = screen.getByText("Каналы за 24ч").closest("section");
  if (strip === null) throw new Error("no channel strip");
  expect(within(strip).getByText("Розница")).toBeInTheDocument();
  expect(within(strip).getByText("B2B")).toBeInTheDocument();
});

it("hides the channel strip against an API that does not send it", async () => {
  // Deploy skew must degrade to the screen the operator had, never to an
  // empty box implying both channels sold nothing.
  renderDashboard();
  await loaded();

  expect(screen.queryByText("Каналы за 24ч")).not.toBeInTheDocument();
});
