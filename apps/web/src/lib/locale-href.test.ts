import { describe, expect, it } from "vitest";

import { hrefForLocale, navSectionActive } from "./locale-href";

describe("hrefForLocale", () => {
  it("keeps a store path and strips the default locale prefix", () => {
    expect(hrefForLocale("en", "/store/mlbb")).toBe("/en/store/mlbb");
    expect(hrefForLocale("ru", "/en/store/mlbb")).toBe("/store/mlbb");
  });

  it("rewrites a blog article to the other locale slug", () => {
    const slugs = { ru: "kak-popolnit", en: "how-to-top-up" };
    expect(hrefForLocale("en", "/blog/kak-popolnit", slugs)).toBe("/en/blog/how-to-top-up");
    expect(hrefForLocale("ru", "/en/blog/how-to-top-up", slugs)).toBe("/blog/kak-popolnit");
  });

  it("falls back to the blog index when that locale has no row", () => {
    expect(hrefForLocale("en", "/blog/kak-popolnit", { ru: "kak-popolnit" })).toBe("/en/blog");
    expect(hrefForLocale("uz", "/blog/kak-popolnit", null)).toBe("/uz/blog");
  });
});

describe("navSectionActive", () => {
  it("matches a section and its children, not the home path", () => {
    expect(navSectionActive("/blog/x", "/blog")).toBe(true);
    expect(navSectionActive("/store", "/store")).toBe(true);
    expect(navSectionActive("/blog", "/")).toBe(false);
  });
});
