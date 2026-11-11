import { existsSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { formatCount } from "./brands";
import { SEO_PATHS, alternates, localeUrl, social } from "./seo";
import { GET as llmsTxt } from "../app/llms.txt/route";

/** `path.join` drops empty segments, so "" already resolves to
 *  `src/app/[locale]/page.tsx` — no special-casing needed here. */
function pageFileFor(path: string): string {
  return join(process.cwd(), "src/app/[locale]", path, "page.tsx");
}

describe("reseller seo helpers", () => {
  it("builds locale urls with as-needed prefixes", () => {
    expect(localeUrl("ru", "/api")).toBe("https://reseller.yupay.uz/api");
    expect(localeUrl("uz", "/api")).toBe("https://reseller.yupay.uz/uz/api");
    expect(localeUrl("en")).toBe("https://reseller.yupay.uz/en");
  });
  it("spells the ru home the way Next prints its canonical — no trailing slash", () => {
    // The sitemap said `…uz/` while canonical and hreflang said `…uz`.
    expect(localeUrl("ru")).toBe("https://reseller.yupay.uz");
    expect(alternates("ru").canonical).toBe(localeUrl("ru"));
  });
  it("gives every page that sets its own Open Graph the preview image", () => {
    const meta = social("uz", { alt: "alt", url: localeUrl("uz", "/api") });
    const image = { url: "https://reseller.yupay.uz/og/uz", width: 1200, height: 630 };
    expect(meta.openGraph?.images).toEqual([expect.objectContaining(image)]);
    expect(meta.twitter).toMatchObject({ card: "summary_large_image" });
    expect(meta.twitter?.images).toEqual([expect.objectContaining(image)]);
  });
  it("lists the public offer now that it is final", () => {
    expect(SEO_PATHS).toContain("/offer");
  });
  it("formats the catalogue size in the reader's locale", () => {
    expect(formatCount("en", 10_000)).toBe("10,000");
    expect(formatCount("ru", 10_000).replace(/\s/g, " ")).toBe("10 000");
    expect(formatCount("ru", 870)).toBe("870");
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
  it("lists the three intent pages", () => {
    // They exist now — `/telegram`, `/api` and `/faq` are real routes, and
    // `sitemap.ts` plus `llms.txt` are built off this list alone. A path
    // dropped from here silently disappears from both.
    expect(SEO_PATHS).toEqual(expect.arrayContaining(["/telegram", "/api", "/faq"]));
  });

  it("never lists the cabinet or auth pages", () => {
    expect(
      SEO_PATHS.some((p) => p.startsWith("/cabinet") || p === "/login" || p === "/register"),
    ).toBe(false);
  });

  it("every SEO_PATHS entry has a real page file", () => {
    for (const path of SEO_PATHS) {
      const file = pageFileFor(path);
      expect(existsSync(file), `SEO_PATHS has "${path}" but ${file} does not exist`).toBe(true);
    }
  });
});

describe("llms.txt stays in sync with the app", () => {
  it("every reseller.yupay.uz link it prints resolves to a real page", async () => {
    const body = await llmsTxt().text();
    const links = [...body.matchAll(/https:\/\/reseller\.yupay\.uz(\/[^\s)]+)/g)].map(
      (m) => m[1] ?? "",
    );
    // A route with no links would pass the loop below vacuously — assert
    // there is something to check in the first place.
    expect(links.length).toBeGreaterThan(0);
    for (const path of links) {
      const file = pageFileFor(path);
      expect(existsSync(file), `llms.txt links "${path}" but ${file} does not exist`).toBe(true);
    }
  });
});
