// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it } from "vitest";

import { OrderSummary } from "./OrderSummary";

import type { OrderOut } from "@/lib/orders-types";
import type { ReactNode } from "react";

const messages = {
  web: {
    orders: {
      total: "Total paid",
      paidWith: "Paid with",
      paidWithWallet: "Balance",
      createdAt: "Created",
      paidAt: "Paid",
      deliveredAt: "Delivered",
    },
  },
};

const order: OrderOut = {
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
  items: [],
};

function wrap(ui: ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      {ui}
    </NextIntlClientProvider>,
  );
}

it("shows the total paid in the order currency and the provider", () => {
  wrap(<OrderSummary order={order} />);
  expect(screen.getByText("$10.00")).toBeInTheDocument();
  // The brand mark is a small decorative icon (alt="") next to the text
  // label, not a stand-in for it — the name must stay visible.
  expect(screen.getByText("Click")).toBeInTheDocument();
});

it("keeps the label for a provider that has no logo", () => {
  // Wallet, Octo and any unrecognised slug ship no asset — just the text.
  wrap(<OrderSummary order={{ ...order, payment_provider: "wallet" }} />);
  expect(screen.getByText("Balance")).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});
