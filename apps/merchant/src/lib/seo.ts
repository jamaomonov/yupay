import { LOCALES } from "@yupay/i18n";
import { getTranslations } from "next-intl/server";

import { pathFor } from "./locale-href";

import type { Metadata } from "next";

/**
 * SEO helpers for the reseller site — a port of `apps/web/src/lib/seo.ts`
 * with the site constant swapped. This is a B2B surface with its own
 * robots.txt, sitemap and hreflang set; it does not borrow the storefront's.
 */
export const SITE = "https://reseller.yupay.uz";

/**
 * The machine-readable contract: the live Merchant API schema.
 *
 * Linked, never pasted into a page. It lives here rather than beside the one
 * page that shows it because `/api` also advertises it in its `<head>` as an
 * `application/json` alternate — the same URL in two roles, and two literals
 * would be one edit away from disagreeing.
 */
export const OPENAPI_URL = "https://api.yupay.uz/merchant/openapi.json";

/**
 * Shared robots directives. Beyond index/follow we opt into the LARGEST
 * previews Google allows — same rationale as the storefront's own `ROBOTS`
 * (see `apps/web/src/lib/seo.ts`).
 */
export const ROBOTS: Metadata["robots"] = {
  index: true,
  follow: true,
  "max-image-preview": "large",
  "max-snippet": -1,
  "max-video-preview": -1,
};

/**
 * The cabinet and every auth screen: signed-in or single-use-token
 * surfaces, never indexed. Segments opt in by re-exporting this from their
 * own layout, which overrides the locale layout's per-page defaults.
 */
export const NOINDEX: Metadata["robots"] = { index: false, follow: false };

const OG_LOCALE: Record<string, string> = {
  ru: "ru_RU",
  en: "en_US",
  uz: "uz_UZ",
};

/**
 * Absolute URL for a locale + path. ru is the default locale → no prefix.
 *
 * The bare apex (ru home) is `https://reseller.yupay.uz` with **no** trailing
 * slash. It used to carry one, but Next's metadata resolver strips it from
 * `canonical` and hreflang, so the sitemap said `…uz/` while every page said
 * `…uz`. Both mean the same URL; one spelling everywhere is the point.
 */
export function localeUrl(locale: string, path = ""): string {
  const base = locale === "ru" ? "" : `/${locale}`;
  return `${SITE}${base}${path}`;
}

/**
 * Root-relative internal path for a locale + path. The app already has one
 * of these — `locale-href.ts` — so it is re-exported rather than duplicated;
 * every in-app `<Link href>` should keep importing it from wherever it
 * already does.
 */
export { pathFor };

/** canonical + hreflang alternates (incl. x-default) for a given path. */
export function alternates(locale: string, path = "") {
  const languages: Record<string, string> = {};
  for (const l of LOCALES) languages[l] = localeUrl(l, path);
  languages["x-default"] = localeUrl("ru", path);
  return { canonical: localeUrl(locale, path), languages };
}

/** Size of the generated link preview — the size every chat client expects. */
export const OG_IMAGE_SIZE = { width: 1200, height: 630 } as const;

/**
 * The link preview for a locale: `/og/<locale>` (`app/og/[locale]/route.tsx`).
 *
 * Outside `[locale]` and outside the i18n middleware, so the URL never
 * redirects — `ru` has no path prefix on the site, and a chat crawler should
 * not have to follow a 308 to reach a picture.
 */
export function ogImage(locale: string, alt: string) {
  return { url: `${SITE}/og/${locale}`, ...OG_IMAGE_SIZE, alt, type: "image/png" };
}

/** The preview's alt text: the hero line it draws, in the page's language. */
export async function ogAlt(locale: string): Promise<string> {
  const t = await getTranslations({ locale, namespace: "merchant.landing" });
  return `YuPay Reseller — ${t("heading")}`;
}

/**
 * Open Graph + Twitter fields for a page.
 *
 * Every page that sets `openGraph` must go through this: Next merges metadata
 * per top-level key, so a page's own `openGraph` replaces the layout's whole
 * object — images included — and a page that forgot them shared as a bare
 * link.
 */
export function social(
  locale: string,
  {
    alt,
    url,
    title,
    description,
  }: { alt: string; url?: string; title?: string; description?: string },
): Pick<Metadata, "openGraph" | "twitter"> {
  const image = ogImage(locale, alt);
  return {
    openGraph: {
      type: "website",
      siteName: "YuPay",
      ...(url !== undefined ? { url } : {}),
      ...(title !== undefined ? { title } : {}),
      ...(description !== undefined ? { description } : {}),
      images: [image],
      ...ogLocale(locale),
    },
    twitter: {
      card: "summary_large_image",
      ...(title !== undefined ? { title } : {}),
      ...(description !== undefined ? { description } : {}),
      images: [image],
    },
  };
}

export function ogLocale(locale: string): { locale: string; alternateLocale: string[] } {
  return {
    locale: OG_LOCALE[locale] ?? "ru_RU",
    // Next's OpenGraph type names this field `alternateLocale`, not
    // `alternate` — the typo shipped silently because `Metadata["openGraph"]`
    // accepts (and drops) unknown keys instead of rejecting them.
    alternateLocale: LOCALES.filter((l) => l !== locale).map((l) => OG_LOCALE[l] ?? "ru_RU"),
  };
}

/**
 * Today at UTC midnight — the generation timestamp truncated to the day.
 *
 * No page here has a real per-content timestamp to draw from, so every
 * sitemap `lastModified` and JSON-LD `dateModified` uses this instead of the
 * literal build time: a timestamp that moves on every hourly regeneration
 * without the content changing teaches a crawler to ignore the field.
 */
export function dayStamp(): Date {
  const d = new Date();
  d.setUTCHours(0, 0, 0, 0);
  return d;
}

/**
 * Every path the reseller site wants indexed. `sitemap.ts` builds its entries
 * off this single list, so a path added or removed here needs no second edit
 * there. `llms.txt/route.ts` keeps its own curated list instead — its
 * grouping (by audience, with prose around each link) does not map to a flat
 * path list — so the two are checked separately by `seo.test.ts`: one test
 * asserts every entry here has a real page file, another asserts every link
 * `llms.txt` prints resolves to one too. `/telegram`, `/api` and `/faq` are
 * the intent pages — one per way somebody arrives. `/offer` is the public
 * offer a reseller accepts at sign-up (final since 2026-11-11, indexed).
 * The cabinet and every auth screen are deliberately absent too; the same
 * test pins that.
 */
export const SEO_PATHS: string[] = [
  "",
  "/telegram",
  "/api",
  "/faq",
  "/docs",
  "/docs/quickstart",
  "/docs/authentication",
  "/docs/webhooks",
  "/docs/errors",
  "/offer",
];
