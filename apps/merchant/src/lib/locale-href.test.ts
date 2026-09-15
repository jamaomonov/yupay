import { describe, expect, it } from "vitest";

import { routing } from "@/i18n/routing";

import { hrefForLocale } from "./locale-href";

/**
 * Switching language must not be a redirect.
 *
 * `localePrefix: "as-needed"` gives the default locale no segment, so this is
 * not a find-and-replace: going *to* Russian has to strip a segment, and going
 * *from* it has to add one that was never in the path. Getting it wrong is not
 * visibly broken — it 308s to the right place — which is exactly why it is
 * worth pinning.
 */
describe("hrefForLocale", () => {
  it("adds a segment when leaving the default locale", () => {
    expect(hrefForLocale("en", "/cabinet/orders")).toBe("/en/cabinet/orders");
    expect(hrefForLocale("uz", "/docs/quickstart")).toBe("/uz/docs/quickstart");
  });

  it("strips the segment when returning to the default locale", () => {
    expect(hrefForLocale("ru", "/en/cabinet/orders")).toBe("/cabinet/orders");
    expect(hrefForLocale("ru", "/uz/docs")).toBe("/docs");
  });

  it("swaps one non-default locale for another", () => {
    expect(hrefForLocale("uz", "/en/docs/errors")).toBe("/uz/docs/errors");
  });

  it("handles the landing page in both directions", () => {
    expect(hrefForLocale("en", "/")).toBe("/en");
    expect(hrefForLocale("ru", "/en")).toBe("/");
    expect(hrefForLocale("ru", "/")).toBe("/");
  });

  it("treats an unrecognised first segment as a path, not a locale", () => {
    // A future top-level route with a two-letter name must not be eaten.
    expect(hrefForLocale("en", "/offer")).toBe("/en/offer");
    expect(hrefForLocale("en", "/de/offer")).toBe("/en/de/offer");
  });

  it("covers every locale the app ships", () => {
    // Pinned to the catalog, so a fourth locale cannot quietly stop working.
    for (const locale of routing.locales) {
      const href = hrefForLocale(locale, "/docs");
      expect(href).toBe(locale === routing.defaultLocale ? "/docs" : `/${locale}/docs`);
    }
  });
});
