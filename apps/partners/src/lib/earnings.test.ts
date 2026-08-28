import { describe, expect, it } from "vitest";

import { DEFAULTS, estimateEarnings } from "./earnings";

/**
 * The arithmetic behind the recruiting page.
 *
 * Worth testing not because multiplication is hard but because this number is
 * a promise a partner will measure us against. A defect here is discovered by
 * someone comparing their first payout to what the site told them.
 */

describe("estimateEarnings", () => {
  it("multiplies audience, conversion, orders per buyer, order value and rate", () => {
    // 10 000 people, 2% buy → 200 buyers, 2 orders each → 400 orders,
    // 10 000 so'm each at 2% → 80 000 so'm.
    expect(
      estimateEarnings({
        audience: 10_000,
        conversionPercent: 2,
        averageOrderUzs: 10_000,
        ordersPerBuyer: 2,
        commissionPercent: 2,
      }),
    ).toEqual({ buyers: 200, orders: 400, earnedUzs: 80_000 });
  });

  it("never returns a negative estimate", () => {
    const result = estimateEarnings({
      audience: -5_000,
      conversionPercent: -1,
      averageOrderUzs: -12_000,
      ordersPerBuyer: -2,
      commissionPercent: -2,
    });
    expect(result).toEqual({ buyers: 0, orders: 0, earnedUzs: 0 });
  });

  it("survives an empty or unparsed field without rendering NaN", () => {
    // A cleared number input yields NaN, and NaN so'm on a recruiting page
    // looks broken rather than empty.
    const result = estimateEarnings({
      audience: Number.NaN,
      conversionPercent: 1,
      averageOrderUzs: 12_000,
      ordersPerBuyer: 1.97,
      commissionPercent: 2,
    });
    expect(result.earnedUzs).toBe(0);
  });

  it("keeps its defaults tied to measured reality, not to a flattering number", () => {
    // These are load-bearing: 12 000 so'm is the shape of a real order here and
    // 1.97 is the measured mean orders per buyer (37% of buyers return). If a
    // future edit inflates them to recruit better, this test is the objection.
    expect(DEFAULTS.averageOrderUzs).toBe(12_000);
    expect(DEFAULTS.ordersPerBuyer).toBe(1.97);
    expect(DEFAULTS.commissionPercent).toBeLessThanOrEqual(2);
  });
});
