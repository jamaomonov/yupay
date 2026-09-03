/**
 * Framework-free helpers for the Steam gift country picker — no React, no
 * Next.js, safe to import from either a Server or Client component.
 * Mirrored (not imported — different app) by the miniapp's own
 * `lib/regions.ts` for the same picker on that surface.
 *
 * The wire and pricing unit stays the *zone* (`GiftZonePrice.zone`,
 * `GiftRegion.zone`) — see `yupay.modules.gifts.service.ZONE_COUNTRIES` on
 * the backend. These two functions only turn a *country* code into
 * something a buyer recognizes: a flag and a localized name. Neither
 * function ever throws — an unmapped or malformed code degrades to the raw
 * input rather than crashing the picker.
 */

const REGIONAL_INDICATOR_BASE = 0x1f1e6;
const A_CHAR_CODE = "A".charCodeAt(0);
const ALPHA2_RE = /^[A-Z]{2}$/;

/**
 * "UZ" -> "🇺🇿". Builds the two regional-indicator code points a country's
 * ISO-3166-1 alpha-2 code maps to — nothing fetched, no image host.
 *
 * @param country An ISO-3166-1 alpha-2 code, any case.
 * @returns The flag emoji, or `country` unchanged when it isn't exactly two
 *   letters (nothing sensible to render as a flag).
 */
export function flagEmoji(country: string): string {
  const code = country.trim().toUpperCase();
  if (!ALPHA2_RE.test(code)) return country;
  // Indexed, not spread/`.split("")`: both decompose on Unicode code
  // points/UTF-16 units rather than the plain ASCII letters `ALPHA2_RE`
  // already guarantees here, which a lint rule (`no-misused-spread`) flags
  // as unsafe for arbitrary strings in general.
  const first = REGIONAL_INDICATOR_BASE + (code.charCodeAt(0) - A_CHAR_CODE);
  const second = REGIONAL_INDICATOR_BASE + (code.charCodeAt(1) - A_CHAR_CODE);
  return String.fromCodePoint(first, second);
}

/**
 * "UZ" + "ru" -> "Узбекистан". Localized via `Intl.DisplayNames`, never a
 * hardcoded name list.
 *
 * @param country An ISO-3166-1 alpha-2 (or UN M49) region code, any case.
 * @param locale A BCP-47 locale tag.
 * @returns The localized country name, or the upper-cased `country` when
 *   the locale has no region data, the code is malformed, or CLDR has no
 *   name for it.
 */
export function countryName(country: string, locale: string): string {
  const code = country.trim().toUpperCase();
  try {
    const names = new Intl.DisplayNames([locale], { type: "region" });
    return names.of(code) ?? code;
  } catch {
    return code;
  }
}
