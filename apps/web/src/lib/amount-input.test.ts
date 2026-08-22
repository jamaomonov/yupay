import { describe, expect, test } from "vitest";

import { amountValue, groupDigits, toDigits } from "./amount-input";

describe("toDigits", () => {
  test("keeps only digits", () => {
    expect(toDigits("100 000")).toBe("100000");
    expect(toDigits("1 000 000")).toBe("1000000");
  });

  test("drops a decimal separator rather than rounding", () => {
    // Soum has no minor unit; the server refuses 10 000.5 instead of rounding
    // it, so letting one be typed only buys the customer a 422.
    expect(toDigits("10000.5")).toBe("100005");
    expect(toDigits("10 000,50")).toBe("1000050");
  });

  test("survives pasted junk", () => {
    expect(toDigits("абв")).toBe("");
    expect(toDigits("100 000 UZS")).toBe("100000");
  });
});

describe("groupDigits", () => {
  test("groups thousands so the amount is read, not counted", () => {
    expect(groupDigits("100000", "ru")).toBe(new Intl.NumberFormat("ru-RU").format(100000));
    expect(groupDigits("1000000", "ru")).toBe(new Intl.NumberFormat("ru-RU").format(1000000));
  });

  test("100 000 and 1 000 000 no longer look alike", () => {
    // The whole point: one character apart, ten times different.
    expect(groupDigits("100000", "ru")).not.toBe(groupDigits("1000000", "ru"));
  });

  test("empty stays empty, so the placeholder still shows", () => {
    expect(groupDigits("", "ru")).toBe("");
    expect(groupDigits("абв", "ru")).toBe("");
  });

  test("leading zeros are dropped — they survive a paste and lie about the value", () => {
    expect(groupDigits("007", "ru")).toBe("7");
    expect(groupDigits("0", "ru")).toBe("0");
  });

  test("groups per locale", () => {
    expect(groupDigits("100000", "en")).toBe(new Intl.NumberFormat("en-US").format(100000));
  });
});

describe("amountValue", () => {
  test("reads a grouped field back as a number", () => {
    expect(amountValue(groupDigits("250000", "ru"))).toBe(250000);
  });

  test("empty is zero, never NaN", () => {
    expect(amountValue("")).toBe(0);
    expect(amountValue("абв")).toBe(0);
  });

  test("the ceiling this field allows round-trips exactly", () => {
    expect(amountValue(groupDigits("5000000", "ru"))).toBe(5_000_000);
  });
});
