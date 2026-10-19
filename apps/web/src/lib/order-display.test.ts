import { describe, expect, it } from "vitest";

import { isTopUpOrder, supportProduct } from "./order-display";

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
  return { items: display.map((d) => ({ display: d })) } as unknown as OrderOut; // only display is read
}

describe("supportProduct", () => {
  it("names the brand and the denomination", () => {
    const o = withItems({
      brand_name: "PUBG Mobile",
      denomination: "60 UC",
      variable_amount: false,
    });
    expect(supportProduct(o)).toBe("PUBG Mobile, 60 UC");
  });

  it("drops the placeholder denomination of a variable amount", () => {
    const o = withItems({
      brand_name: "Steam",
      denomination: "Любая сумма",
      variable_amount: true,
    });
    expect(supportProduct(o)).toBe("Steam");
  });

  it("counts the other lines and gives up without display data", () => {
    const two = withItems(
      { brand_name: "PUBG Mobile", denomination: "60 UC", variable_amount: false },
      { brand_name: "PUBG Mobile", denomination: "325 UC", variable_amount: false },
    );
    expect(supportProduct(two)).toBe("PUBG Mobile, 60 UC +1");
    expect(supportProduct(withItems(null))).toBeNull();
  });
});
