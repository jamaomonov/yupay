import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";

import { OrdersListPage } from "./OrdersListPage";

import { formatMoney } from "@/lib/money";

import type { OrderAdminListOut, OrderAdminOut } from "./types";

import { apiGet } from "@/lib/api";

/**
 * A "failed" order (closed via the "Отметить проблемным" button on the detail
 * page) used to render as a bare, unlabeled dot in the Статус column: the
 * status was outside the admin's `OrderStatus` union, so `STATUS_LABEL`/
 * `STATUS_TONE` — both `Record<OrderStatus, string>` — had no entry for it and
 * the badge fell back to `undefined` label + tone. Pinned here so a future
 * backend status the admin type doesn't know about fails loudly instead of
 * rendering blank.
 */

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);

function makeOrder(over: Partial<OrderAdminOut> = {}): OrderAdminOut {
  return {
    id: "01a004c3-0000-0000-0000-000000000000",
    status: "delivered",
    currency: "UZS",
    total_usd: "1.00",
    charged_usd: "11.30",
    total_charged: "13438.00",
    fx_snapshot_id: null,
    expires_at: "2026-08-16T00:00:00Z",
    created_at: "2026-08-15T13:26:00Z",
    paid_at: "2026-08-15T13:26:00Z",
    fulfilled_at: null,
    delivered_at: "2026-08-15T13:27:00Z",
    cancelled_at: null,
    items: [],
    user_id: null,
    guest_email: "buyer@example.com",
    merchant_id: null,
    merchant_title: null,
    failure_reason: null,
    deposit_charged_usd: null,
    deposit_returned_usd: "0",
    source: "web",
    events: [],
    ...over,
  };
}

function renderPage(items: OrderAdminOut[]) {
  const payload: OrderAdminListOut = { items, total: items.length };
  mockedApiGet.mockResolvedValue(payload);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/orders"]}>
        <OrdersListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The one data row, as opposed to the header row — "Доставлен" is both a
 *  column header (the delivery-date column) and a status label, and
 *  "Проблемный" is both this row's badge and a <select> filter option, so
 *  asserting anywhere-in-the-table isn't enough to pin the badge itself. */
async function findDataRow(): Promise<HTMLElement> {
  const rows = await screen.findAllByRole("row");
  const row = rows[1];
  if (!row) throw new Error("expected a data row");
  return row;
}

it("labels an order marked failed instead of rendering a blank status", async () => {
  renderPage([makeOrder({ status: "failed" })]);

  const row = await findDataRow();
  expect(within(row).getByText("Проблемный")).toBeInTheDocument();
});

it("still labels an ordinary delivered order", async () => {
  renderPage([makeOrder()]);

  const row = await findDataRow();
  expect(within(row).getByText("Доставлен")).toBeInTheDocument();
});

it("says which surface an order came from", async () => {
  renderPage([
    makeOrder({ id: "01a00001-0000-0000-0000-000000000000", source: "miniapp" }),
    makeOrder({ id: "01a00002-0000-0000-0000-000000000000", source: "web" }),
  ]);

  const table = await screen.findByRole("table");
  expect(within(table).getByText("Mini App")).toBeInTheDocument();
  expect(within(table).getByText("Сайт")).toBeInTheDocument();
});

it("names the merchant channel instead of «—»", async () => {
  // A `/merchant/v1` order used to land in `unknown` — the CHECK had no value
  // for it — so the one class of order whose origin is not in doubt rendered
  // as "we have no idea". Migration 0073 + `merchants.orders.place`.
  renderPage([makeOrder({ source: "merchant_api" })]);

  const rows = await screen.findAllByRole("row");
  expect(within(rows[1]!).getByText("Merchant API")).toBeInTheDocument();
  expect(within(rows[1]!).queryByText("—")).not.toBeInTheDocument();
});

it("does not invent a surface for orders that never recorded one", async () => {
  // Every order older than the column reads `unknown`; claiming "Сайт" there
  // would turn an absence of evidence into a fact an operator might act on.
  renderPage([makeOrder({ source: "unknown" })]);

  const rows = await screen.findAllByRole("row");
  expect(within(rows[1]!).getByText("—")).toBeInTheDocument();
  expect(within(rows[1]!).queryByText("Сайт")).not.toBeInTheDocument();
});

it("labels a wallet top-up row instead of an empty item count", async () => {
  renderPage([
    makeOrder({
      purpose: "wallet_topup",
      items: [],
      // As the API actually serialises it: NUMERIC(20, 6). The old assertion
      // used "50000", which reads the same formatted or not and so passed
      // while an operator saw "10000.000000 UZS".
      total_charged: "10000.000000",
      currency: "UZS",
    }),
  ]);

  const row = await findDataRow();
  // Scoped to the label itself, not the row: the Сумма column two cells over
  // already formats correctly, so asserting on the whole row passed happily
  // while this cell rendered "10000.000000 UZS".
  const label = within(row).getByText(/Пополнение кошелька/);
  // Against the shared formatter rather than a literal, so the test cannot
  // disagree with that column about the separator — and via `textContent`,
  // because the query normaliser collapses the NBSP that
  // `Intl.NumberFormat("ru-RU")` actually emits.
  expect(label.textContent).toContain(formatMoney("10000.000000", "UZS"));
});

it("names the reseller on a merchant order instead of «Гость»", async () => {
  // The one class of order whose owner is never in doubt used to read as the
  // one class whose owner is anonymous: both retail arms are null on a B2B
  // order by construction (`ck_orders_actor_exclusive`), and the cell was
  // `guest_email ?? "—"`.
  renderPage([
    makeOrder({
      guest_email: null,
      merchant_id: "0198c3d1-4f2a-7b60-9c11-8e5d2a7f0b34",
      merchant_title: "Reseller LLC",
      source: "merchant_api",
    }),
  ]);

  const row = await findDataRow();
  expect(within(row).getByText(/Reseller LLC/)).toBeInTheDocument();
});

it("still shows a guest order's email", async () => {
  renderPage([makeOrder()]);

  const row = await findDataRow();
  expect(within(row).getByText("buyer@example.com")).toBeInTheDocument();
});

it.each([
  ["fulfillment_failed", "Провалено, решает человек"],
  ["fulfillment_failed_refunded", "Провалено, возвращено"],
  ["fulfillment_delayed", "Задерживается"],
  ["order_failed", "Закрыт вручную"],
])("says %s beside the status, not instead of it", async (reason, label) => {
  // A terminal fulfilment failure deliberately leaves `order.status` alone, so
  // the list said «В работе» on a dead order for ever. The status stays — the
  // FSM is not being lied about — and the reason is rendered next to it.
  renderPage([makeOrder({ status: "fulfilling", failure_reason: reason })]);

  const row = await findDataRow();
  expect(within(row).getByText("В работе")).toBeInTheDocument();
  expect(within(row).getByText(label)).toBeInTheDocument();
});

it("stays silent on a healthy in-flight order", async () => {
  // Without this the annotation becomes a decoration on every row and stops
  // meaning anything on the one row it was written for.
  renderPage([makeOrder({ status: "fulfilling", failure_reason: null })]);

  const row = await findDataRow();
  expect(within(row).getByText("В работе")).toBeInTheDocument();
  expect(within(row).queryByText(/Провалено|Задерживается|Закрыт/)).not.toBeInTheDocument();
});

it("renders nothing for a reason this build has never heard of", async () => {
  // The server's own contract for the field is additive — "treat an unknown
  // value as still in flight" — so a deploy skew must not paint a blank chip.
  renderPage([makeOrder({ status: "fulfilling", failure_reason: "something_new" })]);

  const row = await findDataRow();
  expect(within(row).getByText("В работе")).toBeInTheDocument();
  expect(within(row).queryByText("something_new")).not.toBeInTheDocument();
});
