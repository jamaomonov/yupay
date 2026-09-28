// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it } from "vitest";

import { StatusBlock } from "./StatusBlock";

import type { ReactNode } from "react";

const messages = {
  web: {
    orders: {
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
        unknown: "Checking the status",
      },
      body: {
        pending_payment: "Waiting for your payment.",
        paid: "Payment received — preparing your order.",
        fulfilling:
          "Payment accepted. We're delivering your order — usually automatic and quick. Support is on standby if anything's off.",
        fulfilled: "Your order is ready.",
        delivered: "Delivered. Your items are below.",
        deliveredTopup: "Credited. Details below.",
        failed: "Something went wrong. Our team is on it — contact support if you need help.",
        cancelled: "This order was cancelled.",
        expired: "This order expired before payment.",
        refunded: "This order was refunded.",
        partially_refunded: "This order was partially refunded.",
        fulfillingSkin: "Buying the skin — the trade offer will arrive in Steam.",
        failedSkin: "We are checking the purchase — please contact support.",
        refundedSkin: "The money is back on your YuPay balance.",
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

it("shows real body copy for a fulfilling order (not just the status word)", () => {
  wrap(<StatusBlock status="fulfilling" />);
  expect(screen.getByText(/delivering your order/i)).toBeInTheDocument();
});

it("still shows the status heading alongside the body copy", () => {
  wrap(<StatusBlock status="fulfilling" />);
  expect(screen.getByRole("heading", { name: "Processing" })).toBeInTheDocument();
});

it("describes an unknown status instead of printing it, and shows no body", () => {
  // It used to render the raw code, which meant an eleventh status on the API
  // would read `some_future_status` as the heading of somebody's own order.
  wrap(<StatusBlock status="some_future_status" />);
  expect(screen.getByRole("heading", { name: "Checking the status" })).toBeInTheDocument();
  expect(screen.queryByText("some_future_status")).not.toBeInTheDocument();
});

it("shows top-up-flavored wording for a delivered top-up order", () => {
  wrap(<StatusBlock status="delivered" isTopUp />);
  expect(screen.getByRole("heading", { name: "Credited" })).toBeInTheDocument();
  expect(screen.getByText(/Credited\. Details below\./)).toBeInTheDocument();
});

it("still shows plain delivered wording when isTopUp is false", () => {
  wrap(<StatusBlock status="delivered" isTopUp={false} />);
  expect(screen.getByRole("heading", { name: "Delivered" })).toBeInTheDocument();
});

it("still shows plain delivered wording when isTopUp is omitted", () => {
  wrap(<StatusBlock status="delivered" />);
  expect(screen.getByRole("heading", { name: "Delivered" })).toBeInTheDocument();
});

it("says a skin's trade, not an account credit, while it is being bought", () => {
  wrap(<StatusBlock status="fulfilling" isSkin />);
  expect(screen.getByText(/trade offer will arrive in Steam/)).toBeInTheDocument();
});

it("says a skin refund went to the balance", () => {
  wrap(<StatusBlock status="refunded" isSkin />);
  expect(screen.getByText(/back on your YuPay balance/)).toBeInTheDocument();
});

it("never promises a card refund for a failed skin", () => {
  wrap(<StatusBlock status="failed" isSkin />);
  expect(screen.getByText(/checking the purchase/)).toBeInTheDocument();
});
