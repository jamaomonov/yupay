import type { SkuOut } from "@yupay/api-client/types";
import { describe, expect, it } from "vitest";

import {
  amountRule,
  checkCount,
  countLabel,
  lineOf,
  parseCount,
  priceOf,
  skuKind,
  type AmountRule,
} from "./amount";
import { orderBody } from "./checkout";

function sku(extra: Partial<SkuOut>): SkuOut {
  return {
    id: "s",
    sku_code: "x",
    denomination: null,
    region: "GLOBAL",
    image_url: null,
    price_usd: "1.000000",
    display_price: { amount: "12773.000000", currency: "UZS", source: "fx" },
    ...extra,
  } as SkuOut; // test fixture: only the fields the rules read
}

const steam = sku({
  variable_amount: true,
  min_amount_usd: "1.000000",
  max_amount_usd: "500.000000",
});
const stars = sku({
  amount_unit: "Stars",
  min_qty: 50,
  max_qty: 15000,
  display_price: { amount: "207.260000", currency: "UZS", source: "fx" },
});

describe("amount", () => {
  it("tells a tile from a typed amount", () => {
    expect(skuKind(sku({}))).toBe("fixed");
    expect(skuKind(steam)).toBe("usd");
    expect(skuKind(stars)).toBe("units");
    expect(amountRule(sku({}))).toBeNull();
  });

  it("bounds Steam in whole dollars and Stars in units", () => {
    const usd = amountRule(steam) as AmountRule;
    expect([usd.min, usd.max, usd.unit]).toEqual([1, 500, "$"]);
    expect(usd.placeholder).toBe(10);
    const units = amountRule(stars) as AmountRule;
    expect([units.min, units.max, units.unit]).toEqual([50, 15000, "Stars"]);
    expect(units.placeholder).toBe(50);
  });

  it("reads digits only and checks the bounds", () => {
    const rule = amountRule(stars) as AmountRule;
    expect(parseCount("1 000")).toBe(1000);
    expect(parseCount("abc")).toBe(0);
    expect(checkCount(0, rule)).toBe("empty");
    expect(checkCount(49, rule)).toBe("low");
    expect(checkCount(15001, rule)).toBe("high");
    expect(checkCount(500, rule)).toBe("ok");
  });

  it("prices in whole soʻm and labels the line", () => {
    const rule = amountRule(stars) as AmountRule;
    expect(priceOf(500, rule)).toBe(103630);
    expect(countLabel(1500, rule)).toBe("1 500 Stars");
    expect(countLabel(25, amountRule(steam) as AmountRule)).toBe("$25");
    expect(priceOf(25, amountRule(steam) as AmountRule)).toBe(319325);
  });

  it("sends dollars as amount_usd and units as qty", () => {
    const usd = lineOf(25, amountRule(steam) as AmountRule);
    const units = lineOf(500, amountRule(stars) as AmountRule);
    expect(orderBody({ skuId: "s", fields: {}, ...usd }).items[0]).toEqual({
      sku_id: "s",
      qty: 1,
      amount_usd: "25.00",
      fulfillment_data: {},
    });
    expect(orderBody({ skuId: "s", fields: {}, ...units }).items[0]).toEqual({
      sku_id: "s",
      qty: 500,
      fulfillment_data: {},
    });
  });
});
