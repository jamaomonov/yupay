import { expect, it } from "vitest";

import { orderFingerprint } from "./gift-checkout";

/**
 * `orderFingerprint` is the correctness-by-construction half of the sticky
 * order key (see `GiftPurchasePanel`): the panel mints a new
 * `Idempotency-Key` exactly when this string changes, so every field that
 * determines the order's contents on `POST /orders` — `sku_id`, `qty`,
 * `amount_usd`, every `fulfillment_data` field, and the delivery email —
 * must move the fingerprint, and nothing else (payment method, locale,
 * game name) may. These are unit tests, not component tests, on purpose:
 * the reset rule is the one thing in this feature a money bug can hide in,
 * so it gets to be tested directly rather than only through the panel.
 */

function baseInput() {
  return {
    skuId: "sku-1",
    amountUsd: "1.10",
    fulfillmentData: {
      app_id: 588650,
      package_id: 1,
      region: "UZ",
      invite_url: "https://steamcommunity.com/profiles/76561198000000000",
    },
    email: "buyer@example.com",
  };
}

it("is stable for the exact same order contents", () => {
  expect(orderFingerprint(baseInput())).toBe(orderFingerprint(baseInput()));
});

it("changes when sku_id changes", () => {
  const a = orderFingerprint(baseInput());
  const b = orderFingerprint({ ...baseInput(), skuId: "sku-2" });
  expect(a).not.toBe(b);
});

it("changes when amount_usd changes", () => {
  const a = orderFingerprint(baseInput());
  const b = orderFingerprint({ ...baseInput(), amountUsd: "1.30" });
  expect(a).not.toBe(b);
});

it("changes when fulfillment_data.app_id changes", () => {
  const base = baseInput();
  const a = orderFingerprint(base);
  const b = orderFingerprint({
    ...base,
    fulfillmentData: { ...base.fulfillmentData, app_id: 12345 },
  });
  expect(a).not.toBe(b);
});

it("changes when fulfillment_data.package_id changes (edition switch)", () => {
  const base = baseInput();
  const a = orderFingerprint(base);
  const b = orderFingerprint({
    ...base,
    fulfillmentData: { ...base.fulfillmentData, package_id: 2 },
  });
  expect(a).not.toBe(b);
});

it("changes when fulfillment_data.region changes", () => {
  const base = baseInput();
  const a = orderFingerprint(base);
  const b = orderFingerprint({
    ...base,
    fulfillmentData: { ...base.fulfillmentData, region: "RU" },
  });
  expect(a).not.toBe(b);
});

it("changes when fulfillment_data.invite_url changes (recipient switch)", () => {
  const base = baseInput();
  const a = orderFingerprint(base);
  const b = orderFingerprint({
    ...base,
    fulfillmentData: {
      ...base.fulfillmentData,
      invite_url: "https://steamcommunity.com/profiles/76561198000000001",
    },
  });
  expect(a).not.toBe(b);
});

it("changes when the delivery email changes", () => {
  const a = orderFingerprint(baseInput());
  const b = orderFingerprint({ ...baseInput(), email: "someone-else@example.com" });
  expect(a).not.toBe(b);
});
