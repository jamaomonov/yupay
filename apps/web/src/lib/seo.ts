import { LOCALES } from "@yupay/i18n";

/**
 * SEO helpers shared across routes. Canonical host is the .uz domain (a strong
 * Uzbekistan signal on its own); every page emits hreflang alternates for the
 * three locales + x-default, an og:locale pair, and a geo block pinned to
 * Tashkent so the storefront reads as UZ-local to search engines.
 */
export const SITE = "https://yupay.uz";

const OG_LOCALE: Record<string, string> = {
  ru: "ru_RU",
  en: "en_US",
  uz: "uz_UZ",
};

/** Absolute URL for a locale + path. ru is the default locale → no prefix. */
export function localeUrl(locale: string, path = ""): string {
  const base = locale === "ru" ? "" : `/${locale}`;
  return `${SITE}${base}${path}`;
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
