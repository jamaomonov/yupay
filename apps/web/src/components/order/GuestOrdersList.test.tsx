// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, expect, it, vi } from "vitest";

import { GuestOrdersList } from "./GuestOrdersList";

import type { GuestOrder } from "@/lib/guest-orders";
import type { OrderOut } from "@/lib/orders-types";
import type { ReactNode } from "react";

const messages = {
  web: {
    orders: {
      guestListTitle: "Your orders",
      guestListEmpty: "No orders on this device yet.",
      guestListHint: "Orders on this device",
      toCatalog: "Browse catalog",
      open: "Open",
      fallbackTitle: "Order #{id}",
      status: {
        delivered: "Delivered",
        deliveredTopup: "Credited",
      },
    },
  },
};

const mockMintGuestToken = vi.fn<(email: string) => Promise<string>>();
vi.mock("@/lib/guest", () => ({
  mintGuestToken: (email: string) => mockMintGuestToken(email),
}));

const mockApiFetch = vi.fn<(path: string) => Promise<OrderOut>>();
vi.mock("@/lib/client", () => ({
  apiFetch: (path: string) => mockApiFetch(path),
}));

afterEach(() => {
  vi.restoreAllMocks();
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

function makeOrder(): OrderOut {
  return {
    id: "o1",
    status: "delivered",
    currency: "USD",
    total_usd: "10.00",
    total_charged: "10.00",
    payment_provider: "click",
    fx_snapshot_id: null,
    expires_at: "2026-07-01T00:00:00Z",
    created_at: "2026-07-01T00:00:00Z",
    paid_at: "2026-07-01T00:01:00Z",
    fulfilled_at: null,
    delivered_at: "2026-07-01T00:02:00Z",
    cancelled_at: null,
    items: [
      {
        id: "item-1",
        sku_id: "sku-1",
        qty: 1,
        unit_price_usd: "10.00",
        fulfillment_state: "delivered",
        fulfillment_data: {},
        display: {
          brand_slug: "pubg",
          brand_name: "PUBG Mobile",
          product_slug: "pubg-uc",
          product_name: "PUBG Mobile UC",
          product_kind: "top_up",
          sku_code: "PUBG-100",
          denomination: "100 UC",
          region: "GLOBAL",
          image_url: null,
          variable_amount: false,
        },
      },
    ],
  };
}

it("shows the empty state with a catalog link when there are no guest orders", () => {
  wrap(<GuestOrdersList orders={[]} locale="en" />);
  expect(screen.getByText("No orders on this device yet.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Browse catalog" })).toHaveAttribute("href", "/en/store");
});

it("fetches each guest order via a per-email guest token and renders the full order card", async () => {
  mockMintGuestToken.mockResolvedValue("guest-tok");
  mockApiFetch.mockResolvedValue(makeOrder());

  const orders: GuestOrder[] = [
    {
      orderId: "o1",
      email: "  Buyer@Example.com  ",
      brandSlug: "pubg",
      brandName: "PUBG Mobile",
      createdAt: "2026-07-01T00:00:00.000Z",
    },
  ];
  wrap(<GuestOrdersList orders={orders} locale="en" />);

  expect(await screen.findByText("PUBG Mobile · 100 UC")).toBeInTheDocument();
  expect(screen.getByText("Credited")).toBeInTheDocument();
  expect(mockMintGuestToken).toHaveBeenCalledWith("buyer@example.com");
  expect(mockApiFetch).toHaveBeenCalledWith("/orders/o1");
  expect(screen.getByRole("link")).toHaveAttribute(
    "href",
    "/en/orders/o1?email=buyer%40example.com",
  );
});

it("falls back to the stub card with a normalized-email link when the order fetch fails", async () => {
  mockMintGuestToken.mockResolvedValue("guest-tok");
  mockApiFetch.mockRejectedValue(new Error("not found"));

  const orders: GuestOrder[] = [
    {
      orderId: "o1",
      email: "  Buyer@Example.com  ",
      brandSlug: "pubg",
      brandName: "PUBG Mobile",
      createdAt: "2026-07-01T00:00:00.000Z",
    },
  ];
  wrap(<GuestOrdersList orders={orders} locale="en" />);

  expect(await screen.findByText("Open")).toBeInTheDocument();
  expect(screen.getByText("PUBG Mobile")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /PUBG Mobile/ })).toHaveAttribute(
    "href",
    "/en/orders/o1?email=buyer%40example.com",
  );
});
