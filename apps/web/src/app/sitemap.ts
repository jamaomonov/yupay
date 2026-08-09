import { LOCALES } from "@yupay/i18n";

import type { MetadataRoute } from "next";

import { getBrandSlugs } from "@/lib/catalog";
import { LEGAL_DOCS } from "@/lib/legal";
import { localeUrl } from "@/lib/seo";

/**
 * Locale-aware sitemap. Every public path is emitted for all three locales
 * with per-entry hreflang alternates so search engines map ru/en/uz cleanly —
 * important for surfacing the right language to Uzbekistan vs RU/EN searchers.
 */
function languagesFor(path: string): Record<string, string> {
  return Object.fromEntries(LOCALES.map((l) => [l, localeUrl(l, path)]));
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const entries: MetadataRoute.Sitemap = [];
  const slugs = await getBrandSlugs();

  // No per-entry content timestamps are exposed to the storefront, so use the
  // build/generation time as `lastModified`. It's a truthful "site last
  // rebuilt/deployed" signal (a redeploy is what publishes content changes) and
  // `lastmod` is the one sitemap hint Google actually uses. Computed once so
  // every URL in a given generation shares the same value.
  const lastModified = new Date();

  const paths: {
    path: string;
    priority: number;
    changeFrequency: "daily" | "weekly" | "monthly";
  }[] = [
    { path: "", priority: 1.0, changeFrequency: "daily" },
    { path: "/store", priority: 0.9, changeFrequency: "daily" },
    ...slugs.map((slug) => ({
      path: `/store/${slug}`,
      priority: 0.8,
      changeFrequency: "weekly" as const,
    })),
    // Per-brand "how to top up" guide pages (capture the how-to / where-to-find
    // queries the money pages don't answer head-on).
    ...slugs.map((slug) => ({
      path: `/store/${slug}/how-to`,
      priority: 0.6,
      changeFrequency: "monthly" as const,
    })),
    // Driven off LEGAL_DOCS rather than a second hand-written list: the
    // previous copy here was missing `agreement`, so the document was linked
    // from the footer and routed by the app but never offered to a crawler.
    { path: "/legal", priority: 0.3, changeFrequency: "monthly" },
    ...LEGAL_DOCS.map((doc) => ({
      path: `/legal/${doc}`,
      priority: 0.3,
      changeFrequency: "monthly" as const,
    })),
  ];

  for (const { path, priority, changeFrequency } of paths) {
    const languages = languagesFor(path);
    for (const locale of LOCALES) {
      entries.push({
        url: localeUrl(locale, path),
        lastModified,
        changeFrequency,
        priority,
        alternates: { languages },
      });
    }
  }

  return entries;
}
