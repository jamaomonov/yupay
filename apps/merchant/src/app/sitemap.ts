import { LOCALES } from "@yupay/i18n";

import type { MetadataRoute } from "next";

import { localeUrl, SEO_PATHS } from "@/lib/seo";

/**
 * Locale-aware sitemap, built off the single `SEO_PATHS` list `seo.ts`
 * exports — so a path added there needs no second edit here, and
 * `llms.txt/route.ts` can never list a page this file does not.
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
  // No per-page content timestamp is available, so this is the generation
  // date truncated to the day — see the storefront's own sitemap for why:
  // a `lastmod` that moves on every regeneration without the content
  // changing teaches a crawler to ignore the field.
  const lastModified = new Date();
  lastModified.setUTCHours(0, 0, 0, 0);

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
