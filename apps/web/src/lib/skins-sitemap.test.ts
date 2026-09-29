import { describe, expect, it } from "vitest";

import { chunkCount, SKINS_PER_SITEMAP, sitemapIndexXml, urlsetXml } from "./skins-sitemap";

describe("skins sitemap", () => {
  it("splits the items so no file nears the 50 000-URL limit in three locales", () => {
    expect(SKINS_PER_SITEMAP * 3).toBeLessThan(50_000);
    expect(chunkCount(0)).toBe(0);
    expect(chunkCount(SKINS_PER_SITEMAP)).toBe(1);
    expect(chunkCount(SKINS_PER_SITEMAP + 1)).toBe(2);
  });

  it("lists every page in every locale with hreflang alternates", () => {
    const xml = urlsetXml(["/skins/ak-47-redline-field-tested"], "2026-09-29");
    expect(xml).toContain("<loc>https://yupay.uz/skins/ak-47-redline-field-tested</loc>");
    expect(xml).toContain("<loc>https://yupay.uz/en/skins/ak-47-redline-field-tested</loc>");
    expect(xml).toContain("<loc>https://yupay.uz/uz/skins/ak-47-redline-field-tested</loc>");
    expect(xml.match(/<url>/g)).toHaveLength(3);
    expect(xml).toContain(
      '<xhtml:link rel="alternate" hreflang="uz" href="https://yupay.uz/uz/skins/ak-47-redline-field-tested"/>',
    );
    expect(xml).toContain("<lastmod>2026-09-29</lastmod>");
    expect(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>')).toBe(true);
  });

  it("escapes what XML cannot hold raw", () => {
    expect(urlsetXml(["/skins/a&b"], "2026-09-29")).toContain("/skins/a&amp;b");
  });

  it("indexes the files", () => {
    const xml = sitemapIndexXml(["https://yupay.uz/skins-sitemap/0.xml"], "2026-09-29");
    expect(xml).toContain("<sitemapindex");
    expect(xml).toContain("<loc>https://yupay.uz/skins-sitemap/0.xml</loc>");
  });
});
