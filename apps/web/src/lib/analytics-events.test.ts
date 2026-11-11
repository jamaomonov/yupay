// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";

import {
  addPaymentInfoEvent,
  beginCheckoutEvent,
  LIST_ITEMS_CAP,
  playerCheckEvent,
  pushAnalyticsEvent,
  selectItemEvent,
  trackOrderEvent,
  viewItemEvent,
  viewItemListEvent,
} from "./analytics-events";

import type { SkuOut } from "@/lib/catalog";
import type { OrderOut } from "@/lib/orders-types";

function order(over: Partial<OrderOut> = {}): OrderOut {
  return {
    id: "ord-1",
    status: "awaiting_payment",
    currency: "UZS",
    total_usd: "10.00",
    total_charged: "127000",
    payment_provider: null,
    fx_snapshot_id: null,
    expires_at: "2026-10-21T12:10:00Z",
    created_at: "2026-10-21T11:00:00Z",
    paid_at: null,
    fulfilled_at: null,
    delivered_at: null,
    cancelled_at: null,
    items: [
      {
        id: "item-1",
        sku_id: "sku-1",
        qty: 2,
        unit_price_usd: "5.00",
        // A delivery target rides on the line; it must never reach an event.
        fulfillment_data: { player_id: "123456789", email: "a@b.uz" },
        display: {
          brand_slug: "pubg-mobile",
          brand_name: "PUBG Mobile",
          product_name: "UC",
          sku_code: "pubg-uc-60",
        },
      } as unknown as OrderOut["items"][number], // only the fields the events read
    ],
    ...over,
  };
}

function sku(over: Partial<SkuOut> = {}): SkuOut {
  return {
    id: "sku-1",
    sku_code: "pubg-uc-60",
    denomination: "60 UC",
    region: null,
    image_url: null,
    price_usd: "0.99",
    display_price: { amount: "12609", currency: "UZS", source: "fx" },
    ...over,
  };
}

beforeEach(() => {
  delete window.dataLayer;
});

describe("pushAnalyticsEvent", () => {
  it("clears ecommerce before an ecommerce event", () => {
    expect(pushAnalyticsEvent(viewItemEvent({ slug: "steam", name: "Steam" }))).toBe(true);
    expect(window.dataLayer).toEqual([
      { ecommerce: null },
      {
        event: "view_item",
        ecommerce: { items: [{ item_id: "steam", item_name: "Steam", item_brand: "steam" }] },
      },
    ]);
  });

  it("pushes a custom event without clearing ecommerce", () => {
    pushAnalyticsEvent(playerCheckEvent("invalid", "mlbb"));
    expect(window.dataLayer).toEqual([
      { event: "player_check", result: "invalid", item_brand: "mlbb" },
    ]);
  });

  it("ignores null and never throws", () => {
    expect(pushAnalyticsEvent(null)).toBe(false);
    Object.defineProperty(window, "dataLayer", {
      configurable: true,
      get: () => {
        throw new Error("blocked");
      },
    });
    expect(pushAnalyticsEvent(playerCheckEvent("valid", "mlbb"))).toBe(false);
    Reflect.deleteProperty(window, "dataLayer");
  });
});

describe("viewItemListEvent", () => {
  it("caps the list and indexes the brands", () => {
    const brands = Array.from({ length: 70 }, (_, i) => ({ slug: `b${String(i)}`, name: "B" }));
    const event = viewItemListEvent("all", "Все", brands);
    expect(event?.ecommerce.items).toHaveLength(LIST_ITEMS_CAP);
    expect(event?.ecommerce.items[1]).toEqual({
      item_id: "b1",
      item_name: "B",
      item_brand: "b1",
      index: 1,
    });
    expect(event?.ecommerce.item_list_id).toBe("all");
  });

  it("sends nothing for an empty list", () => {
    expect(viewItemListEvent("all", "Все", [])).toBeNull();
  });
});

describe("selectItemEvent", () => {
  it("prices a fixed pack in the displayed currency", () => {
    expect(selectItemEvent(sku(), { name: "UC" }, "pubg-mobile", true)).toEqual({
      event: "select_item",
      ecommerce: {
        currency: "UZS",
        value: 12609,
        items: [
          {
            item_id: "pubg-uc-60",
            item_name: "UC",
            item_brand: "pubg-mobile",
            item_variant: "60 UC",
            quantity: 1,
            price: 12609,
          },
        ],
      },
    });
  });

  it("falls back to the USD price without a display price", () => {
    const event = selectItemEvent(sku({ display_price: null }), { name: "UC" }, "p", true);
    expect(event.ecommerce).toMatchObject({ currency: "USD", value: 0.99 });
  });

  it("leaves a typed-amount SKU unpriced", () => {
    const event = selectItemEvent(sku({ variable_amount: true }), { name: "Steam" }, "s", false);
    expect(event.ecommerce).not.toHaveProperty("value");
    expect(event.ecommerce.items[0]).not.toHaveProperty("price");
  });
});

describe("order events", () => {
  it("begin_checkout carries value, currency and lines — no transaction id, no PII", () => {
    const event = beginCheckoutEvent(order());
    expect(event).toEqual({
      event: "begin_checkout",
      ecommerce: {
        currency: "UZS",
        value: 127000,
        items: [
          {
            item_id: "pubg-uc-60",
            item_name: "UC",
            item_brand: "pubg-mobile",
            price: 63500,
            quantity: 2,
          },
        ],
      },
    });
    const json = JSON.stringify(event);
    expect(json).not.toContain("123456789");
    expect(json).not.toContain("a@b.uz");
    expect(json).not.toContain("transaction_id");
  });

  it("add_payment_info names the provider", () => {
    expect(addPaymentInfoEvent(order(), "click")?.ecommerce).toMatchObject({
      payment_type: "click",
      value: 127000,
      currency: "UZS",
    });
  });

  it("skips an order that charges nothing", () => {
    expect(beginCheckoutEvent(order({ total_charged: "0" }))).toBeNull();
    expect(addPaymentInfoEvent(order({ total_charged: "x" }), "payme")).toBeNull();
  });

  it("trackOrderEvent swallows a response missing its lines", () => {
    const partial = { id: "ord-2", total_charged: "5", currency: "UZS" } as unknown as OrderOut;
    expect(() => {
      trackOrderEvent(beginCheckoutEvent, partial);
    }).not.toThrow();
    expect(window.dataLayer ?? []).toEqual([]);
  });
});
