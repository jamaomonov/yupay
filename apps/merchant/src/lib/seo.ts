import { LOCALES } from "@yupay/i18n";

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

/** Absolute URL for a locale + path. ru is the default locale → no prefix. */
export function localeUrl(locale: string, path = ""): string {
  const base = locale === "ru" ? "" : `/${locale}`;
  const url = `${SITE}${base}${path}`;
  // The bare apex (ru home) carries the canonical trailing slash, matching
  // how search engines normalise the root — same rule the storefront's own
  // `localeUrl` follows.
  return url === SITE ? `${SITE}/` : url;
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

export function ogLocale(locale: string): { locale: string; alternate: string[] } {
  return {
    locale: OG_LOCALE[locale] ?? "ru_RU",
    alternate: LOCALES.filter((l) => l !== locale).map((l) => OG_LOCALE[l] ?? "ru_RU"),
  };
}

/**
 * Every path the reseller site wants indexed. `sitemap.ts` and
 * `llms.txt/route.ts` both build off this single list, so the two can never
 * drift. `/telegram`, `/api` and `/faq` do not exist yet — a later task adds
 * them — so they are listed here already and neither file needs a further
 * edit once they land. The cabinet and every auth screen are deliberately
 * absent; `seo.test.ts` pins that.
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
