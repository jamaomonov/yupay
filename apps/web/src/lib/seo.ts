import { LOCALES } from "@yupay/i18n";

import type { Metadata } from "next";

/**
 * SEO helpers shared across routes. Canonical host is the .uz domain (a strong
 * Uzbekistan signal on its own); every page emits hreflang alternates for the
 * three locales + x-default, an og:locale pair, and a geo block pinned to
 * Tashkent so the storefront reads as UZ-local to search engines.
 */
export const SITE = "https://yupay.uz";

/**
 * Shared robots directives. Beyond index/follow we opt into the LARGEST
 * previews Google allows — `max-image-preview:large` unlocks full-width image
 * thumbnails (and Discover eligibility) for a visual storefront, and
 * `max-snippet:-1`/`max-video-preview:-1` remove text/video preview caps.
 * Set on the generic `robots` meta so Bing/Yandex honour it too.
 */
export const ROBOTS: Metadata["robots"] = {
  index: true,
  follow: true,
  "max-image-preview": "large",
  "max-snippet": -1,
  "max-video-preview": -1,
};

const OG_LOCALE: Record<string, string> = {
  ru: "ru_RU",
  en: "en_US",
  uz: "uz_UZ",
};

/** Absolute URL for a locale + path. ru is the default locale → no prefix. */
export function localeUrl(locale: string, path = ""): string {
  const base = locale === "ru" ? "" : `/${locale}`;
  const url = `${SITE}${base}${path}`;
  // The bare apex (ru home) must carry the canonical trailing slash so it
  // matches how Google/Yandex normalise the root — `https://yupay.uz/`, not
  // `https://yupay.uz`. This keeps the sitemap <loc> and the <link rel=canonical>
  // identical to the URL search engines actually index. Every other path stays
  // slash-less (Next.js `trailingSlash:false`), so sub-pages and the /en, /uz
  // homes are unaffected.
  return url === SITE ? `${SITE}/` : url;
}

/**
 * Root-relative internal path for a locale + path — the canonical, prefix-less
 * form for ru. Use for every in-app `<Link href>` / router navigation so the
 * default locale never links through a `/ru/...` → `/...` 30x redirect (a crawl
 * tax on every internal link). Keep `localeUrl` for absolute canonical / OG /
 * JSON-LD URLs. An empty result (ru root) collapses to "/" so it stays a valid,
 * navigable href rather than an empty string that resolves to the current URL.
 */
export function pathFor(locale: string, path = ""): string {
  const p = locale === "ru" ? path : `/${locale}${path}`;
  return p === "" ? "/" : p;
}

/**
 * First value that is present and not blank (whitespace-only counts as absent).
 * The catalog API returns empty strings `""` — not null — for missing brand
 * copy, which `??` does not catch, so this is what lets the real fallback fire.
 */
export function firstNonEmpty(...vals: (string | null | undefined)[]): string | undefined {
  for (const v of vals) {
    if (v != null && v.trim() !== "") return v;
  }
  return undefined;
}

/** canonical + hreflang alternates (incl. x-default) for a given path. */
export function alternates(locale: string, path = "") {
  const languages: Record<string, string> = {};
  for (const l of LOCALES) languages[l] = localeUrl(l, path);
  languages["x-default"] = localeUrl("ru", path);
  return { canonical: localeUrl(locale, path), languages };
}

export function ogLocale(locale: string) {
  return {
    locale: OG_LOCALE[locale] ?? "ru_RU",
    alternate: LOCALES.filter((l) => l !== locale).map((l) => OG_LOCALE[l] ?? "ru_RU"),
  };
}

/** Geo signals for Uzbekistan / Tashkent — emitted via metadata.other. */
export const GEO_META: Record<string, string> = {
  "geo.region": "UZ",
  "geo.placename": "Oʻzbekiston",
  "geo.position": "41.311081;69.240562",
  ICBM: "41.311081, 69.240562",
};

/** Format a som amount for display in the active locale. Marketing/display
 * only — real pricing comes from the catalog API in minor units later. */
export function formatUzs(locale: string, amount: number): string {
  const intlLocale = locale === "ru" ? "ru-RU" : locale === "uz" ? "uz-UZ" : "en-US";
  return new Intl.NumberFormat(intlLocale, {
    style: "currency",
    currency: "UZS",
    maximumFractionDigits: 0,
  }).format(amount);
}
