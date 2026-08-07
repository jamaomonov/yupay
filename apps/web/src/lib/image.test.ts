import { describe, expect, it } from "vitest";

import { isOptimizable } from "./image";

describe("isOptimizable", () => {
  it("optimises what we serve ourselves", () => {
    // Root-relative: served by this app, so there is no third party to fail.
    expect(isOptimizable("/payment/payme.png")).toBe(true);
    expect(isOptimizable("https://cdn.yupay.uz/brand_hero/2026/07/a.jpg")).toBe(true);
    expect(isOptimizable("https://yupay.uz/og.png")).toBe(true);
    expect(isOptimizable("https://pub-abc123.r2.dev/hero.jpg")).toBe(true);
  });

  it("leaves third-party catalog art alone", () => {
    // The whole point of the original blanket `unoptimized`: a slow or dead
    // foreign host makes the optimizer 504 and the image vanish, where an
    // untouched <img> would still have rendered.
    expect(isOptimizable("https://cdn.some-vendor.com/pubg.jpg")).toBe(false);
    expect(isOptimizable("http://yupay.uz/insecure.png")).toBe(false);
  });

  it("is not fooled by a lookalike host", () => {
    // `endsWith(".yupay.uz")` must not match a domain that merely ends in the
    // same characters.
    expect(isOptimizable("https://evil-yupay.uz/x.png")).toBe(false);
    expect(isOptimizable("https://yupay.uz.attacker.com/x.png")).toBe(false);
    expect(isOptimizable("https://notr2.dev/x.png")).toBe(false);
  });

  it("handles absent and unparseable values", () => {
    expect(isOptimizable(null)).toBe(false);
    expect(isOptimizable(undefined)).toBe(false);
    expect(isOptimizable("")).toBe(false);
    expect(isOptimizable("not a url")).toBe(false);
  });
});
