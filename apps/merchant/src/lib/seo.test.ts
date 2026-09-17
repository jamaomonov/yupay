import { describe, expect, it } from "vitest";

import { SEO_PATHS, alternates, localeUrl } from "./seo";

describe("reseller seo helpers", () => {
  it("builds locale urls with as-needed prefixes", () => {
    expect(localeUrl("ru", "/api")).toBe("https://reseller.yupay.uz/api");
    expect(localeUrl("uz", "/api")).toBe("https://reseller.yupay.uz/uz/api");
    expect(localeUrl("en")).toBe("https://reseller.yupay.uz/en");
  });
  it("emits canonical, three languages and x-default", () => {
    const a = alternates("uz", "/telegram");
    expect(a.canonical).toBe("https://reseller.yupay.uz/uz/telegram");
    expect(a.languages).toMatchObject({
      ru: "https://reseller.yupay.uz/telegram",
      en: "https://reseller.yupay.uz/en/telegram",
      uz: "https://reseller.yupay.uz/uz/telegram",
      "x-default": "https://reseller.yupay.uz/telegram",
    });
  });
  it("never lists the cabinet or auth pages", () => {
    expect(
      SEO_PATHS.some((p) => p.startsWith("/cabinet") || p === "/login" || p === "/register"),
    ).toBe(false);
  });
});
