import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { OrderDetailPage } from "./OrderDetailPage";

import type { OrderAdminOut, OrderEventOut } from "./types";

import { apiGet, apiPost } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPost = vi.mocked(apiPost);

const ORDER_ID = "01a00262-7fa6-7cb1-b3e2-969df898bae6";

const HELD_EVENT: OrderEventOut = {
  kind: "order.held_for_review",
  payload: { reason: "amount_at_or_above_threshold", total_usd: "43.000000" },
  actor: "risk",
  created_at: "2026-08-14T22:27:05Z",
};

function makeOrder(over: Partial<OrderAdminOut> = {}): OrderAdminOut {
  return {
    id: ORDER_ID,
    status: "paid",
    currency: "UZS",
    total_usd: "43.000000",
    charged_usd: "11.30",
    total_charged: "577735.000000",
    fx_snapshot_id: null,
    expires_at: "2026-08-15T22:26:44Z",
    created_at: "2026-08-14T22:26:44Z",
    paid_at: "2026-08-14T22:27:05Z",
    fulfilled_at: null,
    delivered_at: null,
    cancelled_at: null,
    items: [],
    user_id: null,
    guest_email: "buyer@example.com",
    merchant_id: null,
    merchant_title: null,
    failure_reason: null,
    source: "web",
    events: [HELD_EVENT],
    ...over,
  };
}

/** The page fans out to four endpoints; only the order one varies per test. */
function mockEndpoints(order: OrderAdminOut, tasks: unknown[] = []): void {
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/fulfillment/tasks")) {
      return Promise.resolve({ items: tasks, total: tasks.length });
    }
    if (path.includes("/payments")) return Promise.resolve({ items: [], total: 0 });
    if (path.includes("/deliveries")) return Promise.resolve({ items: [], total: 0 });
    return Promise.resolve(order);
  });
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/orders/${ORDER_ID}`]}>
        <Routes>
          <Route path="/orders/:id" element={<OrderDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiPost.mockReset();
  mockedApiPost.mockResolvedValue({ items: [], total: 0 });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("offers a release for an order held for manual review", async () => {
  // A held order keeps status `paid` and has no fulfilment task at all, so it
  // never shows up on the Fulfilment screen — this banner is the only way in.
  mockEndpoints(makeOrder());
  renderPage();

  expect(await screen.findByText("Заказ на проверке — выдача не запускалась")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /Выдать/ }));
  // Irreversible — goods leave and only money can be clawed back afterwards,
  // so the banner only opens a confirm; the dialog's button is the one that fires.
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Выдать" }));

  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledWith(
      `/api/v1/admin/fulfillment/orders/${ORDER_ID}/release`,
      {},
    );
  });
});

it("hides the release banner once fulfilment has started", async () => {
  // Same held event in history, but a task exists — it was already released,
  // so re-offering the button would invite a pointless second click.
  mockEndpoints(makeOrder(), [
    {
      id: "task-1",
      order_id: ORDER_ID,
      order_item_id: "item-1",
      supplier: "waxpeer",
      status: "in_progress",
      attempts_count: 1,
      last_error: null,
    },
  ]);
  renderPage();

  expect(await screen.findByText("Фулфилмент (1)")).toBeInTheDocument();
  expect(screen.queryByText("Заказ на проверке — выдача не запускалась")).not.toBeInTheDocument();
});

it("shows no release banner for an ordinary paid order", async () => {
  mockEndpoints(makeOrder({ events: [] }));
  renderPage();

  expect(await screen.findByText("Сводка")).toBeInTheDocument();
  expect(screen.queryByText("Заказ на проверке — выдача не запускалась")).not.toBeInTheDocument();
});

it("converts the charged amount at the real rate, not the Steam face value", async () => {
  // `total_usd` on a top-up is the credit the buyer chose ($10), while they
  // actually paid the markup on top. Showing the face value beside the so'm
  // amount read as a conversion and was short by the whole margin.
  mockEndpoints(makeOrder({ total_usd: "10.00", charged_usd: "11.30" }));
  renderPage();

  expect(await screen.findByText("≈ $11,30")).toBeInTheDocument();
  expect(screen.queryByText("≈ $10,00")).not.toBeInTheDocument();
});

it("omits the USD hint when the backend could not value the order", async () => {
  mockEndpoints(makeOrder({ charged_usd: null }));
  renderPage();

  expect(await screen.findByText("Сводка")).toBeInTheDocument();
  expect(screen.queryByText(/≈ \$/)).not.toBeInTheDocument();
});

it("says a merchant order came through the merchant API", async () => {
  // The detail page never rendered the surface at all, and a B2B order is
  // where that costs: nothing else on this header separates a reseller's
  // order from a browser sale.
  mockEndpoints(makeOrder({ source: "merchant_api" }));
  renderPage();

  expect(await screen.findByText("Merchant API")).toBeInTheDocument();
});

it("stays silent about a surface the order never recorded", async () => {
  // «—» earns its place in a table column, which cannot be empty. In the
  // header line it would just be noise — so this is scoped to that line
  // («—» is a legitimate placeholder elsewhere on the page) and it is what
  // fails if the label is ever rendered unconditionally.
  mockEndpoints(makeOrder({ source: "unknown" }));
  renderPage();

  const buyer = await screen.findByText("buyer@example.com");
  const header = buyer.parentElement!;
  expect(within(header).queryByText("—")).not.toBeInTheDocument();
  expect(within(header).queryByText("Сайт")).not.toBeInTheDocument();
});

it("names the reseller on a merchant order instead of «Гость»", async () => {
  // `{order.guest_email ?? "Гость"}` — the header's whole actor line — reads a
  // B2B order as an anonymous buyer, because both retail arms are null on one.
  mockEndpoints(
    makeOrder({
      guest_email: null,
      merchant_id: "0198c3d1-4f2a-7b60-9c11-8e5d2a7f0b34",
      merchant_title: "Reseller LLC",
      source: "merchant_api",
      events: [],
    }),
  );
  renderPage();

  expect(await screen.findByText("Reseller LLC")).toBeInTheDocument();
  expect(screen.queryByText("Гость")).not.toBeInTheDocument();
});

it("links a merchant order to the reseller's own page", async () => {
  // The title answers "who is this"; the link answers "and what is their
  // deposit doing" — which is the next question on a failed B2B order, and
  // the page the money lives on.
  mockEndpoints(
    makeOrder({
      guest_email: null,
      merchant_id: "0198c3d1-4f2a-7b60-9c11-8e5d2a7f0b34",
      merchant_title: "Reseller LLC",
      events: [],
    }),
  );
  renderPage();

  const link = await screen.findByRole("link", { name: "Reseller LLC" });
  expect(link).toHaveAttribute("href", "/merchants/0198c3d1-4f2a-7b60-9c11-8e5d2a7f0b34");
});

it("still shows a guest order's email", async () => {
  mockEndpoints(makeOrder({ events: [] }));
  renderPage();

  expect(await screen.findByText("buyer@example.com")).toBeInTheDocument();
});

it("says why a `fulfilling` order has stopped, beside the status", async () => {
  mockEndpoints(
    makeOrder({ status: "fulfilling", failure_reason: "fulfillment_failed", events: [] }),
  );
  renderPage();

  expect(await screen.findByText("Провалено, решает человек")).toBeInTheDocument();
  // The status itself is untouched — the FSM is what it is.
  expect(screen.getAllByText("В работе").length).toBeGreaterThan(0);
});

it("stays silent on an order that has not stopped", async () => {
  mockEndpoints(makeOrder({ status: "fulfilling", failure_reason: null, events: [] }));
  renderPage();

  expect(await screen.findByText("Сводка")).toBeInTheDocument();
  expect(screen.queryByText(/Провалено|Задерживается|Закрыт вручную/)).not.toBeInTheDocument();
});
