import { describe, expect, test } from "vitest";

import { formatMoney, formatMoneyValue, groupAmountInput, ungroupAmountInput } from "./money";

// ru-RU's Intl grouping separator is U+00A0 (NBSP), not a plain space.
const NBSP = " ";

describe("formatMoneyValue", () => {
  test("rounds zero-decimal currencies (UZS/RUB) to whole units", () => {
    expect(formatMoneyValue("12919.969152", "UZS")).toBe(`12${NBSP}920`);
    expect(formatMoneyValue("10272.51", "RUB")).toBe(`10${NBSP}273`);
    expect(formatMoneyValue("5000.000000", "UZS")).toBe(`5${NBSP}000`);
  });

  test("keeps 2 decimals for USD/USDT", () => {
    expect(formatMoneyValue("1.000000", "USD")).toBe("1,00");
    expect(formatMoneyValue("12919.969152", "USDT")).toBe(`12${NBSP}919,97`);
  });

  test("is case-insensitive on the currency code", () => {
    expect(formatMoneyValue("100", "uzs")).toBe("100");
  });

  test("falls back to 2 decimals for an unknown currency", () => {
    expect(formatMoneyValue("1.005", "EUR")).toBe("1,01");
  });

  test("accepts a number directly (pre-summed amounts)", () => {
    expect(formatMoneyValue(12920, "UZS")).toBe(`12${NBSP}920`);
  });

  test("degrades gracefully on a non-numeric string instead of throwing", () => {
    expect(formatMoneyValue("not-a-number", "UZS")).toBe("not-a-number");
  });
});

describe("formatMoney", () => {
  test("suffixes the formatted value with the currency code", () => {
    expect(formatMoney("12919.969152", "UZS")).toBe(`12${NBSP}920 UZS`);
    expect(formatMoney("1.000000", "USD")).toBe("1,00 USD");
  });
});

describe("groupAmountInput", () => {
  test("groups the integer part in threes, same separator as formatMoneyValue", () => {
    expect(groupAmountInput("12000000")).toBe(`12${NBSP}000${NBSP}000`);
    expect(groupAmountInput("1000")).toBe(`1${NBSP}000`);
  });

  test("leaves amounts under 1000 alone", () => {
    expect(groupAmountInput("500")).toBe("500");
  });

  test("passes the decimal separator and fractional digits through untouched", () => {
    expect(groupAmountInput("1200000.5")).toBe(`1${NBSP}200${NBSP}000.5`);
    expect(groupAmountInput("1200000,5")).toBe(`1${NBSP}200${NBSP}000,5`);
  });

  test("handles a mid-typing state — bare sign, trailing separator, empty", () => {
    expect(groupAmountInput("-")).toBe("-");
    expect(groupAmountInput("12000000.")).toBe(`12${NBSP}000${NBSP}000.`);
    expect(groupAmountInput("")).toBe("");
  });

  test("groups the negative sign's amount too", () => {
    expect(groupAmountInput("-350000")).toBe(`-350${NBSP}000`);
  });
});

describe("ungroupAmountInput", () => {
  test("strips the grouping separator back out", () => {
    expect(ungroupAmountInput(`12${NBSP}000${NBSP}000`)).toBe("12000000");
  });

  test("is the exact inverse of groupAmountInput for canonical amounts", () => {
    for (const raw of ["12000000", "-350000", "1200000.5", "500", ""]) {
      expect(ungroupAmountInput(groupAmountInput(raw))).toBe(raw);
    }
  });
});
