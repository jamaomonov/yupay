// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeAll, expect, it, vi } from "vitest";

import { OrderStatus } from "./OrderStatus";

import type { OrderOut } from "@/lib/orders-types";
import type { ReactNode } from "react";

/**
 * The "codes are ready" block is gated on more than "delivered + guest": a
 * top-up has no code to hand over. `ArtifactReceipt` renders only real
 * deliverables (code / key / pin / serial) and deliberately excludes a
 * top-up's login, so it returns null for one — meaning the block used to send
 * a Steam buyer off to request an email, follow the link, and land on an empty
 * page. Pinned here because nothing about it is visible in the happy path.
 */

const messages = {
  web: {
    orders: {
      backToOrders: "Back",
      codesReadyTitle: "Codes are ready",
      codesNeedAccess: "Open the order from the email to see them.",
      sendAccessLink: "Email me the link",
      accessLinkSent: "Sent",
      accessLinkFailed: "Failed",
      loading: "…",
      supportCta: "Contact support",
      status: {
        delivered: "Delivered",
        deliveredTopup: "Credited",
      },
      // The rest of the page's copy. Present only so next-intl doesn't log a
      // MISSING_MESSAGE per key — noise that would bury a real failure.
      body: { delivered: "Delivered", deliveredTopup: "Credited to the account" },
      progress: {
        label: "Progress",
        paid: "Paid",
        fulfilling: "Delivering",
        delivered: "Delivered",
        credited: "Credited",
      },
      copyOrderId: "Copy",
      total: "Total",
      paidWith: "Paid with",
      createdAt: "Created",
      paidAt: "Paid",
      deliveredAt: "Delivered",
      itemsTitle: "Items",
    },
  },
};

const mockApiFetch = vi.fn<(path: string) => Promise<unknown>>();
vi.mock("@/lib/client", () => ({
  apiFetch: (path: string) => mockApiFetch(path),
}));

vi.mock("@/lib/guest", () => ({
  mintGuestToken: () => Promise.resolve("guest-tok"),
  requestCodeAccess: () => Promise.resolve(undefined),
}));

vi.mock("@/lib/reviews", () => ({
  getMyReviews: () => Promise.resolve({ items: [], total: 0 }),
}));

// No `?access=` in the URL — exactly the state a guest is in when they open the
// order straight after paying, which is when the block appears.
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: null }),
}));

vi.mock("@/store/useRealtimeStatus", () => ({
  useRealtimeStatus: (selector: (s: { connected: boolean }) => unknown) =>
    selector({ connected: false }),
}));

// jsdom ships no layout engine, so it has no scrollIntoView — the component
// calls it to bring the codes block into view once it renders.
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  vi.clearAllMocks();
});

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale="en" messages={messages}>
        {ui}
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

function makeOrder(kind: "top_up" | "voucher"): OrderOut {
  return {
    id: "01a00487-0000-0000-0000-000000000000",
    status: "delivered",
    currency: "UZS",
    total_usd: "1.00",
    total_charged: "13438.00",
    payment_provider: "click",
    fx_snapshot_id: null,
    expires_at: "2026-08-16T00:00:00Z",
    created_at: "2026-08-15T13:26:00Z",
    paid_at: "2026-08-15T13:26:00Z",
    fulfilled_at: null,
    delivered_at: "2026-08-15T13:27:00Z",
    cancelled_at: null,
    items: [
      {
        id: "item-1",
        sku_id: "sku-1",
        qty: 1,
        unit_price_usd: "1.00",
        fulfillment_state: "delivered",
        fulfillment_data: { steam_login: "_jamshid__" },
        display: {
          brand_slug: "steam",
          brand_name: "Steam",
          product_slug: "steam-wallet",
          product_name: "Steam Wallet",
          product_kind: kind,
          sku_code: "steam-wallet-usd",
          denomination: "1,00 $",
          region: "GLOBAL",
          image_url: null,
          variable_amount: true,
        },
      },
    ],
  };
}

it("does not offer a codes link on a delivered top-up — there are none to fetch", async () => {
  mockApiFetch.mockResolvedValue(makeOrder("top_up"));

  wrap(<OrderStatus orderId="01a00487-0000-0000-0000-000000000000" email="buyer@example.com" />);

  // Wait for the order itself so the assertion isn't just racing the fetch.
  // The status hero, not the progress step, which carries the same word.
  expect(await screen.findByRole("heading", { name: "Credited" })).toBeInTheDocument();
  expect(screen.queryByText("Codes are ready")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Email me the link" })).not.toBeInTheDocument();
});

it("still offers it on a delivered voucher, where a real code is waiting", async () => {
  mockApiFetch.mockResolvedValue(makeOrder("voucher"));

  wrap(<OrderStatus orderId="01a00487-0000-0000-0000-000000000000" email="buyer@example.com" />);

  await waitFor(() => {
    expect(screen.getByText("Codes are ready")).toBeInTheDocument();
  });
  expect(screen.getByRole("button", { name: "Email me the link" })).toBeInTheDocument();
});
