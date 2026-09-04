import { afterEach, describe, expect, test } from "vitest";

import { currencySymbol, formatMoney } from "./currency";

import { setActiveLocale } from "@/lib/i18n/core";

/**
 * `Intl.NumberFormat(style:"currency", currency:"UZS")` renders the *ISO
 * code*, not a word, and gets the placement wrong: "165 000 UZS" in ru
 * (Latin letters in a Cyrillic sentence) and "UZS 165,000" in en (the code
 * leads the number). Only `uz` got a real word ("soʻm") for free — this is
 * the storefront-wide fix (2026-09-04 review). `apps/web/src/lib/seo.ts`'s
 * `formatUzs` carries the identical mapping.
 */

afterEach(() => {
  setActiveLocale("ru");
});

/** The grouping separator `Intl` uses for ru/uz is U+00A0 (NBSP), not a
 *  plain space — normalize before comparing against a plain-space literal. */
function collapseNbsp(s: string): string {
  return s.replace(/\u00a0/g, " ");
}

describe("formatMoney", () => {
  test("renders a real ru word for UZS, trailing the number", () => {
    setActiveLocale("ru");
    expect(collapseNbsp(formatMoney(165_000, "UZS"))).toBe("165 000 сум");
  });

  test("renders a real uz word for UZS, trailing the number", () => {
    setActiveLocale("uz");
    expect(collapseNbsp(formatMoney(165_000, "UZS"))).toBe("165 000 soʻm");
  });

  test("renders UZS trailing the number for en, not leading it", () => {
    setActiveLocale("en");
    expect(collapseNbsp(formatMoney(165_000, "UZS"))).toBe("165,000 UZS");
  });

  test("never leaves a bare Latin ISO code sitting in the ru output", () => {
    setActiveLocale("ru");
    const out = formatMoney(165_000, "UZS");
    expect(out).not.toMatch(/UZS/);
    expect(out.endsWith("сум")).toBe(true);
  });

  test("still formats USD/USDT the same way (unaffected by the UZS fix)", () => {
    setActiveLocale("ru");
    expect(formatMoney(12.99, "USD")).toContain("12");
    expect(formatMoney(25, "USDT")).toContain("USDT");
  });
});

describe("currencySymbol", () => {
  test("agrees with formatMoney's UZS word per locale", () => {
    for (const locale of ["ru", "en", "uz"] as const) {
      setActiveLocale(locale);
      const wordFromFormatMoney = formatMoney(1, "UZS").split(/[ ]/).pop();
      expect(currencySymbol("UZS", locale)).toBe(wordFromFormatMoney);
    }
  });

  test("keeps the other three currencies locale-invariant", () => {
    expect(currencySymbol("USD", "ru")).toBe("$");
    expect(currencySymbol("RUB", "ru")).toBe("₽");
    expect(currencySymbol("USDT", "ru")).toBe("USDT");
  });

  /**
   * `currencySymbol`'s UZS word comes from `@yupay/utils`'s `uzsWord`, which
   * normalizes the locale (`locale.slice(0, 2).toLowerCase()`) — a
   * region-qualified tag must resolve the same as its bare form. Nothing in
   * this app passes a region-qualified locale today (`getActiveLocale()`
   * only ever yields "ru"/"en"/"uz"), but this pins the behavior so a
   * reintroduced app-local copy can't silently regress to an exact-match
   * comparison again.
   */
  test("normalizes a region-qualified locale the same as its bare form", () => {
    expect(currencySymbol("UZS", "ru-RU")).toBe("сум");
    expect(currencySymbol("UZS", "ru-RU")).toBe(currencySymbol("UZS", "ru"));
    expect(currencySymbol("UZS", "uz-UZ")).toBe(currencySymbol("UZS", "uz"));
  });
});
