/**
 * The CS2 skins sitemap: ~24 000 item pages in three locales are too many for the main
 * `sitemap.xml`, so they get their own index (`/skins-sitemap.xml`) over files of
 * {@link SKINS_PER_SITEMAP} items each (`/skins-sitemap/<n>.xml`) plus one of the landing
 * pages (`/skins-sitemap/landings.xml`). Each URL carries hreflang alternates, as the main
 * map does. `robots.txt` names the index.
 */

import { LOCALES } from "@yupay/i18n";

import { apiGet } from "@/lib/api";
import { localeUrl, SITE } from "@/lib/seo";

/** Items per file: ×3 locales stays far under the protocol's 50 000 URLs and 50 MB. */
export const SKINS_PER_SITEMAP = 5000;

export const SKINS_SITEMAP_INDEX = `${SITE}/skins-sitemap.xml`;

export function chunkCount(total: number): number {
  return Math.ceil(total / SKINS_PER_SITEMAP);
}

export function chunkUrl(name: string): string {
  return `${SITE}/skins-sitemap/${name}.xml`;
}

const escapeXml = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** `YYYY-MM-DD` of today (UTC): a lastmod that moves at most daily stays believable. */
export function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function urlsetXml(paths: string[], lastmod: string): string {
  const urls = paths.flatMap((path) => {
    const links = LOCALES.map(
      (l) =>
        `<xhtml:link rel="alternate" hreflang="${l}" href="${escapeXml(localeUrl(l, path))}"/>`,
    ).join("");
    return LOCALES.map(
      (l) =>
        `<url><loc>${escapeXml(localeUrl(l, path))}</loc><lastmod>${lastmod}</lastmod>${links}</url>`,
    );
  });
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    ...urls,
    "</urlset>",
  ].join("\n");
}

export function sitemapIndexXml(urls: string[], lastmod: string): string {
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ...urls.map(
      (u) => `<sitemap><loc>${escapeXml(u)}</loc><lastmod>${lastmod}</lastmod></sitemap>`,
    ),
    "</sitemapindex>",
  ].join("\n");
}

interface SkinSlugs {
  items: string[];
  total: number;
}

/** One page of on-sale item slugs, alphabetical (`GET /skins/seo/slugs`). */
export function fetchSkinSlugs(offset: number, limit = SKINS_PER_SITEMAP): Promise<SkinSlugs> {
  return apiGet<SkinSlugs>(`/skins/seo/slugs?offset=${String(offset)}&limit=${String(limit)}`, {
    locale: "ru",
    revalidate: 3600,
    tags: ["skins"],
  });
}

export function xmlResponse(body: string): Response {
  return new Response(body, {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  });
}
