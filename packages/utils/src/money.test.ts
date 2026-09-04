import { describe, expect, it } from "vitest";

import { formatMoney, uzsWord } from "./money";

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

/** `Intl`'s grouping separator for ru/uz is U+00A0 (NBSP), not a plain space
 *  — normalize before comparing against a plain-space literal (mirrors
 *  apps/miniapp/src/lib/currency.test.ts). */
function collapseNbsp(s: string): string {
  return s.replace(/\u00a0/g, " ");
}

/**
 * `Intl`'s `style:"currency"` prints the bare ISO code for UZS — "1 250 000
 * UZS" in ru (Latin letters in a Cyrillic sentence), "UZS 1,250,000" in en
 * (the code even leads the number) — instead of the word every other soum
 * price in the storefront uses (`apps/web/src/lib/seo.ts::formatUzs`,
 * `apps/miniapp/src/lib/currency.ts::formatMoney`). This formatter is the
 * shared one behind order-confirmation and order-history
 * (`OrderSummary.tsx`, `OrderCard.tsx`) — the single most-viewed "how much
 * did I just pay" screen — and was the last of the four sites still
 * carrying the defect (2026-09-04 review, task C1b).
 */
describe("formatMoney — UZS word", () => {
  it("renders a real ru word for UZS, trailing the number", () => {
    expect(collapseNbsp(formatMoney("1250000", "UZS", "ru-RU"))).toBe("1 250 000 сум");
  });

  it("renders a real uz word for UZS, trailing the number", () => {
    expect(collapseNbsp(formatMoney("1250000", "UZS", "uz-UZ"))).toBe("1 250 000 soʻm");
  });

  it("renders UZS trailing the number for en, not leading it", () => {
    expect(formatMoney("1250000", "UZS", "en-US")).toBe("1,250,000 UZS");
  });

  // `OrderSummary.tsx` / `OrderCard.tsx` call this with next-intl's
  // `useLocale()`, which yields the short code ("ru"/"en"/"uz"), not the
  // region-qualified one the default param and this file's other tests use.
  it("also works with the short locale codes the web app actually passes", () => {
    expect(collapseNbsp(formatMoney("1250000", "UZS", "ru"))).toBe("1 250 000 сум");
    expect(collapseNbsp(formatMoney("1250000", "UZS", "uz"))).toBe("1 250 000 soʻm");
    expect(formatMoney("1250000", "UZS", "en")).toBe("1,250,000 UZS");
  });

  it("never leaves a bare Latin ISO code sitting in the ru output", () => {
    const out = formatMoney("1250000", "UZS", "ru-RU");
    expect(out).not.toMatch(/UZS/);
    expect(out.endsWith("сум")).toBe(true);
  });

  it("keeps zero-handling and grouping intact, apart from the currency token", () => {
    expect(formatMoney("0", "UZS", "en-US")).toBe("0 UZS");
  });

  it("still formats USD/USDT the same way (unaffected by the UZS fix)", () => {
    expect(formatMoney("12.34", "USD", "en-US")).toBe("$12.34");
    expect(formatMoney("25", "USDT", "en-US")).toBe("25 USDT");
  });
});

/**
 * Pins `uzsWord`'s locale normalization — this is the single home for the
 * mapping (`apps/web/src/lib/seo.ts` and `apps/miniapp/src/lib/currency.ts`
 * both import it now instead of each carrying their own copy). Before the
 * consolidation, the two app-local copies compared `locale === "ru"`
 * exactly and would have printed the bare "UZS" code for a region-qualified
 * tag; this locks in that a region-qualified tag and its bare form agree.
 */
describe("uzsWord — locale normalization", () => {
  it("treats a region-qualified locale the same as its bare form", () => {
    expect(uzsWord("ru-RU")).toBe("сум");
    expect(uzsWord("ru")).toBe("сум");
    expect(uzsWord("ru-RU")).toBe(uzsWord("ru"));
  });

  it("also normalizes uz the same way", () => {
    expect(uzsWord("uz-UZ")).toBe("soʻm");
    expect(uzsWord("uz")).toBe(uzsWord("uz-UZ"));
  });
});
