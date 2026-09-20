import { describe, expect, it } from "vitest";

import { orderAmount, orderAmountValue } from "./amount";

import type { OrderAdminOut } from "./types";

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

describe("orderAmount", () => {
  it("shows a retail order's charge in its own currency", () => {
    expect(orderAmount(makeOrder())).toEqual({ value: "13438.00", currency: "UZS" });
  });

  it("shows a merchant order's deposit charge, not the order row", () => {
    // The production shape this was written for: a $1.00 Steam top-up placed
    // through /merchant/v1 debited the reseller $1.05. The order row carries
    // the face value the supplier loads; the ledger carries the price.
    const order = makeOrder({
      merchant_id: "01a0be98-0000-0000-0000-000000000000",
      merchant_title: "Reseller",
      currency: "USD",
      total_charged: "1.000000",
      deposit_charged_usd: "1.050000",
    });
    expect(orderAmount(order)).toEqual({ value: "1.050000", currency: "USD" });
  });

  it("leaves a fixed-price merchant order alone, where the two agree", () => {
    const order = makeOrder({
      merchant_id: "01a0837d-0000-0000-0000-000000000000",
      currency: "USD",
      total_charged: "0.240000",
      deposit_charged_usd: "0.240000",
    });
    expect(orderAmount(order).value).toBe("0.240000");
  });

  it("falls back to the order row when the ledger has no charge", () => {
    // Impossible on a live merchant order — the charge and the order row are
    // written in one transaction — so this covers a damaged ledger. A face
    // value beats an empty cell.
    const order = makeOrder({
      merchant_id: "01a0be98-0000-0000-0000-000000000000",
      currency: "USD",
      total_charged: "1.000000",
      deposit_charged_usd: null,
    });
    expect(orderAmount(order)).toEqual({ value: "1.000000", currency: "USD" });
  });

  it("never reads the deposit of a retail order", () => {
    // `merchant_id === null` decides it, not the presence of the field: a
    // retail order carrying a stray deposit figure must still show its own
    // charge, in its own currency.
    const order = makeOrder({ deposit_charged_usd: "9.99" });
    expect(orderAmount(order)).toEqual({ value: "13438.00", currency: "UZS" });
  });
});

describe("orderAmountValue", () => {
  it("sorts on the same figure the cell shows", () => {
    const merchant = makeOrder({
      merchant_id: "01a0be98-0000-0000-0000-000000000000",
      currency: "USD",
      total_charged: "1.000000",
      deposit_charged_usd: "1.050000",
    });
    expect(orderAmountValue(merchant)).toBeCloseTo(1.05);
    expect(orderAmountValue(makeOrder())).toBeCloseTo(13438);
  });

  it("answers 0 for an unparseable amount rather than NaN", () => {
    expect(orderAmountValue(makeOrder({ total_charged: "" }))).toBe(0);
  });
});
