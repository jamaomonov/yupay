import { describe, expect, test } from "vitest";

import { legalUrl } from "./legal";

/**
 * The one thing worth pinning: `ru` is the storefront's default locale and takes
 * no path prefix. A `/ru/legal` link would still work, but only through a 308,
 * and the whole point of building the URL here rather than hardcoding one is
 * that it lands on the page the customer's language actually uses.
 */
describe("legalUrl", () => {
  test("the default locale carries no prefix", () => {
    expect(legalUrl("ru")).toBe("https://yupay.uz/legal");
    expect(legalUrl("ru", "agreement")).toBe("https://yupay.uz/legal/agreement");
  });

  test("the other locales are prefixed", () => {
    expect(legalUrl("en")).toBe("https://yupay.uz/en/legal");
    expect(legalUrl("uz", "privacy")).toBe("https://yupay.uz/uz/legal/privacy");
  });

  test("never emits a redirecting or doubled path", () => {
    for (const locale of ["ru", "en", "uz"] as const) {
      for (const doc of [undefined, "terms", "agreement", "privacy", "refunds", "imprint"]) {
        const url = legalUrl(locale, doc);
        expect(url.startsWith("https://yupay.uz/")).toBe(true);
        expect(url).not.toContain("//legal");
        expect(url.endsWith("/")).toBe(false);
      }
    }
  });
});
