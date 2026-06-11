/**
 * Lightweight i18n for the miniapp (React layer).
 *
 * The active locale is derived from the authenticated user's ``locale``
 * preference (``me.locale``), falling back to the Telegram launch language and
 * finally to ``DEFAULT_LOCALE``. Components read it via ``useT``/``useLocale``.
 * Catalog text (brand / product / category names) is localized server-side via
 * the ``Accept-Language`` header, so when the locale changes we refetch the
 * catalog queries; the header itself is attached by the fetch wrapper from the
 * mirror in ``core.ts``.
 */

import { useQueryClient } from "@tanstack/react-query";
import type { Locale } from "@yupay/i18n";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { useMe } from "@/lib/auth";
import { getWebApp } from "@/lib/telegram";

import {
  getActiveLocale,
  lookup,
  lookupPlural,
  readStoredLocale,
  resolveLocale,
  setActiveLocale,
  subscribeActiveLocale,
  type Params,
} from "./core";
import type { MessageKey, PluralKey } from "./messages";

export { translate } from "./core";
export type { MessageKey, PluralKey } from "./messages";

// Seed the mirror so even the pre-auth bootstrap prefetch (catalog) requests
// the right locale. An explicitly stored choice (anonymous sessions persist
// it locally) wins over the Telegram launch language.
setActiveLocale(
  readStoredLocale() ?? resolveLocale(getWebApp()?.initDataUnsafe.user?.language_code ?? null),
);

interface I18nValue {
  locale: Locale;
  t: (key: MessageKey, params?: Params) => string;
  tn: (key: PluralKey, count: number, params?: Params) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const { data: me } = useMe();
  // The server-side preference wins for authenticated users; anonymous
  // sessions follow the local mirror (seeded above, flipped by Settings).
  const mirrorLocale = useSyncExternalStore(subscribeActiveLocale, getActiveLocale);
  const locale = useMemo(
    () => (me?.locale ? resolveLocale(me.locale) : mirrorLocale),
    [me?.locale, mirrorLocale],
  );
  const prevLocale = useRef(getActiveLocale());

  useEffect(() => {
    setActiveLocale(locale);
    document.documentElement.lang = locale;
    if (prevLocale.current !== locale) {
      prevLocale.current = locale;
      // Catalog names are localized server-side via Accept-Language — refetch
      // so they follow the new locale (form-field label maps switch in place).
      void qc.invalidateQueries({ queryKey: ["catalog"] });
    }
  }, [locale, qc]);

  const value = useMemo<I18nValue>(
    () => ({
      locale,
      t: (key, params) => lookup(locale, key, params),
      tn: (key, count, params) => lookupPlural(locale, key, count, params),
    }),
    [locale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useT(): I18nValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useT must be used within I18nProvider");
  return ctx;
}

export function useLocale(): Locale {
  return useT().locale;
}
