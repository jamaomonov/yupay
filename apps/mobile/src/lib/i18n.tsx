/**
 * App strings from `@yupay/i18n` (namespace `mobile`), one locale at a time.
 *
 * `t("brand.check")` reads a dotted key; a missing key shows the key itself so a gap is
 * visible in review rather than blank.
 */
import en from "@yupay/i18n/locales/en/mobile.json";
import ru from "@yupay/i18n/locales/ru/mobile.json";
import uz from "@yupay/i18n/locales/uz/mobile.json";
import { createContext, use, useEffect, useState, type ReactNode } from "react";

import { fill } from "@/lib/format";
import { readPref, writePref } from "@/lib/prefs";

export const LOCALES = ["ru", "uz", "en"] as const;
export type Locale = (typeof LOCALES)[number];

export const LOCALE_NAMES: Record<Locale, string> = {
  ru: "Русский",
  uz: "Oʻzbekcha",
  en: "English",
};

type Messages = typeof ru;
const CATALOGUES: Record<Locale, Messages> = { ru, en, uz };

function lookup(messages: Messages, key: string): string | undefined {
  let node: unknown = messages;
  for (const part of key.split(".")) {
    if (typeof node !== "object" || node === null) return undefined;
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === "string" ? node : undefined;
}

interface I18nValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
}

const PREF_KEY = "locale";
const I18nContext = createContext<I18nValue | null>(null);

function isLocale(value: string | null): value is Locale {
  return (LOCALES as readonly (string | null)[]).includes(value);
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("ru");

  useEffect(() => {
    void readPref(PREF_KEY).then((saved) => {
      if (isLocale(saved)) setLocaleState(saved);
    });
  }, []);

  const setLocale = (next: Locale) => {
    setLocaleState(next);
    void writePref(PREF_KEY, next);
  };

  const t = (key: string, vars?: Record<string, string | number>) =>
    fill(lookup(CATALOGUES[locale], key) ?? key, vars);

  return <I18nContext value={{ locale, setLocale, t }}>{children}</I18nContext>;
}

export function useI18n(): I18nValue {
  const value = use(I18nContext);
  if (!value) throw new Error("useI18n outside I18nProvider");
  return value;
}

/** Pick the current locale's text from a `{ru, en, uz}` object the API returns. */
export function pickLocalized(value: unknown, locale: Locale): string | undefined {
  if (typeof value === "string") return value;
  if (typeof value !== "object" || value === null) return undefined;
  const map = value as Partial<Record<Locale, unknown>>;
  const text = map[locale] ?? map.ru;
  return typeof text === "string" ? text : undefined;
}
