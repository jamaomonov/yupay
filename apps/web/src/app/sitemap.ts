import { LOCALES } from "@yupay/i18n";

import type { MetadataRoute } from "next";

import { getBrandSlugs } from "@/lib/catalog";
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
  const lastModified = new Date();
  const entries: MetadataRoute.Sitemap = [];
  const slugs = await getBrandSlugs();

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
    ...["terms", "privacy", "refunds", "imprint"].map((doc) => ({
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
