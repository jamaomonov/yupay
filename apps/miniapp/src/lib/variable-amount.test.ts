import { describe, expect, test } from "vitest";

import { amountError, parseAmount } from "./variable-amount";

describe("parseAmount", () => {
  test("parses a dot decimal", () => expect(parseAmount("10.5")).toBe(10.5));
  test("parses a comma decimal", () => expect(parseAmount("10,5")).toBe(10.5));
  test("parses a whole number", () => expect(parseAmount("10")).toBe(10));
  test("trims surrounding whitespace", () => expect(parseAmount("  10  ")).toBe(10));
  test("keeps more than two decimals — amountError's job to reject", () =>
    expect(parseAmount("10.123")).toBeCloseTo(10.123));

  test("empty string is null", () => expect(parseAmount("")).toBeNull());
  test("blank string is null", () => expect(parseAmount("   ")).toBeNull());
  test("junk is null", () => expect(parseAmount("abc")).toBeNull());
  test("a leading sign is rejected", () => expect(parseAmount("-5")).toBeNull());
  test("a lone separator is rejected", () => expect(parseAmount(".")).toBeNull());
  test("a trailing separator with no digits is rejected", () =>
    expect(parseAmount("10.")).toBeNull());
  test("two decimal separators is rejected", () => expect(parseAmount("10.5.5")).toBeNull());
  test("a thousands separator is rejected", () => expect(parseAmount("1,000.5")).toBeNull());
  test("scientific notation is rejected", () => expect(parseAmount("1e5")).toBeNull());
});

describe("amountError", () => {
  const min = 1;
  const max = 300;

  test("within bounds, at most two decimals ⇒ null", () => {
    expect(amountError(10, min, max)).toBeNull();
    expect(amountError(10.5, min, max)).toBeNull();
    expect(amountError(10.12, min, max)).toBeNull();
  });
  test("below the minimum", () => expect(amountError(0.5, min, max)).toBe("below"));
  test("exactly at the minimum is fine (closed interval)", () =>
    expect(amountError(1, min, max)).toBeNull());
  test("above the maximum", () => expect(amountError(301, min, max)).toBe("above"));
  test("exactly at the maximum is fine (closed interval)", () =>
    expect(amountError(300, min, max)).toBeNull());
  test("more than two decimals", () => expect(amountError(10.123, min, max)).toBe("precision"));
  test("precision is checked before range", () =>
    expect(amountError(301.123, min, max)).toBe("precision"));
});
