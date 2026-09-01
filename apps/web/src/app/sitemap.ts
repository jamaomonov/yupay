import { LOCALES } from "@yupay/i18n";

import type { MetadataRoute } from "next";

import { getBrandDetail, getBrandSlugs, getProductDetail } from "@/lib/catalog";
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

/**
 * Regenerate hourly instead of only at build time.
 *
 * Without this the map is baked by `next build`, which reads the *deployed*
 * API — so a brand added to the catalogue stayed missing until someone
 * remembered to rebuild, even though its page was already live through ISR.
 * That caught us with Telegram Stars and Standoff 2: the pages worked, the map
 * did not list them, and it took a second deploy after the seeds to fix.
 */
export const revalidate = 3600;

/**
 * SKU and hero images for one brand, for the sitemap's `images` field.
 *
 * Declaring them here is what tells Google Images the SKU art on a brand page
 * is content, not chrome — the pages only ever surfaced the hero because the
 * hero was the only image any signal (og:image, this map) ever named.
 * Best-effort: an unreachable catalogue yields an empty list, never a build
 * failure (`next build` prerenders against the deployed API).
 */
async function brandImages(slug: string): Promise<string[]> {
  try {
    const brand = await getBrandDetail(slug, "ru", "UZS");
    if (!brand) return [];
    const products = await Promise.all(
      (brand.products ?? []).map((prod) => getProductDetail(prod.slug, "ru", "UZS")),
    );
    const images = [
      brand.hero_image_url,
      ...products.flatMap((prod) =>
        prod ? [prod.image_url, ...prod.skus.map((sku) => sku.image_url)] : [],
      ),
    ].filter((u): u is string => Boolean(u));
    return [...new Set(images)];
  } catch {
    return [];
  }
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const entries: MetadataRoute.Sitemap = [];
  const slugs = await getBrandSlugs();
  const imagesBySlug = new Map(
    await Promise.all(slugs.map(async (slug) => [slug, await brandImages(slug)] as const)),
  );

  // No per-entry content timestamps are exposed to the storefront, so this is
  // the generation date — but truncated to the day.
  //
  // `lastmod` is the one sitemap hint Google actually uses, and it only keeps
  // using it while it stays believable: a value that moves on every URL without
  // the content changing teaches a crawler to ignore the field. Regenerating
  // hourly would do exactly that, and even today's build-time value moves on
  // every deploy — six of them in one afternoon, recently. Truncating bounds
  // the churn to once a day whatever the release cadence.
  //
  // The real fix is a content timestamp per brand; the catalogue API exposes
  // none today.
  const lastModified = new Date();
  lastModified.setUTCHours(0, 0, 0, 0);

  const paths: {
    path: string;
    priority: number;
    changeFrequency: "daily" | "weekly" | "monthly";
    images?: string[];
  }[] = [
    { path: "", priority: 1.0, changeFrequency: "daily" },
    { path: "/store", priority: 0.9, changeFrequency: "daily" },
    ...slugs.map((slug) => ({
      path: `/store/${slug}`,
      priority: 0.8,
      changeFrequency: "weekly" as const,
      images: imagesBySlug.get(slug) ?? [],
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

  for (const { path, priority, changeFrequency, images } of paths) {
    const languages = languagesFor(path);
    for (const locale of LOCALES) {
      entries.push({
        url: localeUrl(locale, path),
        lastModified,
        changeFrequency,
        priority,
        alternates: { languages },
        ...(images && images.length > 0 ? { images } : {}),
      });
    }
  }

  return entries;
}
