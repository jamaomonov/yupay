import { describe, expect, it } from "vitest";

import { fixedTotal, formatUsd, scaledTotal, toCents } from "./money";

describe("parsing and formatting", () => {
  it("reads the decimal strings the API actually sends", () => {
    expect(toCents("0")).toBe(0n);
    expect(toCents("42.50")).toBe(4250n);
    expect(toCents("42.500000")).toBe(4250n);
    expect(toCents("104.00")).toBe(10400n);
  });

  it("always renders two decimals", () => {
    // The ledger sends "0" for an untouched account and "42.500000" for a
    // credited one. A balance that renders two ways on two screens is the bug
    // the API's own value types exist to stop.
    expect(formatUsd(0n)).toBe("0.00");
    expect(formatUsd(4250n)).toBe("42.50");
    expect(formatUsd(7n)).toBe("0.07");
  });
});

describe("order totals agree with the server", () => {
  it("a fixed denomination costs its published price", () => {
    expect(formatUsd(fixedTotal("1.07"))).toBe("1.07");
  });

  it("a thousand Stars is $16.54, not $20.00", () => {
    // The published per-unit price is $0.016537. Rounding it to the cent first
    // and multiplying gives $20.00 — a 29% markup arrived at by arithmetic.
    // One rounding, at the end, is the server's rule and has to be ours too,
    // or `expected_price` never matches and every order 422s.
    expect(formatUsd(scaledTotal("0.016537", "1000"))).toBe("16.54");
  });

  it("a hundred dollars of wallet balance is $104.00 at a 4% markup", () => {
    expect(formatUsd(scaledTotal("1.040000", "100"))).toBe("104.00");
  });

  it("rounds a fractional cent up, like the server", () => {
    // 3 × 0.016537 = 0.049611 → one cent short of five, and the merchant pays
    // the cent. Rounding down here would under-quote and the order would be
    // refused for drift.
    expect(formatUsd(scaledTotal("0.016537", "3"))).toBe("0.05");
  });

  it("handles a fractional amount", () => {
    expect(formatUsd(scaledTotal("1.040000", "7.64"))).toBe("7.95");
  });
});
