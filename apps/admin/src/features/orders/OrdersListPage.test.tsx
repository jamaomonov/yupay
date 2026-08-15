import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";

import { OrdersListPage } from "./OrdersListPage";

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
