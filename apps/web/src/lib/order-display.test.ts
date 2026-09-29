import { describe, expect, it } from "vitest";

import { isTopUpOrder } from "./order-display";

import type { OrderOut } from "./orders-types";

function order(kind: string, sku = "x"): OrderOut {
  return {
    items: [{ display: { product_kind: kind, sku_code: sku }, skin_trade: null }],
  } as unknown as OrderOut; // only the fields isTopUpOrder reads
}

describe("isTopUpOrder", () => {
  it("is a top-up, not a code and not a CS2 skin seeded as one", () => {
    expect(isTopUpOrder(order("top_up"))).toBe(true);
    expect(isTopUpOrder(order("voucher"))).toBe(false);
    expect(isTopUpOrder(order("top_up", "cs2-skin"))).toBe(false);
  });
});
