import { describe, expect, it } from "vitest";

import { isTopUpOrder, orderTitle, supportProduct } from "./order-display";

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

function withItems(...display: (Record<string, unknown> | null)[]): OrderOut {
  // only the fields the helpers read; a variable-amount line credits its unit price
  return {
    items: display.map((d) => ({ display: d, unit_price_usd: "11.30", qty: 1 })),
  } as unknown as OrderOut;
}

describe("supportProduct", () => {
  it("names the brand and the denomination", () => {
    const o = withItems({
      brand_name: "PUBG Mobile",
      denomination: "60 UC",
      variable_amount: false,
    });
    expect(supportProduct(o, "en")).toBe("PUBG Mobile, 60 UC");
  });

  it("names the credited amount instead of the «Любая сумма» placeholder", () => {
    const o = withItems({
      brand_name: "Steam",
      denomination: "Любая сумма",
      variable_amount: true,
    });
    expect(supportProduct(o, "en")).toBe("Steam, $11.30");
    expect(orderTitle(o, "fallback", "en")).toBe("Steam · $11.30");
  });

  it("counts the other lines and gives up without display data", () => {
    const two = withItems(
      { brand_name: "PUBG Mobile", denomination: "60 UC", variable_amount: false },
      { brand_name: "PUBG Mobile", denomination: "325 UC", variable_amount: false },
    );
    expect(supportProduct(two, "en")).toBe("PUBG Mobile, 60 UC +1");
    expect(supportProduct(withItems(null), "en")).toBeNull();
    expect(orderTitle(withItems(null), "fallback", "en")).toBe("fallback");
  });
});
