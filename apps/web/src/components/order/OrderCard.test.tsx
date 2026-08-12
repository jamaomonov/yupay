// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it } from "vitest";

import { OrderCard } from "./OrderCard";

import type { OrderOut } from "@/lib/orders-types";
import type { ReactNode } from "react";

const messages = {
  web: {
    orders: {
      fallbackTitle: "Order #{id}",
      status: {
        pending_payment: "Awaiting payment",
        paid: "Paid",
        fulfilling: "Processing",
        fulfilled: "Fulfilled",
        delivered: "Delivered",
        deliveredTopup: "Credited",
        failed: "Failed",
        cancelled: "Cancelled",
        expired: "Expired",
        refunded: "Refunded",
        partially_refunded: "Partially refunded",
      },
    },
  },
};

function wrap(ui: ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      {ui}
    </NextIntlClientProvider>,
  );
}

function makeOrder(overrides: Partial<OrderOut> = {}): OrderOut {
  return {
    id: "abcdef123456",
    status: "delivered",
    currency: "USD",
    total_usd: "10.00",
    total_charged: "10.00",
    payment_provider: "click",
    fx_snapshot_id: null,
    expires_at: "2026-01-01T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    paid_at: "2026-01-01T00:01:00Z",
    fulfilled_at: null,
    delivered_at: "2026-01-01T00:02:00Z",
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
          brand_slug: "steam",
          brand_name: "Steam",
          product_slug: "steam-wallet",
          // Same as brand_name on purpose: exercises the "skip a
          // non-informative subtitle" branch (see the GLOBAL-region test).
          product_name: "Steam",
          product_kind: "wallet",
          sku_code: "STEAM-10",
          denomination: "$10",
          region: "GLOBAL",
          image_url: null,
          variable_amount: false,
        },
      },
    ],
    ...overrides,
  };
}

it("renders the brand · denomination title, the amount, and the status label", () => {
  wrap(<OrderCard order={makeOrder()} locale="en" href="/en/orders/abcdef123456" />);

  expect(screen.getByText("Steam · $10")).toBeInTheDocument();
  expect(screen.getByText("$10.00")).toBeInTheDocument();
  expect(screen.getByText("Delivered")).toBeInTheDocument();
  expect(screen.getByRole("link")).toHaveAttribute("href", "/en/orders/abcdef123456");
});

it("skips the generic GLOBAL region and falls back to the formatted date as the subtitle", () => {
  wrap(<OrderCard order={makeOrder()} locale="en" href="/en/orders/abcdef123456" />);

  const expectedDate = new Intl.DateTimeFormat("en").format(new Date("2026-01-01T00:00:00Z"));
  expect(screen.getByText(expectedDate)).toBeInTheDocument();
});

it("uses the top-up-flavored status label for a delivered top-up order", () => {
  const order = makeOrder({
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
          region: null,
          image_url: null,
          variable_amount: false,
        },
      },
    ],
  });

  wrap(<OrderCard order={order} locale="en" href="/en/orders/abcdef123456" />);

  expect(screen.getByText("Credited")).toBeInTheDocument();
  expect(screen.queryByText("Delivered")).not.toBeInTheDocument();
});

it("shows the product name as the subtitle when it differs from the brand name", () => {
  const order = makeOrder({
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
          product_name: "PUBG Mobile UC 100",
          product_kind: "top_up",
          sku_code: "PUBG-100",
          denomination: "100 UC",
          region: "GLOBAL",
          image_url: null,
          variable_amount: false,
        },
      },
    ],
  });

  wrap(<OrderCard order={order} locale="en" href="/en/orders/abcdef123456" />);

  const expectedDate = new Intl.DateTimeFormat("en").format(new Date("2026-01-01T00:00:00Z"));
  expect(screen.getByText(`${expectedDate} · PUBG Mobile UC 100`)).toBeInTheDocument();
});
