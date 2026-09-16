import { describe, expect, it, test } from "vitest";

import { alternates, blogAlternates, formatUzs, truncate } from "./seo";

test("truncate leaves short strings untouched", () => {
  expect(truncate("Короткое описание")).toBe("Короткое описание");
});

test("truncate cuts long strings to <= max at a word boundary with an ellipsis", () => {
  const long =
    "Пополнение Steam в Узбекистане за сумы без комиссии: сколько платите — столько и зачисляется на кошелёк Steam, один к одному. Оплата картами Uzcard и Humo через Click, Payme или Uzum, моментально.";
  const out = truncate(long, 155);
  expect(out.length).toBeLessThanOrEqual(156); // 155 + the ellipsis char
  expect(out.endsWith("…")).toBe(true);
  expect(out).not.toMatch(/[\s,]…$/); // no dangling space/comma before the ellipsis
  expect(long.startsWith(out.slice(0, -1))).toBe(true); // prefix of the original
});

/** `Intl`'s grouping separator for ru/uz is U+00A0 (NBSP), not a plain
 *  space — normalize it before comparing against a plain-space literal. */
function collapseNbsp(s: string): string {
  return s.replace(/\u00a0/g, " ");
}

/**
 * `Intl.NumberFormat(style:"currency", currency:"UZS")` renders the *ISO
 * code*, not a word, and gets the placement wrong: "1 250 000 UZS" in ru
 * (Latin letters in a Cyrillic sentence) and "UZS 1,250,000" in en (the code
 * leads the number). Only `uz` got a real word ("soʻm") for free — this is
 * the storefront-wide fix (2026-09-04 review).
 */
test("formatUzs renders a real word for ru, trailing the number", () => {
  expect(collapseNbsp(formatUzs("ru", 1_250_000))).toBe("1 250 000 сум");
});

test("formatUzs renders a real word for uz, trailing the number", () => {
  expect(collapseNbsp(formatUzs("uz", 1_250_000))).toBe("1 250 000 soʻm");
});

test("formatUzs renders UZS trailing the number for en, not leading it", () => {
  expect(collapseNbsp(formatUzs("en", 1_250_000))).toBe("1,250,000 UZS");
});

test("formatUzs never leaves a bare Latin ISO code sitting in the ru output", () => {
  // The exact bug this guards: the old `style:"currency"` output was
  // "1 250 000 UZS" for ru — a Latin code, not the Cyrillic word "сум".
  const out = formatUzs("ru", 1_250_000);
  expect(out).not.toMatch(/UZS/);
  expect(out.endsWith("сум")).toBe(true);
});

test("formatUzs keeps the locale's own digit grouping", () => {
  expect(collapseNbsp(formatUzs("ru", 1_250_000))).toContain("1 250 000");
  expect(formatUzs("en", 1_250_000)).toContain("1,250,000");
});

describe("the Markdown alternate", () => {
  it("is advertised on a blog post", () => {
    // The blog builds hreflang from translated slugs and so has its own helper.
    // That helper was the one place the Markdown link was missing — on prod,
    // `/store/steam-gifts` advertised its view and `/blog/steam` did not, which
    // is backwards: a post is what an agent is most often asked to read.
    const a = blogAlternates("ru", { ru: "steam", en: "steam-en" });
    expect(a.types?.["text/markdown"]).toBe("https://yupay.uz/md/blog/steam");
  });

  it("follows the locale into the path", () => {
    const a = blogAlternates("en", { ru: "steam", en: "steam-en" });
    expect(a.types?.["text/markdown"]).toBe("https://yupay.uz/md/en/blog/steam-en");
  });

  it("is absent when the post has no translation in this locale", () => {
    // No slug means no post to serve, in HTML or Markdown; advertising one
    // would point an agent at a 404.
    const a = blogAlternates("uz", { ru: "steam", uz: "" });
    expect(a.types).toBeUndefined();
  });

  it("is advertised on an ordinary page too", () => {
    expect(alternates("ru", "/store/steam").types?.["text/markdown"]).toBe(
      "https://yupay.uz/md/store/steam",
    );
  });

  it("is absent on a page with no Markdown view", () => {
    expect(alternates("ru", "/store/steam-gifts/3454300").types).toBeUndefined();
  });
});
