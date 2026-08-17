import { describe, expect, it } from "vitest";

import { boundToUnits, toUsd, unitAmountError, unitsPerUsd } from "./variable-amount";

/**
 * Telegram Stars is bought in stars, not dollars. The conversion has to be
 * exact in one specific way: the count the customer sees must be the count the
 * supplier is sent, or they are credited a different amount than they paid for.
 */

const STARS = 64.705882;

describe("unitsPerUsd", () => {
  it("is null for a dollar-priced SKU, which is every existing one", () => {
    expect(unitsPerUsd({ amount_unit: null, units_per_usd: null })).toBeNull();
  });

  it("ignores a rate without a unit rather than labelling the field with nothing", () => {
    expect(unitsPerUsd({ amount_unit: null, units_per_usd: "64.7" })).toBeNull();
  });

  it("refuses a zero rate instead of dividing by it", () => {
    expect(unitsPerUsd({ amount_unit: "stars", units_per_usd: "0" })).toBeNull();
  });
});

describe("toUsd", () => {
  it.each([50, 75, 137, 500, 1000, 2500, 50_000])("round-trips %i stars", (stars) => {
    expect(Math.round(toUsd(stars, STARS) * STARS)).toBe(stars);
  });
});

describe("boundToUnits", () => {
  it("rounds a minimum up so the range never promises a rejected amount", () => {
    // $0.772727 is 49.99997 stars. Showing "от 49" would offer a purchase the
    // server bounces.
    expect(boundToUnits(0.772727, STARS, "min")).toBe(50);
  });

  it("rounds a maximum down for the same reason", () => {
    expect(boundToUnits(772.7, STARS, "max")).toBe(49_998);
  });
});

describe("unitAmountError", () => {
  it("rejects a fraction — half a star does not exist", () => {
    expect(unitAmountError(50.5, 50, 1000)).toBe("precision");
  });

  it("reports below and above against the unit bounds", () => {
    expect(unitAmountError(49, 50, 1000)).toBe("below");
    expect(unitAmountError(1001, 50, 1000)).toBe("above");
  });

  it("accepts the endpoints, matching the server's closed interval", () => {
    expect(unitAmountError(50, 50, 1000)).toBeNull();
    expect(unitAmountError(1000, 50, 1000)).toBeNull();
  });
});
