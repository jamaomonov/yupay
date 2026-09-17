import { LOCALES } from "@yupay/i18n";

import type { MetadataRoute } from "next";

import { dayStamp, localeUrl, SEO_PATHS } from "@/lib/seo";

/**
 * Locale-aware sitemap, built off the single `SEO_PATHS` list `seo.ts`
 * exports — so a path added there needs no second edit here.
 *
 * `llms.txt/route.ts` is **not** derived from that list: it curates its own
 * links, because its grouping and prose do not map onto a flat set of paths.
 * `seo.test.ts` is what keeps the two honest — one test per side, each
 * asserting the paths it names resolve to a real page.
 */
function languagesFor(path: string): Record<string, string> {
  return Object.fromEntries(LOCALES.map((l) => [l, localeUrl(l, path)]));
}

/**
 * Regenerate hourly rather than only at build time — same reasoning as the
 * storefront's own sitemap: a path that starts existing between deploys
 * (Task 4's `/telegram`, `/api`, `/faq`) should not wait for the next build
 * to be listed.
 */
export const revalidate = 3600;

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = dayStamp();

  const entries: MetadataRoute.Sitemap = [];
  for (const path of SEO_PATHS) {
    const languages = languagesFor(path);
    for (const locale of LOCALES) {
      entries.push({
        url: localeUrl(locale, path),
        lastModified,
        changeFrequency: "weekly",
        priority: path === "" ? 1 : 0.7,
        alternates: { languages },
      });
    }
  }
  return entries;
}
