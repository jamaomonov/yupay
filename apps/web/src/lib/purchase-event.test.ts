// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";

import { purchaseEventFor, sendPurchaseOnce } from "./purchase-event";

import type { OrderOut } from "@/lib/orders-types";

const NOW = Date.parse("2026-10-21T12:00:00Z");

function order(over: Partial<OrderOut> = {}): OrderOut {
  return {
    id: "ord-1",
    status: "delivered",
    currency: "UZS",
    total_usd: "10.00",
    total_charged: "127000",
    payment_provider: "click",
    fx_snapshot_id: null,
    expires_at: "2026-10-21T12:10:00Z",
    created_at: "2026-10-21T11:00:00Z",
    paid_at: "2026-10-21T11:01:00Z",
    fulfilled_at: null,
    delivered_at: null,
    cancelled_at: null,
    items: [
      {
        id: "item-1",
        sku_id: "sku-1",
        qty: 2,
        unit_price_usd: "5.00",
        display: {
          brand_slug: "steam",
          brand_name: "Steam",
          product_name: "Steam Wallet",
          sku_code: "steam-wallet-usd",
        },
      } as OrderOut["items"][number], // only the fields the event reads
    ],
    ...over,
  };
}

describe("purchaseEventFor", () => {
  it("carries the charged total and lines in the order currency", () => {
    const event = purchaseEventFor(order(), NOW);
    expect(event?.ecommerce).toEqual({
      transaction_id: "ord-1",
      value: 127000,
      currency: "UZS",
      items: [
        {
          item_id: "steam-wallet-usd",
          item_name: "Steam Wallet",
          item_brand: "steam",
          price: 63500,
          quantity: 2,
        },
      ],
    });
  });

  it("skips unpaid orders, wallet top-ups and old revisits", () => {
    expect(purchaseEventFor(order({ paid_at: null }), NOW)).toBeNull();
    expect(purchaseEventFor(order({ purpose: "wallet_topup" }), NOW)).toBeNull();
    expect(purchaseEventFor(order({ paid_at: "2026-10-19T11:00:00Z" }), NOW)).toBeNull();
  });
});

describe("sendPurchaseOnce", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.dataLayer = [];
  });

  it("pushes the event once per order", () => {
    expect(sendPurchaseOnce(order(), NOW)).toBe(true);
    expect(sendPurchaseOnce(order(), NOW)).toBe(false);
    expect(window.dataLayer).toHaveLength(2);
    expect(window.dataLayer?.[1]).toMatchObject({ event: "purchase" });
  });
});
