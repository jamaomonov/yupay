import { beforeEach, describe, expect, it, vi } from "vitest";

import sitemap, { revalidate } from "./sitemap";

import { getBrandSlugs } from "@/lib/catalog";

/**
 * The sitemap has silently gone wrong twice, both times invisibly: it is not a
 * page anyone looks at, so a missing brand only shows up as traffic that never
 * arrives.
 *
 * Telegram Stars and Standoff 2 were live and crawlable through ISR while the
 * map still listed neither, because the map is generated and the pages are not.
 */

vi.mock("@/lib/catalog", () => ({ getBrandSlugs: vi.fn() }));

const mockedSlugs = vi.mocked(getBrandSlugs);

beforeEach(() => {
  mockedSlugs.mockReset();
  mockedSlugs.mockResolvedValue(["telegram-stars", "standoff-2"]);
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
