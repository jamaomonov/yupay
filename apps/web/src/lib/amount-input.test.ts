import { describe, expect, test } from "vitest";

import {
  amountValue,
  caretAfterDigits,
  digitsBeforeCaret,
  groupDigits,
  pastedDigits,
  toDigits,
} from "./amount-input";

describe("toDigits", () => {
  test("keeps only digits", () => {
    expect(toDigits("100 000")).toBe("100000");
    expect(toDigits("1 000 000")).toBe("1000000");
  });

  test("typing never guesses at a fraction", () => {
    // In `en` the field's own group separator is a comma, so "250,000" minus
    // one character is "250,00" — indistinguishable from a decimal by string
    // alone. A version that guessed turned one Backspace into a thousandfold
    // cut, silently, on a money field.
    expect(toDigits("250,00")).toBe("25000");
    expect(toDigits("1,000,00")).toBe("100000");
  });

  test("a Backspace through the grouping deletes one digit, in every locale", () => {
    for (const locale of ["ru", "en", "uz"]) {
      const shown = groupDigits("250000", locale);
      // What the browser hands `onChange` after one Backspace at the end.
      expect(toDigits(shown.slice(0, -1))).toBe("25000");
    }
  });

  test("grouping survives, whichever locale emitted it", () => {
    expect(toDigits("1,000,000")).toBe("1000000");
    // A narrow no-break space is what `Intl` actually emits for ru-RU.
    expect(toDigits(new Intl.NumberFormat("ru-RU").format(250000))).toBe("250000");
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

describe("pastedDigits", () => {
  test("drops the fraction an invoice puts on the clipboard", () => {
    // "50000.00" read as digits is 5 000 000 — a hundredfold inflation that
    // lands exactly on the ceiling and passes every bound check in silence.
    // Most software shows two decimals whether or not the currency has them.
    expect(pastedDigits("50000.00")).toBe("50000");
    expect(pastedDigits("10 000,50")).toBe("10000");
  });

  test("keeps grouping, whichever locale the customer copied from", () => {
    // A Russian customer can perfectly well paste an English-formatted number.
    expect(pastedDigits("1,000,000")).toBe("1000000");
    expect(pastedDigits("1 000 000")).toBe("1000000");
  });

  test("junk pastes as nothing", () => {
    expect(pastedDigits("абв")).toBe("");
  });
});

describe("caret preservation", () => {
  test("counts the digits left of the caret, not the offset", () => {
    // "1 923 456" with the caret at 2 has one digit behind it — the separators
    // move as the number grows, so the offset itself cannot be reused.
    expect(digitsBeforeCaret("1 923 456", 2)).toBe(1);
    // slice(0, 5) is "1 923" — four digits, not three.
    expect(digitsBeforeCaret("1 923 456", 5)).toBe(4);
  });

  test("puts the caret back beside the digit that was being edited", () => {
    // Typing a digit at offset 1 of "123 456" gives digits "1923456", which
    // regroups to "1 923 456"; the caret belongs after the 2nd digit, not at
    // the end where the rewrite would otherwise leave it.
    const regrouped = groupDigits("1923456", "ru");
    expect(caretAfterDigits(regrouped, 2)).toBe(regrouped.indexOf("9") + 1);
  });

  test("start of field stays at the start", () => {
    expect(caretAfterDigits(groupDigits("250000", "ru"), 0)).toBe(0);
  });

  test("past the end clamps to the end", () => {
    const s = groupDigits("250000", "ru");
    expect(caretAfterDigits(s, 99)).toBe(s.length);
  });
});
