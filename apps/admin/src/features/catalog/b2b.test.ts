/**
 * Pins the preview to the server's exact semantics —
 * `apps/api/src/yupay/modules/merchants/pricing.py::merchant_price` is the
 * authority: `(cost * (1 + markup/100)).quantize(0.01, ROUND_CEILING)`.
 * Several cases here are chosen precisely because `Math.ceil(x * 100) / 100`
 * over floats gets them wrong.
 */
import { describe, expect, it } from "vitest";

import { parseMarkupPct, previewB2bPrice } from "./b2b";

describe("previewB2bPrice", () => {
  it("rounds up to the cent, exactly like the server's ROUND_CEILING", () => {
    // 0.60 × 1.07 = 0.642 → up to 0.65
    expect(previewB2bPrice("0.60", "7")).toEqual({ price: "0.65", belowCost: false });
    // 1.00 × 1.075 = 1.075 → up to 1.08
    expect(previewB2bPrice("1.00", "7.5")).toEqual({ price: "1.08", belowCost: false });
  });

  it("does not invent a cent where floats would (8.20 × 1.10 is exactly 9.02)", () => {
    // In floats 8.2 * 1.1 * 100 = 902.0000000000001, so Math.ceil says 9.03.
    expect(previewB2bPrice("8.20", "10")).toEqual({ price: "9.02", belowCost: false });
    // In floats 0.07 * 100 = 7.000000000000001, so Math.ceil says 0.08.
    expect(previewB2bPrice("0.07", "0")).toEqual({ price: "0.07", belowCost: false });
  });

  it("keeps an already-exact price untouched", () => {
    expect(previewB2bPrice("0.60", "5")).toEqual({ price: "0.63", belowCost: false });
    expect(previewB2bPrice("100", "0")).toEqual({ price: "100.00", belowCost: false });
  });

  it("applies a negative markup verbatim and flags the price as below cost", () => {
    // Negative markups are legal at write time by explicit ruling — the
    // order-time margin floor is the money guard. The preview's job is to
    // make the effect visible, not to block it.
    expect(previewB2bPrice("1.00", "-50")).toEqual({ price: "0.50", belowCost: true });
    expect(previewB2bPrice("1.00", "-150")).toEqual({ price: "-0.50", belowCost: true });
    // Ceiling on a negative price goes toward zero: -0.035 → -0.03,
    // matching Decimal ROUND_CEILING.
    expect(previewB2bPrice("0.07", "-150")).toEqual({ price: "-0.03", belowCost: true });
  });

  it("accepts a comma decimal the way the money inputs do", () => {
    expect(previewB2bPrice("1,00", "7,5")).toEqual({ price: "1.08", belowCost: false });
  });

  it("returns null while either side is missing or half-typed", () => {
    expect(previewB2bPrice("", "7")).toBeNull();
    expect(previewB2bPrice("0.60", "")).toBeNull();
    expect(previewB2bPrice("0.60", "-")).toBeNull();
    expect(previewB2bPrice("abc", "7")).toBeNull();
    expect(previewB2bPrice("0.60", "7.")).toBeNull();
  });
});

describe("parseMarkupPct", () => {
  it("canonicalizes valid Numeric(5,2)-shaped input", () => {
    expect(parseMarkupPct("7")).toBe("7");
    expect(parseMarkupPct(" 7.50 ")).toBe("7.50");
    expect(parseMarkupPct("7,5")).toBe("7.5");
    expect(parseMarkupPct("-2")).toBe("-2");
    expect(parseMarkupPct("999.99")).toBe("999.99");
  });

  it("rejects anything the column cannot hold", () => {
    expect(parseMarkupPct("")).toBeNull();
    expect(parseMarkupPct("1000")).toBeNull();
    expect(parseMarkupPct("7.123")).toBeNull();
    expect(parseMarkupPct("abc")).toBeNull();
    expect(parseMarkupPct("--2")).toBeNull();
  });
});
