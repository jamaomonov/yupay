import { expect, it } from "vitest";

import { merchantSettlement, settlementBlock, toWireAmount } from "./settlement";

import type { OrderAdminOut } from "./types";

const MERCHANT = "0198c3d1-4f2a-7b60-9c11-8e5d2a7f0b34";

function makeOrder(over: Partial<OrderAdminOut> = {}): OrderAdminOut {
  return {
    id: "01a00262-7fa6-7cb1-b3e2-969df898bae6",
    status: "fulfilling",
    currency: "USD",
    total_usd: "1.070000",
    charged_usd: "1.07",
    total_charged: "1.070000",
    fx_snapshot_id: null,
    expires_at: "2026-09-10T00:00:00Z",
    created_at: "2026-09-09T00:00:00Z",
    paid_at: "2026-09-09T00:00:01Z",
    fulfilled_at: null,
    delivered_at: null,
    cancelled_at: null,
    items: [],
    user_id: null,
    guest_email: null,
    merchant_id: MERCHANT,
    merchant_title: "Reseller LLC",
    failure_reason: "fulfillment_failed",
    deposit_charged_usd: "1.070000",
    deposit_returned_usd: "0.000000",
    source: "merchant_api",
    events: [],
    ...over,
  };
}

it("offers the charge, trimmed to the wire's two decimals", () => {
  // `NUMERIC(20, 6)` on the wire, `decimal_places=2` in the endpoint's schema.
  expect(merchantSettlement(makeOrder())).toEqual({
    merchantId: MERCHANT,
    orderId: "01a00262-7fa6-7cb1-b3e2-969df898bae6",
    amount: "1.07",
  });
});

it("never offers it on a retail order", () => {
  // The gate, with a case. `merchant_id` and a deposit charge cannot co-occur
  // with a retail actor in the database — `ck_orders_actor_exclusive` and the
  // ledger see to that — so the fixture is hypothetical on purpose: without it
  // the guard has nothing to be wrong about, and deleting the line would go
  // unnoticed because every real retail order is already stopped one line
  // later by a null charge.
  const retail = makeOrder({
    merchant_id: null,
    merchant_title: null,
    guest_email: "buyer@example.com",
    deposit_charged_usd: "1.070000",
  });

  expect(merchantSettlement(retail)).toBeNull();
  // And nothing is said about deposits on a page that has a payments card.
  expect(settlementBlock(retail)).toBeNull();
});

it("never offers it on an order with no deposit charge", () => {
  // `null`, not `0`: there is no charge to return, and guessing an amount is
  // the one thing that must not happen on a damaged ledger row.
  const order = makeOrder({ deposit_charged_usd: null });

  expect(merchantSettlement(order)).toBeNull();
  expect(settlementBlock(order)).toBe("no_charge");
});

it("never offers it on an order that is already square", () => {
  const order = makeOrder({ deposit_returned_usd: "1.070000" });

  expect(merchantSettlement(order)).toBeNull();
  expect(settlementBlock(order)).toBe("settled");
});

it("never offers it on a partly settled order, and says which state that is", () => {
  // One cent back and the button would post the full charge, which
  // `order_already_settled` refuses every time. Finishing a partial is a
  // second decision with its own amount and belongs on the merchant's page.
  const order = makeOrder({ deposit_returned_usd: "0.010000" });

  expect(merchantSettlement(order)).toBeNull();
  expect(settlementBlock(order)).toBe("partly_settled");
});

it("refuses an amount that is not a whole cent rather than rounding it", () => {
  expect(toWireAmount("1.070000")).toBe("1.07");
  expect(toWireAmount("2")).toBe("2.00");
  expect(toWireAmount("0.500000")).toBe("0.50");
  expect(toWireAmount("1.005000")).toBeNull();
  expect(toWireAmount("0.000000")).toBeNull();
  expect(merchantSettlement(makeOrder({ deposit_charged_usd: "1.005000" }))).toBeNull();
});

it("waits for a delivery that has terminally failed", () => {
  // Narrower than the plan's "any unsettled merchant order", deliberately:
  // settling a live order returns the money and stops nothing, so the drain
  // can still deliver goods the reseller has already been paid back for. The
  // gap is the API's and predates this button; a one-click way in is not
  // something to add while it is open.
  expect(merchantSettlement(makeOrder({ failure_reason: null }))).toBeNull();
  expect(settlementBlock(makeOrder({ failure_reason: null }))).toBe("still_open");

  // A stall is not an ending either — the goods are still coming.
  expect(merchantSettlement(makeOrder({ failure_reason: "fulfillment_delayed" }))).toBeNull();
  expect(settlementBlock(makeOrder({ failure_reason: "fulfillment_delayed" }))).toBe("still_open");
});

it("offers it on an order support already closed by hand", () => {
  // `order_failed` means closed with money still owed, which is exactly the
  // procedure this button shortcuts.
  expect(
    merchantSettlement(makeOrder({ status: "failed", failure_reason: "order_failed" })),
  ).not.toBeNull();
});
