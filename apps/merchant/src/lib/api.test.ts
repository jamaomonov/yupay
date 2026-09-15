import { LOCALES } from "@yupay/i18n";
import { describe, expect, it } from "vitest";

import { loginPathFor } from "./api";

/**
 * Where a lapsed session lands.
 *
 * The cabinet's screens each render an *empty state* when their read fails,
 * so a session that cannot be rotated used to look like "your account is
 * broken" rather than "you are signed out". The redirect is what fixes that,
 * and the only part of it with a decision in it is the locale.
 */
describe("loginPathFor", () => {
  it("keeps the locale the reader is actually in", () => {
    expect(loginPathFor("/en/cabinet/orders")).toBe("/en/login");
    expect(loginPathFor("/uz/cabinet/settings")).toBe("/uz/login");
  });

  it("adds no prefix for the default locale, which has no segment", () => {
    // `localePrefix: "as-needed"`: `/cabinet` is already Russian, and
    // `/ru/login` would be a second URL for the same form.
    expect(loginPathFor("/cabinet")).toBe("/login");
    expect(loginPathFor("/")).toBe("/login");
  });

  it("treats an unrecognised first segment as a path, not a locale", () => {
    // The failure this guards: a future top-level route whose name is two
    // letters would otherwise be read as a locale and lose the redirect.
    expect(loginPathFor("/cabinet/orders")).toBe("/login");
    expect(loginPathFor("/de/cabinet")).toBe("/login");
  });

  it("covers every locale the app actually ships", () => {
    // Pinned to the catalog rather than to a literal list: a fourth locale
    // must not quietly stop redirecting.
    for (const locale of LOCALES) {
      expect(loginPathFor(`/${locale}/cabinet`)).toBe(`/${locale}/login`);
    }
  });
});
