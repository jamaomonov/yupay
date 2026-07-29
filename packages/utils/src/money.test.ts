import { describe, expect, it } from "vitest";

import { formatMoney } from "./money";

describe("formatMoney", () => {
  it("formats USD with en-US locale", () => {
    expect(formatMoney("12.34", "USD", "en-US")).toMatch(/12\.34/);
  });

  it("falls back gracefully for unknown currency", () => {
    expect(formatMoney("1", "XYZ", "en-US")).toContain("XYZ");
  });

  it("formats USD with two decimals", () => {
    expect(formatMoney("10", "USD", "en-US")).toBe("$10.00");
  });

  it("formats UZS with zero decimals and grouping", () => {
    // en-US grouping keeps it locale-stable for the assertion
    const out = formatMoney("20000", "UZS", "en-US");
    expect(out).not.toMatch(/\.\d/); // no fractional part
    expect(out).toMatch(/20[,\s]?000/);
  });

  it("formats USDT as a plain amount with the ticker (not a real ISO currency)", () => {
    expect(formatMoney("12.5", "USDT", "en-US")).toBe("12.5 USDT");
  });

  it("falls back gracefully for an unknown currency", () => {
    // "ZZZ" is a well-formed but unassigned ISO 4217 code. Per the ECMA-402 spec,
    // Intl.NumberFormat only validates currency-code *syntax* (3 letters), not real-world
    // assignment, so this takes the `try` path (renders as "ZZZ 5.00") rather than our
    // `catch` fallback (which would render "5.00 ZZZ"). Assert order-agnostically: the
    // output must be non-crashing and contain both the amount and the currency code.
    const out = formatMoney("5", "ZZZ", "en-US");
    expect(out).toContain("ZZZ");
    expect(out).toMatch(/5(\.00)?/);
  });
});
