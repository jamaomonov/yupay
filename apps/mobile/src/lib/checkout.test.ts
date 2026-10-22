import { describe, expect, it } from "vitest";

import {
  checkBlocks,
  isEmail,
  orderBody,
  orderFingerprint,
  returnUrl,
  stageOf,
  stageTone,
} from "./checkout";

describe("checkout", () => {
  it("accepts an address and refuses a half-typed one", () => {
    expect(isEmail(" a@b.uz ")).toBe(true);
    expect(isEmail("a@b")).toBe(false);
  });

  it("builds an order with trimmed fields", () => {
    expect(orderBody({ skuId: "s1", fields: { player_id: " 123 " } })).toEqual({
      currency: "UZS",
      items: [{ sku_id: "s1", qty: 1, fulfillment_data: { player_id: "123" } }],
    });
  });

  it("keeps the fingerprint across cosmetic edits and changes it with the order", () => {
    const base = { skuId: "s1", fields: { player_id: "123" } };
    expect(orderFingerprint({ ...base, fields: { player_id: " 123 " } })).toBe(
      orderFingerprint(base),
    );
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

  it("colours a stage: done green, waiting amber, failed red, the rest grey", () => {
    expect(stageTone(stageOf("delivered"))).toBe("ok");
    expect(stageTone(stageOf("pending_payment"))).toBe("warn");
    expect(stageTone(stageOf("fulfilling"))).toBe("warn");
    expect(stageTone(stageOf("failed"))).toBe("danger");
    expect(stageTone(stageOf("refunded"))).toBe("mute");
    expect(stageTone(stageOf("cancelled"))).toBe("mute");
  });
});
