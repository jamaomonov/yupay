import { beforeEach, describe, expect, it, vi } from "vitest";

import sitemap, { revalidate } from "./sitemap";

import { getBrandDetail, getBrandSlugs, getProductDetail } from "@/lib/catalog";

/**
 * The sitemap has silently gone wrong twice, both times invisibly: it is not a
 * page anyone looks at, so a missing brand only shows up as traffic that never
 * arrives.
 *
 * Telegram Stars and Standoff 2 were live and crawlable through ISR while the
 * map still listed neither, because the map is generated and the pages are not.
 */

vi.mock("@/lib/catalog", () => ({
  getBrandSlugs: vi.fn(),
  getBrandDetail: vi.fn(),
  getProductDetail: vi.fn(),
}));

const mockedSlugs = vi.mocked(getBrandSlugs);
const mockedBrand = vi.mocked(getBrandDetail);
const mockedProduct = vi.mocked(getProductDetail);

beforeEach(() => {
  mockedSlugs.mockReset();
  mockedSlugs.mockResolvedValue(["telegram-stars", "standoff-2"]);
  mockedBrand.mockReset();
  mockedBrand.mockResolvedValue(null);
  mockedProduct.mockReset();
  mockedProduct.mockResolvedValue(null);
});

describe("sitemap", () => {
  it("regenerates rather than being frozen at build time", () => {
    // This is the whole fix: `next build` reads the deployed API, so a brand
    // added after the last deploy stayed missing until someone rebuilt.
    expect(revalidate).toBe(3600);
  });

  it("lists every brand's product and guide page, in every locale", async () => {
    const urls = (await sitemap()).map((e) => e.url);

    for (const slug of ["telegram-stars", "standoff-2"]) {
      for (const prefix of ["", "/en", "/uz"]) {
        expect(urls).toContain(`https://yupay.uz${prefix}/store/${slug}`);
        expect(urls).toContain(`https://yupay.uz${prefix}/store/${slug}/how-to`);
      }
    }
  });

  it("survives a catalogue that cannot be reached", async () => {
    // `getBrandSlugs` swallows its own failure and answers []. The map must
    // still carry the static pages rather than coming back empty.
    mockedSlugs.mockResolvedValue([]);

    const urls = (await sitemap()).map((e) => e.url);

    expect(urls).toContain("https://yupay.uz/");
    expect(urls).toContain("https://yupay.uz/store");
    expect(urls.some((u) => u.includes("/store/"))).toBe(false);
  });

  it("dates every entry to the day, not the minute", async () => {
    // `lastmod` is only useful while it stays believable. Regenerating hourly
    // with a live timestamp would move all ~126 URLs every hour without the
    // content changing, which teaches a crawler to ignore the field.
    const stamps = (await sitemap()).map((e) => e.lastModified);

    for (const stamp of stamps) {
      expect(stamp).toBeInstanceOf(Date);
      const d = stamp as Date;
      expect([
        d.getUTCHours(),
        d.getUTCMinutes(),
        d.getUTCSeconds(),
        d.getUTCMilliseconds(),
      ]).toEqual([0, 0, 0, 0]);
    }
    // One value shared by every entry, not one per URL.
    expect(new Set(stamps.map((s) => (s as Date).getTime())).size).toBe(1);
  });

  it("gives each entry hreflang alternates for all three locales", async () => {
    const entry = (await sitemap()).find((e) => e.url === "https://yupay.uz/store/telegram-stars");

    expect(Object.keys(entry?.alternates?.languages ?? {}).sort()).toEqual(["en", "ru", "uz"]);
  });
});

describe("brand images", () => {
  it("declares hero, product and sku art on the brand entries", async () => {
    // Google Images only ever surfaced the hero because the hero was the only
    // image any signal named. The map now names the SKU art too.
    mockedBrand.mockResolvedValue({
      hero_image_url: "https://cdn.yupay.uz/brand_hero/h.webp",
      products: [{ slug: "p" }],
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- partial fixture
    } as any);
    mockedProduct.mockResolvedValue({
      image_url: "https://cdn.yupay.uz/product_image/p.png",
      skus: [
        { image_url: "https://cdn.yupay.uz/sku_image/a.png" },
        { image_url: null },
        { image_url: "https://cdn.yupay.uz/sku_image/a.png" }, // deduped
      ],
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- partial fixture
    } as any);

    const brandEntry = (await sitemap()).find((e) => e.url.endsWith("/store/telegram-stars"));
    expect(brandEntry?.images).toEqual([
      "https://cdn.yupay.uz/brand_hero/h.webp",
      "https://cdn.yupay.uz/product_image/p.png",
      "https://cdn.yupay.uz/sku_image/a.png",
    ]);
  });

  it("an image lookup failure costs the images, never the entry", async () => {
    mockedBrand.mockRejectedValue(new Error("api down"));
    const entries = await sitemap();
    const brandEntry = entries.find((e) => e.url.endsWith("/store/telegram-stars"));
    expect(brandEntry).toBeDefined();
    expect(brandEntry?.images).toBeUndefined();
  });
});
