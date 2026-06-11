/**
 * Non-React i18n core: the active-locale mirror, message lookup and the
 * ``translate`` helpers usable from any context (the fetch wrapper, the
 * top-level ErrorBoundary, catalog adapters). The React layer in ``index.tsx``
 * builds on top of this.
 */

import { DEFAULT_LOCALE, isLocale, type Locale } from "@yupay/i18n";

import { CATALOGS, type MessageKey, type PluralKey } from "./messages";

export type Params = Record<string, string | number>;

/** Best-effort map an arbitrary BCP-47 / language tag to a supported locale. */
export function resolveLocale(candidate: string | null | undefined): Locale {
  const base = (candidate ?? "").split("-")[0]?.toLowerCase() ?? "";
  return isLocale(base) ? base : DEFAULT_LOCALE;
}

// Module-level mirror of the active locale. Seeded by ``index.tsx`` (stored
// choice, then Telegram launch language) and kept in sync with ``me.locale``
// by ``I18nProvider``. Components subscribe via ``useSyncExternalStore`` so an
// anonymous-session switch (no ``me`` to observe) still re-renders the tree.
let activeLocale: Locale = DEFAULT_LOCALE;
const localeListeners = new Set<() => void>();

const LOCALE_STORAGE_KEY = "yupay.miniapp.locale";

/** The locale the user explicitly picked, surviving relaunches without auth. */
export function readStoredLocale(): Locale | null {
  try {
    const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    return stored !== null && isLocale(stored) ? stored : null;
  } catch {
    return null;
  }
}

export function persistLocale(locale: Locale): void {
  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    /* storage blocked — the choice just won't survive a relaunch */
  }
}

export function setActiveLocale(locale: Locale): void {
  if (locale === activeLocale) return;
  activeLocale = locale;
  for (const listener of localeListeners) listener();
}

export function subscribeActiveLocale(listener: () => void): () => void {
  localeListeners.add(listener);
  return () => localeListeners.delete(listener);
}

export function getActiveLocale(): Locale {
  return activeLocale;
}

function interpolate(template: string, params?: Params): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_match, key: string) =>
    key in params ? String(params[key]) : `{${key}}`,
  );
}

const pluralCache = new Map<Locale, Intl.PluralRules>();
function pluralRules(locale: Locale): Intl.PluralRules {
  let rules = pluralCache.get(locale);
  if (!rules) {
    rules = new Intl.PluralRules(locale);
    pluralCache.set(locale, rules);
  }
  return rules;
}

export function lookup(locale: Locale, key: MessageKey, params?: Params): string {
  const message: string = CATALOGS[locale][key];
  return interpolate(message, params);
}

export function lookupPlural(
  locale: Locale,
  key: PluralKey,
  count: number,
  params?: Params,
): string {
  const forms = CATALOGS[locale][key] as Record<string, string>;
  const category = pluralRules(locale).select(count);
  const message = forms[category] ?? forms.other ?? "";
  return interpolate(message, { ...params, count });
}

/** Translate using the last known active locale (outside React). */
export function translate(key: MessageKey, params?: Params): string {
  return lookup(activeLocale, key, params);
}

/** Plural translate using the last known active locale (outside React). */
export function translatePlural(key: PluralKey, count: number, params?: Params): string {
  return lookupPlural(activeLocale, key, count, params);
}
