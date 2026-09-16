import { describe, expect, it } from "vitest";

import { markdownUrl, supportsMarkdown } from "./markdown-paths";

/**
 * The HTML head advertises a Markdown view; the middleware serves one. They
 * read the same rule from this module, and these tests are why that matters:
 * the two used to be a private copy in `middleware.ts` and nothing at all in
 * the head, so an agent holding a page had no way to learn the Markdown view
 * existed — content negotiation is invisible once you already have the HTML.
 *
 * The failure mode if they drift is silent in both directions: advertise a
 * view the middleware will not rewrite and the agent gets a 404; serve one
 * nobody advertises and only `llms.txt` can find it.
 */

const SITE = "https://yupay.uz";

describe("supportsMarkdown", () => {
  it.each([
    "/",
    "/store",
    "/blog",
    "/store/steam-gifts",
    "/store/steam-gifts/how-to",
    "/blog/kak-kupit-igru-v-steam-iz-uzbekistana",
  ])("covers %s", (p) => {
    expect(supportsMarkdown(p)).toBe(true);
  });

  it.each(["/en/blog", "/uz/store/steam", "/ru/"])("covers %s whatever the locale prefix", (p) => {
    expect(supportsMarkdown(p)).toBe(true);
  });

  it.each([
    // Deferred with the rest of the per-game work: these have no Markdown view.
    "/store/steam-gifts/3454300",
    "/account/wallet",
    "/checkout",
    "/legal/terms",
  ])("leaves %s alone", (p) => {
    expect(supportsMarkdown(p)).toBe(false);
  });
});

describe("markdownUrl", () => {
  it("has no locale segment for the default locale", () => {
    // `localePrefix: "as-needed"` — ru lives at the bare path, and the md
    // route peels an optional locale, so ru must not grow one here.
    expect(markdownUrl(SITE, "ru", "/blog/steam")).toBe(`${SITE}/md/blog/steam`);
  });

  it("keeps the locale segment for the others", () => {
    expect(markdownUrl(SITE, "en", "/blog/steam")).toBe(`${SITE}/md/en/blog/steam`);
    expect(markdownUrl(SITE, "uz", "/store")).toBe(`${SITE}/md/uz/store`);
  });

  it("maps the home page to the bare /md", () => {
    expect(markdownUrl(SITE, "ru", "")).toBe(`${SITE}/md`);
    expect(markdownUrl(SITE, "en", "")).toBe(`${SITE}/md/en`);
  });

  it("is null for a page with no Markdown view", () => {
    expect(markdownUrl(SITE, "ru", "/store/steam-gifts/3454300")).toBeNull();
    expect(markdownUrl(SITE, "en", "/checkout")).toBeNull();
  });
});
