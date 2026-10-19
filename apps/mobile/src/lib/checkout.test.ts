import { describe, expect, it } from "vitest";

import { checkBlocks, isEmail, orderBody, orderFingerprint, returnUrl, stageOf } from "./checkout";

describe("checkout", () => {
  it("accepts an address and refuses a half-typed one", () => {
    expect(isEmail(" a@b.uz ")).toBe(true);
    expect(isEmail("a@b")).toBe(false);
  });

  it("builds an order with trimmed fields and the receipt address, or none", () => {
    expect(orderBody({ skuId: "s1", fields: { player_id: " 123 " }, email: " A@B.uz" })).toEqual({
      currency: "UZS",
      items: [{ sku_id: "s1", qty: 1, fulfillment_data: { player_id: "123" } }],
      delivery_email: "a@b.uz",
    });
    expect(orderBody({ skuId: "s1", fields: {}, email: " " })).not.toHaveProperty("delivery_email");
  });

  it("keeps the fingerprint across cosmetic edits and changes it with the order", () => {
    const base = { skuId: "s1", fields: { player_id: "123" }, email: "a@b.uz" };
    expect(orderFingerprint({ ...base, email: " A@b.uz " })).toBe(orderFingerprint(base));
    expect(orderFingerprint({ ...base, fields: { player_id: "124" } })).not.toBe(
      orderFingerprint(base),
    );
  });

  it("returns to the storefront order page in the buyer's language", () => {
    expect(returnUrl("https://yupay.uz/", "ru", "o1")).toBe("https://yupay.uz/orders/o1");
    expect(returnUrl("https://yupay.uz", "uz", "o1")).toBe("https://yupay.uz/uz/orders/o1");
  });

  it("blocks paying until the check has answered, and on «not found» only", () => {
    expect(checkBlocks(null)).toBe(true);
    expect(checkBlocks({ status: "invalid" })).toBe(true);
    expect(checkBlocks({ status: "error" })).toBe(false);
    expect(checkBlocks({ status: "valid", name: "x" })).toBe(false);
  });

  it("folds the API statuses into stages", () => {
    expect(stageOf("pending_payment")).toBe("awaiting");
    expect(stageOf("fulfilling")).toBe("working");
    expect(stageOf("delivered")).toBe("done");
    expect(stageOf("partially_refunded")).toBe("refunded");
    expect(stageOf("expired")).toBe("closed");
  });
});
