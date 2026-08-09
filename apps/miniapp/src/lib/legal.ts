import type { Locale } from "@yupay/i18n";

/**
 * Links out to the legal documents on the storefront.
 *
 * The Mini App does not render them. They are one published set of documents —
 * the offer a customer accepts is the one at yupay.uz, and a second rendering
 * here would be a second thing to keep in step with it. Linking out also means a
 * correction goes live for both surfaces the moment the storefront redeploys.
 *
 * The host is fixed rather than configurable: these are the *published*
 * documents, so a staging build should still point at the real ones.
 */
const STOREFRONT = "https://yupay.uz";

/**
 * Absolute URL of a legal document, or of the index when `doc` is omitted.
 *
 * Mirrors the storefront's locale routing: `ru` is the default locale and
 * carries no prefix (see `apps/web/src/lib/seo.ts`). Getting this wrong costs a
 * redirect on every tap, which inside a Telegram in-app browser is a visible
 * stutter rather than a silent hop.
 */
export function legalUrl(locale: Locale, doc?: string): string {
  const prefix = locale === "ru" ? "" : `/${locale}`;
  return `${STOREFRONT}${prefix}/legal${doc ? `/${doc}` : ""}`;
}
