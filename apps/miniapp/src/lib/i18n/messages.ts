/**
 * Static message catalogs for the miniapp.
 *
 * The Russian catalog is canonical: its key set defines ``MessageKey`` /
 * ``PluralKey``. ``en`` and ``uz`` are typed against it, so a missing key in
 * any locale is a compile error (key parity is also asserted by a unit test).
 *
 * Plain string values are looked up with ``t``; values that are objects keyed
 * by CLDR plural category (``one``/``few``/``many``/``other``) are looked up
 * with ``tn`` and selected via ``Intl.PluralRules``.
 */

import type { Locale } from "@yupay/i18n";
import enMessages from "@yupay/i18n/locales/en/miniapp.json";
import ruMessages from "@yupay/i18n/locales/ru/miniapp.json";
import uzMessages from "@yupay/i18n/locales/uz/miniapp.json";

export type Catalog = typeof ruMessages;

type StringValueKeys<T> = { [K in keyof T]: T[K] extends string ? K : never }[keyof T];
type ObjectValueKeys<T> = { [K in keyof T]: T[K] extends string ? never : K }[keyof T];

/** Keys whose value is a plain string — used with ``t``. */
export type MessageKey = StringValueKeys<Catalog>;
/** Keys whose value is a plural-form object — used with ``tn``. */
export type PluralKey = ObjectValueKeys<Catalog>;

// Compile-time parity guard: en/uz must be structurally identical to ru.
const en: Catalog = enMessages;
const uz: Catalog = uzMessages;

export const CATALOGS: Record<Locale, Catalog> = {
  ru: ruMessages,
  en,
  uz,
};
