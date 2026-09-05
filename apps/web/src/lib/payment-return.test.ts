/**
 * The order-page payment return: what the checkout panels put in the URL when
 * they hand the buyer to the order page, and what the order page reads back
 * out of it.
 *
 * Pinned because the whole fix hangs on these four properties: the guest's
 * `?email=` survives the flag being added (without it the order page cannot
 * fetch anything and the guest loses their order), the flag is stripped
 * exactly once so a buyer returning from the bank app is not thrown back into
 * it, and only a genuinely still-payable payment yields a URL to open at all.
 */
import { describe, expect, it } from "vitest";

import {
  AUTO_OPEN_PARAM,
  hrefWithoutAutoOpen,
  isAutoOpenRequested,
  resumableIntentUrl,
  withAutoOpen,
} from "./payment-return";

import type { PaymentOut } from "./orders-types";

function payment(overrides: Partial<PaymentOut> = {}): PaymentOut {
  return {
    id: "pay-1",
    order_id: "order-1",
    provider: "uzum",
    status: "pending",
    amount: "45000.00",
    currency: "UZS",
    intent_url: "https://uzumbank.uz/open-service?id=1",
    external_id: "ext-1",
    ...overrides,
  };
}

describe("withAutoOpen", () => {
  it("adds the one-shot flag to a plain order href", () => {
    expect(withAutoOpen("/orders/order-1")).toBe(`/orders/order-1?${AUTO_OPEN_PARAM}=1`);
  });

  it("keeps the guest's email — the order page cannot load without it", () => {
    expect(withAutoOpen("/orders/order-1?email=guest%40example.com")).toBe(
      `/orders/order-1?email=guest%40example.com&${AUTO_OPEN_PARAM}=1`,
    );
  });

  it("keeps a locale prefix", () => {
    expect(withAutoOpen("/en/orders/order-1")).toBe(`/en/orders/order-1?${AUTO_OPEN_PARAM}=1`);
  });

  it("never doubles the flag when one is somehow already there", () => {
    expect(withAutoOpen(`/orders/order-1?${AUTO_OPEN_PARAM}=1`)).toBe(
      `/orders/order-1?${AUTO_OPEN_PARAM}=1`,
    );
  });
});

describe("isAutoOpenRequested", () => {
  it("is true only for the exact flag value", () => {
    expect(isAutoOpenRequested(new URLSearchParams(`${AUTO_OPEN_PARAM}=1`))).toBe(true);
    expect(isAutoOpenRequested(new URLSearchParams(`${AUTO_OPEN_PARAM}=0`))).toBe(false);
    expect(isAutoOpenRequested(new URLSearchParams("email=guest%40example.com"))).toBe(false);
    expect(isAutoOpenRequested(new URLSearchParams())).toBe(false);
  });
});

describe("hrefWithoutAutoOpen", () => {
  it("strips the flag and nothing else", () => {
    expect(
      hrefWithoutAutoOpen(
        "/orders/order-1",
        new URLSearchParams(`email=guest%40example.com&${AUTO_OPEN_PARAM}=1`),
      ),
    ).toBe("/orders/order-1?email=guest%40example.com");
  });

  it("leaves no trailing question mark when the flag was the only param", () => {
    expect(
      hrefWithoutAutoOpen("/orders/order-1", new URLSearchParams(`${AUTO_OPEN_PARAM}=1`)),
    ).toBe("/orders/order-1");
  });
});

describe("resumableIntentUrl", () => {
  it("yields the acquirer URL for a payment still awaiting the buyer", () => {
    expect(resumableIntentUrl(payment({ status: "pending" }))).toBe(
      "https://uzumbank.uz/open-service?id=1",
    );
    expect(resumableIntentUrl(payment({ status: "requires_action" }))).toBe(
      "https://uzumbank.uz/open-service?id=1",
    );
  });

  it("yields nothing for a payment that is over", () => {
    for (const status of ["succeeded", "failed", "cancelled", "refunded", "partially_refunded"]) {
      expect(resumableIntentUrl(payment({ status }))).toBeNull();
    }
  });

  it("yields nothing for a wallet payment, which has no page to open", () => {
    // `WalletGateway` settles inside `create_intent` — it never hands back a URL.
    expect(resumableIntentUrl(payment({ provider: "wallet", intent_url: null }))).toBeNull();
  });

  it("yields nothing when there is no payment at all", () => {
    expect(resumableIntentUrl(undefined)).toBeNull();
  });
});
